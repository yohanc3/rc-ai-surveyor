# Implementation Notes

Status: implemented
Last updated: 2026-10-03

This describes what the code **actually does today**.
[AI_PIPELINE_DESIGN.md](AI_PIPELINE_DESIGN.md) is the proposal it was built
from; where the two disagree, this file wins.

## What runs

```text
GoPro (UDP MPEG-TS/H.264, 10.5.5.9)
         |
    FFmpeg stream copy          <- no re-encode, so no added latency
         |
      MediaMTX (Docker)
       /          \
  browser WebRTC   frame sampler (0.5 fps JPEG)
   (live video)         |
                   2-second batch (1 frame, newest only)
                        |
                   Gemini vision  -> technical + narration text -> SSE
                        |
                   ElevenLabs TTS -> MP3 -> /api/audio/{id}.mp3
```

The two branches share only MediaMTX. Nothing on the analysis side can delay
the live video.

## Module map

```text
run.py                   CLI, process lifecycle, camera, Docker, FFmpeg, sampler
app/config.py            env + .env loading, validation, redacted logging
app/models.py            Frame, FrameBatch, Analysis, AudioResult, ids, health
app/frame_pipeline.py    batching, bounded workers, retry and speech policy
app/providers.py         VisionAnalyzer / SpeechSynthesizer protocols + mocks
app/gemini_analyzer.py   google-genai call, prompt, response validation
app/elevenlabs_tts.py    streaming TTS over plain HTTP
app/audio_store.py       atomic publish, retention ring, id validation
app/events.py            fan-out bus behind the SSE endpoint
app/state.py             thread-safe snapshot shared by everything
app/server.py            dashboard, status, SSE, audio, frame endpoints
frontend/                React dashboard (Vite)
static/                  dependency-free fallback dashboard
tests/                   45 stdlib unittest tests
```

## Endpoints

| Path | Returns |
| --- | --- |
| `GET /` | the dashboard |
| `GET /api/config` | WHEP URL, fallback player URL, sample rate, provider mode |
| `GET /api/status` | service health, frame and pipeline metrics, latest analysis and audio |
| `GET /api/events` | SSE stream of `analysis`, `audio_ready`, `health` |
| `GET /api/audio/{analysis_id}.mp3` | generated narration audio |
| `GET /api/frame` | most recent sampled JPEG (`503` before the first frame) |

Connecting to `/api/events` replays the current analysis and audio, so a
reconnecting browser is immediately consistent.

## Rules the pipeline enforces

- One Gemini request in flight; at most one pending batch, always the newest.
  A burst collapses to the latest batch and the rest are dropped and counted.
- One ElevenLabs request in flight; only the newest pending narration.
- Identical narration is never synthesized twice.
- A minimum speech interval (default 3 s). Audio already playing is never
  interrupted; a newer clip replaces only what is queued and unplayed.
- Transient provider errors retry once with jitter. Schema rejections never
  retry; the dashboard degrades and keeps the last good text.
- Mock vision output explicitly says it is not derived from camera pixels;
  frame-grounded descriptions require live Gemini mode.
- Every analysis carries one id through logs, SSE and the audio URL.
- All durations use the monotonic clock, so a system clock step cannot distort
  a reported rate or age.

## Running it

Two phases, because the GoPro's Wi-Fi has no internet:

```bash
python3 run.py --setup   # online once: Docker image + dashboard build
python3 run.py           # on the GoPro network: needs nothing from the net
```

With the default `PROVIDER_MODE=mock`, the whole pipeline runs offline with no
API key and no third-party package. `PROVIDER_MODE=live` calls the real
providers and additionally needs an internet route (ethernet or tethering)
alongside the camera Wi-Fi.

Configuration comes from the environment or a git-ignored `.env`; see the
README. Keys are never logged or sent to the browser.

## Frontend

React in `frontend/`, served from `frontend/dist` by `run.py` once built;
`static/` is used when no build exists. Panels are registered in
`frontend/src/panels/registry.js` — add a component and one line. The demo mode
(`?demo=1`, or no backend reachable) generates a synthetic feed, telemetry and
analysis text in the browser, so the whole UI is explorable with no hardware.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

46 tests, standard library only: no pip install, no network, no camera. They
cover batching and backpressure accounting, the retry policy, speech
de-duplication and cooldown, every endpoint, SSE delivery and reconnect, and
path traversal on both static files and audio ids. One integration test drives
the real pipeline behind the real HTTP server.

## Known gaps

- **Live Gemini analysis has been exercised successfully.** Frames from the
  GoPro reached Gemini and produced successful responses. The live ElevenLabs
  request failed TLS certificate verification before HTTP/authentication; the
  existing `certifi` bundle validated a TLS handshake when selected via
  `SSL_CERT_FILE`, but a successful TTS response still needs confirmation.
- The GoPro sampling path has run end to end, though startup emitted transient
  MPEG-TS/H.264 warnings before frames began flowing.
- Deliberate deviations from the proposal: the stdlib HTTP server is kept
  instead of FastAPI, and ElevenLabs is called over plain HTTP instead of its
  SDK. Both keep mock mode free of third-party dependencies, which is what lets
  the system run offline.
- Audio is served whole, with no HTTP range support. Fine for short clips.
