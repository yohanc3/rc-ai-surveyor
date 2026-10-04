"""End-to-end: real pipeline behind the real HTTP server, mock providers only.

This is the closest thing to a full run that works with no GoPro, no Docker and
no internet, and it mirrors acceptance criterion 13.8.
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from app.audio_store import AudioStore
from app.events import EventBus
from app.frame_pipeline import AnalysisPipeline
from app.providers import MockSpeechSynthesizer, MockVisionAnalyzer
from app.server import start_dashboard
from app.state import PipelineState
from tests.helpers import JPEG, make_config, make_frame, wait_until
from tests.test_server import free_port


class TestFullPipelineOverHttp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config = make_config(
            AUDIO_DIR=self._tmp.name,
            TTS_MIN_INTERVAL_SECONDS=0,
            ANALYSIS_FPS=2,
            ANALYSIS_BATCH_SECONDS=1,
        )
        self.store = AudioStore(Path(self._tmp.name), 5)
        self.bus = EventBus()
        self.state = PipelineState(self.config, "http://media/", "http://media/whep")
        self.pipeline = AnalysisPipeline(
            self.config,
            MockVisionAnalyzer(latency_seconds=0.05),
            MockSpeechSynthesizer(self.store, latency_seconds=0.05),
            self.bus,
            self.state,
        )
        self.state.attach_pipeline(self.pipeline)
        self.pipeline.start()

        self.port = free_port()
        self.server, _, _ = start_dashboard(self.port, self.state, self.bus, self.store)
        self.base = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.pipeline.stop()
        self._tmp.cleanup()

    def fetch(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as response:
            return response.status, response.headers, response.read()

    def test_frames_become_text_and_playable_audio(self):
        events = []
        opened = threading.Event()

        def reader():
            response = urllib.request.urlopen(self.base + "/api/events", timeout=15)
            opened.set()
            for raw in response:
                line = raw.decode("utf-8").strip()
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))

        threading.Thread(target=reader, daemon=True).start()
        self.assertTrue(opened.wait(5), "SSE stream did not open")
        wait_until(lambda: self.bus.subscriber_count == 1)

        # Feed one full batching window, exactly as the sampler would.
        for sequence in (1, 2):
            self.state.record_frame(JPEG)
            self.pipeline.submit_frame(make_frame(sequence))

        wait_until(lambda: sum(e["type"] == "analysis" for e in events) == 1,
                   message="no analysis event arrived over SSE")
        wait_until(lambda: sum(e["type"] == "audio_ready" for e in events) == 1,
                   message="no audio_ready event arrived over SSE")

        analysis = next(e for e in events if e["type"] == "analysis")
        audio = next(e for e in events if e["type"] == "audio_ready")

        # the design document's event contract
        self.assertEqual(
            sorted(analysis),
            sorted(["type", "analysis_id", "frame_sequences", "captured_at",
                    "technical_description", "narration_text"]),
        )
        self.assertEqual(analysis["frame_sequences"], [1, 2])
        self.assertTrue(analysis["captured_at"].endswith("Z"))
        self.assertEqual(audio["analysis_id"], analysis["analysis_id"])

        # the advertised audio URL must actually serve a playable MP3
        status, headers, body = self.fetch(audio["audio_url"])
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "audio/mpeg")
        self.assertEqual(body[:2], b"\xff\xfb", "must be a real MPEG frame")
        self.assertGreater(len(body), 1000)

        # and the snapshot must agree with the stream
        _, _, raw = self.fetch("/api/status")
        snapshot = json.loads(raw)
        self.assertEqual(snapshot["latest_analysis"]["analysis_id"], analysis["analysis_id"])
        self.assertEqual(snapshot["latest_audio"]["audio_url"], audio["audio_url"])
        self.assertEqual(snapshot["services"]["gemini"]["state"], "ok")
        self.assertEqual(snapshot["services"]["elevenlabs"]["state"], "ok")
        self.assertEqual(snapshot["metrics"]["analyses_succeeded"], 1)
        self.assertEqual(snapshot["metrics"]["speech_succeeded"], 1)
        self.assertEqual(snapshot["metrics"]["batches_dropped"], 0)

        # the sampled frame is served too
        status, headers, frame = self.fetch("/api/frame")
        self.assertEqual(status, 200)
        self.assertEqual(frame, JPEG)

    def test_sustained_feed_never_queues_unboundedly(self):
        for sequence in range(1, 41):
            self.state.record_frame(JPEG)
            self.pipeline.submit_frame(make_frame(sequence))

        wait_until(lambda: self.pipeline.metrics.batches_created == 20)

        # A batch that is mid-flight is neither pending nor finished, so the
        # accounting only balances once the pipeline is at rest.
        def settled():
            m = self.pipeline.metrics
            return (
                self.pipeline.pending_batches == 0
                and m.batches_dropped + m.analyses_succeeded + m.analyses_failed
                == m.batches_created
            )

        wait_until(settled, message="pipeline never settled")

        _, _, raw = self.fetch("/api/status")
        metrics = json.loads(raw)["metrics"]
        self.assertEqual(metrics["batches_created"], 20)
        self.assertEqual(
            metrics["batches_created"],
            metrics["batches_dropped"] + metrics["analyses_succeeded"] + metrics["analyses_failed"],
            "every batch must be accounted for once settled",
        )
        self.assertEqual(metrics["analyses_failed"], 0)
        self.assertLessEqual(metrics["pending_batches"], 1)
        self.assertGreater(metrics["analyses_succeeded"], 0)


if __name__ == "__main__":
    unittest.main()
