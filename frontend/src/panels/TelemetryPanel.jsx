import { Panel } from '../components/Panel';
import { Stat, StatList } from '../components/Stat';
import { Icon } from '../components/Icon';
import { formatBytes, formatDuration, formatMs, isStale } from '../lib/format';

/**
 * Activity counters.
 *
 * The four figures on top are the ones anyone can read: how much the camera
 * has seen, said and spoken, and how long it has been going. Everything
 * measured in milliseconds, batches or bytes is real but specialised, so it
 * folds away behind a disclosure instead of competing for attention.
 */
export function TelemetryPanel({ status }) {
  const frames = status.frames ?? {};
  const relay = status.relay ?? {};
  const metrics = status.metrics ?? {};
  const stale = isStale(status);

  return (
    <Panel
      title={
        <>
          <Icon name="activity" size={17} />
          Activity
        </>
      }
    >
      <StatList>
        <Stat
          label="Pictures taken"
          value={(frames.captured ?? 0).toLocaleString()}
          tone={stale ? 'warn' : ''}
        />
        <Stat
          label="Descriptions"
          value={(metrics.analyses_succeeded ?? 0).toLocaleString()}
        />
        <Stat
          label="Read aloud"
          value={(metrics.speech_succeeded ?? 0).toLocaleString()}
        />
        <Stat label="Running for" value={formatDuration(status.uptime_seconds)} />
      </StatList>

      <details className="disclosure">
        <summary>Technical details</summary>
        <div className="disclosure-body">
          <StatList>
            <Stat
              label="Pictures / second"
              value={`${frames.measured_fps || '—'} of ${frames.configured_fps ?? '—'}`}
              tone={stale ? 'bad' : ''}
            />
            <Stat label="Picture size" value={formatBytes(frames.last_bytes)} />
            <Stat
              label="Video connection"
              value={relay.up ? 'Up' : 'Down'}
              tone={relay.up ? 'ok' : 'bad'}
            />
            <Stat label="Reconnections" value={String(relay.restarts ?? 0)} />
            <Stat label="Picture groups" value={String(metrics.batches_created ?? 0)} />
            <Stat
              label="Groups skipped"
              value={String(metrics.batches_dropped ?? 0)}
              tone={metrics.batches_dropped ? 'warn' : ''}
            />
            <Stat label="Waiting" value={String(metrics.pending_batches ?? 0)} />
            <Stat
              label="Failed"
              value={String(metrics.analyses_failed ?? 0)}
              tone={metrics.analyses_failed ? 'bad' : ''}
            />
            <Stat
              label="Describe time"
              value={formatMs(metrics.gemini_last_latency_ms)}
            />
            <Stat
              label="Speak time"
              value={formatMs(metrics.elevenlabs_last_latency_ms)}
            />
          </StatList>
        </div>
      </details>
    </Panel>
  );
}
