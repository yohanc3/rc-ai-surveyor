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
                   6-second batch (3 frames, newest only)
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
app/gemini_analyzer.py   google-genai call, concise prompt, recent observations
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
- Live Gemini receives three frames per six-second request by default and has
  the five most recent validated observations available to avoid repetition.
- Technical notes are concise; spoken narration is a short first-person update.
- Every analysis carries one id through logs, SSE and the audio URL.
- All durations use the monotonic clock, so a system clock step cannot distort
  a reported rate or age.

## Running it

Two phases, because the GoPro's Wi-Fi has no internet:

```bash
python3 run.py --setup   # online once: Docker image + dashboard build
python3 run.py           # on the GoPro network: needs nothing from the net
```

On Windows under WSL2, substitute `./start.sh` for `python3 run.py`. It runs
`run.py` under `.venv/bin/python`, the only interpreter that can import
`google-genai` on a PEP 668 distribution, and wraps the call in `sg docker`
when the shell has not yet picked up the `docker` group. Mock mode works under
either interpreter; live mode does not. The README's Windows section covers the
rest of that path, including the inbound UDP firewall rule the camera stream
needs.

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

47 tests, standard library only: no pip install, no network, no camera. They
cover batching and backpressure accounting, the retry policy, speech
de-duplication and cooldown, every endpoint, SSE delivery and reconnect, and
path traversal on both static files and audio ids. One integration test drives
the real pipeline behind the real HTTP server.

## Known gaps

- **Live Gemini analysis has been exercised successfully.** Frames from the
  GoPro reached Gemini and produced successful responses.
- **Live ElevenLabs synthesis has now also succeeded**, on Linux/WSL with the
  default certificate store: four narrations, zero failures, 143-154 kB MP3s.
  The TLS verification failure recorded earlier was specific to macOS trust
  configuration, not to the request construction; see `app/tls.py`.
- The GoPro sampling path has run end to end, though startup emitted transient
  MPEG-TS/H.264 warnings before frames began flowing.
- Measured provider latency is far above the mock assumption. See
  [First live run](#first-live-run). That run predates the current 0.5 fps,
  six-second batch defaults, which were chosen to address exactly this.
- Deliberate deviations from the proposal: the stdlib HTTP server is kept
  instead of FastAPI, and ElevenLabs is called over plain HTTP instead of its
  SDK. Both keep mock mode free of third-party dependencies, which is what lets
  the system run offline.
- Audio is served whole, with no HTTP range support. Fine for short clips.

## First live run

Recorded 2026-10-03 on Windows 11 / WSL2 Ubuntu 24.04, HERO7 Silver over its
own Wi-Fi with a USB-tethered phone supplying the second route. This was the
first execution of ElevenLabs end to end, and it ran at the old 2 fps,
one-second, two-frame cadence — before the 0.5 fps six-second defaults. The
latency figures still hold; the backpressure ratio no longer does.

| Stage | Measured |
| --- | --- |
| Gemini vision | 2496–3918 ms per two-frame batch |
| ElevenLabs TTS | 645–778 ms, 143–154 kB per MP3 |
| Frame sampling | 1.8 fps sustained, no relay restarts |
| Speech | 4 succeeded, 0 failed |
| Backpressure | 8 batches created, 4 dropped |

Gemini described the scene accurately, including objects outside the prompt's
survey vocabulary, so the two-frame inline JPEG request shape works as designed.

The result that matters is the latency. `MockVisionAnalyzer` assumes 600 ms;
the real model takes about five times that. One request in flight plus a
one-second batch window means the sampler produces batches faster than analysis
consumes them, and the newest-wins rule discards the excess — hence 4 dropped
of 8. The pipeline behaves correctly under that load, but narration trails the
live video by roughly three seconds, and half of the analysis spend is
discarded by design.

The 0.5 fps, six-second, three-frame defaults now on main are the response to
exactly this, and they should eliminate the drop ratio above. Gating analysis
on scene change, listed as an open question in design document section 14,
would address the cause rather than the symptom.

Windows/WSL2 environment notes from the same session, each of which cost time:

- `docker_image_present()` runs `docker image inspect` and treats any non-zero
  exit as a missing image. A permission error from an unjoined `docker` group
  therefore reports "the image is not downloaded", pointing at the wrong fix.
- The HERO7 streams MPEG-TS over **UDP** to port 8554. A host firewall allowing
  only TCP on that port drops every frame while leaving the camera's HTTP
  control endpoint reachable, so the camera check passes and no video arrives.
- Running `run.py` once under `sudo` creates a root-owned `var/`, after which
  the audio store fails with `PermissionError` on every narration while the
  rest of the pipeline continues normally.
