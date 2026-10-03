#!/usr/bin/env python3
"""Send the HERO7 Silver preview to a low-latency WebRTC browser page."""

from __future__ import annotations

import argparse
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


CAMERA_KEEPALIVE = b"_GPHD_:0:0:2:0.000000\n"
CONTAINER_IMAGE = "bluenviron/mediamtx:latest"
CONTAINER_NAME = "rc-ai-surveyor"


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
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
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
    try:
        start_backend(args.rtsp_port, args.web_port, args.ice_port)
        started_backend = True
        wait_for_port(args.rtsp_port, stopping)

        keepalive = threading.Thread(
            target=keep_camera_alive,
            args=(args.camera_ip, stopping),
            name="gopro-keepalive",
            daemon=True,
        )
        keepalive.start()

        viewer_url = (
            f"http://127.0.0.1:{args.web_port}/gopro/"
            "?controls=false&muted=true&autoplay=true&playsInline=true"
        )
        opened_browser = False

        while not stopping.is_set():
            log("starting raw H.264 relay")
            process = subprocess.Popen(ffmpeg_command(args.rtsp_port))
            time.sleep(0.5)
            request_camera_preview(args.camera_ip)

            if not opened_browser:
                log(f"website: {viewer_url}")
                if not args.no_browser:
                    webbrowser.open(viewer_url)
                opened_browser = True

            while process.poll() is None and not stopping.wait(0.5):
                pass
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

            if not stopping.is_set():
                log(f"relay exited with code {process.returncode}; restarting")
                stopping.wait(1)
    finally:
        stopping.set()
        if keepalive:
            keepalive.join(timeout=2)
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
