"""Unit tests for the pure pieces: ids, config, batching, store, bus, parsing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.audio_store import AudioStore
from app.config import ConfigError
from app.events import EventBus, sse_frame
from app.frame_pipeline import FrameBatcher
from app.gemini_analyzer import parse_analysis_response
from app.models import FrameBatch, SchemaValidationError, new_analysis_id
from app.providers import MockVisionAnalyzer, silent_mp3
from tests.helpers import make_config, make_frame


class TestIds(unittest.TestCase):
    def test_sortable_and_well_formed(self):
        ids = [new_analysis_id() for _ in range(50)]
        self.assertTrue(all(len(i) == 26 for i in ids))
        self.assertEqual(len(set(ids)), 50, "ids must be unique")
        self.assertEqual(ids, sorted(ids), "ids must sort by creation order")


class TestConfig(unittest.TestCase):
    def test_defaults_match_design_document(self):
        config = make_config()
        self.assertEqual(config.provider_mode, "mock")
        self.assertEqual(config.gemini_model, "gemini-3.8-flash")
        self.assertEqual(config.elevenlabs_model_id, "eleven_flash_v2_5")
        self.assertEqual(config.analysis_fps, 0.5)
        self.assertEqual(config.analysis_batch_seconds, 2.0)
        self.assertEqual(config.tts_min_interval_seconds, 3.0)
        self.assertEqual(config.frames_per_batch, 1)

    def test_live_requires_credentials(self):
        with self.assertRaises(ConfigError):
            make_config(PROVIDER_MODE="live")

    def test_live_accepts_full_credentials(self):
        config = make_config(
            PROVIDER_MODE="live", GEMINI_API_KEY="g", ELEVENLABS_API_KEY="e",
            ELEVENLABS_VOICE_ID="v",
        )
        self.assertTrue(config.is_live)

    def test_redacted_never_contains_secrets(self):
        config = make_config(
            PROVIDER_MODE="live", GEMINI_API_KEY="SECRET-G", ELEVENLABS_API_KEY="SECRET-E",
            ELEVENLABS_VOICE_ID="v",
        )
        blob = repr(config.redacted())
        self.assertNotIn("SECRET-G", blob)
        self.assertNotIn("SECRET-E", blob)

    def test_rejects_bad_values(self):
        with self.assertRaises(ConfigError):
            make_config(PROVIDER_MODE="banana")
        with self.assertRaises(ConfigError):
            make_config(ANALYSIS_FPS="not-a-number")


class TestFrameBatcher(unittest.TestCase):
    def test_groups_frames_into_windows(self):
        batcher = FrameBatcher(2)
        self.assertIsNone(batcher.add(make_frame(1)))
        batch = batcher.add(make_frame(2))
        self.assertIsNotNone(batch)
        self.assertEqual(batch.sequences, [1, 2])
        self.assertEqual(batcher.buffered, 0, "buffer must reset after emitting")
        self.assertIsNone(batcher.add(make_frame(3)))

    def test_single_frame_batches(self):
        batcher = FrameBatcher(1)
        self.assertIsNotNone(batcher.add(make_frame(1)))


class TestAudioStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = AudioStore(Path(self._tmp.name), retention=3)

    def tearDown(self):
        self._tmp.cleanup()

    def test_retention_keeps_newest(self):
        ids = [new_analysis_id() for _ in range(5)]
        for i in ids:
            self.store.publish(i, silent_mp3(0.1))
        self.assertEqual(len(list(Path(self._tmp.name).glob("*.mp3"))), 3)
        self.assertIsNone(self.store.path_for(ids[0]))
        self.assertIsNotNone(self.store.path_for(ids[-1]))

    def test_rejects_path_traversal(self):
        for bad in ("../../run", "..", "abc", "", "../" + new_analysis_id(), "A" * 27):
            self.assertIsNone(self.store.path_for(bad), bad)
        with self.assertRaises(ValueError):
            self.store.publish("../evil", b"x")

    def test_publish_is_atomic(self):
        analysis_id = new_analysis_id()
        self.store.publish(analysis_id, silent_mp3(0.2))
        leftovers = list(Path(self._tmp.name).glob(".*part"))
        self.assertEqual(leftovers, [], "no partial files may remain")


class TestEventBus(unittest.TestCase):
    def test_fan_out_and_drop_oldest(self):
        bus = EventBus()
        a, b = bus.subscribe(), bus.subscribe()
        bus.publish({"n": 1})
        self.assertEqual(a.get_nowait()["n"], 1)
        self.assertEqual(b.get_nowait()["n"], 1)

        for n in range(200):
            bus.publish({"n": n})
        newest = None
        while not a.empty():
            newest = a.get_nowait()
        self.assertEqual(newest["n"], 199, "newest event must survive")
        self.assertGreater(bus.dropped, 0)

    def test_unsubscribe(self):
        bus = EventBus()
        sub = bus.subscribe()
        bus.unsubscribe(sub)
        self.assertEqual(bus.subscriber_count, 0)

    def test_sse_encoding(self):
        self.assertEqual(sse_frame({"a": 1}), b'data: {"a": 1}\n\n')


class TestGeminiParsing(unittest.TestCase):
    def setUp(self):
        self.batch = FrameBatch(new_analysis_id(), (make_frame(7), make_frame(8)), 0.0)

    def test_accepts_valid_response(self):
        analysis = parse_analysis_response(
            '{"technical_description":"A crack.","narration_text":"I see a crack."}',
            self.batch,
        )
        self.assertEqual(analysis.frame_sequences, [7, 8])
        self.assertEqual(analysis.analysis_id, self.batch.analysis_id)

    def test_rejects_invalid_responses(self):
        bad = [
            "", "   ", "not json", "[1,2]", "null",
            '{"technical_description":"x"}',
            '{"narration_text":"x"}',
            '{"technical_description":"x","narration_text":123}',
            '{"technical_description":"","narration_text":"y"}',
            '{"technical_description":"x","narration_text":"   "}',
        ]
        for payload in bad:
            with self.assertRaises(SchemaValidationError, msg=payload):
                parse_analysis_response(payload, self.batch)

    def test_event_shape_matches_design_document(self):
        analysis = parse_analysis_response(
            '{"technical_description":"t","narration_text":"n"}', self.batch
        )
        event = analysis.to_event()
        self.assertEqual(
            sorted(event),
            ["analysis_id", "captured_at", "frame_sequences", "technical_description",
             "narration_text", "type"].__class__(sorted(
                ["type", "analysis_id", "frame_sequences", "captured_at",
                 "technical_description", "narration_text"])),
        )
        self.assertEqual(event["type"], "analysis")
        self.assertTrue(event["captured_at"].endswith("Z"))


class TestMockVisionAnalyzer(unittest.IsolatedAsyncioTestCase):
    async def test_discloses_that_it_does_not_analyze_frame_pixels(self):
        batch = FrameBatch(new_analysis_id(), (make_frame(1),), 0.0)
        analysis = await MockVisionAnalyzer(latency_seconds=0).analyze(batch)

        self.assertEqual(analysis.frame_sequences, [1])
        self.assertIn("not derived from the camera frame", analysis.technical_description)


class TestElevenLabsRequest(unittest.TestCase):
    def test_request_shape_and_key_placement(self):
        from app.elevenlabs_tts import build_request

        config = make_config(
            PROVIDER_MODE="live", GEMINI_API_KEY="g", ELEVENLABS_API_KEY="SECRET",
            ELEVENLABS_VOICE_ID="voice42",
        )
        request = build_request(config, "Hello.")
        self.assertIn("voice42", request.full_url)
        self.assertIn("output_format=mp3_44100_128", request.full_url)
        self.assertNotIn("SECRET", request.full_url, "key must never be in a URL")
        headers = {k.lower(): v for k, v in request.headers.items()}
        self.assertEqual(headers["xi-api-key"], "SECRET")
        self.assertEqual(headers["accept"], "audio/mpeg")

    def test_refuses_empty_text(self):
        from app.elevenlabs_tts import build_request
        from app.models import AnalysisError

        config = make_config(
            PROVIDER_MODE="live", GEMINI_API_KEY="g", ELEVENLABS_API_KEY="e",
            ELEVENLABS_VOICE_ID="v",
        )
        with self.assertRaises(AnalysisError):
            build_request(config, "   ")


class TestMockAudio(unittest.TestCase):
    def test_produces_valid_mp3_frames(self):
        audio = silent_mp3(1.0)
        self.assertEqual(audio[:2], b"\xff\xfb", "MPEG-1 Layer III sync word")
        self.assertEqual(len(audio) % 417, 0, "whole frames only")
        self.assertGreater(len(audio), 10_000)


if __name__ == "__main__":
    unittest.main()
