import { Panel } from '../components/Panel';
import { useNarrationAudio } from '../audio/useNarrationAudio';

export function NarrationAudioPanel({ latestAudio, status }) {
  const { enabled, enable, disable, playing, error } = useNarrationAudio(latestAudio);
  const interval = status?.tts_min_interval_seconds;

  return (
    <Panel
      title="Narration audio"
      actions={
        enabled ? (
          <button type="button" onClick={disable}>
            Mute
          </button>
        ) : (
          <button type="button" className="primary" onClick={enable}>
            Enable audio
          </button>
        )
      }
    >
      {!enabled ? (
        <p className="muted small">
          Browsers block audio until you interact with the page once. Enable it
          and each new narration plays automatically.
        </p>
      ) : (
        <p className="small">
          {playing ? 'Playing narration…' : 'Waiting for the next narration.'}
          {interval ? ` Minimum gap ${interval}s.` : ''}
        </p>
      )}

      {error ? <p className="small bad">Playback failed: {error}</p> : null}

      {latestAudio ? (
        <audio className="player" controls preload="none" src={latestAudio.audio_url} />
      ) : (
        <p className="muted small">No narration has been generated yet.</p>
      )}
    </Panel>
  );
}
