import { useCallback, useEffect, useRef, useState } from 'react';
import { createMockBackend } from './mockBackend';

const POLL_MS = 1000;
const MAX_ANALYSES = 40;

export const EMPTY_STATUS = {
  uptime_seconds: 0,
  provider_mode: 'unknown',
  frames: {
    captured: 0,
    last_sequence: 0,
    last_bytes: 0,
    last_age_seconds: null,
    measured_fps: 0,
    configured_fps: 0.5,
    stale: false,
  },
  relay: { up: false, restarts: 0 },
  services: {
    camera: { state: 'unknown', detail: '' },
    video: { state: 'unknown', detail: '' },
    gemini: { state: 'unknown', detail: '' },
    elevenlabs: { state: 'unknown', detail: '' },
  },
  latest_analysis: null,
  latest_audio: null,
  metrics: {},
};

function wantsDemo() {
  return new URLSearchParams(window.location.search).has('demo');
}

/**
 * Single source of truth for the dashboard.
 *
 * Analysis and audio arrive over Server-Sent Events (design document section 8);
 * /api/status is polled for telemetry. The demo mock produces the same shapes,
 * so no panel knows which source it is reading.
 */
export function useBackend() {
  const [mode, setMode] = useState('connecting'); // connecting | live | demo | offline
  const [config, setConfig] = useState(null);
  const [status, setStatus] = useState(EMPTY_STATUS);
  const [analyses, setAnalyses] = useState([]);
  const [latestAudio, setLatestAudio] = useState(null);
  const [frameUrl, setFrameUrl] = useState(null);

  const mockRef = useRef(null);
  const seenFrame = useRef(0);
  const newestId = useRef(null);

  // Apply one event. Text is accepted only when it is newer than the analysis
  // already shown, so an out-of-order delivery cannot roll the dashboard back.
  const applyEvent = useCallback((event) => {
    if (!event || typeof event !== 'object') return;

    if (event.type === 'hello' && event.status) {
      setStatus(event.status);
      if (event.status.latest_analysis) applyEvent(event.status.latest_analysis);
      if (event.status.latest_audio) applyEvent(event.status.latest_audio);
      return;
    }

    if (event.type === 'analysis') {
      if (newestId.current && event.analysis_id <= newestId.current) return;
      newestId.current = event.analysis_id;
      setAnalyses((prev) => {
        if (prev.some((item) => item.analysis_id === event.analysis_id)) return prev;
        return [{ ...event, received_at: new Date() }, ...prev].slice(0, MAX_ANALYSES);
      });
      return;
    }

    if (event.type === 'audio_ready') {
      setLatestAudio(event);
      setAnalyses((prev) =>
        prev.map((item) =>
          item.analysis_id === event.analysis_id
            ? { ...item, audio_url: event.audio_url }
            : item,
        ),
      );
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer = null;
    let source = null;

    function startMock(sampleFps) {
      const mock = createMockBackend({
        sampleFps,
        onEvent: (event) => {
          if (!cancelled) applyEvent(event);
        },
      });
      mockRef.current = mock;
      setMode('demo');
      setConfig(mock.config);
      mock.subscribe((snap, url) => {
        if (cancelled) return;
        setStatus(snap);
        setFrameUrl(url);
      });
    }

    async function poll() {
      try {
        const response = await fetch('/api/status', { cache: 'no-store' });
        if (!response.ok) throw new Error(`status ${response.status}`);
        const snap = await response.json();
        if (cancelled) return;
        setStatus(snap);
        setMode('live');
        const captured = snap.frames?.captured ?? 0;
        if (captured > seenFrame.current) {
          seenFrame.current = captured;
          setFrameUrl(`/api/frame?n=${captured}`);
        }
      } catch {
        if (!cancelled) setMode('offline');
      } finally {
        if (!cancelled) timer = setTimeout(poll, POLL_MS);
      }
    }

    function openEventStream() {
      source = new EventSource('/api/events');
      source.onmessage = (message) => {
        if (cancelled) return;
        try {
          applyEvent(JSON.parse(message.data));
        } catch {
          // a malformed frame must not tear down the stream
        }
      };
      // EventSource reconnects on its own; the backend replays current state.
      source.onerror = () => {};
    }

    async function boot() {
      if (wantsDemo()) {
        startMock(2);
        return;
      }
      try {
        const response = await fetch('/api/config', { cache: 'no-store' });
        if (!response.ok) throw new Error(`config ${response.status}`);
        const cfg = await response.json();
        if (cancelled) return;
        setConfig(cfg);
        openEventStream();
        poll();
      } catch {
        if (cancelled) return;
        console.warn('backend unreachable, using demo data');
        startMock(2);
      }
    }

    boot();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      if (source) source.close();
      if (mockRef.current) {
        mockRef.current.stop();
        mockRef.current = null;
      }
    };
  }, [applyEvent]);

  return { mode, config, status, analyses, latestAudio, frameUrl };
}
