import { useBackend } from './backend/useBackend';
import { panelsFor } from './panels/registry';
import { Badge } from './components/Badge';
import { formatDuration, isStale } from './lib/format';

const MODE_BADGE = {
  connecting: { text: 'connecting', kind: '' },
  live: { text: 'live backend', kind: 'ready' },
  demo: { text: 'demo data', kind: 'warn' },
  offline: { text: 'backend unavailable', kind: 'error' },
};

function liveBadge(mode, status) {
  if (mode === 'offline') return { text: 'backend unavailable', kind: 'error' };
  const captured = status.frames?.captured ?? 0;
  if (captured === 0) return { text: 'waiting for frames', kind: '' };
  if (isStale(status)) return { text: 'frames stalled', kind: 'error' };
  return { text: `frame ${captured.toLocaleString()}`, kind: 'ready' };
}

export default function App() {
  const ctx = useBackend();
  const { mode, status } = ctx;

  const source = MODE_BADGE[mode] ?? MODE_BADGE.connecting;
  const live = liveBadge(mode, status);

  const render = (panel) => {
    const Component = panel.component;
    return <Component key={panel.id} {...ctx} />;
  };

  return (
    <main>
      <header>
        <div>
          <h1>RC AI Surveyor</h1>
          <p className="sub">HERO7 Silver · low-latency relay</p>
        </div>
        <div className="badges">
          <Badge kind={live.kind}>{live.text}</Badge>
          <Badge kind={source.kind}>{source.text}</Badge>
          <Badge kind="quiet">up {formatDuration(status.uptime_seconds)}</Badge>
        </div>
      </header>

      {mode === 'demo' ? (
        <p className="notice">
          Showing simulated data — no GoPro or Python backend reachable. Start{' '}
          <code>python3 run.py</code> and reload, or drop the{' '}
          <code>?demo=1</code> query parameter.
        </p>
      ) : null}

      <div className="stage">
        <div className="stage-main">{panelsFor('stage', ctx).map(render)}</div>
        <aside>{panelsFor('side', ctx).map(render)}</aside>
      </div>

      <div className="grid">{panelsFor('row', ctx).map(render)}</div>
    </main>
  );
}
