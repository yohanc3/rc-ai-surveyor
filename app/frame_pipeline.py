"""Frame batching and the bounded analysis/speech workers.

Backpressure policy (design document sections 5 and 7): one request in flight
per stage, and at most one pending item, which is always the newest. Stale
footage and stale narration are discarded rather than queued.
"""

from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from dataclasses import asdict, dataclass, field

from .config import Config
from .events import EventBus
from .models import (
    Analysis,
    AnalysisError,
    Frame,
    FrameBatch,
    SchemaValidationError,
    new_analysis_id,
)

log = logging.getLogger("rc.pipeline")

RETRY_BASE_SECONDS = 0.4


@dataclass
class Metrics:
    frames_captured: int = 0
    batches_created: int = 0
    batches_dropped: int = 0
    analyses_succeeded: int = 0
    analyses_failed: int = 0
    schema_rejections: int = 0
    gemini_last_latency_ms: int = 0
    speech_succeeded: int = 0
    speech_failed: int = 0
    speech_skipped_duplicate: int = 0
    speech_skipped_superseded: int = 0
    elevenlabs_last_latency_ms: int = 0
    audio_bytes_last: int = 0
    last_batch_age_ms: int = 0

    def to_json(self) -> dict:
        return asdict(self)


class FrameBatcher:
    """Groups the frames from one batching window into a single request."""

    def __init__(self, frames_per_batch: int) -> None:
        self._size = max(1, frames_per_batch)
        self._frames: list[Frame] = []

    def add(self, frame: Frame) -> FrameBatch | None:
        self._frames.append(frame)
        if len(self._frames) < self._size:
            return None
        batch = FrameBatch(
            analysis_id=new_analysis_id(),
            frames=tuple(self._frames),
            created_mono=time.monotonic(),
        )
        self._frames.clear()
        return batch

    @property
    def buffered(self) -> int:
        return len(self._frames)


class AnalysisPipeline:
    """Owns an asyncio loop on its own thread and drives both provider stages."""

    def __init__(
        self, config: Config, analyzer, synthesizer, bus: EventBus, state,
        skills=None,
    ) -> None:
        self._config = config
        self._skills = skills
        self._analyzer = analyzer
        self._synthesizer = synthesizer
        self._bus = bus
        self._state = state
        self._batcher = FrameBatcher(config.frames_per_batch)
        self._metrics = Metrics()
        self._metrics_lock = threading.Lock()

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stopping: asyncio.Event | None = None
        self._batch_ready: asyncio.Event | None = None
        self._narration_ready: asyncio.Event | None = None
        self._pending_batch: FrameBatch | None = None
        self._pending_narration: Analysis | None = None
        self._last_narration_text: str | None = None
        self._last_speech_start = 0.0

    # ---------- lifecycle ----------

    def start(self) -> None:
        ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run, args=(ready,), name="analysis-pipeline", daemon=True
        )
        self._thread.start()
        if not ready.wait(timeout=5):
            raise RuntimeError("analysis pipeline failed to start")

    def _run(self, ready: threading.Event) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)

        async def main() -> None:
            self._stopping = asyncio.Event()
            self._batch_ready = asyncio.Event()
            self._narration_ready = asyncio.Event()
            ready.set()
            await asyncio.gather(self._analysis_worker(), self._speech_worker())

        try:
            loop.run_until_complete(main())
        except Exception:  # pragma: no cover - surfaced in logs
            log.exception("analysis pipeline crashed")
        finally:
            ready.set()
            loop.close()

    def stop(self) -> None:
        loop, stopping = self._loop, self._stopping
        if loop and stopping:
            for action in (stopping.set, self._batch_ready.set, self._narration_ready.set):
                try:
                    loop.call_soon_threadsafe(action)
                except RuntimeError:
                    # The loop finished between the check and the call; nothing
                    # left to wake.
                    break
        if self._thread:
            self._thread.join(timeout=5)

    # ---------- ingestion ----------

    def submit_frame(self, frame: Frame) -> None:
        """Called from the sampler thread. Never blocks on provider work."""
        with self._metrics_lock:
            self._metrics.frames_captured += 1
        batch = self._batcher.add(frame)
        if batch is None:
            return
        with self._metrics_lock:
            self._metrics.batches_created += 1
        loop = self._loop
        if loop and not loop.is_closed():
            loop.call_soon_threadsafe(self._offer_batch, batch)

    def _offer_batch(self, batch: FrameBatch) -> None:
        if self._pending_batch is not None:
            # Busy: keep only the newest complete batch.
            with self._metrics_lock:
                self._metrics.batches_dropped += 1
        self._pending_batch = batch
        self._batch_ready.set()

    # ---------- analysis stage ----------

    async def _analysis_worker(self) -> None:
        while not self._stopping.is_set():
            await self._wait(self._batch_ready)
            if self._stopping.is_set():
                return
            batch = self._pending_batch
            self._pending_batch = None
            self._batch_ready.clear()
            if batch is not None:
                await self._analyze(batch)

    async def _analyze(self, batch: FrameBatch) -> None:
        age_ms = batch.age_ms(time.monotonic())
        with self._metrics_lock:
            self._metrics.last_batch_age_ms = age_ms
        log.info(
            "frame_batch_ready analysis_id=%s frames=%s age_ms=%d",
            batch.analysis_id,
            ",".join(str(s) for s in batch.sequences),
            age_ms,
        )

        started = time.monotonic()
        try:
            analysis = await self._call_analyzer(batch)
        except SchemaValidationError as error:
            with self._metrics_lock:
                self._metrics.schema_rejections += 1
                self._metrics.analyses_failed += 1
            self._degrade("gemini", f"invalid response: {error}")
            return
        except AnalysisError as error:
            with self._metrics_lock:
                self._metrics.analyses_failed += 1
            self._degrade("gemini", str(error))
            return

        latency_ms = int((time.monotonic() - started) * 1000)
        with self._metrics_lock:
            self._metrics.analyses_succeeded += 1
            self._metrics.gemini_last_latency_ms = latency_ms
        log.info("gemini_complete analysis_id=%s latency_ms=%d", analysis.analysis_id, latency_ms)

        self._state.set_analysis(analysis)
        self._state.health("gemini").set("ok", f"{latency_ms} ms")
        self._bus.publish(analysis.to_event())
        log.info("analysis_published analysis_id=%s", analysis.analysis_id)

        self._offer_narration(analysis)

    async def _call_analyzer(self, batch: FrameBatch) -> Analysis:
        """One retry with jitter for transient faults; never for schema failures."""
        try:
            return await self._analyzer.analyze(batch)
        except SchemaValidationError:
            raise
        except AnalysisError as error:
            delay = RETRY_BASE_SECONDS + random.random() * RETRY_BASE_SECONDS
            log.warning(
                "gemini_retry analysis_id=%s delay_ms=%d reason=%s",
                batch.analysis_id,
                int(delay * 1000),
                error,
            )
            await asyncio.sleep(delay)
            return await self._analyzer.analyze(batch)
        except Exception as error:
            raise AnalysisError(f"{type(error).__name__}: {error}") from error

    def _speech_interval(self) -> float:
        """How long to wait between spoken lines.

        A skill may set its own pace — a documentary narrator needs room, a
        sports commentator does not — and falls back to the configured value
        when it names none.
        """
        if self._skills is not None:
            override = self._skills.active().speech_interval
            if override is not None:
                return override
        return self._config.tts_min_interval_seconds

    # ---------- speech stage ----------

    def _offer_narration(self, analysis: Analysis) -> None:
        if analysis.narration_text.strip() == "Nothing new to report.":
            self._pending_narration = None
            self._narration_ready.clear()
            log.info("speech_skipped_no_news analysis_id=%s", analysis.analysis_id)
            return
        if analysis.narration_text == self._last_narration_text:
            with self._metrics_lock:
                self._metrics.speech_skipped_duplicate += 1
            log.info("speech_skipped_duplicate analysis_id=%s", analysis.analysis_id)
            return
        self._pending_narration = analysis
        self._narration_ready.set()

    async def _speech_worker(self) -> None:
        while not self._stopping.is_set():
            await self._wait(self._narration_ready)
            if self._stopping.is_set():
                return
            analysis = self._pending_narration
            self._pending_narration = None
            self._narration_ready.clear()
            if analysis is None:
                continue

            cooldown = self._speech_interval() - (
                time.monotonic() - self._last_speech_start
            )
            if cooldown > 0:
                await asyncio.sleep(cooldown)
                if self._stopping.is_set():
                    return
                if self._pending_narration is not None:
                    # A newer narration arrived while waiting; that one wins.
                    with self._metrics_lock:
                        self._metrics.speech_skipped_superseded += 1
                    continue

            await self._speak(analysis)

    async def _speak(self, analysis: Analysis) -> None:
        self._last_speech_start = time.monotonic()
        self._last_narration_text = analysis.narration_text
        started = time.monotonic()
        try:
            result = await self._synthesizer.synthesize(analysis)
        except Exception as error:
            with self._metrics_lock:
                self._metrics.speech_failed += 1
            self._degrade("elevenlabs", f"{type(error).__name__}: {error}")
            return

        latency_ms = int((time.monotonic() - started) * 1000)
        with self._metrics_lock:
            self._metrics.speech_succeeded += 1
            self._metrics.elevenlabs_last_latency_ms = latency_ms
            self._metrics.audio_bytes_last = result.byte_count
        log.info(
            "elevenlabs_complete analysis_id=%s latency_ms=%d bytes=%d",
            result.analysis_id,
            latency_ms,
            result.byte_count,
        )
        self._state.set_audio(result)
        self._state.health("elevenlabs").set("ok", f"{latency_ms} ms")
        self._bus.publish(result.to_event())
        log.info("audio_published analysis_id=%s url=%s", result.analysis_id, result.audio_url)

    # ---------- helpers ----------

    def _degrade(self, service: str, detail: str) -> None:
        log.warning("%s_degraded detail=%s", service, detail)
        self._state.health(service).set("degraded", detail)
        self._bus.publish({"type": "health", "service": service, "state": "degraded", "detail": detail})

    async def _wait(self, event: asyncio.Event) -> None:
        """Wait for an event, but return promptly on shutdown."""
        waiter = asyncio.ensure_future(event.wait())
        stopper = asyncio.ensure_future(self._stopping.wait())
        done, pending = await asyncio.wait(
            {waiter, stopper}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()

    @property
    def metrics(self) -> Metrics:
        with self._metrics_lock:
            return Metrics(**self._metrics.to_json())

    @property
    def pending_batches(self) -> int:
        return 1 if self._pending_batch is not None else 0
