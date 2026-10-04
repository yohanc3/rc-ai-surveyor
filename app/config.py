"""Validated environment and CLI configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent

MOCK = "mock"
LIVE = "live"


class ConfigError(RuntimeError):
    """Configuration is missing or contradictory."""


def load_env_file(path: Path) -> None:
    """Minimal .env reader so secrets never have to be typed on the command line.

    Values already present in the real environment win, so an explicit export
    always overrides the file.
    """
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as error:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from error


def _int(name: str, default: int) -> int:
    return int(_float(name, default))


@dataclass(frozen=True)
class Config:
    provider_mode: str

    gemini_api_key: str
    gemini_model: str
    gemini_thinking_level: str
    gemini_timeout_seconds: float

    elevenlabs_api_key: str
    elevenlabs_voice_id: str
    elevenlabs_model_id: str
    elevenlabs_timeout_seconds: float

    analysis_fps: float
    analysis_batch_seconds: float
    tts_min_interval_seconds: float
    audio_retention: int
    audio_dir: Path

    @property
    def is_live(self) -> bool:
        return self.provider_mode == LIVE

    @property
    def frames_per_batch(self) -> int:
        """How many frames make up one complete batching window."""
        return max(1, round(self.analysis_fps * self.analysis_batch_seconds))

    def redacted(self) -> dict:
        """Safe to log: never includes key material."""
        return {
            "provider_mode": self.provider_mode,
            "gemini_model": self.gemini_model,
            "gemini_thinking_level": self.gemini_thinking_level,
            "elevenlabs_model_id": self.elevenlabs_model_id,
            "elevenlabs_voice_id": self.elevenlabs_voice_id or "(unset)",
            "analysis_fps": self.analysis_fps,
            "analysis_batch_seconds": self.analysis_batch_seconds,
            "tts_min_interval_seconds": self.tts_min_interval_seconds,
            "gemini_api_key": "set" if self.gemini_api_key else "unset",
            "elevenlabs_api_key": "set" if self.elevenlabs_api_key else "unset",
        }


def load_config(sample_fps: float | None = None, provider_mode: str | None = None) -> Config:
    load_env_file(PROJECT_DIR / ".env")

    mode = (provider_mode or os.environ.get("PROVIDER_MODE") or MOCK).strip().lower()
    if mode not in (MOCK, LIVE):
        raise ConfigError(f"PROVIDER_MODE must be '{MOCK}' or '{LIVE}', got {mode!r}")

    analysis_fps = sample_fps if sample_fps is not None else _float("ANALYSIS_FPS", 0.5)
    if analysis_fps <= 0:
        raise ConfigError("analysis FPS must be greater than zero")

    batch_seconds = _float("ANALYSIS_BATCH_SECONDS", 2.0)
    if batch_seconds <= 0:
        raise ConfigError("ANALYSIS_BATCH_SECONDS must be greater than zero")

    config = Config(
        provider_mode=mode,
        gemini_api_key=os.environ.get("GEMINI_API_KEY", "").strip(),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip(),
        gemini_thinking_level=os.environ.get("GEMINI_THINKING_LEVEL", "low").strip(),
        gemini_timeout_seconds=_float("GEMINI_TIMEOUT_SECONDS", 20.0),
        elevenlabs_api_key=os.environ.get("ELEVENLABS_API_KEY", "").strip(),
        elevenlabs_voice_id=os.environ.get("ELEVENLABS_VOICE_ID", "").strip(),
        elevenlabs_model_id=os.environ.get("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5").strip(),
        elevenlabs_timeout_seconds=_float("ELEVENLABS_TIMEOUT_SECONDS", 20.0),
        analysis_fps=analysis_fps,
        analysis_batch_seconds=batch_seconds,
        tts_min_interval_seconds=_float("TTS_MIN_INTERVAL_SECONDS", 3.0),
        audio_retention=_int("AUDIO_RETENTION", 10),
        audio_dir=Path(os.environ.get("AUDIO_DIR", str(PROJECT_DIR / "var" / "audio"))),
    )

    if config.is_live:
        missing = []
        if not config.gemini_api_key:
            missing.append("GEMINI_API_KEY")
        if not config.elevenlabs_api_key:
            missing.append("ELEVENLABS_API_KEY")
        if not config.elevenlabs_voice_id:
            missing.append("ELEVENLABS_VOICE_ID")
        if missing:
            raise ConfigError(
                "PROVIDER_MODE=live requires " + ", ".join(missing)
                + ". Set them in .env, or run with PROVIDER_MODE=mock."
            )

    return config
