import { Panel } from '../components/Panel';
import { Button } from '../components/Button';
import { EmptyState } from '../components/EmptyState';
import { Icon, SoundBars } from '../components/Icon';
import { useNarrationAudio } from '../audio/useNarrationAudio';
import { EMPTY } from '../lib/labels';

/**
 * Spoken narration. Browsers refuse to play audio until the page has been
 * interacted with once, so the first state here is a single clear action
 * rather than an explanation of the browser's rules.
 */
export function NarrationAudioPanel({ latestAudio }) {
  const { enabled, enable, disable, playing, error } =
    useNarrationAudio(latestAudio);

  return (
    <Panel
      title={
        <>
          <Icon name="speaker" size={17} />
          Narration
        </>
      }
      actions={
        enabled ? (
          <Button onClick={disable}>
            <Icon name="speakerOff" size={14} />
            <span>Turn off sound</span>
          </Button>
        ) : (
          <Button variant="primary" onClick={enable}>
            <Icon name="speaker" size={14} />
            <span>Turn on sound</span>
          </Button>
        )
      }
    >
      {enabled ? (
        <p className={`audio-state ${playing ? 'is-playing' : ''}`.trim()}>
          {playing ? <SoundBars /> : <Icon name="clock" size={15} />}
          {playing ? 'Reading a description aloud' : 'Ready — will speak as descriptions arrive'}
        </p>
      ) : (
        <p className="small muted">
          Turn on sound to hear each description read aloud as it arrives.
        </p>
      )}

      {error ? (
        <p className="small is-bad">Could not play the audio: {error}</p>
      ) : null}

      {latestAudio ? (
        <audio
          className="player"
          controls
          preload="none"
          src={latestAudio.audio_url}
        />
      ) : (
        <EmptyState
          icon="speaker"
          title={EMPTY.audio.title}
          hint={EMPTY.audio.hint}
        />
      )}
    </Panel>
  );
}
