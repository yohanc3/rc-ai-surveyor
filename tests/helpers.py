"""Shared test helpers."""

from __future__ import annotations

import os
import time

from app.config import load_config
from app.models import Frame, utc_now

JPEG = b"\xff\xd8" + b"test-frame-payload" * 8 + b"\xff\xd9"


def wait_until(predicate, timeout=6.0, interval=0.01, message="condition not met"):
    """Poll for a condition instead of sleeping a fixed amount.

    Fixed sleeps make these tests flaky on a loaded machine.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError(f"{message} (waited {timeout}s)")


def make_config(**overrides):
    for key in (
        "PROVIDER_MODE", "GEMINI_API_KEY", "ELEVENLABS_API_KEY",
        "ELEVENLABS_VOICE_ID", "ANALYSIS_FPS", "ANALYSIS_BATCH_SECONDS",
        "TTS_MIN_INTERVAL_SECONDS", "AUDIO_DIR", "AUDIO_RETENTION",
    ):
        os.environ.pop(key, None)
    os.environ.update({k: str(v) for k, v in overrides.items()})
    return load_config()


def make_frame(sequence: int) -> Frame:
    return Frame(
        sequence=sequence, jpeg=JPEG, captured_at=utc_now(), captured_mono=time.monotonic()
    )
