#!/usr/bin/env python3
"""Run the HERO7 Silver WebRTC viewer and backend frame pipeline."""

from __future__ import annotations

import argparse
import json
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


CAMERA_KEEPALIVE = b"_GPHD_:0:0:2:0.000000\n"
CONTAINER_IMAGE = "bluenviron/mediamtx:latest"
CONTAINER_NAME = "rc-ai-surveyor"
JPEG_START = b"\xff\xd8"
JPEG_END = b"\xff\xd9"


class PipelineState:
    """Small thread-safe snapshot for the dashboard and future AI worker."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame_count = 0
        self._last_frame_at: float | None = None
        self._last_frame_bytes = 0

    def record_frame(self, size: int) -> int:
        with self._lock:
            self._frame_count += 1
            self._last_frame_at = time.time()
            self._last_frame_bytes = size
            return self._frame_count

    def snapshot(self) -> dict[str, int | float | None | str]:
        with self._lock:
            return {
                "frameCount": self._frame_count,
                "lastFrameAt": self._last_frame_at,
                "lastFrameBytes": self._last_frame_bytes,
                "gemini": "not connected",
                "elevenLabs": "not connected",
            }


def dashboard_html(media_url: str, sample_fps: float) -> bytes:
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RC AI Surveyor</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: #090d12; color: #eef4fb; }}
    main {{ width: min(1280px, calc(100% - 32px)); margin: 24px auto 40px; }}
    header {{ display: flex; align-items: baseline; justify-content: space-between; gap: 16px; }}
    h1 {{ margin: 0 0 16px; font-size: clamp(1.35rem, 3vw, 2rem); }}
    .status {{ color: #fbbf24; font-size: .9rem; }}
    .status.ready {{ color: #4ade80; }}
    .video-shell {{ position: relative; aspect-ratio: 16 / 9; overflow: hidden; border-radius: 14px; background: #000; border: 1px solid #202a36; }}
    iframe {{ width: 100%; height: 100%; border: 0; display: block; }}
    .waiting {{ position: absolute; inset: 0; display: grid; place-items: center; color: #8c9aac; pointer-events: none; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-top: 16px; }}
    section {{ padding: 18px; min-height: 145px; border: 1px solid #202a36; border-radius: 14px; background: #111821; }}
    h2 {{ margin: 0 0 9px; font-size: .78rem; letter-spacing: .1em; text-transform: uppercase; color: #8ba3bd; }}
    p {{ margin: 0; color: #d8e2ec; line-height: 1.55; }}
    .muted {{ color: #728094; }}
    .pipeline {{ margin-top: 16px; color: #8c9aac; font: .82rem ui-monospace, SFMono-Regular, Menlo, monospace; }}
    @media (max-width: 720px) {{ .grid {{ grid-template-columns: 1fr; }} header {{ align-items: flex-start; flex-direction: column; }} }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>RC AI Surveyor</h1>
      <div id="status" class="status">Waiting for backend frames…</div>
    </header>
    <div class="video-shell">
      <div id="waiting" class="waiting">Starting live video…</div>
      <iframe id="video" data-src="{media_url}" allow="autoplay; fullscreen" title="Live GoPro feed"></iframe>
    </div>
    <div class="grid">
      <section>
        <h2>Technical description</h2>
        <p class="muted">Gemini Flash is not connected yet. Its short, concise analysis will appear here.</p>
      </section>
      <section>
        <h2>Human-friendly narration</h2>
        <p class="muted">The narration text for ElevenLabs—and its audio player—will appear here.</p>
      </section>
    </div>
    <div id="pipeline" class="pipeline">Sampling backend frames at {sample_fps:g} FPS.</div>
  </main>
  <script>
    const video = document.querySelector('#video');
    const waiting = document.querySelector('#waiting');
    const status = document.querySelector('#status');
    const pipeline = document.querySelector('#pipeline');
    let videoStarted = false;

    async function refresh() {{
      try {{
        const response = await fetch('/api/status', {{ cache: 'no-store' }});
        const data = await response.json();
        if (data.frameCount > 0) {{
          if (!videoStarted) {{
            video.src = video.dataset.src;
            videoStarted = true;
            waiting.hidden = true;
          }}
          status.textContent = `Live · backend frame ${{data.frameCount}}`;
          status.classList.add('ready');
          pipeline.textContent = `Last backend frame: ${{data.lastFrameBytes.toLocaleString()}} bytes · Gemini: ${{data.gemini}} · ElevenLabs: ${{data.elevenLabs}}`;
        }}
      }} catch (_) {{
        status.textContent = 'Backend unavailable';
        status.classList.remove('ready');
      }}
    }}
    refresh();
    setInterval(refresh, 1000);
  </script>
</body>
</html>
"""
    return page.encode("utf-8")


def make_dashboard_handler(
    state: PipelineState, media_url: str, sample_fps: float
) -> type[BaseHTTPRequestHandler]:
    page = dashboard_html(media_url, sample_fps)

    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
                return

            if self.path == "/api/status":
                body = json.dumps(state.snapshot()).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            self.send_error(404)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return DashboardHandler


def log(message: str) -> None:
    print(time.strftime("%H:%M:%S"), message, flush=True)


def camera_url(camera_ip: str, path: str) -> str:
    return f"http://{camera_ip}{path}"


def check_camera(camera_ip: str) -> None:
    url = camera_url(camera_ip, "/gp/gpControl/status")
    try:
        with urllib.request.urlopen(url, timeout=4) as response:
            response.read(1)
    except (OSError, urllib.error.URLError) as error:
        raise RuntimeError(
            f"GoPro is not reachable at {camera_ip}. "
            "Connect the Mac to the camera's GP Wi-Fi network first."
        ) from error


def request_camera_preview(camera_ip: str) -> None:
    url = camera_url(
        camera_ip,
        "/gp/gpControl/execute?p1=gpStream&a1=proto_v2&c1=restart",
    )
    request = urllib.request.Request(url, headers={"Connection": "close"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            response.read()
        log("camera preview started")
    except urllib.error.HTTPError as error:
        # Some legacy firmware starts the preview while returning an error.
        log(f"camera preview request returned HTTP {error.code}; continuing")


def keep_camera_alive(camera_ip: str, stop: threading.Event) -> None:
    target = (camera_ip, 8554)
    while not stop.is_set():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(CAMERA_KEEPALIVE, target)
        except OSError as error:
            log(f"camera keepalive failed: {error}")
        stop.wait(2)


def container_exists() -> bool:
    result = subprocess.run(
        ["docker", "inspect", CONTAINER_NAME],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def start_backend(rtsp_port: int, web_port: int, ice_port: int) -> None:
    if container_exists():
        raise RuntimeError(
            f"Docker container {CONTAINER_NAME!r} already exists. "
            f"Run: docker stop {CONTAINER_NAME}"
        )

    log("starting MediaMTX backend")
    command = [
        "docker",
        "run",
        "--rm",
        "-d",
        "--name",
        CONTAINER_NAME,
        "-e",
        "MTX_WEBRTCADDITIONALHOSTS=127.0.0.1",
        "-p",
        f"{rtsp_port}:8554/tcp",
        "-p",
        f"{web_port}:8889/tcp",
        "-p",
        f"{ice_port}:8189/udp",
        CONTAINER_IMAGE,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"could not start MediaMTX: {message}")


def stop_backend() -> None:
    if not container_exists():
        return
    log("stopping MediaMTX backend")
    subprocess.run(
        ["docker", "stop", "--time", "2", CONTAINER_NAME],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_for_port(port: int, stop: threading.Event) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not stop.is_set():
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.25)
    raise RuntimeError(f"backend did not open TCP port {port}")


def start_dashboard(
    port: int, media_url: str, sample_fps: float, state: PipelineState
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    try:
        server = ThreadingHTTPServer(
            ("127.0.0.1", port),
            make_dashboard_handler(state, media_url, sample_fps),
        )
    except OSError as error:
        raise RuntimeError(f"could not start dashboard on port {port}: {error}") from error

    thread = threading.Thread(
        target=server.serve_forever,
        name="dashboard",
        daemon=True,
    )
    thread.start()
    return server, thread


def frame_sampler_command(rtsp_port: int, sample_fps: float) -> list[str]:
    source = f"rtsp://127.0.0.1:{rtsp_port}/gopro"
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "fatal",
        "-rtsp_transport",
        "tcp",
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-i",
        source,
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        f"fps={sample_fps:g}",
        "-c:v",
        "mjpeg",
        "-q:v",
        "5",
        "-f",
        "image2pipe",
        "pipe:1",
    ]


class FrameSampler:
    """Decode a few frames per second without touching the WebRTC video path."""

    def __init__(
        self,
        rtsp_port: int,
        sample_fps: float,
        state: PipelineState,
        stopping: threading.Event,
    ) -> None:
        self._command = frame_sampler_command(rtsp_port, sample_fps)
        self._state = state
        self._stopping = stopping
        self._process: subprocess.Popen[bytes] | None = None
        self._process_lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run,
            name="frame-sampler",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        with self._process_lock:
            process = self._process
        if process and process.poll() is None:
            process.terminate()
        self._thread.join(timeout=3)
        if process and process.poll() is None:
            process.kill()
            process.wait()

    def _run(self) -> None:
        while not self._stopping.is_set():
            process = subprocess.Popen(
                self._command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
            with self._process_lock:
                self._process = process

            try:
                self._read_frames(process)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                with self._process_lock:
                    if self._process is process:
                        self._process = None

            if not self._stopping.is_set():
                log("backend frame sampler waiting for video; retrying")
                self._stopping.wait(1)

    def _read_frames(self, process: subprocess.Popen[bytes]) -> None:
        if process.stdout is None:
            return

        buffer = bytearray()
        while not self._stopping.is_set():
            chunk = process.stdout.read(64 * 1024)
            if not chunk:
                return
            buffer.extend(chunk)

            while True:
                start = buffer.find(JPEG_START)
                if start < 0:
                    if len(buffer) > 1:
                        del buffer[:-1]
                    break

                end = buffer.find(JPEG_END, start + len(JPEG_START))
                if end < 0:
                    if start > 0:
                        del buffer[:start]
                    if len(buffer) > 10_000_000:
                        buffer.clear()
                    break

                end += len(JPEG_END)
                frame = bytes(buffer[start:end])
                del buffer[:end]
                self._frame_received(frame)

    def _frame_received(self, frame: bytes) -> None:
        sequence = self._state.record_frame(len(frame))
        log(
            f"backend frame #{sequence} received ({len(frame)} bytes) | "
            "ready for Gemini Flash -> technical + narration text -> ElevenLabs"
        )


def ffmpeg_command(rtsp_port: int) -> list[str]:
    source = "udp://@:8554?fifo_size=2000000&overrun_nonfatal=1"
    destination = f"rtsp://127.0.0.1:{rtsp_port}/gopro"
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-probesize",
        "8192",
        "-analyzeduration",
        "1000000",
        "-f",
        "mpegts",
        "-i",
        source,
        "-map",
        "0:v:0",
        "-an",
        "-c:v",
        "copy",
        "-f",
        "rtsp",
        "-rtsp_transport",
        "tcp",
        destination,
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stream a HERO7 Silver preview to a local WebRTC webpage."
    )
    parser.add_argument("--camera-ip", default="10.5.5.9")
    parser.add_argument("--rtsp-port", type=int, default=8554)
    parser.add_argument("--web-port", type=int, default=8889)
    parser.add_argument("--ice-port", type=int, default=8189)
    parser.add_argument("--dashboard-port", type=int, default=8787)
    parser.add_argument("--sample-fps", type=float, default=2.0)
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.sample_fps <= 0:
        raise RuntimeError("--sample-fps must be greater than zero")

    for program in ("docker", "ffmpeg"):
        if not shutil.which(program):
            raise RuntimeError(f"{program} is not installed or not on PATH")

    log("checking GoPro connection")
    check_camera(args.camera_ip)

    stopping = threading.Event()

    def stop_handler(_signum: int, _frame: object) -> None:
        stopping.set()

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    started_backend = False
    keepalive: threading.Thread | None = None
    dashboard: ThreadingHTTPServer | None = None
    dashboard_thread: threading.Thread | None = None
    frame_sampler: FrameSampler | None = None
    relay_process: subprocess.Popen[bytes] | None = None
    try:
        start_backend(args.rtsp_port, args.web_port, args.ice_port)
        started_backend = True
        wait_for_port(args.rtsp_port, stopping)

        media_url = (
            f"http://127.0.0.1:{args.web_port}/gopro/"
            "?controls=false&muted=true&autoplay=true&playsInline=true"
        )
        pipeline_state = PipelineState()
        dashboard, dashboard_thread = start_dashboard(
            args.dashboard_port,
            media_url,
            args.sample_fps,
            pipeline_state,
        )
        frame_sampler = FrameSampler(
            args.rtsp_port,
            args.sample_fps,
            pipeline_state,
            stopping,
        )
        frame_sampler.start()
        log(
            f"backend sampler ready at {args.sample_fps:g} FPS "
            "(Gemini and ElevenLabs are not connected)"
        )

        keepalive = threading.Thread(
            target=keep_camera_alive,
            args=(args.camera_ip, stopping),
            name="gopro-keepalive",
            daemon=True,
        )
        keepalive.start()

        viewer_url = f"http://127.0.0.1:{args.dashboard_port}/"
        opened_browser = False

        while not stopping.is_set():
            log("starting raw H.264 relay")
            relay_process = subprocess.Popen(ffmpeg_command(args.rtsp_port))
            time.sleep(0.5)
            request_camera_preview(args.camera_ip)

            if not opened_browser:
                log(f"website: {viewer_url}")
                if not args.no_browser:
                    webbrowser.open(viewer_url)
                opened_browser = True

            while relay_process.poll() is None and not stopping.wait(0.5):
                pass
            if relay_process.poll() is None:
                relay_process.terminate()
                try:
                    relay_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    relay_process.kill()
                    relay_process.wait()

            if not stopping.is_set():
                log(f"relay exited with code {relay_process.returncode}; restarting")
                stopping.wait(1)
            relay_process = None
    finally:
        stopping.set()
        if relay_process and relay_process.poll() is None:
            relay_process.terminate()
            try:
                relay_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                relay_process.kill()
                relay_process.wait()
        if frame_sampler:
            frame_sampler.stop()
        if keepalive:
            keepalive.join(timeout=2)
        if dashboard:
            dashboard.shutdown()
            dashboard.server_close()
        if dashboard_thread:
            dashboard_thread.join(timeout=2)
        if started_backend:
            stop_backend()

    log("stopped")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2)
