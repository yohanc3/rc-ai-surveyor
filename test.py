"""One-shot ElevenLabs text-to-speech smoke test."""

import os

from app.config import PROJECT_DIR, load_env_file


def main() -> None:
    load_env_file(PROJECT_DIR / ".env")

    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(
            "ELEVENLABS_API_KEY is not set. Add it to .env or export it first."
        )

    try:
        from elevenlabs.client import ElevenLabs
        from elevenlabs.play import play
    except ImportError as error:
        raise SystemExit(
            "The ElevenLabs SDK is not installed. Run: "
            "python3 -m pip install elevenlabs"
        ) from error

    client = ElevenLabs(api_key=api_key)
    text = os.getenv(
        "ELEVENLABS_TEST_TEXT",
        "The first move is what sets everything in motion.",
    )
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
    model_id = os.getenv("ELEVENLABS_MODEL_ID", "eleven_v3")

    print(f"Requesting ElevenLabs speech with model {model_id}...")
    audio = client.text_to_speech.convert(
        text=text,
        voice_id=voice_id,
        model_id=model_id,
        output_format="mp3_44100_128",
    )

    print("Audio received. Playing it now...")
    play(audio)


if __name__ == "__main__":
    main()
