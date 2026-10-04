import { useBackend } from './backend/useBackend';
import { panelsFor } from './panels/registry';
import { Badge, StatusDot } from './components/Badge';
import { Icon } from './components/Icon';
import { cameraHeadline, providerLabel, SOURCE_LABELS } from './lib/labels';
import { formatDuration } from './lib/format';

/**
 * Application shell.
 *
 * A sidebar carries identity and standing status — the things that are always
 * true. The main column carries what changes: a sticky bar answering "is this
 * working?", the live picture, then everything that streams in beneath it.
 *
 * Panels are still looked up through the registry, so the extension point is
 * unchanged: write a component, add one line to panels/registry.js. The three
 * slots now map onto the shell as stage → hero, side → sidebar, row → content.
 */
export default function App() {
  const ctx = useBackend();
  const { mode, status, skills } = ctx;

  const camera = cameraHeadline(mode, status);
  const source = SOURCE_LABELS[mode] ?? SOURCE_LABELS.connecting;
  const provider = providerLabel(status?.provider_mode);
  const activeSkill =
    skills?.skills?.find((skill) => skill.id === skills.active_id) ?? null;

  const render = (panel) => {
    const Component = panel.component;
    return <Component key={panel.id} {...ctx} />;
  };

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <Icon name="compass" size={19} />
          </span>
          <div className="brand-text">
            <h1>Surveyor</h1>
            <p>Live camera companion</p>
          </div>
        </div>

        {panelsFor('side', ctx).map(render)}

        <div className="sidebar-foot">
          <div className="sidebar-foot-row">
            <span>Running for</span>
            <strong>{formatDuration(status?.uptime_seconds)}</strong>
          </div>
          {activeSkill ? (
            <div className="sidebar-foot-row">
              <span>Skill</span>
              <strong>{activeSkill.name}</strong>
            </div>
          ) : null}
          {provider ? (
            <div className="sidebar-foot-row">
              <span>Descriptions</span>
              <strong>{provider.text}</strong>
            </div>
          ) : null}
        </div>
      </aside>

      <main className="main">
        <div className="appbar">
          <div className="appbar-title">
            <h2>Live view</h2>
            <span className="appbar-sub">
              See what your camera sees, described as you go
            </span>
          </div>
          <div className="appbar-actions">
            <Badge tone={camera.tone} dot live={camera.live}>
              {camera.text}
            </Badge>
            <Badge tone={source.tone}>{source.text}</Badge>
            {activeSkill ? (
              <Badge tone="accent">{activeSkill.name}</Badge>
            ) : null}
          </div>
        </div>

        <div className="content">
          {mode === 'demo' ? (
            <div className="notice" role="status">
              <Icon name="alert" size={18} />
              <div>
                <p className="notice-title">You are looking at demo data</p>
                <p className="notice-body">
                  No camera is connected, so the pictures and descriptions on
                  this page are made up. Start the app and reload to see the
                  real thing.
                </p>
              </div>
            </div>
          ) : null}

          {panelsFor('stage', ctx).map(render)}

          <div className="columns">{panelsFor('row', ctx).map(render)}</div>
        </div>
      </main>
    </div>
  );
}
