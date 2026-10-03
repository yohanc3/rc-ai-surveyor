# RC AI Surveyor

Low-latency HERO7 Silver video with a backend frame pipeline.

```text
GoPro UDP/H.264 -> MediaMTX -+-> browser WebRTC (live video)
                             |
                             +-> frame sampler (2 FPS)
                                  -> 1-second batch (2 frames, newest only)
                                  -> Gemini vision analysis
                                  -> technical + narration text   -> SSE
                                  -> ElevenLabs streaming TTS     -> MP3
```

The live video and AI pipeline are separate consumers. Sampling or future model
work therefore does not add delay to the browser video.

## Run

Setup is split in two, because **the GoPro's Wi-Fi has no internet access**. The
Docker image, the npm packages and any API keys must all be in place *before*
you join the camera's network.

### Step 1 — online setup (needs internet, no GoPro)

Stay on your normal network. Install Docker and FFmpeg, then:

```bash
python3 run.py --setup
```

That downloads the `bluenviron/mediamtx` image, builds the dashboard
(`npm install && npm run build`), and validates the configuration. It is the
only step that touches the internet. Re-run it only when something changes.

### Step 2 — offline run (on the GoPro network)

1. Connect this machine's Wi-Fi to the GoPro's `GP...` network.
2. From this directory:

```bash
python3 run.py
```

The dashboard opens automatically at:

```text
http://127.0.0.1:8787/
```

Nothing in this step reaches the internet: with the default
`PROVIDER_MODE=mock`, the whole pipeline — video, frame sampling, analysis text
and narration audio — runs entirely offline. If the MediaMTX image is missing,
`run.py` says so and points you back at step 1 rather than hanging on a pull it
cannot complete.

Press `Ctrl+C` once to stop the camera relay, sampler, dashboard, and backend.

### Running the real providers

Gemini and ElevenLabs are cloud services, so live mode needs internet *while
running*, in addition to the GoPro Wi-Fi. Per design document section 4 that
means a second route — ethernet, USB phone tethering, or a second Wi-Fi adapter:

```bash
pip install google-genai          # online, during step 1
PROVIDER_MODE=live python3 run.py
```

Put the keys in a `.env` file beside `run.py` (it is git-ignored):

```text
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.8-flash
GEMINI_THINKING_LEVEL=low

ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=
ELEVENLABS_MODEL_ID=eleven_flash_v2_5

ANALYSIS_FPS=2
ANALYSIS_BATCH_SECONDS=1
TTS_MIN_INTERVAL_SECONDS=3
PROVIDER_MODE=mock
```

`run.py` refuses to start in live mode without the required keys, and refuses if
no internet route is present, rather than failing once frames are flowing.

### ElevenLabs smoke test

With `ELEVENLABS_API_KEY` in `.env` or the environment, run a one-shot billable
text-to-speech test:

```bash
python3 -m pip install elevenlabs
python3 test.py
```

It uses the configured `ELEVENLABS_VOICE_ID` and `ELEVENLABS_MODEL_ID`, falling
back to the example voice and `eleven_v3`, then plays the returned audio. Set
`ELEVENLABS_TEST_TEXT` to change the spoken sentence.

### Tests

```bash
python3 -m unittest discover -s tests -t .
```

Standard library only: no pip install, no network, no camera.

## Frontend

The dashboard is a React app in `frontend/`. `run.py` serves `frontend/dist`
when it exists and falls back to the dependency-free `static/` page when it does
not, so the tool still works before anyone runs npm.

### Develop

```bash
cd frontend
npm install
npm run dev          # http://127.0.0.1:5173, proxies /api to the Python backend
```

Run `python3 run.py` in another terminal for real camera data. Without it the app
drops into demo mode on its own. Point the proxy elsewhere with
`RC_BACKEND=http://host:8787 npm run dev`.

### Build

```bash
cd frontend && npm run build
```

`python3 run.py` then serves the built app at `http://127.0.0.1:8787/`.

### Demo mode

Append `?demo=1` to the URL, or just open the app with no backend running. A
mock generates an animated synthetic feed, telemetry, periodic relay blips and
sample analysis text, so the whole UI is explorable with no GoPro, no Docker and
no Python. The demo is clearly marked by a banner and a `demo data` badge.

### Layout

```text
frontend/src/
  App.jsx                   shell: header, badges, slots
  panels/registry.js        which panels exist and where they go
  panels/*.jsx              one file per panel
  backend/useBackend.js     SSE events + /api/status polling
  backend/mockBackend.js    demo data generator
  audio/useNarrationAudio.js  consent, playback, queue-newest-only
  video/useWhep.js          WebRTC (WHEP) client hook
  components/               Panel, Badge, Stat
  lib/format.js             byte/duration/age formatting
```

### Adding a panel

Panels are the extension point. Write a component taking
`{ status, config, analyses, latestAudio, frameUrl, mode }` and add one line to
`frontend/src/panels/registry.js`:

```jsx
export const PANELS = [
  // …
  { id: 'my-panel', slot: 'row', component: MyPanel },
];
```

`slot` is `stage` (large, beside the sidebar), `side` (narrow right column) or
`row` (full-width grid below). An optional `enabled: (ctx) => boolean` hides a
panel contextually. Nothing else needs to change.

Panels never need to know whether data is real or mocked — both sources produce
the same `status` shape.

### Endpoints

| Path | Returns |
| --- | --- |
| `GET /` | the dashboard |
| `GET /api/config` | WHEP URL, fallback player URL, sample rate, provider mode |
| `GET /api/status` | service health, frame and pipeline metrics, latest analysis and audio |
| `GET /api/events` | SSE stream of `analysis`, `audio_ready` and `health` events |
| `GET /api/audio/{analysis_id}.mp3` | generated narration audio |
| `GET /api/frame` | the most recent sampled JPEG (`503` until the first frame) |

All durations are measured on the monotonic clock, so a system clock adjustment
cannot distort a reported rate or age. On connect, `/api/events` replays the
current analysis and audio, so a reconnecting browser is immediately consistent.

### How the pipeline protects the live video

The WebRTC branch and the analysis branch share only MediaMTX. Cloud latency
cannot buffer the video path, and the analysis side is bounded at both stages:

- One Gemini request in flight, and at most one pending batch. A burst collapses
  to the **newest** batch; stale footage is dropped and counted, never queued.
- One ElevenLabs request in flight, only the newest pending narration, identical
  narration never synthesized twice, and a minimum speech interval.
- A clip that is already playing is never interrupted. A newer clip replaces
  whatever is queued and unplayed.
- Transient provider failures retry once with jitter. Schema rejections never
  retry; the dashboard shows a degraded state and keeps the last good text.

## Observability

Every analysis carries one id from capture through to audio, so a single run can
be followed end to end in the logs:

```text
frame_batch_ready analysis_id=01M4... frames=121,122 age_ms=18
gemini_complete analysis_id=01M4... latency_ms=740
analysis_published analysis_id=01M4...
elevenlabs_complete analysis_id=01M4... latency_ms=310 bytes=28440
audio_published analysis_id=01M4... url=/api/audio/01M4....mp3
```

Provider keys are never logged: configuration is printed through a redacting
view that reports only whether each key is set.

`GET /api/status` exposes the same counters the dashboard shows — frames
captured, batches created and dropped, pending queue depth, frame age at
submission, provider latencies, schema rejections, and audio bytes.

Use `--sample-fps` to change the analysis rate, and `--provider-mode` to switch
between mock and live without editing `.env`:

```bash
python3 run.py --sample-fps 1
python3 run.py --provider-mode mock
```

Press `Ctrl+C` once to stop the camera relay, sampler, dashboard, and backend.

## Design

See [Gemini Vision and ElevenLabs TTS Design](docs/AI_PIPELINE_DESIGN.md) for
the planned cloud-analysis, text, and browser-audio pipeline, and
[Implementation Notes](docs/IMPLEMENTATION.md) for what the code does today.
