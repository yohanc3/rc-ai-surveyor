#!/usr/bin/env python3
"""Pull a relayed video stream and process only the newest sampled JPEG frame."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


SOI = b"\xff\xd8"
EOI = b"\xff\xd9"

VIEWER_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>RC AI Surveyor</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; }
    body { margin: 0; background: #0b0d10; color: #eef2f7; }
    main { width: min(1100px, calc(100% - 32px)); margin: 24px auto; }
    header { display: flex; justify-content: space-between; align-items: baseline; }
    h1 { font-size: 20px; margin: 0 0 16px; }
    #status { color: #9ca9b8; font-variant-numeric: tabular-nums; }
    .frame { background: #000; border: 1px solid #29313a; border-radius: 10px;
             min-height: 240px; overflow: hidden; display: grid; place-items: center; }
    img { width: 100%; height: auto; display: block; image-rendering: auto; }
  </style>
</head>
<body>
  <main>
    <header><h1>RC AI Surveyor</h1><span id="status">waiting for frames...</span></header>
    <div class="frame"><img src="/stream.mjpg" alt="Live GoPro frames"></div>
  </main>
  <script>
    async function refreshStatus() {
      try {
        const s = await fetch('/status', {cache: 'no-store'}).then(r => r.json());
        document.getElementById('status').textContent = s.available
          ? `frame ${s.sequence} · ${Math.round(s.age_ms)} ms old`
          : 'waiting for frames...';
      } catch (_) {}
    }
    setInterval(refreshStatus, 1000); refreshStatus();
  </script>
</body>
</html>
""".encode()


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


def start_viewer(
    latest: LatestFrame, host: str, port: int
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    class ViewerHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            path = self.path.split("?", 1)[0]
            if path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(VIEWER_HTML)))
                self.end_headers()
                self.wfile.write(VIEWER_HTML)
                return

            if path == "/status":
                with latest.condition:
                    available = latest.data is not None
                    payload = {
                        "available": available,
                        "sequence": latest.sequence,
                        "age_ms": (
                            (time.time() - latest.captured_at) * 1000
                            if available
                            else None
                        ),
                    }
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if path == "/latest.jpg":
                with latest.condition:
                    data = latest.data
                    sequence = latest.sequence
                if data is None:
                    self.send_error(503, "No frame available yet")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Frame-Sequence", str(sequence))
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            if path == "/stream.mjpg":
                self.send_response(200)
                self.send_header(
                    "Content-Type", "multipart/x-mixed-replace; boundary=frame"
                )
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                sequence = 0
                try:
                    while item := latest.wait_after(sequence):
                        sequence, _captured_at, data = item
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(
                            f"Content-Length: {len(data)}\r\n".encode()
                        )
                        self.wfile.write(
                            f"X-Frame-Sequence: {sequence}\r\n\r\n".encode()
                        )
                        self.wfile.write(data)
                        self.wfile.write(b"\r\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return

            self.send_error(404)

        def log_message(self, _format: str, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer((host, port), ViewerHandler)
    server.daemon_threads = True
    thread = threading.Thread(
        target=server.serve_forever,
        name="frame-viewer",
        daemon=True,
    )
    thread.start()
    return server, thread


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
    parser.add_argument(
        "--viewer",
        action="store_true",
        help="Serve a browser viewer and latest JPEG",
    )
    parser.add_argument("--viewer-host", default="127.0.0.1")
    parser.add_argument("--viewer-port", type=int, default=8787)
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Open the viewer in the default browser (also enables --viewer)",
    )
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

    viewer_server: ThreadingHTTPServer | None = None
    viewer_thread: threading.Thread | None = None
    if args.viewer or args.open_browser:
        viewer_server, viewer_thread = start_viewer(
            latest, args.viewer_host, args.viewer_port
        )
        viewer_url = f"http://{args.viewer_host}:{args.viewer_port}"
        log(f"viewer available at {viewer_url}")
        if args.open_browser:
            webbrowser.open(viewer_url)

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
    if viewer_server:
        viewer_server.shutdown()
        viewer_server.server_close()
    if viewer_thread:
        viewer_thread.join(timeout=2)
    worker.join(timeout=2)
    log(f"sampler stopped (ffmpeg exit={last_exit})")
    return 0 if stopping.is_set() else last_exit


if __name__ == "__main__":
    raise SystemExit(main())
