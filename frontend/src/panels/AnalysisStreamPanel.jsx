import { Panel } from '../components/Panel';
import { EmptyState } from '../components/EmptyState';
import { Icon, SoundBars } from '../components/Icon';
import { EMPTY } from '../lib/labels';
import { formatClock } from '../lib/format';

/**
 * The transcript — what the camera has described, newest first.
 *
 * This is the product, so it gets the most room and the clearest type. Each
 * entry leads with the spoken sentence; the shorter factual line sits beneath
 * as supporting detail. The internal identifier is deliberately absent from
 * the interface — it stays in the logs, where it is actually useful.
 */
export function AnalysisStreamPanel({ analyses, status, latestAudio }) {
  const isPractice = (status?.provider_mode ?? '').startsWith('mock');
  const empty = isPractice ? EMPTY.observationsPractice : EMPTY.observations;
  const speakingId = latestAudio?.analysis_id;

  return (
    <Panel
      title={
        <>
          <Icon name="sparkle" size={17} />
          What the camera sees
        </>
      }
      subtitle={analyses.length ? `${analyses.length} most recent` : undefined}
      className="span-2"
    >
      {analyses.length === 0 ? (
        <EmptyState icon="sparkle" title={empty.title} hint={empty.hint} />
      ) : (
        <ul className="feed">
          {analyses.map((item, index) => {
            const spoken = Boolean(item.audio_url);
            const isSpeaking = spoken && item.analysis_id === speakingId;
            return (
              <li
                key={item.analysis_id}
                className={index === 0 ? 'is-latest' : undefined}
              >
                <p className="feed-said">{item.narration_text}</p>
                {item.technical_description ? (
                  <p className="feed-detail">{item.technical_description}</p>
                ) : null}
                <div className="feed-meta">
                  <time>{formatClock(item.received_at ?? item.captured_at)}</time>
                  {isSpeaking ? (
                    <span className="tag">
                      <SoundBars />
                      Reading aloud
                    </span>
                  ) : spoken ? (
                    <span className="tag">
                      <Icon name="speaker" size={12} />
                      Spoken
                    </span>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
