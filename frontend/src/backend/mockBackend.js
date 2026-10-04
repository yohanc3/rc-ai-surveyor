// Demo backend: runs the whole dashboard with no GoPro, no Docker and no
// Python. Emits the same events and status shape as the real backend, so no
// panel can tell the difference. Enable with ?demo=1, or let it engage when the
// real backend cannot be reached.

const WIDTH = 480;
const HEIGHT = 270;

// Demo output is intentionally labeled as synthetic, never camera analysis.
const SCENES = [
  {
    technical_description:
      'Synthetic demo scene; this description was not derived from camera pixels.',
    narration_text:
      'This is synthetic demo output, not an analysis of the camera image.',
  },
];

const ID_ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';

function mockAnalysisId(counter) {
  // Sortable like the backend's ULID-style ids: time prefix, then a counter.
  const stamp = Date.now().toString(32).toUpperCase().padStart(10, '0');
  const tail = String(counter).padStart(16, '0');
  return (stamp + tail)
    .slice(0, 26)
    .split('')
    .map((c) => (ID_ALPHABET.includes(c) ? c : '0'))
    .join('');
}

function drawScene(ctx, t) {
  const sky = ctx.createLinearGradient(0, 0, 0, HEIGHT);
  sky.addColorStop(0, '#16222e');
  sky.addColorStop(1, '#2c3b48');
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, WIDTH, HEIGHT);

  ctx.fillStyle = '#1b2630';
  ctx.fillRect(0, HEIGHT * 0.62, WIDTH, HEIGHT * 0.38);
  ctx.strokeStyle = 'rgba(138,163,189,0.28)';
  ctx.lineWidth = 1;
  const drift = (t * 60) % 40;
  for (let y = HEIGHT * 0.62 + drift; y < HEIGHT; y += 40) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(WIDTH, y);
    ctx.stroke();
  }

  const crates = [
    { x: ((t * 70) % (WIDTH + 160)) - 80, w: 54, h: 40, fill: '#6b7f94' },
    { x: ((t * 45 + 220) % (WIDTH + 160)) - 80, w: 38, h: 62, fill: '#8a9cb0' },
  ];
  for (const crate of crates) {
    ctx.fillStyle = crate.fill;
    ctx.fillRect(crate.x, HEIGHT * 0.62 - crate.h, crate.w, crate.h);
    ctx.strokeStyle = 'rgba(0,0,0,0.35)';
    ctx.strokeRect(crate.x, HEIGHT * 0.62 - crate.h, crate.w, crate.h);
  }

  ctx.fillStyle = 'rgba(238,244,251,0.75)';
  ctx.font = '12px ui-monospace, monospace';
  ctx.fillText(`DEMO  t=${t.toFixed(1)}s`, 10, 20);
}

/**
 * A short, valid MP3 of silence, built the same way app/providers.py does it:
 * repeated MPEG-1 Layer III frames (128 kbps, 44.1 kHz, mono, 417 bytes each).
 * Real audio would need an encoder; silence still exercises the whole player.
 */
function silentMp3Url(seconds) {
  const FRAME = 417;
  const count = Math.max(1, Math.round((seconds * 44100) / 1152));
  const bytes = new Uint8Array(FRAME * count);
  for (let i = 0; i < count; i += 1) {
    const at = i * FRAME;
    bytes[at] = 0xff;
    bytes[at + 1] = 0xfb;
    bytes[at + 2] = 0x90;
    bytes[at + 3] = 0xc4;
  }
  return URL.createObjectURL(new Blob([bytes], { type: 'audio/mpeg' }));
}

export function createMockBackend({ sampleFps = 0.5, onEvent } = {}) {
  const started = performance.now();
  const canvas = document.createElement('canvas');
  canvas.width = WIDTH;
  canvas.height = HEIGHT;
  const ctx = canvas.getContext('2d');

  let frameCount = 0;
  let lastFrameAt = null;
  let lastFrameBytes = 0;
  let frameUrl = null;
  let relayUp = true;
  let relayRestarts = 0;
  let analyses = 0;
  let speechCount = 0;
  let latestAnalysis = null;
  let latestAudio = null;
  const audioUrls = [];
  const listeners = new Set();

  const elapsed = () => (performance.now() - started) / 1000;

  function snapshot() {
    const t = elapsed();
    return {
      uptime_seconds: t,
      provider_mode: 'mock (browser demo)',
      frames: {
        captured: frameCount,
        last_sequence: frameCount,
        last_bytes: lastFrameBytes,
        last_age_seconds: lastFrameAt === null ? null : t - lastFrameAt,
        last_captured_at: lastFrameAt === null ? null : Date.now() / 1000,
        measured_fps: frameCount > 1 ? sampleFps : 0,
        configured_fps: sampleFps,
        stale: lastFrameAt !== null && t - lastFrameAt > 3,
      },
      relay: { up: relayUp, restarts: relayRestarts },
      services: {
        camera: { state: frameCount ? 'ok' : 'unknown', detail: 'demo feed' },
        video: { state: relayUp ? 'ok' : 'down', detail: relayUp ? '' : 'relay not running' },
        gemini: { state: 'ok', detail: 'mock provider' },
        elevenlabs: { state: 'ok', detail: 'mock provider' },
      },
      latest_analysis: latestAnalysis,
      latest_audio: latestAudio,
      metrics: {
        frames_captured: frameCount,
        batches_created: analyses,
        batches_dropped: 0,
        analyses_succeeded: analyses,
        analyses_failed: 0,
        schema_rejections: 0,
        gemini_last_latency_ms: 620,
        speech_succeeded: speechCount,
        speech_failed: 0,
        speech_skipped_duplicate: 0,
        speech_skipped_superseded: 0,
        elevenlabs_last_latency_ms: 310,
        audio_bytes_last: 15846,
        last_batch_age_ms: 18,
        pending_batches: 0,
      },
    };
  }

  function emitStatus() {
    for (const fn of listeners) fn(snapshot(), frameUrl);
  }

  function tick() {
    const t = elapsed();

    // An occasional relay blip, so the telemetry and event log have something
    // real to react to.
    const blip = t > 23 && t % 23 < 2.2;
    if (blip && relayUp) {
      relayUp = false;
      relayRestarts += 1;
    } else if (!blip && !relayUp) {
      relayUp = true;
    }
    if (!relayUp) {
      emitStatus();
      return;
    }

    drawScene(ctx, t);
    const dataUrl = canvas.toDataURL('image/jpeg', 0.6);
    frameCount += 1;
    lastFrameAt = t;
    lastFrameBytes = Math.round((dataUrl.length - dataUrl.indexOf(',') - 1) * 0.75);
    frameUrl = dataUrl;

    // One analysis per batching window, matching ANALYSIS_BATCH_SECONDS.
    const framesPerBatch = Math.max(1, Math.round(sampleFps));
    if (frameCount % framesPerBatch === 0) {
      analyses += 1;
      const scene = SCENES[(analyses - 1) % SCENES.length];
      const analysisId = mockAnalysisId(analyses);
      const event = {
        type: 'analysis',
        analysis_id: analysisId,
        frame_sequences: [frameCount - framesPerBatch + 1, frameCount],
        captured_at: new Date().toISOString().replace(/\.(\d{3})\d*Z$/, '.$1Z'),
        ...scene,
      };
      latestAnalysis = event;
      onEvent?.(event);

      // Speech follows the text, as it does on the real backend.
      window.setTimeout(() => {
        speechCount += 1;
        const url = silentMp3Url(Math.min(12, scene.narration_text.split(' ').length / 3));
        audioUrls.push(url);
        while (audioUrls.length > 10) URL.revokeObjectURL(audioUrls.shift());
        latestAudio = { type: 'audio_ready', analysis_id: analysisId, audio_url: url };
        onEvent?.(latestAudio);
      }, 320);
    }

    emitStatus();
  }

  const timer = setInterval(tick, 1000 / sampleFps);
  tick();

  return {
    mode: 'demo',
    config: {
      sample_fps: sampleFps,
      whep_url: null,
      media_url: null,
      provider_mode: 'mock (browser demo)',
      tts_min_interval_seconds: 3,
      demo: true,
    },
    subscribe(fn) {
      listeners.add(fn);
      fn(snapshot(), frameUrl);
      return () => listeners.delete(fn);
    },
    stop() {
      clearInterval(timer);
      listeners.clear();
      for (const url of audioUrls) URL.revokeObjectURL(url);
      audioUrls.length = 0;
    },
  };
}
