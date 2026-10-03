"""HTTP surface: status, config, frame, SSE, audio, and path safety."""

from __future__ import annotations

import json
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from app.audio_store import AudioStore
from app.events import EventBus
from app.models import new_analysis_id
from app.providers import silent_mp3
from app.server import start_dashboard
from app.state import PipelineState
from tests.helpers import JPEG, make_config, wait_until


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config = make_config(AUDIO_DIR=self._tmp.name)
        self.store = AudioStore(Path(self._tmp.name), 5)
        self.bus = EventBus()
        self.state = PipelineState(self.config, "http://media/", "http://media/whep")
        self.port = free_port()
        self.server, self.thread, self.label = start_dashboard(
            self.port, self.state, self.bus, self.store
        )
        self.base = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self._tmp.cleanup()

    def get(self, path, timeout=5):
        try:
            with urllib.request.urlopen(self.base + path, timeout=timeout) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def get_json(self, path):
        status, _, body = self.get(path)
        return status, json.loads(body)


class TestStaticAndApi(ServerTestCase):
    def test_serves_dashboard(self):
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type"))
        self.assertIn(b"<", body)

    def test_config_endpoint(self):
        status, payload = self.get_json("/api/config")
        self.assertEqual(status, 200)
        self.assertEqual(payload["whep_url"], "http://media/whep")
        self.assertEqual(payload["sample_fps"], 2.0)
        self.assertEqual(payload["provider_mode"], "mock")

    def test_status_shape_matches_design_document(self):
        status, payload = self.get_json("/api/status")
        self.assertEqual(status, 200)
        for key in ("uptime_seconds", "provider_mode", "frames", "relay",
                    "services", "latest_analysis", "latest_audio", "metrics"):
            self.assertIn(key, payload)
        self.assertEqual(
            sorted(payload["services"]), ["camera", "elevenlabs", "gemini", "video"],
            "the four indicators from section 2 must all be present",
        )
        self.assertIsNone(payload["latest_analysis"])

    def test_query_string_is_ignored(self):
        status, _ = self.get_json("/api/status?cachebust=123")
        self.assertEqual(status, 200)

    def test_unknown_api_route_is_json_404(self):
        status, _, body = self.get("/api/nonexistent")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"], "not found")

    def test_frame_endpoint(self):
        status, _, _ = self.get("/api/frame")
        self.assertEqual(status, 503, "no frame sampled yet")

        self.state.record_frame(JPEG)
        status, headers, body = self.get("/api/frame")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "image/jpeg")
        self.assertEqual(headers.get("X-Frame-Sequence"), "1")
        self.assertEqual(body, JPEG)

    def test_path_traversal_is_blocked(self):
        for probe in ("/../run.py", "/%2e%2e/run.py", "/../../etc/passwd",
                      "/../app/config.py", "/nope.txt", "/static/../run.py"):
            status, _, _ = self.get(probe)
            self.assertEqual(status, 404, f"{probe} must not be served")


class TestAudioEndpoint(ServerTestCase):
    def test_serves_published_audio(self):
        analysis_id = new_analysis_id()
        audio = silent_mp3(0.5)
        self.store.publish(analysis_id, audio)

        status, headers, body = self.get(f"/api/audio/{analysis_id}.mp3")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "audio/mpeg")
        self.assertEqual(body, audio)

    def test_rejects_unknown_and_malformed_ids(self):
        for probe in (
            "/api/audio/" + new_analysis_id() + ".mp3",   # valid shape, absent
            "/api/audio/notanid.mp3",
            "/api/audio/../../run.py",
            "/api/audio/%2e%2e%2f%2e%2e%2frun.py",
            "/api/audio/.mp3",
            "/api/audio/" + new_analysis_id(),            # missing extension
        ):
            status, _, _ = self.get(probe)
            self.assertEqual(status, 404, f"{probe} must 404")


class TestServerSentEvents(ServerTestCase):
    def _open_stream(self):
        """Open /api/events and collect decoded events on a background thread."""
        received = []
        opened = threading.Event()
        errors = []
        holder = {}

        def reader():
            try:
                response = urllib.request.urlopen(self.base + "/api/events", timeout=10)
                holder["response"] = response
                opened.set()
                for raw in response:
                    line = raw.decode("utf-8").strip()
                    if line.startswith("data: "):
                        received.append(json.loads(line[6:]))
            except Exception as error:  # closed by teardown
                errors.append(error)

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        self.assertTrue(opened.wait(5), "SSE stream did not open")
        return received, holder

    def test_sends_hello_then_live_events(self):
        received, _holder = self._open_stream()

        wait_until(lambda: len(received) >= 1, message="no hello event")
        self.assertEqual(received[0]["type"], "hello")
        self.assertIn("status", received[0], "hello must carry a status snapshot")

        wait_until(lambda: self.bus.subscriber_count == 1)
        self.bus.publish({"type": "analysis", "analysis_id": "A1"})
        self.bus.publish({"type": "audio_ready", "analysis_id": "A1"})

        wait_until(lambda: len(received) >= 3, message="live events not delivered")
        self.assertEqual(received[1]["type"], "analysis")
        self.assertEqual(received[2]["type"], "audio_ready")

    def test_replays_latest_state_to_a_reconnecting_client(self):
        from app.models import Analysis, AudioResult, utc_now

        analysis = Analysis(
            analysis_id="01ABCDEFGHJKMNPQRSTVWXYZ00",
            frame_sequences=[1, 2],
            captured_at=utc_now(),
            technical_description="t",
            narration_text="n",
        )
        self.state.set_analysis(analysis)
        self.state.set_audio(AudioResult(analysis.analysis_id, "/api/audio/x.mp3", 10))

        received, _holder = self._open_stream()
        wait_until(lambda: len(received) >= 3,
                   message="reconnecting client was not resynchronised")
        self.assertEqual([e["type"] for e in received[:3]],
                         ["hello", "analysis", "audio_ready"])

    def test_unsubscribes_when_client_disconnects(self):
        import app.server

        # The handler only notices a dead client on its next write, so shorten
        # the heartbeat to keep this test quick.
        original = app.server.HEARTBEAT_SECONDS
        app.server.HEARTBEAT_SECONDS = 0.2
        try:
            received, holder = self._open_stream()
            wait_until(lambda: self.bus.subscriber_count == 1)
            holder["response"].close()
            wait_until(lambda: self.bus.subscriber_count == 0, timeout=10,
                       message="subscriber leaked after the client disconnected")
        finally:
            app.server.HEARTBEAT_SECONDS = original


if __name__ == "__main__":
    unittest.main()
