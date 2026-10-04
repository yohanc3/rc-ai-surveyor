"""One-shot ElevenLabs text-to-speech smoke test."""

import argparse
import os
import urllib.error
import urllib.request
from pathlib import Path

from app.config import PROJECT_DIR, load_env_file
from app.tls import verified_context


def check_connection(api_key: str) -> int:
    """Read account metadata without generating or playing speech."""
    request = urllib.request.Request(
        "https://api.elevenlabs.io/v1/user/subscription",
        headers={"xi-api-key": api_key},
    )
    try:
        with urllib.request.urlopen(
            request, timeout=10, context=verified_context()
        ) as response:
            print(f"ElevenLabs reachable; account access confirmed (HTTP {response.status}).")
        return 0
    except urllib.error.HTTPError as error:
        print(f"ElevenLabs reachable (HTTP {error.code}).")
        if error.code in (401, 403):
            print("Check key validity, endpoint permissions, and IP allowlisting. "
                  "A restricted TTS key may not permit this account check.")
        else:
            print("The provider returned an HTTP error; try again later.")
        return 1
    except OSError as error:
        print(f"ElevenLabs connection failed before an HTTP response: {error}")
        print("Key validity is unknown. Try a different internet connection; "
              "a TLS reset can indicate hostname filtering on the network path.")
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="check HTTPS/account access without generating speech")
    args = parser.parse_args()
    load_env_file(PROJECT_DIR / ".env")

    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(
            "ELEVENLABS_API_KEY is not set. Add it to .env or export it first."
        )

    if args.check:
        raise SystemExit(check_connection(api_key))

    try:
        import httpx
        from elevenlabs.client import ElevenLabs
        from elevenlabs.core.api_error import ApiError
        from elevenlabs.play import play
    except ImportError as error:
        raise SystemExit(
            "The ElevenLabs SDK is not installed. Run: "
            "python3 -m pip install elevenlabs"
        ) from error

    client = ElevenLabs(api_key=api_key, timeout=20)
    text = os.getenv(
        "ELEVENLABS_TEST_TEXT",
        "The first move is what sets everything in motion.",
    )
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "").strip() or "JBFqnCBsd6RMkjVDRZzb"
    model_id = os.getenv("ELEVENLABS_MODEL_ID", "").strip() or "eleven_v3"

    print(f"Requesting ElevenLabs speech with model {model_id}...")
    try:
        # Consume the lazy iterator before claiming audio has arrived.
        # Do not retry a paid POST: a lost response may already be charged.
        audio_bytes = b"".join(
            client.text_to_speech.convert(
                text=text,
                voice_id=voice_id,
                model_id=model_id,
                output_format="mp3_44100_128",
                request_options={"max_retries": 0},
            )
        )
    except httpx.TransportError as error:
        raise SystemExit(
            f"ElevenLabs transport failed ({type(error).__name__}). "
            "Run python3 test.py --check to test connectivity without generating "
            "speech. Try phone tethering or ask the network administrator to "
            "allow api.elevenlabs.io on TCP 443."
        ) from None
    except ApiError as error:
        detail = str(error.body).replace(api_key, "[REDACTED]")[:400]
        raise SystemExit(f"ElevenLabs HTTP {error.status_code}: {detail}") from None

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
