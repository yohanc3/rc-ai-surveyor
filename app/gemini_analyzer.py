"""Gemini vision analysis (design document section 6)."""

from __future__ import annotations

import asyncio
import json
import logging

from .config import Config
from .models import Analysis, AnalysisError, FrameBatch, SchemaValidationError

log = logging.getLogger("rc.gemini")

SYSTEM_PROMPT = """\
You are the vision stage of a remote-controlled survey robot. You receive one \
or more camera frames and report only what is visibly supported by them.

Return exactly two fields.

technical_description: concise, factual and domain-oriented. At most two short \
sentences. Use precise wording an inspector would use.

narration_text: natural spoken language for a non-specialist listener. Normally \
at most three short sentences. It will be read aloud by a text-to-speech voice, \
so write numbers, units, abbreviations and symbols as words ("twenty \
centimetres", not "20cm").

Rules:
- Describe only what is visible as evidence in the frames.
- State uncertainty explicitly rather than guessing.
- Do not infer identity, protected traits, intent, ownership, or anything not \
present in the images.
- You may compare the frames, but do not claim motion unless the evidence \
supports it.
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "technical_description": {"type": "string"},
        "narration_text": {"type": "string"},
    },
    "required": ["technical_description", "narration_text"],
}


def parse_analysis_response(payload: str, batch: FrameBatch) -> Analysis:
    """Validate a model response against the required schema.

    Kept free of SDK types so it can be tested without network access.
    """
    if not payload or not payload.strip():
        raise SchemaValidationError("empty response from Gemini")

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as error:
        raise SchemaValidationError(f"response was not valid JSON: {error}") from error

    if not isinstance(data, dict):
        raise SchemaValidationError(f"expected a JSON object, got {type(data).__name__}")

    missing = [key for key in RESPONSE_SCHEMA["required"] if key not in data]
    if missing:
        raise SchemaValidationError(f"response missing required field(s): {', '.join(missing)}")

    values = {}
    for key in RESPONSE_SCHEMA["required"]:
        value = data[key]
        if not isinstance(value, str):
            raise SchemaValidationError(f"{key} must be a string, got {type(value).__name__}")
        value = value.strip()
        if not value:
            raise SchemaValidationError(f"{key} must not be empty")
        values[key] = value

    return Analysis(
        analysis_id=batch.analysis_id,
        frame_sequences=batch.sequences,
        captured_at=batch.captured_at,
        technical_description=values["technical_description"],
        narration_text=values["narration_text"],
    )


class GeminiVisionAnalyzer:
    """Calls Gemini through the official google-genai SDK.

    The SDK is imported lazily so mock mode needs neither the package nor a key.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        try:
            from google import genai  # noqa: PLC0415
        except ImportError as error:
            raise AnalysisError(
                "google-genai is not installed. Run 'pip install google-genai' "
                "while online, or use PROVIDER_MODE=mock."
            ) from error
        self._client = genai.Client(api_key=self._config.gemini_api_key)
        return self._client

    def _build_config(self):
        from google.genai import types  # noqa: PLC0415

        kwargs = {
            "system_instruction": SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "response_schema": RESPONSE_SCHEMA,
        }
        # Thinking controls moved between SDK releases; a mismatch must not stop
        # the request, since this task only ever wants minimal thinking.
        level = self._config.gemini_thinking_level
        if level:
            try:
                kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=level)
            except (TypeError, ValueError, AttributeError):
                log.debug("thinking_level=%s unsupported by this SDK; omitting", level)
        return types.GenerateContentConfig(**kwargs)

    def _build_contents(self, batch: FrameBatch):
        from google.genai import types  # noqa: PLC0415

        parts = [
            types.Part.from_bytes(data=frame.jpeg, mime_type="image/jpeg")
            for frame in batch.frames
        ]
        parts.append(
            types.Part.from_text(
                text=(
                    f"These {len(batch.frames)} frames were captured over "
                    f"{self._config.analysis_batch_seconds:g} second(s) of travel. "
                    "Describe what is visible."
                )
            )
        )
        return parts

    async def analyze(self, batch: FrameBatch) -> Analysis:
        client = self._ensure_client()
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=self._config.gemini_model,
                    contents=self._build_contents(batch),
                    config=self._build_config(),
                ),
                timeout=self._config.gemini_timeout_seconds,
            )
        except asyncio.TimeoutError as error:
            raise AnalysisError(
                f"Gemini timed out after {self._config.gemini_timeout_seconds:g}s"
            ) from error
        except AnalysisError:
            raise
        except Exception as error:  # SDK raises a wide range of transport errors
            raise AnalysisError(f"Gemini request failed: {type(error).__name__}: {error}") from error

        return parse_analysis_response(getattr(response, "text", "") or "", batch)
