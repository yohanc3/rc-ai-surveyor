import { Panel } from '../components/Panel';
import { formatAge, formatBytes } from '../lib/format';

export function SampledFramePanel({ status, frameUrl }) {
  const frames = status.frames ?? {};
  return (
    <Panel title="Latest sampled frame">
      <div className="frame-shell">
        {frameUrl ? (
          <img src={frameUrl} alt="Most recent frame sent to the analysis pipeline" />
        ) : (
          <p className="muted small">No frames sampled yet.</p>
        )}
      </div>
      <p className="muted small">
        {frames.captured
          ? `#${frames.captured} · ${formatBytes(frames.last_bytes)} · ${formatAge(frames.last_age_seconds)}`
          : '—'}
      </p>
    </Panel>
  );
}
