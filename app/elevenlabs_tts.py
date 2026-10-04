"""ElevenLabs streaming text-to-speech (design document section 7)."""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request

from .audio_store import AudioStore
from .config import Config
from .models import Analysis, AnalysisError, AudioResult
from .tls import verified_context

log = logging.getLogger("rc.elevenlabs")

API_ROOT = "https://api.elevenlabs.io/v1/text-to-speech"
OUTPUT_FORMAT = "mp3_44100_128"
CHUNK = 16 * 1024


def build_request(config: Config, text: str) -> urllib.request.Request:
    """Construct the streaming TTS request.

    Separated from the network call so the URL, headers and body can be checked
    without an API key. The key is set here and must never be logged.
    """
    if not text.strip():
        raise AnalysisError("refusing to synthesize empty narration")

    url = f"{API_ROOT}/{config.elevenlabs_voice_id}/stream?output_format={OUTPUT_FORMAT}"
    body = json.dumps(
        {"text": text, "model_id": config.elevenlabs_model_id}
    ).encode("utf-8")
    return urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "xi-api-key": config.elevenlabs_api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
    )


class ElevenLabsSpeechSynthesizer:
    """Streams narration audio and publishes it atomically."""

    def __init__(self, config: Config, store: AudioStore) -> None:
        self._config = config
        self._store = store

    def _fetch(self, text: str) -> bytes:
        request = build_request(self._config, text)
        chunks: list[bytes] = []
        try:
            with urllib.request.urlopen(
                request, timeout=self._config.elevenlabs_timeout_seconds,
                context=verified_context(),
            ) as response:
                while True:
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    chunks.append(chunk)
        except urllib.error.HTTPError as error:
            # The body may explain the failure, but it must not leak the key.
            detail = ""
            try:
                detail = error.read(512).decode("utf-8", "replace")
            except Exception:
                pass
            detail = detail.replace(self._config.elevenlabs_api_key, "[REDACTED]")
            raise AnalysisError(
                f"ElevenLabs returned HTTP {error.code}: {detail[:200]}"
            ) from error
        except urllib.error.URLError as error:
            raise AnalysisError(f"ElevenLabs unreachable: {error.reason}") from error
        except OSError as error:
            raise AnalysisError(f"ElevenLabs transport failed: {error}") from error

        audio = b"".join(chunks)
        if not audio:
            raise AnalysisError("ElevenLabs returned no audio")
        return audio

    async def synthesize(self, analysis: Analysis) -> AudioResult:
        audio = await asyncio.to_thread(self._fetch, analysis.narration_text)
        return await asyncio.to_thread(self._store.publish, analysis.analysis_id, audio)
