# HERO7 Silver preview gateway

This is a small, dependency-free Python supervisor around FFmpeg. It automates
the legacy HERO7 Silver preview-start request, UDP keepalive, reception, and
forwarding. The project is intentionally small so the legacy camera adapter can
be replaced later without changing the rest of the media pipeline.

## Architecture

```text
HERO7 Silver
  Wi-Fi AP + legacy UDP/MPEG-TS (H.264/AAC, port 8554)
        |
        v
Mac edge gateway: gopro_gateway.py + FFmpeg
        |
        | RTMP now; SRT is a later option for a lossy WAN
        v
MediaMTX relay
        |
        +--> RTSP/WebRTC/HLS viewers
        |
        `--> frame_sampler.py --> latest-frame model worker
```

For a remote backend, the Mac needs two network paths: Wi-Fi connected to the
GoPro plus Ethernet, USB tethering, or a second Wi-Fi adapter for Internet/LAN.
For an all-local prototype, MediaMTX and the sampler can run on the same Mac.

## 1. One-command replacement for the three-terminal preview

Connect the Mac to the GoPro Wi-Fi, then run:

```bash
python3 gopro_gateway.py --preview
```

The script opens FFplay, requests preview, sends the keepalive every two
seconds, and restarts the player if it fails. Stop it with `Ctrl+C`.

It can optionally join the GoPro network. Keep the password out of shell
history:

```bash
export GOPRO_WIFI_PASSWORD='the-camera-password'
python3 gopro_gateway.py --wifi-ssid 'goproshka' --preview
```

## 2. Local backend prototype with MediaMTX

Start the relay on the Mac while Internet is available so Docker can fetch the
image the first time:

```bash
docker run --rm --name gopro-mediamtx \
  -p 1935:1935 \
  -p 8554:8554 \
  bluenviron/mediamtx:latest
```

Connect Wi-Fi to the GoPro. In another terminal, publish the camera preview to
the relay. Transcoding at the edge prevents the HERO7's damaged legacy packets
from being forwarded unchanged to every downstream decoder:

```bash
python3 gopro_gateway.py \
  --transcode \
  --output rtmp://127.0.0.1:1935/gopro
```

MediaMTX now exposes the stream locally as:

```text
rtmp://127.0.0.1:1935/gopro
rtsp://127.0.0.1:8554/gopro
```

On a separate backend host, replace `127.0.0.1` in the gateway output with the
backend's reachable IP or DNS name and allow inbound TCP port 1935.

## 3. Sample frames for a vision worker

This keeps a size-one frame buffer: decoding can continue while a slow model
works, and every completed inference receives the newest available frame.
The sampler also reconnects automatically when the publisher or relay starts
late or temporarily disappears.

```bash
python3 frame_sampler.py \
  --input rtsp://127.0.0.1:8554/gopro \
  --fps 2 \
  --latest-file /tmp/gopro-latest.jpg \
  --viewer \
  --open-browser
```

The viewer is available at `http://127.0.0.1:8787`. It provides:

- `/` — a human-friendly live page.
- `/stream.mjpg` — the sampled MJPEG stream.
- `/latest.jpg` — the newest complete JPEG.
- `/status` — JSON containing sequence number and frame age.

It can instead POST each selected JPEG to an existing API:

```bash
export FRAME_API_TOKEN='replace-me-if-needed'
python3 frame_sampler.py \
  --input rtsp://127.0.0.1:8554/gopro \
  --fps 2 \
  --post-url https://backend.example.com/frames
```

The request has `Content-Type: image/jpeg`, `X-Frame-Sequence`, and an optional
bearer token. Posting happens in the worker thread, so slow HTTP/model work does
not accumulate old frames.

## Recommended stack

- Edge gateway: this Python supervisor plus FFmpeg. FFmpeg owns transport,
  demuxing, and remuxing; Python owns lifecycle and the legacy camera protocol.
- Media plane: MediaMTX. Start with RTMP from the gateway; use SRT when crossing
  an unreliable WAN. Use RTSP over TCP between MediaMTX and backend workers.
- Vision worker: Python, PyTorch/ONNX/OpenCV as needed, with the latest-frame
  queue pattern demonstrated here.
- API/control plane: FastAPI for camera/session state and WebSocket events.
- Persistence: PostgreSQL for structured detections and object storage for only
  selected evidence frames/clips. Do not persist every decoded frame.
- Scaling later: Redis Streams or NATS for detection events, not raw video.

The HERO7 Silver feed is an unsupported legacy preview path. Treat the gateway
as a replaceable adapter. The relay and worker interfaces can remain unchanged
if the camera is later upgraded to RTMP, RTSP, SRT, or WebRTC.
