import { Panel } from '../components/Panel';
import { EmptyState } from '../components/EmptyState';
import { EMPTY } from '../lib/labels';
import { formatAge } from '../lib/format';

/**
 * The exact picture the descriptions are written from. Worth showing because
 * the live view and the analysed moment are not always the same instant.
 */
export function SampledFramePanel({ status, frameUrl }) {
  const frames = status.frames ?? {};
  const age = frames.captured ? formatAge(frames.last_age_seconds) : null;

  return (
    <Panel title="Last picture" subtitle={age ? `Taken ${age}` : undefined}>
      {frameUrl ? (
        <div className="snapshot">
          <img src={frameUrl} alt="Most recent picture taken from the camera" />
        </div>
      ) : (
        <EmptyState
          icon="image"
          title={EMPTY.snapshot.title}
          hint={EMPTY.snapshot.hint}
        />
      )}
    </Panel>
  );
}
