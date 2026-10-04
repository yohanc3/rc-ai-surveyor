import { useWhep } from '../video/useWhep';
import { Button } from '../components/Button';
import { StatusDot } from '../components/Badge';
import { Icon } from '../components/Icon';
import { VIDEO_OVERLAY } from '../lib/labels';

/**
 * The live picture, presented as the hero of the page.
 *
 * Two sources feed the same frame: WebRTC in normal use, and the generated
 * demo images when nothing is reachable. Controls float over the video on
 * glass, so the picture never shifts when a label changes.
 */
export function LiveVideoPanel({ config, mode, frameUrl }) {
  const isDemo = mode === 'demo';
  const { videoRef, state, error, reconnect } = useWhep(config?.whep_url, {
    enabled: !isDemo && Boolean(config?.whep_url),
  });

  if (isDemo) {
    return (
      <div className="video-shell">
        {frameUrl ? (
          <img className="video-media" src={frameUrl} alt="Simulated camera view" />
        ) : (
          <div className="overlay">
            <div className="spinner" />
            <p className="overlay-title">Building the demo view</p>
          </div>
        )}
        <div className="video-foot">
          <span className="glass">
            <StatusDot tone="warn" />
            Demo picture
          </span>
        </div>
      </div>
    );
  }

  const showFallback = state === 'fallback' && Boolean(config?.media_url);
  const isPlaying = state === 'playing' || showFallback;

  let overlay = null;
  if (state === 'fallback' && !showFallback) overlay = VIDEO_OVERLAY.nofallback;
  else if (!isPlaying) overlay = VIDEO_OVERLAY[state] ?? null;

  const isError = state === 'failed' || (state === 'fallback' && !showFallback);

  return (
    <div className="video-shell">
      {showFallback ? (
        <iframe
          className="video-media"
          src={config.media_url}
          allow="autoplay; fullscreen"
          title="Live camera view"
        />
      ) : (
        <video className="video-media" ref={videoRef} autoPlay muted playsInline />
      )}

      {overlay ? (
        <div className={`overlay ${isError ? 'overlay-bad' : ''}`.trim()}>
          {isError ? (
            <span className="overlay-icon">
              <Icon name="alert" size={20} />
            </span>
          ) : (
            <div className="spinner" />
          )}
          <p className="overlay-title">{overlay.title}</p>
          <p className="overlay-hint">{overlay.hint}</p>
          {error && isError ? <p className="overlay-hint">{error}</p> : null}
        </div>
      ) : null}

      <div className="video-foot">
        <span className="glass">
          <StatusDot tone={isPlaying ? 'ok' : 'idle'} live={isPlaying} />
          {isPlaying ? 'Live' : 'Not live'}
        </span>
        <Button onClick={reconnect}>
          <Icon name="refresh" size={14} />
          <span>Reconnect</span>
        </Button>
      </div>
    </div>
  );
}
