"""On-disk store for generated narration audio.

Files are streamed to a temporary name and atomically renamed, so the dashboard
can never fetch a half-written clip (design document section 7).
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path

from .models import AudioResult

VALID_ID = re.compile(r"^[0-9A-Z]{26}$")


class AudioStore:
    def __init__(self, directory: Path, retention: int = 10) -> None:
        self._dir = Path(directory)
        self._retention = max(1, retention)
        self._lock = threading.Lock()
        self._order: list[str] = []
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def directory(self) -> Path:
        return self._dir

    def publish(self, analysis_id: str, audio: bytes) -> AudioResult:
        if not VALID_ID.match(analysis_id):
            raise ValueError(f"refusing to write unexpected analysis id {analysis_id!r}")

        final = self._dir / f"{analysis_id}.mp3"
        tmp = self._dir / f".{analysis_id}.mp3.part"
        tmp.write_bytes(audio)
        os.replace(tmp, final)  # atomic within one filesystem

        with self._lock:
            if analysis_id not in self._order:
                self._order.append(analysis_id)
            stale = self._order[: -self._retention] if len(self._order) > self._retention else []
            self._order = self._order[-self._retention :]

        for old in stale:
            self._dir.joinpath(f"{old}.mp3").unlink(missing_ok=True)

        return AudioResult(
            analysis_id=analysis_id,
            audio_url=f"/api/audio/{analysis_id}.mp3",
            byte_count=len(audio),
        )

    def path_for(self, analysis_id: str) -> Path | None:
        """Resolve an id to a file, rejecting anything that is not a plain id."""
        if not VALID_ID.match(analysis_id):
            return None
        candidate = (self._dir / f"{analysis_id}.mp3").resolve()
        if self._dir.resolve() != candidate.parent or not candidate.is_file():
            return None
        return candidate

    def clear(self) -> None:
        with self._lock:
            ids = list(self._order)
            self._order.clear()
        for old in ids:
            self._dir.joinpath(f"{old}.mp3").unlink(missing_ok=True)
