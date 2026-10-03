import { Panel } from '../components/Panel';
import { formatClock } from '../lib/format';

/**
 * Rolling history of model output. The hook only admits an analysis whose id is
 * newer than the one already shown, so entries here are always in order.
 */
export function AnalysisStreamPanel({ analyses, status }) {
  const mode = status?.provider_mode ?? '';

  return (
    <Panel title="Analysis stream" className="span-2">
      {analyses.length === 0 ? (
        <p className="muted">
          {mode.startsWith('mock')
            ? 'Waiting for the first mock analysis…'
            : 'Waiting for the first analysis. Each one appears here as a timestamped entry.'}
        </p>
      ) : (
        <ul className="thoughts">
          {analyses.map((item) => (
            <li key={item.analysis_id}>
              <div className="thought-meta">
                <span className="tag">frames {item.frame_sequences?.join('–')}</span>
                <time>{formatClock(item.received_at ?? item.captured_at)}</time>
                {item.audio_url ? <span className="chip">audio</span> : null}
                <code className="id" title={item.analysis_id}>
                  {item.analysis_id.slice(-6)}
                </code>
              </div>
              <div className="thought-body">
                <p className="technical">{item.technical_description}</p>
                <p className="narration">{item.narration_text}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
