# Gemini Vision and ElevenLabs TTS Design

Status: proposed

Last updated: 2026-10-03

## 1. Objective

Extend RC AI Surveyor so one camera stream supports two independent paths:

1. The browser continuously shows the lowest-latency live GoPro video.
2. The backend samples two frames per second, asks Gemini to describe what is
   visible, displays Gemini's two text outputs, converts the narration output
   to speech with ElevenLabs, and plays that speech in the browser.

The live video must never wait for Gemini or ElevenLabs.

## 2. User experience

The dashboard contains:

- A live video panel using the existing MediaMTX WebRTC feed.
- A **Technical description** panel containing a short, precise description.
- A **Human-friendly narration** panel containing the text sent to ElevenLabs.
- An audio player plus an **Enable audio** control. The user must interact once
  because browsers commonly block unprompted audio playback.
- Connection indicators for Camera, Video, Gemini, and ElevenLabs.

New analysis text should appear before audio generation finishes. When the
matching audio is ready, the browser plays it if audio has been enabled.

## 3. Architecture

```text
HERO7 Silver (UDP MPEG-TS/H.264)
              |
              v
       FFmpeg stream copy
              |
              v
          MediaMTX
          /      \
         /        \ RTSP
        v          v
Browser WebRTC   Frame sampler (2 JPEG frames/second)
                       |
                       v
              latest-frame batch (max size 2)
                       |
                       v
              Gemini vision analysis
                  /             \
                 v               v
       technical_description  narration_text
                 |               |
                 |               v
                 |       ElevenLabs streaming TTS
                 |               |
                 +-------+-------+
                         v
                 Dashboard events/API
                         |
                         v
                 Text + audio playback
```

The WebRTC and analysis branches only share MediaMTX as their source. Frame
decoding, cloud latency, API failures, and speech playback cannot buffer the
live-video path.

## 4. Network prerequisite

The GoPro operates as a Wi-Fi access point and normally does not provide
internet access. Cloud analysis therefore requires two network paths:

- Wi-Fi remains connected to the GoPro so `10.5.5.9` is reachable.
- Ethernet, USB phone tethering, or a second Wi-Fi adapter provides the default
  internet route for Gemini and ElevenLabs.

Startup must check both routes independently and report which one is missing.
Mock-provider mode must remain available for development with only the GoPro
network connected.

## 5. Frame ingestion and backpressure

The current `FrameSampler` already produces JPEG bytes at two frames per
second. Replace its log-only callback with a bounded analysis queue.

Design rules:

- Capture exactly two frames per second by default.
- Group the two frames from each one-second window into one Gemini request.
  Gemini sees both images, preserving the requested 2 FPS visual sampling while
  avoiding two independent model calls every second.
- Allow only one Gemini request in flight initially.
- Keep at most one pending batch. When the worker is busy, replace the pending
  batch with the newest complete batch instead of accumulating stale footage.
- Timestamp every frame at capture time and carry its sequence number through
  analysis, speech, browser events, and logs.
- Resize only if required by cost or latency testing. The GoPro preview frames
  are already small enough to send inline as JPEG data.

Two frames per second equals 7,200 images per hour. Batching reduces request
count, but both image volume and model cost must be measured during testing.

## 6. Gemini analysis

### Model and SDK

Use the official `google-genai` Python SDK behind a `VisionAnalyzer` interface.
Start with the generally available `gemini-3.8-flash` model and low thinking
effort for this latency-sensitive task. Keep the model configurable through
`GEMINI_MODEL`; model names and lifecycle must not be hard-coded throughout the
application.

Each request contains:

- The two JPEG frames as inline `image/jpeg` parts.
- A stable system/task prompt describing the survey domain.
- A structured response schema.

Gemini supports inline image bytes and structured JSON output. The JPEG batch
is far below the documented 20 MB inline-request threshold.

### Required response schema

```json
{
  "technical_description": "Crack approximately 20 cm long beside the lower-left window frame; severity uncertain from this angle.",
  "narration_text": "I can see a short crack beside the lower-left window. It may need a closer inspection to determine how serious it is."
}
```

Both properties are required strings. Reject or retry responses that do not
validate against the schema.

Prompt requirements:

- `technical_description`: concise, factual, domain-oriented, and no more than
  two short sentences.
- `narration_text`: natural spoken language, understandable to a non-specialist,
  and normally no more than three short sentences.
- Describe only visible evidence; explicitly state uncertainty.
- Do not infer identity, protected traits, intent, ownership, or facts outside
  the images.
- Normalize numbers, units, abbreviations, and symbols into speech-friendly
  wording in `narration_text` because low-latency TTS models may not normalize
  every number as expected.
- Compare the two frames when useful, but do not claim motion from insufficient
  evidence.

### Failure policy

- Timeout each Gemini request.
- Retry transient failures once with jitter; do not retry validation or safety
  rejections indefinitely.
- Continue live video and frame capture during an outage.
- Publish a degraded-state event to the dashboard while retaining the last
  successful description.
- Never send a failed or unvalidated model response to ElevenLabs.

## 7. ElevenLabs speech generation

Use the ElevenLabs streaming text-to-speech endpoint with:

- `ELEVENLABS_MODEL_ID=eleven_flash_v2_5` initially.
- A user-selected `ELEVENLABS_VOICE_ID`.
- `narration_text` as the only synthesized content.
- MP3 output for broad browser compatibility.

The technical description is displayed but is not spoken.

### Preventing a speech backlog

Analysis may arrive faster than speech can be played. The TTS and playback
policy is therefore latest-relevant-result, not FIFO:

- Allow one ElevenLabs request in flight.
- Keep only the newest pending narration.
- Do not synthesize identical narration twice.
- Add a configurable minimum speech interval, initially three seconds.
- Do not interrupt a sentence already playing in the MVP. Replace only queued,
  unplayed narration with the newest result.

### Audio lifecycle

For the first implementation:

1. Publish Gemini text to the browser immediately.
2. Stream ElevenLabs response chunks into a temporary MP3 file.
3. Atomically rename the file when complete.
4. Publish an `audio_ready` event containing its analysis ID and URL.
5. Retain a small ring of recent audio files and remove older files.

This is reliable across browsers. A later optimization can proxy audio chunks
directly to the browser if measured time-to-first-audio is too high.

## 8. Backend-to-browser contract

Server-Sent Events are sufficient because updates only flow from backend to
browser. Keep ordinary HTTP endpoints for state and audio.

### Endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /` | Dashboard |
| `GET /api/status` | Current service and latest-analysis snapshot |
| `GET /api/events` | SSE stream for analysis, audio, and health events |
| `GET /api/audio/{analysis_id}.mp3` | Generated narration audio |

### Analysis event

```json
{
  "type": "analysis",
  "analysis_id": "01J...",
  "frame_sequences": [121, 122],
  "captured_at": "2026-10-03T18:42:11.250Z",
  "technical_description": "...",
  "narration_text": "..."
}
```

### Audio-ready event

```json
{
  "type": "audio_ready",
  "analysis_id": "01J...",
  "audio_url": "/api/audio/01J....mp3"
}
```

The browser updates text only when an event is newer than its current analysis
ID. It plays audio only when the event matches the latest relevant analysis and
audio has been enabled by the user.

## 9. Proposed code organization

Keep `run.py` as the one-command supervisor, but move application concerns into
small modules:

```text
run.py                    process lifecycle and CLI
app/config.py             validated environment and CLI configuration
app/models.py             frame, analysis, and event types
app/frame_pipeline.py     batching and bounded latest-frame queue
app/gemini_analyzer.py    VisionAnalyzer implementation
app/elevenlabs_tts.py     SpeechSynthesizer implementation
app/server.py             dashboard, status, SSE, and audio endpoints
web/index.html            dashboard UI
tests/                    provider mocks and pipeline tests
```

Use FastAPI/Uvicorn for the dashboard API and SSE lifecycle. Keep FFmpeg and
MediaMTX for media transport; neither cloud provider should receive the live
video stream directly.

Provider interfaces must support real and mock implementations:

```python
class VisionAnalyzer(Protocol):
    async def analyze(self, frames: list[Frame]) -> Analysis: ...

class SpeechSynthesizer(Protocol):
    async def synthesize(self, analysis: Analysis) -> AudioResult: ...
```

## 10. Configuration and secrets

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
PROVIDER_MODE=mock|live
```

- Store secrets only in environment variables or a local `.env` excluded from
  Git.
- Never send provider keys to the browser.
- Log provider request IDs, latency, and status, but never keys, full request
  bodies, or raw image bytes.
- Default to in-memory processing. Do not retain camera frames unless an
  explicit evidence-retention feature is added later.

## 11. Observability

Every analysis carries one ID across the pipeline. Structured logs should make
the lifecycle visible:

```text
frame_batch_ready analysis_id=01J... frames=121,122 age_ms=18
gemini_complete analysis_id=01J... latency_ms=740
analysis_published analysis_id=01J...
elevenlabs_complete analysis_id=01J... latency_ms=310 bytes=28440
audio_published analysis_id=01J... url=/api/audio/01J....mp3
```

Track at least:

- Captured, dropped, and analyzed frames.
- Current pending-queue size.
- Frame age when submitted to Gemini.
- Gemini latency, errors, and schema-validation failures.
- ElevenLabs latency, errors, generated characters, and audio bytes.
- Time from frame capture to text display and to audio playback readiness.

## 12. Delivery phases

### Phase 1: contracts and mocks

- Extract the current dashboard into `web/index.html`.
- Add typed models, bounded frame batches, SSE, and mock providers.
- Render mock technical/narration text and play a fixture audio clip.
- Verify the WebRTC feed remains unaffected under slow mock providers.

### Phase 2: Gemini

- Add the `google-genai` dependency and structured response model.
- Send each two-frame batch and publish validated text.
- Add timeouts, one retry, metrics, and model configuration.

### Phase 3: ElevenLabs

- Add streaming TTS, atomic audio publication, retention, and the audio consent
  control.
- Add deduplication, speech cooldown, and latest-result queue behavior.

### Phase 4: field hardening

- Test dual-network routing while connected to the physical GoPro.
- Measure end-to-end latency and cost over a one-hour session.
- Tune image size, prompt, analysis cadence, and narration cadence.
- Add provider rate-limit handling and a visible offline/degraded state.

## 13. Acceptance criteria

- Live video remains available and does not visibly gain latency while cloud
  processing is slow or unavailable.
- The sampler captures two frames per second and never builds an unbounded
  backlog.
- Gemini returns exactly the two validated text fields for each accepted batch.
- Technical text appears without waiting for speech generation.
- ElevenLabs receives only `narration_text` and produces playable browser audio.
- No stale narration plays after a newer relevant result has replaced it.
- Provider keys never appear in browser traffic, logs, or Git history.
- The system runs end to end with mock providers and no internet connection.

## 14. Open product decisions

- Which survey domain and defect vocabulary should the Gemini prompt prioritize?
- Which ElevenLabs voice should be the default?
- Should narration speak continuously, only on meaningful changes, or only when
  the user presses a button?
- Should evidence frames or audio be retained, and for how long?
- Is one Gemini request per second acceptable for the target budget, or should
  analysis be event-triggered after the first field trial?

## 15. Official references

- [Gemini 3.8 Flash](https://ai.google.dev/gemini-api/docs/latest-model)
- [Gemini image understanding](https://ai.google.dev/gemini-api/docs/generate-content/image-understanding)
- [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output)
- [ElevenLabs streaming TTS endpoint](https://elevenlabs.io/docs/api-reference/text-to-speech/stream)
- [ElevenLabs model selection](https://elevenlabs.io/docs/overview/models)
- [ElevenLabs latency optimization](https://elevenlabs.io/docs/eleven-api/guides/how-to/best-practices/latency-optimization)
