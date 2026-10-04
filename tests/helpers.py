"""Shared test helpers."""

from __future__ import annotations

import os
import time
from unittest.mock import patch

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
    with patch.dict(os.environ, {}, clear=True), patch("app.config.load_env_file"):
        os.environ.update({key: str(value) for key, value in overrides.items()})
        return load_config()


def make_frame(sequence: int) -> Frame:
    return Frame(
        sequence=sequence, jpeg=JPEG, captured_at=utc_now(), captured_mono=time.monotonic()
    )
