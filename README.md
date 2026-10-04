# RC AI Surveyor

Low-latency HERO7 Silver video with a backend frame pipeline.

```text
GoPro UDP/H.264 -> MediaMTX -+-> browser WebRTC (live video)
                             |
                          +-> frame sampler (0.5 FPS)
                            -> 6-second batch (3 frames, newest only)
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
For live Gemini analysis, also install its SDK now:

```bash
python3 -m pip install google-genai
```

On Windows under WSL2 this fails with `externally-managed-environment`; use the
virtual environment described in [Windows — WSL2](#windows--wsl2) instead.

### Step 2 — connect and run

Connect the laptop to the GoPro's `GP...` Wi-Fi. For live AI, also provide
internet through USB phone tethering or Ethernet; the GoPro Wi-Fi itself has no
internet route. Live mode needs both network paths at the same time.

Create `.env` beside `run.py` before starting live mode:

```text
GEMINI_API_KEY=your-gemini-key
GEMINI_MODEL=gemini-3.8-flash
GEMINI_THINKING_LEVEL=low

ELEVENLABS_API_KEY=your-elevenlabs-key
ELEVENLABS_VOICE_ID=your-voice-id
ELEVENLABS_MODEL_ID=eleven_flash_v2_5

ANALYSIS_FPS=0.5
ANALYSIS_BATCH_SECONDS=6
TTS_MIN_INTERVAL_SECONDS=3
```

Use the voice ID from your ElevenLabs account, not the model name. The model
groups three sampled frames into one six-second description and short spoken
update, with the twenty latest observations supplied as context to reduce
repetition. That observation history resets when the app restarts.

For offline video and sampling without image analysis or real speech:

```bash
python3 run.py --provider-mode mock
```

For live Gemini analysis and ElevenLabs speech, use:

```bash
python3 run.py --provider-mode live
```

On macOS, the app automatically selects certifi's certificate bundle (or the
system CA bundle if certifi is unavailable). Existing `SSL_CERT_FILE` settings
are respected. No shell prefix is necessary.

See [COMMON_ISSUES.MD](COMMON_ISSUES.MD) for GoPro/iPhone USB routing,
certificate errors, and ElevenLabs connectivity troubleshooting.

Narration uses the user's playful "you are alive!!!" RC persona: brief emotional
reactions, casual slang, and lighthearted jokes about the surroundings. The last
twenty analysis messages (technical text and narration) provide continuity and
callbacks within a session. Routine driving stays in the background.
When Gemini returns "Nothing new to report.", the text can update but no new
speech is generated. Technical descriptions remain concise and factual.

The dashboard opens at:

```text
http://127.0.0.1:8787/
```

In live mode, click **Enable audio** once in the dashboard. The native audio
player also lets you replay the latest generated clip. Successful synthesis is
logged as `elevenlabs_complete` followed by `audio_published`; `/api/status`
reports the latest audio and speech counters.

Press `Ctrl+C` once to stop the camera relay, sampler, dashboard, and backend.

The `.env` file is git-ignored. `run.py` refuses live mode when required keys
are missing. A failed TCP DNS connectivity probe is only a warning: cellular
networks can block that probe while provider HTTPS still works. Provider
requests report actual failures. If the MediaMTX image is missing,
run `python3 run.py --setup` again while connected to regular internet.

### macOS — GoPro Wi-Fi plus iPhone USB

Keep Wi-Fi on the GoPro and iPhone USB above Wi-Fi in macOS network service
order. Some cellular connections use IPv6/NAT64 translation. On this Mac,
ordinary requests to `10.5.5.9` attempted a synthesized IPv6 address and timed
out, while `curl -4` and explicit IPv4 sockets returned HTTP 200.

Camera status and preview-start requests now use direct IPv4 sockets and skip
macOS proxy discovery. Cloud requests retain normal IPv4/IPv6 support. This
does not disable IPv6 on the Mac or alter its network routes. See Apple's
[DNS64/NAT64 guidance](https://developer.apple.com/support/ipv6/).

### Windows — WSL2

Verified on Windows 11, WSL2 Ubuntu 24.04, `networkingMode=mirrored`. Five
things differ from the macOS path above.

**Install the SDK into a virtual environment.** Ubuntu 24.04 follows PEP 668,
so the `python3 -m pip install google-genai` in step 1 fails with
`error: externally-managed-environment`. Instead:

```bash
python3 -m venv .venv
.venv/bin/pip install google-genai
```

**Launch with `start.sh`, not `python3 run.py`.** It selects
`.venv/bin/python`, the only interpreter that can import `google-genai`, and
wraps the call in `sg docker` when the shell has not yet picked up the `docker`
group:

```bash
./start.sh --provider-mode live
```

`python3 run.py` still works for mock mode, but in live mode it degrades to
repeated `gemini_retry` and `gemini_degraded` lines reporting the missing
import.

**Windows owns the Wi-Fi.** WSL2 has no radio and routes through whatever the
host is joined to, so the camera network is joined on the Windows side:

```powershell
netsh wlan connect name=<your GoPro SSID>
```

USB phone tethering replaces iPhone USB and appears as its own adapter. The
GoPro hands out a default gateway despite having no internet, so if internet
drops once the camera is joined, demote Wi-Fi below the tether in an
Administrator PowerShell:

```powershell
Set-NetIPInterface -InterfaceAlias "Wi-Fi" -InterfaceMetric 60
```

**Allow the camera's UDP stream through Windows Firewall.** The HERO7 pushes
MPEG-TS over UDP to port 8554. Windows ships inbound rules for TCP 8554 only,
so without this rule the camera's HTTP control endpoint answers, the startup
check passes, and no frame ever arrives — the sampler logs
`waiting for video; retrying` indefinitely. In an Administrator PowerShell:

```powershell
New-NetFirewallRule -DisplayName "GoPro UDP 8554" -Direction Inbound `
  -Protocol UDP -LocalPort 8554 -Action Allow
```

**Do not run `run.py` under `sudo`.** It creates a root-owned `var/`, after
which every narration fails with `PermissionError` while the rest of the
pipeline keeps running normally. Recover with
`sudo chown -R "$USER:$USER" var`.

A note on `npm`: if `npm` resolves to the Windows binary under
`/mnt/c/Program Files/nodejs`, the dashboard build in `--setup` fails with
`EISDIR` because Windows cannot `lstat` WSL directories across the
`\\wsl.localhost` boundary. Install a Linux Node to build the frontend. A
prebuilt `frontend/dist` is served as-is, and `static/` is the fallback when no
build exists, so this blocks nothing at run time.

### ElevenLabs smoke test

With `ELEVENLABS_API_KEY` in `.env` or the environment, run a one-shot billable
text-to-speech test:

```bash
python3 -m pip install elevenlabs
python3 test.py
```

It uses the configured `ELEVENLABS_VOICE_ID` and `ELEVENLABS_MODEL_ID`, falling
back to the example voice and `eleven_v3`, then plays the returned audio. Set
`ELEVENLABS_TEST_TEXT` to change the spoken sentence. The script saves
successful audio to `var/elevenlabs-test.mp3`, and
only reports success after the SDK's lazy audio iterator has actually finished.
Paid requests are not automatically retried if their response is lost.

To check HTTPS and account access without generating speech:

```bash
python3 test.py --check
```

This check uses the standard library and reports network failures separately
from HTTP authentication/permission errors. A TTS-only key may lack permission
to read subscription metadata. On macOS, the check and backend use the system
CA bundle if Python has no default certificate store; TLS verification remains
enabled.

On the network tested on 2026-10-03, TCP connections to ElevenLabs succeed but
TLS is reset when its hostname is sent. Both the global API and documented US
API endpoint are affected, while other HTTPS sites work. This strongly suggests
hostname-based filtering along that network path, but the responsible device
is unconfirmed. Use a different internet connection (for example phone USB
tethering) or ask the network administrator to allow `api.elevenlabs.io` on TCP
443. Repeated API calls and changing the key cannot fix a pre-HTTP TLS reset.
See [ElevenLabs authentication](https://elevenlabs.io/docs/api-reference/authentication)
and [official endpoint guidance](https://elevenlabs.io/docs/eleven-api/guides/how-to/best-practices/latency-optimization).

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
