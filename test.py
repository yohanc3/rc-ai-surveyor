"""One-shot ElevenLabs text-to-speech smoke test."""

import os
import time
from pathlib import Path

from app.config import PROJECT_DIR, load_env_file


def main() -> None:
    load_env_file(PROJECT_DIR / ".env")

    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(
            "ELEVENLABS_API_KEY is not set. Add it to .env or export it first."
        )

    try:
        import httpx
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

    audio_bytes: bytes | None = None
    last_transport_error: Exception | None = None
    for attempt in range(1, 4):
        print(
            f"Requesting ElevenLabs speech with model {model_id} "
            f"(attempt {attempt}/3)..."
        )
        try:
            # convert() returns a lazy iterator. Joining it performs the network
            # request now, before we claim that audio was received.
            audio_bytes = b"".join(
                client.text_to_speech.convert(
                    text=text,
                    voice_id=voice_id,
                    model_id=model_id,
                    output_format="mp3_44100_128",
                )
            )
            break
        except httpx.TransportError as error:
            last_transport_error = error
            if attempt < 3:
                print(f"Connection failed ({error}); retrying...")
                time.sleep(attempt)

    if audio_bytes is None:
        raise SystemExit(
            "Could not connect to ElevenLabs after 3 attempts. The request did "
            "not reach an HTTP response, so this is not an API-key rejection. "
            "The ElevenLabs domain is being reset by the current network path. "
            "Try iPhone USB tethering, another network, or disabling any VPN, "
            f"firewall, or web filter. Last error: {last_transport_error}"
        )

    if not audio_bytes:
        raise SystemExit("ElevenLabs returned an empty audio response.")

    output_path = Path(
        os.getenv("ELEVENLABS_TEST_OUTPUT", PROJECT_DIR / "var" / "elevenlabs-test.mp3")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio_bytes)

    print(f"Audio received ({len(audio_bytes)} bytes) and saved to {output_path}.")
    print("Playing it now...")
    try:
        play(audio_bytes)
    except ValueError as error:
        raise SystemExit(
            f"Audio was saved successfully, but playback failed: {error}"
        ) from error


if __name__ == "__main__":
    main()
