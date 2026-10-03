'use strict';

// Fallback dashboard. Polls /api/status only; the React build uses SSE.

const el = (id) => document.getElementById(id);

const video = el('video');
const fallback = el('video-fallback');
const overlay = el('overlay');
const overlayText = el('overlay-text');
const videoMode = el('video-mode');
const liveBadge = el('live-badge');
const frameImg = el('frame');
const frameEmpty = el('frame-empty');
const player = el('player');

let config = null;
let pc = null;
let whepAttempts = 0;
let usingFallback = false;
let lastFrameSeq = 0;
let lastAudioId = null;
let audioEnabled = false;

const MAX_WHEP_ATTEMPTS = 2;

function setOverlay(text, failed = false) {
  if (text === null) {
    overlay.hidden = true;
    return;
  }
  overlay.hidden = false;
  overlay.classList.toggle('failed', failed);
  overlayText.textContent = text;
}

function setBadge(node, text, kind = '') {
  node.textContent = text;
  node.classList.remove('ready', 'error', 'quiet');
  if (kind) node.classList.add(kind);
}

/* ---------- live video over WHEP ---------- */

function waitForIce(peer) {
  if (peer.iceGatheringState === 'complete') return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => {
      peer.removeEventListener('icegatheringstatechange', check);
      clearTimeout(timer);
      resolve();
    };
    const check = () => {
      if (peer.iceGatheringState === 'complete') done();
    };
    const timer = setTimeout(done, 2000);
    peer.addEventListener('icegatheringstatechange', check);
  });
}

function teardown() {
  if (!pc) return;
  pc.onconnectionstatechange = null;
  pc.ontrack = null;
  pc.close();
  pc = null;
}

async function startWhep() {
  teardown();
  whepAttempts += 1;
  setOverlay('Connecting to live video…');

  const peer = new RTCPeerConnection({ iceServers: [] });
  pc = peer;
  peer.addTransceiver('video', { direction: 'recvonly' });

  const stream = new MediaStream();
  peer.ontrack = (event) => {
    stream.addTrack(event.track);
    video.srcObject = stream;
  };

  peer.onconnectionstatechange = () => {
    if (peer !== pc) return;
    if (peer.connectionState === 'connected') {
      whepAttempts = 0;
      setOverlay(null);
      video.hidden = false;
    } else if (peer.connectionState === 'failed' || peer.connectionState === 'closed') {
      handleWhepFailure(`connection ${peer.connectionState}`);
    }
  };

  const offer = await peer.createOffer();
  await peer.setLocalDescription(offer);
  await waitForIce(peer);

  const response = await fetch(config.whep_url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/sdp' },
    body: peer.localDescription.sdp,
  });
  if (!response.ok) throw new Error(`WHEP responded ${response.status}`);

  const answer = await response.text();
  if (peer !== pc) return;
  await peer.setRemoteDescription({ type: 'answer', sdp: answer });
}

function handleWhepFailure(reason) {
  teardown();
  if (whepAttempts < MAX_WHEP_ATTEMPTS) {
    setOverlay(`Live video retrying (${reason})…`);
    setTimeout(() => connectVideo(), 1500);
    return;
  }
  useFallback(reason);
}

function useFallback(reason) {
  if (usingFallback) return;
  usingFallback = true;
  teardown();
  console.warn('falling back to the MediaMTX player:', reason);
  if (!config.media_url) {
    setOverlay('Live video unavailable and no fallback player configured', true);
    return;
  }
  video.hidden = true;
  fallback.hidden = false;
  fallback.src = config.media_url;
  videoMode.textContent = 'MediaMTX player';
  setOverlay(null);
}

async function connectVideo() {
  if (usingFallback || !config || !config.whep_url) return;
  try {
    await startWhep();
  } catch (error) {
    handleWhepFailure(error.message);
  }
}

el('reconnect').addEventListener('click', () => {
  whepAttempts = 0;
  usingFallback = false;
  fallback.hidden = true;
  fallback.removeAttribute('src');
  video.hidden = false;
  videoMode.textContent = 'WebRTC';
  connectVideo();
});

el('enable-audio').addEventListener('click', () => {
  audioEnabled = true;
  el('enable-audio').hidden = true;
  player.hidden = false;
  player.play().catch(() => {});
});

/* ---------- status polling ---------- */

function formatBytes(value) {
  if (!value) return '—';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(2)} MB`;
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  const total = Math.floor(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

const DOT = { ok: 'ok', degraded: 'warn', down: 'bad', disabled: 'muted', unknown: 'muted' };

function renderServices(services) {
  el('services').innerHTML = ['camera', 'video', 'gemini', 'elevenlabs']
    .map((name) => {
      const service = services[name] || { state: 'unknown', detail: '' };
      return `<li><span class="dot ${DOT[service.state] || 'muted'}"></span>` +
        `<span class="service-name">${name}</span>` +
        `<span class="service-state">${service.state}</span></li>`;
    })
    .join('');
}

function renderStats(status) {
  const frames = status.frames || {};
  const relay = status.relay || {};
  const metrics = status.metrics || {};
  const rows = [
    ['Frames', (frames.captured || 0).toLocaleString()],
    ['Sample rate', `${frames.measured_fps || '—'} / ${frames.configured_fps || '—'} fps`],
    ['Frame size', formatBytes(frames.last_bytes)],
    ['Relay', relay.up ? 'up' : 'down'],
    ['Restarts', String(relay.restarts || 0)],
    ['Providers', status.provider_mode || '—'],
    ['Analysed', String(metrics.analyses_succeeded || 0)],
    ['Dropped', String(metrics.batches_dropped || 0)],
    ['Spoken', String(metrics.speech_succeeded || 0)],
  ];
  el('stats').innerHTML = rows
    .map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`)
    .join('');
}

function renderAnalysis(status) {
  const analysis = status.latest_analysis;
  if (analysis) {
    el('technical').textContent = analysis.technical_description;
    el('technical').classList.remove('muted');
    el('narration').textContent = analysis.narration_text;
    el('narration').classList.remove('muted');
  }
  const audio = status.latest_audio;
  if (audio && audio.analysis_id !== lastAudioId) {
    lastAudioId = audio.analysis_id;
    player.src = audio.audio_url;
    player.hidden = false;
    if (audioEnabled) player.play().catch(() => {});
  }
}

async function refresh() {
  try {
    const response = await fetch('/api/status', { cache: 'no-store' });
    if (!response.ok) throw new Error(`status ${response.status}`);
    const status = await response.json();
    const frames = status.frames || {};

    if (!frames.captured) {
      setBadge(liveBadge, 'waiting for frames', '');
    } else if (frames.stale) {
      setBadge(liveBadge, 'frames stalled', 'error');
    } else {
      setBadge(liveBadge, `frame ${frames.captured}`, 'ready');
    }
    setBadge(el('uptime'), `up ${formatDuration(status.uptime_seconds)}`, 'quiet');

    renderServices(status.services || {});
    renderStats(status);
    renderAnalysis(status);

    if (frames.captured > lastFrameSeq) {
      lastFrameSeq = frames.captured;
      frameImg.src = `/api/frame?n=${lastFrameSeq}`;
      frameImg.hidden = false;
      frameEmpty.hidden = true;
    }
    el('frame-meta').textContent = frames.captured
      ? `#${frames.captured} · ${formatBytes(frames.last_bytes)}`
      : '—';
  } catch (_) {
    setBadge(liveBadge, 'backend unavailable', 'error');
  }
}

/* ---------- boot ---------- */

async function boot() {
  try {
    const response = await fetch('/api/config', { cache: 'no-store' });
    config = await response.json();
  } catch (error) {
    setOverlay('Cannot reach the backend. Is run.py still going?', true);
    return;
  }
  connectVideo();
  refresh();
  setInterval(refresh, 1000);
}

boot();
