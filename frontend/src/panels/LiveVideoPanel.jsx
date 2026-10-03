import { useWhep } from '../video/useWhep';

const LABELS = {
  idle: 'Starting…',
  connecting: 'Connecting to live video…',
  playing: '',
  fallback: '',
  failed: 'Live video unavailable',
};

export function LiveVideoPanel({ config, mode, frameUrl, status }) {
  const isDemo = mode === 'demo';
  const { videoRef, state, error, reconnect } = useWhep(config?.whep_url, {
    enabled: !isDemo && Boolean(config?.whep_url),
  });

  // In demo mode there is no WebRTC stream, so animate the mock frames in the
  // video slot instead. Same panel, no special-casing anywhere else.
  if (isDemo) {
    return (
      <div className="video-shell">
        {frameUrl ? (
          <img className="video-media" src={frameUrl} alt="Simulated camera feed" />
        ) : (
          <div className="overlay">
            <div className="spinner" />
            <p>Generating demo feed…</p>
          </div>
        )}
        <div className="video-foot">
          <span className="tag">demo feed · {status.frames?.configured_fps ?? 2} fps</span>
        </div>
      </div>
    );
  }

  const showFallback = state === 'fallback' && Boolean(config?.media_url);
  const overlay =
    state === 'fallback' && !showFallback
      ? 'Live video unavailable and no fallback player configured'
      : LABELS[state];
  const isError = state === 'failed' || (state === 'fallback' && !showFallback);

  return (
    <div className="video-shell">
      {showFallback ? (
        <iframe
          className="video-media"
          src={config.media_url}
          allow="autoplay; fullscreen"
          title="Live GoPro feed"
        />
      ) : (
        <video className="video-media" ref={videoRef} autoPlay muted playsInline />
      )}

      {overlay ? (
        <div className={`overlay ${isError ? 'failed' : ''}`.trim()}>
          {!isError ? <div className="spinner" /> : null}
          <p>{overlay}</p>
          {error ? <p className="small muted">{error}</p> : null}
        </div>
      ) : null}

      <div className="video-foot">
        <span className="tag">{showFallback ? 'MediaMTX player' : 'WebRTC'}</span>
        <button type="button" onClick={reconnect}>
          Reconnect
        </button>
      </div>
    </div>
  );
}
