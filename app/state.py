"""Thread-safe snapshot shared by the sampler, pipeline, and dashboard."""

from __future__ import annotations

import threading
import time
from collections import deque

from .models import Analysis, AudioResult, ServiceHealth, iso

STALE_FRAME_SECONDS = 3.0
FPS_WINDOW = 32

SERVICES = ("camera", "video", "gemini", "elevenlabs")


class PipelineState:
    def __init__(self, config, media_url: str, whep_url: str) -> None:
        self._skills = None
        self._lock = threading.Lock()
        self._config = config
        self._media_url = media_url
        self._whep_url = whep_url
        # Wall clock is for display only; every duration uses the monotonic
        # clock so an NTP step cannot distort a rate or an age.
        self._started_at = time.monotonic()

        self._frame_count = 0
        self._last_frame_wall: float | None = None
        self._last_frame_mono: float | None = None
        self._last_frame_bytes = 0
        self._last_frame: bytes | None = None
        self._frame_times: deque[float] = deque(maxlen=FPS_WINDOW)

        self._relay_up = False
        self._relay_restarts = 0

        self._latest_analysis: Analysis | None = None
        self._latest_audio: AudioResult | None = None

        self._health = {name: ServiceHealth() for name in SERVICES}
        if not config.is_live:
            for name in ("gemini", "elevenlabs"):
                self._health[name].set("ok", "mock provider")

        self._pipeline = None

    def attach_skills(self, skills) -> None:
        """Hand the state the skill registry so the API can report it."""
        self._skills = skills

    def attach_pipeline(self, pipeline) -> None:
        self._pipeline = pipeline

    # ---------- frames ----------

    def record_frame(self, frame: bytes) -> int:
        wall = time.time()
        now = time.monotonic()
        with self._lock:
            self._frame_count += 1
            self._last_frame_wall = wall
            self._last_frame_mono = now
            self._last_frame_bytes = len(frame)
            self._last_frame = frame
            self._frame_times.append(now)
            return self._frame_count

    def latest_frame(self) -> tuple[int, bytes | None]:
        with self._lock:
            return self._frame_count, self._last_frame

    # ---------- relay ----------

    def set_relay_up(self, up: bool) -> None:
        with self._lock:
            self._relay_up = up
        self._health["video"].set("ok" if up else "down", "" if up else "relay not running")

    def record_relay_restart(self) -> None:
        with self._lock:
            self._relay_restarts += 1

    # ---------- analysis ----------

    def set_analysis(self, analysis: Analysis) -> None:
        with self._lock:
            self._latest_analysis = analysis

    def set_audio(self, audio: AudioResult) -> None:
        with self._lock:
            self._latest_audio = audio

    def health(self, service: str) -> ServiceHealth:
        return self._health[service]

    # ---------- snapshot ----------

    def config_json(self) -> dict:
        return {
            "media_url": self._media_url,
            "whep_url": self._whep_url,
            "sample_fps": self._config.analysis_fps,
            "provider_mode": self._config.provider_mode,
            "tts_min_interval_seconds": self._config.tts_min_interval_seconds,
            "skills": self._skills.to_json() if self._skills else None,
        }

    def snapshot(self) -> dict:
        now = time.monotonic()
        with self._lock:
            measured_fps = 0.0
            if len(self._frame_times) >= 2:
                span = self._frame_times[-1] - self._frame_times[0]
                if span > 0:
                    measured_fps = (len(self._frame_times) - 1) / span
            frame_age = None if self._last_frame_mono is None else now - self._last_frame_mono
            analysis = self._latest_analysis
            audio = self._latest_audio
            snapshot = {
                "uptime_seconds": now - self._started_at,
                "provider_mode": self._config.provider_mode,
                "active_skill": self._skills.active().id if self._skills else None,
                "frames": {
                    "captured": self._frame_count,
                    "last_sequence": self._frame_count,
                    "last_bytes": self._last_frame_bytes,
                    "last_age_seconds": frame_age,
                    "last_captured_at": self._last_frame_wall,
                    "measured_fps": round(measured_fps, 2),
                    "configured_fps": self._config.analysis_fps,
                    "stale": frame_age is not None and frame_age > STALE_FRAME_SECONDS,
                },
                "relay": {"up": self._relay_up, "restarts": self._relay_restarts},
            }

        snapshot["services"] = {name: h.to_json() for name, h in self._health.items()}
        snapshot["latest_analysis"] = analysis.to_event() if analysis else None
        snapshot["latest_audio"] = audio.to_event() if audio else None

        pipeline = self._pipeline
        if pipeline is not None:
            metrics = pipeline.metrics.to_json()
            metrics["pending_batches"] = pipeline.pending_batches
            snapshot["metrics"] = metrics
        else:
            snapshot["metrics"] = {}
        return snapshot
