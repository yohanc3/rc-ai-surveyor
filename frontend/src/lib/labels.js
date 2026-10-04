/**
 * Plain-English copy for the dashboard.
 *
 * Every user-facing string lives here so the interface can be read by someone
 * who has never seen the code. The backend speaks in its own vocabulary —
 * relay, WHEP, batches, schema rejections — and this module is the single
 * place that translates it. Panels import from here rather than inventing
 * their own wording, which keeps the voice consistent and makes the whole UI
 * translatable later by swapping one file.
 */

/* Service rows in the Status panel. The backend keys stay as they are; only
   the presentation changes, so nothing downstream has to know. */
export const SERVICE_LABELS = {
  camera: 'Camera',
  video: 'Live view',
  gemini: 'Scene descriptions',
  elevenlabs: 'Voice',
};

const SERVICE_STATE = {
  ok: { text: 'Ready', tone: 'ok' },
  degraded: { text: 'Having trouble', tone: 'warn' },
  down: { text: 'Not working', tone: 'bad' },
  disabled: { text: 'Turned off', tone: 'idle' },
  unknown: { text: 'Not started', tone: 'idle' },
};

export function serviceState(state) {
  return SERVICE_STATE[state] ?? SERVICE_STATE.unknown;
}

/* Where the page is getting its data. */
export const SOURCE_LABELS = {
  connecting: { text: 'Connecting', tone: 'quiet' },
  live: { text: 'Connected', tone: 'ok' },
  demo: { text: 'Demo mode', tone: 'warn' },
  offline: { text: 'Not connected', tone: 'bad' },
};

/* Whether real descriptions are being generated, or stand-ins. */
export function providerLabel(providerMode) {
  // 'unknown' is the placeholder before the first /api/status reply, so say
  // nothing rather than claiming a mode the app has not confirmed yet.
  if (!providerMode || providerMode === 'unknown') return null;
  return providerMode.startsWith('mock')
    ? { text: 'Practice mode', tone: 'quiet' }
    : { text: 'Live descriptions', tone: 'ok' };
}

/**
 * Turn a raw status snapshot into one headline sentence about the camera.
 * This is the first thing a person reads, so it answers the only question
 * they actually have: is it working?
 */
export function cameraHeadline(mode, status) {
  if (mode === 'offline') {
    return { text: 'Not connected', tone: 'bad', live: false };
  }
  const captured = status?.frames?.captured ?? 0;
  if (captured === 0) {
    return { text: 'Waiting for camera', tone: 'quiet', live: false };
  }
  if (status?.frames?.stale) {
    return { text: 'Camera stopped', tone: 'bad', live: false };
  }
  return { text: 'Camera live', tone: 'ok', live: true };
}

/* Event-log phrasing. The log used to print internal vocabulary verbatim;
   these read like something happening to the camera instead. */
export const EVENT_TEXT = {
  videoUp: 'Live view reconnected',
  videoDown: 'Live view interrupted',
  videoRestarted: 'Live view recovered on its own',
  framesStalled: 'Camera stopped sending pictures',
  framesResumed: 'Camera is sending pictures again',
  demoStarted: 'Switched to demo mode',
  liveStarted: 'Connected to the camera',
  offline: 'Lost connection to the app',
};

export function sourceChangeEvent(mode) {
  if (mode === 'demo') return { tone: 'warn', text: EVENT_TEXT.demoStarted };
  if (mode === 'offline') return { tone: 'bad', text: EVENT_TEXT.offline };
  if (mode === 'live') return { tone: 'ok', text: EVENT_TEXT.liveStarted };
  return null;
}

/** A service changing state, phrased for a person. */
export function serviceChangeEvent(key, state) {
  const name = SERVICE_LABELS[key] ?? key;
  const info = serviceState(state);
  const tone = info.tone === 'idle' ? 'info' : info.tone;
  if (state === 'ok') return { tone, text: `${name} is ready` };
  if (state === 'degraded') return { tone, text: `${name} is having trouble` };
  if (state === 'down') return { tone, text: `${name} stopped working` };
  return { tone, text: `${name}: ${info.text.toLowerCase()}` };
}

/* Live-view overlay copy, keyed by the connection state of the video hook. */
export const VIDEO_OVERLAY = {
  idle: { title: 'Starting up', hint: 'Getting the live view ready.' },
  connecting: {
    title: 'Connecting to the camera',
    hint: 'This usually takes a couple of seconds.',
  },
  failed: {
    title: 'No live view',
    hint: 'The camera picture is not coming through. Check that the camera is on and still connected, then try again.',
  },
  nofallback: {
    title: 'No live view',
    hint: 'The video connection could not be started.',
  },
};

/* Empty states, written as guidance rather than a null value. */
export const EMPTY = {
  observations: {
    title: 'Nothing described yet',
    hint: 'Descriptions of what the camera sees will appear here as they come in.',
  },
  observationsPractice: {
    title: 'Practice mode',
    hint: 'Sample descriptions will appear here. Turn on live descriptions to see what the camera really sees.',
  },
  snapshot: {
    title: 'No picture yet',
    hint: 'The most recent picture from the camera will show here.',
  },
  audio: {
    title: 'Nothing to play yet',
    hint: 'When a description is read aloud, the recording appears here.',
  },
  events: {
    title: 'Nothing to report',
    hint: 'Interruptions and reconnections will be listed here.',
  },
};
