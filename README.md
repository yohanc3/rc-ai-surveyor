# RC AI Surveyor

Low-latency HERO7 Silver video in a browser.

```text
GoPro UDP preview -> FFmpeg stream copy -> MediaMTX -> browser WebRTC
```

There is no frame extraction, JPEG conversion, RTMP hop, or video
re-encoding. MediaMTX is the backend and serves the browser page.

## Run

Requirements: Docker and FFmpeg.

1. Connect the Mac's Wi-Fi to the GoPro's `GP...` network.
2. From this directory, run:

```bash
python3 run.py
```

The script starts the backend, starts and maintains the camera preview, relays
the original H.264 video, and opens:

```text
http://127.0.0.1:8889/gopro/
```

Press `Ctrl+C` once to stop the relay and backend.

## Why this is faster

The earlier prototype decoded the stream into JPEGs at 2 FPS after passing
through RTMP and RTSP. That added buffering and made the picture visibly old.
This version keeps the compressed camera video intact and sends it directly to
the browser through WebRTC.
