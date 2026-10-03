# RC AI Surveyor

Low-latency HERO7 Silver video with a backend frame pipeline.

```text
GoPro UDP/H.264 -> MediaMTX -+-> browser WebRTC (live video)
                             |
                             +-> backend sampler (2 FPS)
                                  -> Gemini Flash (next)
                                  -> technical + narration text (next)
                                  -> ElevenLabs audio (later)
```

The live video and AI pipeline are separate consumers. Sampling or future model
work therefore does not add delay to the browser video.

## Run

Requirements: Docker and FFmpeg.

1. Connect the Mac's Wi-Fi to the GoPro's `GP...` network.
2. From this directory, run:

```bash
python3 run.py
```

The dashboard opens automatically at:

```text
http://127.0.0.1:8787/
```

It contains the live feed plus placeholders for the concise technical response,
the human-friendly narration, and future audio.

## Backend frame confirmation

The backend samples two JPEG frames per second from the relayed video. Each
received frame produces a log like:

```text
backend frame #12 received (42891 bytes) | ready for Gemini Flash -> technical + narration text -> ElevenLabs
```

The frame stops there for now: no data is sent to Gemini or ElevenLabs yet. The
dashboard also shows the current backend frame number and byte size.

Use `--sample-fps` to change the analysis rate:

```bash
python3 run.py --sample-fps 1
```

Press `Ctrl+C` once to stop the camera relay, sampler, dashboard, and backend.
