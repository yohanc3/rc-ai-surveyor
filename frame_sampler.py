#!/usr/bin/env python3
"""Pull a relayed video stream and process only the newest sampled JPEG frame."""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path


SOI = b"\xff\xd8"
EOI = b"\xff\xd9"


@dataclass
class LatestFrame:
    condition: threading.Condition
    data: bytes | None = None
    sequence: int = 0
    captured_at: float = 0.0
    closed: bool = False

    def publish(self, data: bytes) -> None:
        with self.condition:
            self.data = data
            self.sequence += 1
            self.captured_at = time.time()
            self.condition.notify_all()

    def close(self) -> None:
        with self.condition:
            self.closed = True
            self.condition.notify_all()

    def wait_after(self, sequence: int) -> tuple[int, float, bytes] | None:
        with self.condition:
            self.condition.wait_for(lambda: self.sequence > sequence or self.closed)
            if self.sequence > sequence:
                assert self.data is not None
                return self.sequence, self.captured_at, self.data
            return None


def log(message: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), message, flush=True)


def ffmpeg_command(source: str, fps: float, width: int) -> list[str]:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "warning"]
    if source.startswith(("rtsp://", "rtmp://", "rtmps://", "srt://", "udp://")):
        command += ["-fflags", "nobuffer", "-flags", "low_delay"]
    if source.startswith("rtsp://"):
        command += ["-rtsp_transport", "tcp"]
    command += [
        "-i",
        source,
        "-an",
        "-vf",
        f"fps={fps},scale={width}:-2,format=yuvj420p",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "-q:v",
        "3",
        "pipe:1",
    ]
    return command


def read_frames(stream: object, latest: LatestFrame) -> None:
    buffer = bytearray()
    read = getattr(stream, "read")
    try:
        while chunk := read(65536):
            buffer.extend(chunk)
            while True:
                start = buffer.find(SOI)
                if start < 0:
                    if len(buffer) > 1:
                        del buffer[:-1]
                    break
                end = buffer.find(EOI, start + 2)
                if end < 0:
                    if start:
                        del buffer[:start]
                    if len(buffer) > 20_000_000:
                        buffer.clear()
                    break
                end += 2
                latest.publish(bytes(buffer[start:end]))
                del buffer[:end]
    finally:
        # The supervisor may reconnect FFmpeg. Only main() permanently closes
        # the shared latest-frame channel during shutdown.
        pass


def write_latest(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def post_frame(url: str, token: str | None, sequence: int, data: bytes) -> None:
    headers = {
        "Content-Type": "image/jpeg",
        "X-Frame-Sequence": str(sequence),
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=15) as response:
        response.read()


def process_loop(
    latest: LatestFrame,
    latest_file: Path | None,
    post_url: str | None,
    token: str | None,
) -> None:
    sequence = 0
    processed = 0
    while item := latest.wait_after(sequence):
        sequence, captured_at, data = item
        started = time.monotonic()
        try:
            if latest_file:
                write_latest(latest_file, data)
            if post_url:
                post_frame(post_url, token, sequence, data)

            # Replace or extend this block with local inference/model invocation.
            processed += 1
            elapsed_ms = (time.monotonic() - started) * 1000
            age_ms = (time.time() - captured_at) * 1000
            if processed == 1 or processed % 10 == 0:
                log(
                    f"processed frame={sequence} bytes={len(data)} "
                    f"work_ms={elapsed_ms:.1f} age_ms={age_ms:.1f}"
                )
        except Exception as error:  # keep the stream alive on handler failures
            log(f"frame {sequence} processing failed: {error}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sample a video stream without allowing stale-frame backlog."
    )
    parser.add_argument("--input", required=True, help="RTSP, RTMP, SRT, or file URL")
    parser.add_argument("--fps", type=float, default=2.0)
    parser.add_argument("--width", type=int, default=848)
    parser.add_argument("--latest-file", type=Path)
    parser.add_argument("--post-url", help="Optional HTTP endpoint accepting image/jpeg")
    parser.add_argument("--restart-delay", type=float, default=2.0)
    parser.add_argument(
        "--no-restart",
        action="store_true",
        help="Exit when FFmpeg exits instead of reconnecting",
    )
    parser.add_argument(
        "--token-env",
        default="FRAME_API_TOKEN",
        help="Environment variable containing the optional bearer token",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not shutil.which("ffmpeg"):
        print("error: ffmpeg is not installed or not on PATH", file=sys.stderr)
        return 2

    token = os.environ.get(args.token_env)
    latest = LatestFrame(condition=threading.Condition())
    worker = threading.Thread(
        target=process_loop,
        args=(latest, args.latest_file, args.post_url, token),
        name="frame-worker",
        daemon=True,
    )
    worker.start()

    stopping = threading.Event()

    def stop_handler(_signum: int, _frame: object) -> None:
        stopping.set()

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    last_exit = 0
    while not stopping.is_set():
        log(f"sampling {args.input} at {args.fps:g} FPS")
        process = subprocess.Popen(
            ffmpeg_command(args.input, args.fps, args.width),
            stdout=subprocess.PIPE,
        )
        assert process.stdout is not None
        reader = threading.Thread(
            target=read_frames,
            args=(process.stdout, latest),
            name="frame-reader",
            daemon=True,
        )
        reader.start()

        while process.poll() is None and not stopping.wait(0.5):
            pass
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        last_exit = process.returncode or 0
        reader.join(timeout=2)

        if stopping.is_set() or args.no_restart:
            break
        log(f"decoder exited with code {last_exit}; reconnecting")
        stopping.wait(args.restart_delay)

    latest.close()
    worker.join(timeout=2)
    log(f"sampler stopped (ffmpeg exit={last_exit})")
    return 0 if stopping.is_set() else last_exit


if __name__ == "__main__":
    raise SystemExit(main())
