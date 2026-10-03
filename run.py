#!/usr/bin/env python3
"""Run the HERO7 Silver WebRTC viewer and the AI analysis pipeline.

Two phases, because the GoPro's Wi-Fi has no internet access:

  python3 run.py --setup    once, while online  (downloads everything)
  python3 run.py            on the GoPro network (needs nothing from the net)
"""

from __future__ import annotations

import argparse
import logging
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
from http.server import ThreadingHTTPServer

from app.audio_store import AudioStore
from app.config import ConfigError, load_config
from app.events import EventBus
from app.frame_pipeline import AnalysisPipeline
from app.models import Frame, utc_now
from app.providers import MockSpeechSynthesizer, MockVisionAnalyzer
from app.server import PROJECT_DIR, VITE_DIST, start_dashboard
from app.state import PipelineState

CAMERA_KEEPALIVE = b"_GPHD_:0:0:2:0.000000\n"
CONTAINER_IMAGE = "bluenviron/mediamtx:latest"
CONTAINER_NAME = "rc-ai-surveyor"
JPEG_START = b"\xff\xd8"
JPEG_END = b"\xff\xd9"
INTERNET_PROBE = ("8.8.8.8", 53)

log = logging.getLogger("rc")


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )


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
            "Connect this machine to the camera's GP Wi-Fi network first."
        ) from error


def has_internet(timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection(INTERNET_PROBE, timeout=timeout):
            return True
    except OSError:
        return False


def request_camera_preview(camera_ip: str) -> None:
    url = camera_url(
        camera_ip, "/gp/gpControl/execute?p1=gpStream&a1=proto_v2&c1=restart"
    )
    request = urllib.request.Request(url, headers={"Connection": "close"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            response.read()
        log.info("camera preview started")
    except urllib.error.HTTPError as error:
        # Some legacy firmware starts the preview while returning an error.
        log.info("camera preview request returned HTTP %s; continuing", error.code)


def keep_camera_alive(camera_ip: str, stop: threading.Event) -> None:
    target = (camera_ip, 8554)
    while not stop.is_set():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(CAMERA_KEEPALIVE, target)
        except OSError as error:
            log.warning("camera keepalive failed: %s", error)
        stop.wait(2)


# ---------- docker ----------


def docker_image_present() -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", CONTAINER_IMAGE],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


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
    if not docker_image_present():
        raise RuntimeError(
            f"the {CONTAINER_IMAGE} image is not downloaded, and the GoPro "
            "network has no internet access.\n"
            "       Reconnect to a normal network and run: python3 run.py --setup"
        )

    log.info("starting MediaMTX backend")
    command = [
        "docker", "run", "--rm", "-d",
        "--name", CONTAINER_NAME,
        "-e", "MTX_WEBRTCADDITIONALHOSTS=127.0.0.1",
        "-p", f"{rtsp_port}:8554/tcp",
        "-p", f"{web_port}:8889/tcp",
        "-p", f"{ice_port}:8189/udp",
        CONTAINER_IMAGE,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"could not start MediaMTX: {message}")


def stop_backend() -> None:
    if not container_exists():
        return
    log.info("stopping MediaMTX backend")
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


# ---------- ffmpeg ----------


def frame_sampler_command(rtsp_port: int, sample_fps: float) -> list[str]:
    source = f"rtsp://127.0.0.1:{rtsp_port}/gopro"
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "fatal",
        "-rtsp_transport", "tcp",
        "-fflags", "nobuffer", "-flags", "low_delay",
        "-i", source,
        "-map", "0:v:0", "-an",
        "-vf", f"fps={sample_fps:g}",
        "-c:v", "mjpeg", "-q:v", "5",
        "-f", "image2pipe", "pipe:1",
    ]


def ffmpeg_command(rtsp_port: int) -> list[str]:
    source = "udp://@:8554?fifo_size=2000000&overrun_nonfatal=1"
    destination = f"rtsp://127.0.0.1:{rtsp_port}/gopro"
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-fflags", "nobuffer", "-flags", "low_delay",
        "-probesize", "8192", "-analyzeduration", "1000000",
        "-f", "mpegts", "-i", source,
        "-map", "0:v:0", "-an", "-c:v", "copy",
        "-f", "rtsp", "-rtsp_transport", "tcp", destination,
    ]


class FrameSampler:
    """Decode a few frames per second without touching the WebRTC video path."""

    def __init__(self, rtsp_port, sample_fps, state, pipeline, stopping) -> None:
        self._command = frame_sampler_command(rtsp_port, sample_fps)
        self._state = state
        self._pipeline = pipeline
        self._stopping = stopping
        self._process: subprocess.Popen[bytes] | None = None
        self._process_lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="frame-sampler", daemon=True)

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
                self._command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
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
                log.info("backend frame sampler waiting for video; retrying")
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

    def _frame_received(self, jpeg: bytes) -> None:
        sequence = self._state.record_frame(jpeg)
        self._state.health("camera").set("ok", f"frame {sequence}")
        self._pipeline.submit_frame(
            Frame(
                sequence=sequence,
                jpeg=jpeg,
                captured_at=utc_now(),
                captured_mono=time.monotonic(),
            )
        )


# ---------- providers ----------


def build_providers(config, store: AudioStore):
    """Mock providers need no network, no SDK and no API key."""
    if not config.is_live:
        return MockVisionAnalyzer(), MockSpeechSynthesizer(store)

    from app.elevenlabs_tts import ElevenLabsSpeechSynthesizer
    from app.gemini_analyzer import GeminiVisionAnalyzer

    return GeminiVisionAnalyzer(config), ElevenLabsSpeechSynthesizer(config, store)


# ---------- setup phase ----------


def run_setup(args) -> int:
    """Everything that needs the internet. Run this before going to the GoPro."""
    log.info("running online setup")
    ok = True

    for program in ("docker", "ffmpeg"):
        if shutil.which(program):
            log.info("  [ok]   %s found", program)
        else:
            log.error("  [fail] %s is not installed or not on PATH", program)
            ok = False

    if not shutil.which("docker"):
        return 1

    if not has_internet():
        log.error("  [fail] no internet route; connect to a normal network first")
        return 1
    log.info("  [ok]   internet reachable")

    log.info("  ...    pulling %s", CONTAINER_IMAGE)
    result = subprocess.run(["docker", "pull", CONTAINER_IMAGE], capture_output=True, text=True)
    if result.returncode != 0:
        log.error("  [fail] docker pull: %s", (result.stderr or result.stdout).strip()[:300])
        ok = False
    else:
        log.info("  [ok]   %s downloaded", CONTAINER_IMAGE)

    if (PROJECT_DIR / "frontend" / "package.json").is_file():
        if shutil.which("npm"):
            log.info("  ...    building the dashboard (npm install && npm run build)")
            for command in (["npm", "install", "--no-audit", "--no-fund"], ["npm", "run", "build"]):
                step = subprocess.run(
                    command, cwd=PROJECT_DIR / "frontend", capture_output=True, text=True
                )
                if step.returncode != 0:
                    log.error("  [fail] %s: %s", " ".join(command), (step.stderr or step.stdout).strip()[:300])
                    ok = False
                    break
            else:
                log.info("  [ok]   dashboard built into frontend/dist")
        else:
            log.warning("  [warn] npm not found; the vanilla static/ dashboard will be used")

    try:
        config = load_config(provider_mode=args.provider_mode)
    except ConfigError as error:
        log.error("  [fail] configuration: %s", error)
        return 1

    if config.is_live:
        log.info("  [ok]   live providers configured (%s)", config.gemini_model)
        log.warning(
            "  [warn] live mode needs internet while running: keep an ethernet or "
            "tethered route up alongside the GoPro Wi-Fi (design document section 4)"
        )
    else:
        log.info("  [ok]   mock providers: no internet needed at run time")

    log.info("setup %s", "complete" if ok else "finished with errors")
    if ok:
        log.info("next: connect to the GoPro's GP... Wi-Fi, then run: python3 run.py")
    return 0 if ok else 1


# ---------- main ----------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stream a HERO7 Silver preview and run the AI analysis pipeline."
    )
    parser.add_argument("--setup", action="store_true",
                        help="online phase: download the Docker image and build the dashboard")
    parser.add_argument("--camera-ip", default="10.5.5.9")
    parser.add_argument("--rtsp-port", type=int, default=8554)
    parser.add_argument("--web-port", type=int, default=8889)
    parser.add_argument("--ice-port", type=int, default=8189)
    parser.add_argument("--dashboard-port", type=int, default=8787)
    parser.add_argument("--sample-fps", type=float, default=None,
                        help="analysis sampling rate (default: ANALYSIS_FPS or 2)")
    parser.add_argument("--provider-mode", choices=("mock", "live"), default=None,
                        help="mock needs no internet; live calls Gemini and ElevenLabs")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)

    if args.setup:
        return run_setup(args)

    config = load_config(sample_fps=args.sample_fps, provider_mode=args.provider_mode)
    log.info("configuration: %s", config.redacted())

    for program in ("docker", "ffmpeg"):
        if not shutil.which(program):
            raise RuntimeError(
                f"{program} is not installed or not on PATH. "
                "Run 'python3 run.py --setup' while online."
            )

    log.info("checking GoPro connection")
    check_camera(args.camera_ip)

    if config.is_live and not has_internet():
        raise RuntimeError(
            "PROVIDER_MODE=live needs an internet route in addition to the GoPro "
            "Wi-Fi (ethernet or phone tethering). Use --provider-mode mock to run "
            "entirely offline."
        )

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
    pipeline: AnalysisPipeline | None = None
    relay_process: subprocess.Popen[bytes] | None = None
    try:
        start_backend(args.rtsp_port, args.web_port, args.ice_port)
        started_backend = True
        wait_for_port(args.rtsp_port, stopping)

        media_url = (
            f"http://127.0.0.1:{args.web_port}/gopro/"
            "?controls=false&muted=true&autoplay=true&playsInline=true"
        )
        whep_url = f"http://127.0.0.1:{args.web_port}/gopro/whep"

        state = PipelineState(config, media_url, whep_url)
        bus = EventBus()
        store = AudioStore(config.audio_dir, config.audio_retention)
        store.clear()

        analyzer, synthesizer = build_providers(config, store)
        pipeline = AnalysisPipeline(config, analyzer, synthesizer, bus, state)
        state.attach_pipeline(pipeline)
        pipeline.start()
        log.info(
            "analysis pipeline ready: %s providers, %g fps, %d frame(s) per request",
            config.provider_mode, config.analysis_fps, config.frames_per_batch,
        )

        dashboard, dashboard_thread, label = start_dashboard(
            args.dashboard_port, state, bus, store
        )
        log.info("serving dashboard from %s", label)

        frame_sampler = FrameSampler(
            args.rtsp_port, config.analysis_fps, state, pipeline, stopping
        )
        frame_sampler.start()

        keepalive = threading.Thread(
            target=keep_camera_alive, args=(args.camera_ip, stopping),
            name="gopro-keepalive", daemon=True,
        )
        keepalive.start()

        viewer_url = f"http://127.0.0.1:{args.dashboard_port}/"
        opened_browser = False

        while not stopping.is_set():
            log.info("starting raw H.264 relay")
            relay_process = subprocess.Popen(ffmpeg_command(args.rtsp_port))
            state.set_relay_up(True)
            time.sleep(0.5)
            request_camera_preview(args.camera_ip)

            if not opened_browser:
                log.info("website: %s", viewer_url)
                if not args.no_browser:
                    webbrowser.open(viewer_url)
                opened_browser = True

            while relay_process.poll() is None and not stopping.wait(0.5):
                pass
            state.set_relay_up(False)
            if relay_process.poll() is None:
                relay_process.terminate()
                try:
                    relay_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    relay_process.kill()
                    relay_process.wait()

            if not stopping.is_set():
                log.info("relay exited with code %s; restarting", relay_process.returncode)
                state.record_relay_restart()
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
        if pipeline:
            pipeline.stop()
        if keepalive:
            keepalive.join(timeout=2)
        if dashboard:
            dashboard.shutdown()
            dashboard.server_close()
        if dashboard_thread:
            dashboard_thread.join(timeout=2)
        if started_backend:
            stop_backend()

    log.info("stopped")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ConfigError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2)
