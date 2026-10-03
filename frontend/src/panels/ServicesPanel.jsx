import { Panel } from '../components/Panel';

// The four indicators required by design document section 2.
const SERVICES = [
  ['camera', 'Camera'],
  ['video', 'Video'],
  ['gemini', 'Gemini'],
  ['elevenlabs', 'ElevenLabs'],
];

const DOT = {
  ok: 'ok',
  degraded: 'warn',
  down: 'bad',
  disabled: 'muted',
  unknown: 'muted',
};

export function ServicesPanel({ status }) {
  const services = status.services ?? {};
  return (
    <Panel title="Connections">
      <ul className="services">
        {SERVICES.map(([key, label]) => {
          const service = services[key] ?? { state: 'unknown', detail: '' };
          return (
            <li key={key}>
              <span className={`dot ${DOT[service.state] ?? 'muted'}`} aria-hidden="true" />
              <span className="service-name">{label}</span>
              <span className="service-state">{service.state}</span>
              {service.detail ? (
                <span className="service-detail" title={service.detail}>
                  {service.detail}
                </span>
              ) : null}
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}
