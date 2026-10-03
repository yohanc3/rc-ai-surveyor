#!/usr/bin/env python3
"""Supervise the legacy HERO7 Silver preview and forward it with FFmpeg."""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


KEEPALIVE = b"_GPHD_:0:0:2:0.000000\n"


@dataclass
class Config:
    camera_ip: str
    listen_port: int
    output: str | None
    preview: bool
    transcode: bool
    restart_delay: float
    wifi_ssid: str | None
    wifi_interface: str
    wifi_password_env: str


def log(message: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), message, flush=True)


def connect_wifi(config: Config) -> None:
    if not config.wifi_ssid:
        return

    password = os.environ.get(config.wifi_password_env)
    if not password:
        raise RuntimeError(
            f"{config.wifi_password_env} must be set when --wifi-ssid is used"
        )

    networksetup = shutil.which("networksetup") or "/usr/sbin/networksetup"
    log(f"joining Wi-Fi network {config.wifi_ssid!r} on {config.wifi_interface}")
    subprocess.run(
        [
            networksetup,
            "-setairportnetwork",
            config.wifi_interface,
            config.wifi_ssid,
            password,
        ],
        check=True,
    )

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["ipconfig", "getifaddr", config.wifi_interface],
            capture_output=True,
            text=True,
        )
        address = result.stdout.strip()
        if address.startswith("10.5.5."):
            log(f"Wi-Fi ready at {address}")
            return
        time.sleep(1)
    raise RuntimeError("joined Wi-Fi but did not receive a 10.5.5.x address")


def start_camera(camera_ip: str) -> None:
    url = (
        f"http://{camera_ip}/gp/gpControl/execute"
        "?p1=gpStream&a1=proto_v2&c1=restart"
    )
    request = urllib.request.Request(url, headers={"Connection": "close"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            response.read()
        log("camera preview requested")
    except urllib.error.HTTPError as error:
        # Some legacy firmware starts preview while returning a non-2xx response.
        log(f"camera start returned HTTP {error.code}; continuing to listen")


def keepalive_loop(camera_ip: str, stop: threading.Event) -> None:
    target = (camera_ip, 8554)
    while not stop.is_set():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(KEEPALIVE, target)
        except OSError as error:
            log(f"keepalive failed: {error}")
        stop.wait(2.0)


def input_url(port: int) -> str:
    return f"udp://@:{port}?fifo_size=2000000&overrun_nonfatal=1"


def build_media_command(config: Config) -> list[str]:
    source = input_url(config.listen_port)
    common_input = [
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
    ]

    if config.preview:
        return [
            "ffplay",
            "-hide_banner",
            "-loglevel",
            "warning",
            *common_input,
            "-framedrop",
            source,
        ]

    assert config.output
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        *common_input,
        "-i",
        source,
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
    ]

    if config.transcode:
        command += [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-tune",
            "zerolatency",
            "-g",
            "30",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
        ]
    else:
        command += ["-c:v", "copy", "-c:a", "copy"]

    if config.output.startswith(("rtmp://", "rtmps://")):
        command += ["-f", "flv"]
    elif config.output.startswith(("srt://", "udp://")):
        command += ["-f", "mpegts"]

    return [*command, config.output]


def parse_args() -> Config:
    parser = argparse.ArgumentParser(
        description="Start a HERO7 Silver preview, keep it alive, and preview or forward it."
    )
    parser.add_argument("--camera-ip", default="10.5.5.9")
    parser.add_argument("--listen-port", type=int, default=8554)
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--preview", action="store_true")
    destination.add_argument("--output", help="RTMP, SRT, UDP, or file destination")
    parser.add_argument(
        "--transcode",
        action="store_true",
        help="Re-encode instead of copying the camera's H.264/AAC streams",
    )
    parser.add_argument("--restart-delay", type=float, default=2.0)
    parser.add_argument(
        "--wifi-ssid",
        help="Optionally join the GoPro Wi-Fi before starting (macOS only)",
    )
    parser.add_argument("--wifi-interface", default="en0")
    parser.add_argument("--wifi-password-env", default="GOPRO_WIFI_PASSWORD")
    args = parser.parse_args()
    return Config(**vars(args))


def main() -> int:
    config = parse_args()
    required = "ffplay" if config.preview else "ffmpeg"
    if not shutil.which(required):
        raise RuntimeError(f"{required} is not installed or not on PATH")

    connect_wifi(config)

    stopping = threading.Event()

    def stop_handler(_signum: int, _frame: object) -> None:
        stopping.set()

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    keepalive = threading.Thread(
        target=keepalive_loop,
        args=(config.camera_ip, stopping),
        name="gopro-keepalive",
        daemon=True,
    )
    keepalive.start()

    command = build_media_command(config)
    while not stopping.is_set():
        log(f"starting {required} (input UDP :{config.listen_port})")
        process = subprocess.Popen(command)
        try:
            # Give the receiver time to bind before asking the camera to transmit.
            time.sleep(0.5)
            start_camera(config.camera_ip)
            while process.poll() is None and not stopping.wait(0.5):
                pass
        except (OSError, urllib.error.URLError) as error:
            log(f"camera connection failed: {error}")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
            exit_code = process.poll()

        if stopping.is_set():
            break
        log(f"media process exited with code {exit_code}; restarting")
        stopping.wait(config.restart_delay)

    stopping.set()
    keepalive.join(timeout=3)
    log("gateway stopped")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2)
