import { Panel } from '../components/Panel';
import { StatusDot } from '../components/Badge';
import { Icon } from '../components/Icon';
import { SERVICE_LABELS, serviceState } from '../lib/labels';

// The four indicators required by design document section 2, named for what
// they do rather than which vendor provides them.
const ROWS = [
  ['camera', 'camera'],
  ['video', 'video'],
  ['gemini', 'sparkle'],
  ['elevenlabs', 'speaker'],
];

const TONE_CLASS = { ok: 'is-ok', warn: 'is-warn', bad: 'is-bad' };

export function ServicesPanel({ status }) {
  const services = status.services ?? {};

  return (
    <Panel title="Status">
      <ul className="status-list">
        {ROWS.map(([key, icon]) => {
          const service = services[key] ?? { state: 'unknown' };
          const info = serviceState(service.state);
          return (
            <li key={key}>
              <span className="status-icon">
                <Icon name={icon} size={15} />
              </span>
              <span className="status-name">{SERVICE_LABELS[key] ?? key}</span>
              <span className={`status-value ${TONE_CLASS[info.tone] ?? ''}`.trim()}>
                <StatusDot tone={info.tone} live={info.tone === 'ok'} />
                {info.text}
              </span>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}
