import { useEffect, useRef, useState } from 'react';
import { Panel } from '../components/Panel';
import { isStale } from '../lib/format';

const MAX_EVENTS = 60;

/**
 * Watches the status stream for transitions and logs them. Purely client side —
 * useful for spotting a relay that keeps dropping or a sampler that stalls.
 */
export function EventLogPanel({ status, mode }) {
  const [events, setEvents] = useState([]);
  const prev = useRef({ relayUp: null, restarts: null, stale: null, mode: null, services: {} });
  const nextId = useRef(0);

  useEffect(() => {
    const relay = status.relay ?? {};
    const services = status.services ?? {};
    const stale = isStale(status);
    const next = [];
    const p = prev.current;

    if (p.mode !== null && p.mode !== mode) {
      next.push({ kind: 'info', text: `source changed to ${mode}` });
    }
    if (p.relayUp !== null && p.relayUp !== relay.up) {
      next.push(
        relay.up
          ? { kind: 'ok', text: 'relay came up' }
          : { kind: 'bad', text: 'relay went down' },
      );
    }
    if (p.restarts !== null && (relay.restarts ?? 0) > p.restarts) {
      next.push({ kind: 'warn', text: `relay restarted (${relay.restarts} total)` });
    }
    if (p.stale !== null && p.stale !== stale) {
      next.push(
        stale
          ? { kind: 'bad', text: 'frame sampling stalled' }
          : { kind: 'ok', text: 'frame sampling resumed' },
      );
    }
    for (const [name, service] of Object.entries(services)) {
      const before = p.services[name];
      if (before && before !== service.state) {
        next.push({
          kind: service.state === 'ok' ? 'ok' : service.state === 'degraded' ? 'warn' : 'bad',
          text: `${name} ${service.state}${service.detail ? `: ${service.detail}` : ''}`,
        });
      }
    }

    prev.current = {
      relayUp: relay.up ?? false,
      restarts: relay.restarts ?? 0,
      stale,
      mode,
      services: Object.fromEntries(
        Object.entries(services).map(([name, service]) => [name, service.state]),
      ),
    };

    if (next.length) {
      const stamped = next.map((event) => ({
        ...event,
        id: (nextId.current += 1),
        at: new Date(),
      }));
      setEvents((old) => [...stamped, ...old].slice(0, MAX_EVENTS));
    }
  }, [status, mode]);

  return (
    <Panel title="Event log">
      {events.length === 0 ? (
        <p className="muted small">No events yet. Relay drops and provider faults show up here.</p>
      ) : (
        <ul className="events">
          {events.map((event) => (
            <li key={event.id}>
              <time>{event.at.toLocaleTimeString()}</time>
              <span className={event.kind}>{event.text}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
