"""Frame, analysis, and event types shared across the pipeline."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Crockford base32, as used by ULID.
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


_id_lock = threading.Lock()
_last_ms = 0
_last_rand = 0
_RAND_MAX = (1 << 80) - 1


def new_analysis_id() -> str:
    """A ULID-style identifier: lexicographically sortable by creation time.

    Ids minted within the same millisecond stay ordered by incrementing the
    random component rather than drawing a fresh one, because the dashboard
    decides whether an event is newer by comparing these strings.
    """
    global _last_ms, _last_rand
    with _id_lock:
        now_ms = int(time.time() * 1000)
        if now_ms == _last_ms:
            _last_rand = (_last_rand + 1) & _RAND_MAX
        else:
            _last_ms = now_ms
            _last_rand = secrets.randbits(80)
        value = (now_ms << 80) | _last_rand

    chars = []
    for _ in range(26):
        chars.append(_ALPHABET[value & 0b11111])
        value >>= 5
    return "".join(reversed(chars))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    """RFC 3339 with a trailing Z, matching the design document's examples."""
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Frame:
    """One sampled JPEG, timestamped at capture time."""

    sequence: int
    jpeg: bytes
    captured_at: datetime
    captured_mono: float

    @property
    def size(self) -> int:
        return len(self.jpeg)


@dataclass(frozen=True)
class FrameBatch:
    """The frames from one batching window, analysed as a single request."""

    analysis_id: str
    frames: tuple[Frame, ...]
    created_mono: float

    @property
    def sequences(self) -> list[int]:
        return [frame.sequence for frame in self.frames]

    @property
    def captured_at(self) -> datetime:
        return self.frames[0].captured_at

    def age_ms(self, now_mono: float) -> int:
        return int((now_mono - self.frames[-1].captured_mono) * 1000)


@dataclass(frozen=True)
class Analysis:
    """A validated Gemini response."""

    analysis_id: str
    frame_sequences: list[int]
    captured_at: datetime
    technical_description: str
    narration_text: str

    def to_event(self) -> dict:
        return {
            "type": "analysis",
            "analysis_id": self.analysis_id,
            "frame_sequences": self.frame_sequences,
            "captured_at": iso(self.captured_at),
            "technical_description": self.technical_description,
            "narration_text": self.narration_text,
        }


@dataclass(frozen=True)
class AudioResult:
    """A generated narration clip that is ready to serve."""

    analysis_id: str
    audio_url: str
    byte_count: int

    def to_event(self) -> dict:
        return {
            "type": "audio_ready",
            "analysis_id": self.analysis_id,
            "audio_url": self.audio_url,
        }


class AnalysisError(Exception):
    """A provider call failed. Treated as transient and retried once."""


class SchemaValidationError(AnalysisError):
    """A provider replied, but the response does not satisfy the contract.

    Never retried: the same request would produce the same rejection.
    """


@dataclass
class ServiceHealth:
    """One of the dashboard's Camera / Video / Gemini / ElevenLabs indicators."""

    state: str = "unknown"  # ok | degraded | down | disabled | unknown
    detail: str = ""
    updated_at: float = field(default_factory=time.monotonic)

    def set(self, state: str, detail: str = "") -> None:
        self.state = state
        self.detail = detail
        self.updated_at = time.monotonic()

    def to_json(self) -> dict:
        return {"state": self.state, "detail": self.detail}
