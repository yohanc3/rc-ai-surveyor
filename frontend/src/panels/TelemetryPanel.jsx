import { Panel } from '../components/Panel';
import { Stat, StatList } from '../components/Stat';
import { formatBytes, formatDuration, formatMs, isStale } from '../lib/format';

export function TelemetryPanel({ status }) {
  const frames = status.frames ?? {};
  const relay = status.relay ?? {};
  const metrics = status.metrics ?? {};
  const stale = isStale(status);

  return (
    <Panel title="Pipeline">
      <StatList>
        <Stat label="Frames" value={(frames.captured ?? 0).toLocaleString()} />
        <Stat
          label="Sample rate"
          value={`${frames.measured_fps || '—'} / ${frames.configured_fps ?? '—'} fps`}
          kind={stale ? 'bad' : ''}
        />
        <Stat label="Frame size" value={formatBytes(frames.last_bytes)} />
        <Stat
          label="Relay"
          value={relay.up ? 'up' : 'down'}
          kind={relay.up ? 'ok' : 'bad'}
        />
        <Stat label="Restarts" value={String(relay.restarts ?? 0)} />
        <Stat label="Uptime" value={formatDuration(status.uptime_seconds)} />
        <Stat label="Providers" value={status.provider_mode ?? '—'} />
      </StatList>

      <h3 className="sub-head">Analysis</h3>
      <StatList>
        <Stat label="Batches" value={String(metrics.batches_created ?? 0)} />
        <Stat
          label="Dropped"
          value={String(metrics.batches_dropped ?? 0)}
          kind={metrics.batches_dropped ? 'warn' : ''}
        />
        <Stat label="Pending" value={String(metrics.pending_batches ?? 0)} />
        <Stat label="Analysed" value={String(metrics.analyses_succeeded ?? 0)} />
        <Stat
          label="Failed"
          value={String(metrics.analyses_failed ?? 0)}
          kind={metrics.analyses_failed ? 'bad' : ''}
        />
        <Stat label="Gemini latency" value={formatMs(metrics.gemini_last_latency_ms)} />
        <Stat label="Spoken" value={String(metrics.speech_succeeded ?? 0)} />
        <Stat label="Speech latency" value={formatMs(metrics.elevenlabs_last_latency_ms)} />
      </StatList>
    </Panel>
  );
}
