"""Provider protocols plus the mock implementations used offline.

Mock mode satisfies acceptance criterion 13.8: the system runs end to end with
no internet connection.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from .models import Analysis, AudioResult, FrameBatch, new_analysis_id

# One silent MPEG-1 Layer III frame: 128 kbps, 44.1 kHz, mono.
# 144 * 128000 / 44100 = 417 bytes per frame, of which 4 are the header.
_MP3_FRAME = bytes([0xFF, 0xFB, 0x90, 0xC4]) + b"\x00" * 413
_MP3_FRAMES_PER_SECOND = 44100 / 1152  # samples per second / samples per frame


def silent_mp3(seconds: float) -> bytes:
    """A valid, decodable MP3 of silence, for mock speech with no encoder."""
    count = max(1, int(seconds * _MP3_FRAMES_PER_SECOND))
    return _MP3_FRAME * count


class VisionAnalyzer(Protocol):
    async def analyze(self, batch: FrameBatch) -> Analysis: ...


class SpeechSynthesizer(Protocol):
    async def synthesize(self, analysis: Analysis) -> AudioResult: ...


class MockVisionAnalyzer:
    """Offline stand-in that clearly reports it does not inspect frame pixels."""

    def __init__(self, latency_seconds: float = 0.6, fail_every: int = 0) -> None:
        self._latency = latency_seconds
        self._fail_every = fail_every
        self._calls = 0

    async def analyze(self, batch: FrameBatch) -> Analysis:
        self._calls += 1
        await asyncio.sleep(self._latency)
        if self._fail_every and self._calls % self._fail_every == 0:
            raise RuntimeError("mock gemini failure")
        return Analysis(
            analysis_id=batch.analysis_id,
            frame_sequences=batch.sequences,
            captured_at=batch.captured_at,
            technical_description=(
                "Mock provider active; this description was not derived from the camera frame."
            ),
            narration_text=(
                "Mock mode is active, so I am not analyzing the camera image."
            ),
        )


class MockSpeechSynthesizer:
    """Stand-in for ElevenLabs. Produces real, playable MP3 silence."""

    def __init__(self, store, latency_seconds: float = 0.3) -> None:
        self._store = store
        self._latency = latency_seconds

    async def synthesize(self, analysis: Analysis) -> AudioResult:
        await asyncio.sleep(self._latency)
        # Roughly three words per second, so the clip length tracks the text.
        words = max(1, len(analysis.narration_text.split()))
        audio = silent_mp3(min(12.0, words / 3.0))
        return await asyncio.to_thread(self._store.publish, analysis.analysis_id, audio)
