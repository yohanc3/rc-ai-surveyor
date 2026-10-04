"""Pipeline behaviour: batching, backpressure, retries, and speech policy."""

from __future__ import annotations

import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path

from app.audio_store import AudioStore
from app.events import EventBus
from app.frame_pipeline import AnalysisPipeline
from app.models import Analysis, AnalysisError, SchemaValidationError
from app.providers import MockSpeechSynthesizer, MockVisionAnalyzer
from app.state import PipelineState
from tests.helpers import make_config, make_frame, wait_until


class RecordingAnalyzer:
    """Analyzer whose latency and failure pattern the test controls."""

    def __init__(self, latency=0.0, errors=None):
        self.latency = latency
        self._errors = list(errors or [])
        self._lock = threading.Lock()
        self.calls = 0
        self.seen_batches = []

    def set_errors(self, errors):
        """Mutating the queue from the test thread needs the same lock."""
        with self._lock:
            self._errors = list(errors)

    def _next_error(self):
        with self._lock:
            return self._errors.pop(0) if self._errors else None

    async def analyze(self, batch):
        self.calls += 1
        self.seen_batches.append(batch.sequences)
        if self.latency:
            await asyncio.sleep(self.latency)
        error = self._next_error()
        if error is not None:
            raise error
        return Analysis(
            analysis_id=batch.analysis_id,
            frame_sequences=batch.sequences,
            captured_at=batch.captured_at,
            technical_description=f"technical {batch.sequences}",
            narration_text=f"narration {batch.sequences}",
        )


class FixedNarrationAnalyzer(RecordingAnalyzer):
    """Always returns identical narration, to exercise de-duplication."""

    async def analyze(self, batch):
        analysis = await super().analyze(batch)
        return Analysis(
            analysis_id=analysis.analysis_id,
            frame_sequences=analysis.frame_sequences,
            captured_at=analysis.captured_at,
            technical_description="same technical",
            narration_text="same narration",
        )


class RecordingSynthesizer:
    def __init__(self, store, latency=0.0):
        self._inner = MockSpeechSynthesizer(store, latency_seconds=latency)
        self.started_at = []
        self.texts = []

    async def synthesize(self, analysis):
        self.started_at.append(time.monotonic())
        self.texts.append(analysis.narration_text)
        return await self._inner.synthesize(analysis)


class PipelineTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config = make_config(
            AUDIO_DIR=self._tmp.name,
            TTS_MIN_INTERVAL_SECONDS=0,
            ANALYSIS_FPS=2,
            ANALYSIS_BATCH_SECONDS=1,
        )
        self.store = AudioStore(Path(self._tmp.name), self.config.audio_retention)
        self.bus = EventBus()
        self.events = self.bus.subscribe()
        self.state = PipelineState(self.config, "m", "w")
        self.pipeline = None

    def tearDown(self):
        if self.pipeline:
            self.pipeline.stop()
        self._tmp.cleanup()

    def build(self, analyzer, synthesizer, config=None):
        config = config or self.config
        self.pipeline = AnalysisPipeline(config, analyzer, synthesizer, self.bus, self.state)
        self.state.attach_pipeline(self.pipeline)
        self.pipeline.start()
        return self.pipeline

    def drain(self):
        out = []
        while not self.events.empty():
            out.append(self.events.get_nowait())
        return out

    def feed(self, pipeline, count, start=1):
        for i in range(start, start + count):
            pipeline.submit_frame(make_frame(i))


class TestEndToEnd(PipelineTestCase):
    def test_two_frames_produce_analysis_then_audio(self):
        synth = RecordingSynthesizer(self.store)
        pipeline = self.build(MockVisionAnalyzer(latency_seconds=0.0), synth)

        self.feed(pipeline, 2)

        wait_until(lambda: pipeline.metrics.speech_succeeded >= 1,
                   message="no audio produced")
        events = self.drain()
        kinds = [e["type"] for e in events]
        self.assertEqual(kinds, ["analysis", "audio_ready"],
                         "analysis text must be published before audio")

        analysis_event, audio_event = events
        self.assertEqual(analysis_event["frame_sequences"], [1, 2])
        self.assertTrue(analysis_event["captured_at"].endswith("Z"))
        self.assertEqual(audio_event["analysis_id"], analysis_event["analysis_id"])
        self.assertEqual(audio_event["audio_url"],
                         f"/api/audio/{analysis_event['analysis_id']}.mp3")

        # the referenced file must exist and be a real MP3
        path = self.store.path_for(audio_event["analysis_id"])
        self.assertIsNotNone(path)
        self.assertEqual(path.read_bytes()[:2], b"\xff\xfb")

        snapshot = self.state.snapshot()
        self.assertEqual(snapshot["latest_analysis"]["analysis_id"],
                         analysis_event["analysis_id"])
        self.assertEqual(snapshot["latest_audio"]["analysis_id"],
                         analysis_event["analysis_id"])

    def test_one_frame_does_not_trigger_analysis(self):
        analyzer = RecordingAnalyzer()
        pipeline = self.build(analyzer, RecordingSynthesizer(self.store))
        self.feed(pipeline, 1)
        time.sleep(0.25)
        self.assertEqual(analyzer.calls, 0, "a partial window must not be analysed")
        self.assertEqual(pipeline.metrics.batches_created, 0)


class TestBackpressure(PipelineTestCase):
    def test_burst_keeps_only_the_newest_batch(self):
        """A burst far faster than the analyzer must not queue up requests."""
        analyzer = RecordingAnalyzer(latency=0.25)
        pipeline = self.build(analyzer, RecordingSynthesizer(self.store))

        # 20 frames = 10 batches, delivered in one go
        self.feed(pipeline, 20)

        wait_until(lambda: pipeline.metrics.batches_created == 10)
        wait_until(lambda: pipeline.metrics.batches_dropped > 0,
                   message="stale batches were not dropped")
        # let the pipeline settle: pending drained and nothing in flight
        wait_until(lambda: pipeline.pending_batches == 0)
        time.sleep(0.45)

        metrics = pipeline.metrics
        self.assertEqual(metrics.batches_created, 10)
        self.assertEqual(
            metrics.batches_dropped + analyzer.calls, 10,
            "every batch is either analysed or explicitly dropped",
        )
        # The exact split depends on scheduling, but a 0.25s analyzer can never
        # keep up with an instantaneous burst of ten batches.
        self.assertLessEqual(analyzer.calls, 3,
                             f"burst was not collapsed (analysed {analyzer.calls}/10)")
        self.assertGreaterEqual(metrics.batches_dropped, 7)
        self.assertEqual(analyzer.seen_batches[-1], [19, 20],
                         "the newest batch must be the last one analysed")

    def test_pending_never_exceeds_one(self):
        analyzer = RecordingAnalyzer(latency=0.15)
        pipeline = self.build(analyzer, RecordingSynthesizer(self.store))

        observed = []
        for wave in range(6):
            self.feed(pipeline, 2, start=1 + wave * 2)
            observed.append(pipeline.pending_batches)
            time.sleep(0.05)

        wait_until(lambda: pipeline.metrics.analyses_succeeded >= 1)
        self.assertTrue(all(count <= 1 for count in observed),
                        f"pending batch slot exceeded one: {observed}")

    def test_sustained_slow_rate_drops_nothing(self):
        """When the analyzer keeps up, no footage may be discarded."""
        analyzer = RecordingAnalyzer(latency=0.02)
        pipeline = self.build(analyzer, RecordingSynthesizer(self.store))

        for wave in range(4):
            self.feed(pipeline, 2, start=1 + wave * 2)
            wait_until(lambda w=wave: analyzer.calls == w + 1,
                       message="analyzer fell behind a slow feed")

        self.assertEqual(pipeline.metrics.batches_dropped, 0)
        self.assertEqual(analyzer.seen_batches,
                         [[1, 2], [3, 4], [5, 6], [7, 8]])


class TestRetryPolicy(PipelineTestCase):
    def test_transient_error_is_retried_once(self):
        analyzer = RecordingAnalyzer(errors=[AnalysisError("boom"), None])
        pipeline = self.build(analyzer, RecordingSynthesizer(self.store))
        self.feed(pipeline, 2)

        wait_until(lambda: pipeline.metrics.analyses_succeeded == 1,
                   message="retry did not recover")
        self.assertEqual(analyzer.calls, 2, "exactly one retry")
        self.assertEqual(pipeline.metrics.analyses_failed, 0)

    def test_schema_rejection_is_not_retried(self):
        analyzer = RecordingAnalyzer(errors=[SchemaValidationError("bad shape")])
        pipeline = self.build(analyzer, RecordingSynthesizer(self.store))
        self.feed(pipeline, 2)

        wait_until(lambda: pipeline.metrics.schema_rejections == 1)
        time.sleep(0.3)
        self.assertEqual(analyzer.calls, 1, "schema failures must never be retried")
        self.assertEqual(pipeline.metrics.analyses_succeeded, 0)

        health = [e for e in self.drain() if e["type"] == "health"]
        self.assertTrue(health, "a degraded health event must be published")
        self.assertEqual(health[0]["service"], "gemini")
        self.assertEqual(health[0]["state"], "degraded")

    def test_repeated_failure_degrades_but_keeps_running(self):
        analyzer = RecordingAnalyzer(errors=[AnalysisError("a"), AnalysisError("b")])
        pipeline = self.build(analyzer, RecordingSynthesizer(self.store))
        self.feed(pipeline, 2)

        wait_until(lambda: pipeline.metrics.analyses_failed == 1)
        self.assertEqual(self.state.health("gemini").state, "degraded")

        # the pipeline must still accept and analyse later batches
        analyzer.set_errors([])
        self.feed(pipeline, 2, start=3)
        wait_until(lambda: pipeline.metrics.analyses_succeeded == 1,
                   message="pipeline did not recover after an outage")
        self.assertEqual(self.state.health("gemini").state, "ok")


class TestSpeechPolicy(PipelineTestCase):
    def test_identical_narration_is_not_synthesized_twice(self):
        synth = RecordingSynthesizer(self.store)
        pipeline = self.build(FixedNarrationAnalyzer(), synth)

        self.feed(pipeline, 2)
        wait_until(lambda: pipeline.metrics.speech_succeeded == 1)
        self.feed(pipeline, 2, start=3)
        wait_until(lambda: pipeline.metrics.speech_skipped_duplicate == 1,
                   message="duplicate narration was not skipped")

        time.sleep(0.2)
        self.assertEqual(len(synth.texts), 1, "the same text must be spoken once")

    def test_minimum_speech_interval_is_enforced(self):
        config = make_config(
            AUDIO_DIR=self._tmp.name,
            TTS_MIN_INTERVAL_SECONDS=1.0,
            ANALYSIS_FPS=2,
            ANALYSIS_BATCH_SECONDS=1,
        )
        synth = RecordingSynthesizer(self.store)
        pipeline = self.build(RecordingAnalyzer(), synth, config=config)

        self.feed(pipeline, 2)
        wait_until(lambda: len(synth.started_at) == 1)
        self.feed(pipeline, 2, start=3)
        wait_until(lambda: len(synth.started_at) == 2, timeout=8,
                   message="second narration never spoke")

        gap = synth.started_at[1] - synth.started_at[0]
        self.assertGreaterEqual(round(gap, 2), 1.0,
                                f"speech cooldown not honoured (gap {gap:.2f}s)")

    def test_newer_narration_supersedes_one_waiting_on_cooldown(self):
        config = make_config(
            AUDIO_DIR=self._tmp.name,
            TTS_MIN_INTERVAL_SECONDS=1.5,
            ANALYSIS_FPS=2,
            ANALYSIS_BATCH_SECONDS=1,
        )
        synth = RecordingSynthesizer(self.store)
        analyzer = RecordingAnalyzer()
        pipeline = self.build(analyzer, synth, config=config)

        self.feed(pipeline, 2)
        wait_until(lambda: len(synth.started_at) == 1)

        # two more analyses arrive while the cooldown is still running
        self.feed(pipeline, 2, start=3)
        wait_until(lambda: pipeline.metrics.analyses_succeeded >= 2)
        self.feed(pipeline, 2, start=5)
        wait_until(lambda: pipeline.metrics.speech_skipped_superseded >= 1, timeout=8,
                   message="older queued narration was not superseded")

        wait_until(lambda: len(synth.started_at) == 2, timeout=8)
        self.assertEqual(synth.texts[1], "narration [5, 6]",
                         "the newest narration must win, not the queued one")


if __name__ == "__main__":
    unittest.main()
