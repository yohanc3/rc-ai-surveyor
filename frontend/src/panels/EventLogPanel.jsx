import { useEffect, useRef, useState } from 'react';
import { Panel } from '../components/Panel';
import { EmptyState } from '../components/EmptyState';
import { Icon } from '../components/Icon';
import { isStale } from '../lib/format';
import {
  EMPTY,
  EVENT_TEXT,
  serviceChangeEvent,
  sourceChangeEvent,
} from '../lib/labels';

const MAX_EVENTS = 60;

const TONE_CLASS = {
  ok: 'is-ok',
  warn: 'is-warn',
  bad: 'is-bad',
};

/**
 * Watches the status stream for changes and writes them down in plain words.
 * Purely client side — it is how you notice a connection that keeps dropping
 * without having to read the server log.
 */
export function EventLogPanel({ status, mode }) {
  const [events, setEvents] = useState([]);
  const prev = useRef({
    relayUp: null,
    restarts: null,
    stale: null,
    mode: null,
    services: {},
  });
  const nextId = useRef(0);

  useEffect(() => {
    const relay = status.relay ?? {};
    const services = status.services ?? {};
    const stale = isStale(status);
    const next = [];
    const p = prev.current;

    if (p.mode !== null && p.mode !== mode) {
      const event = sourceChangeEvent(mode);
      if (event) next.push(event);
    }
    if (p.relayUp !== null && p.relayUp !== relay.up) {
      next.push(
        relay.up
          ? { tone: 'ok', text: EVENT_TEXT.videoUp }
          : { tone: 'bad', text: EVENT_TEXT.videoDown },
      );
    }
    if (p.restarts !== null && (relay.restarts ?? 0) > p.restarts) {
      next.push({ tone: 'warn', text: EVENT_TEXT.videoRestarted });
    }
    if (p.stale !== null && p.stale !== stale) {
      next.push(
        stale
          ? { tone: 'bad', text: EVENT_TEXT.framesStalled }
          : { tone: 'ok', text: EVENT_TEXT.framesResumed },
      );
    }
    for (const [name, service] of Object.entries(services)) {
      const before = p.services[name];
      if (before && before !== service.state) {
        next.push(serviceChangeEvent(name, service.state));
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
    <Panel
      title={
        <>
          <Icon name="list" size={17} />
          Recent activity
        </>
      }
    >
      {events.length === 0 ? (
        <EmptyState icon="list" title={EMPTY.events.title} hint={EMPTY.events.hint} />
      ) : (
        <ul className="events">
          {events.map((event) => (
            <li key={event.id}>
              <time>{event.at.toLocaleTimeString()}</time>
              <span className={`event-text ${TONE_CLASS[event.tone] ?? ''}`.trim()}>
                {event.text}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
