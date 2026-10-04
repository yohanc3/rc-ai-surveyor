/**
 * Small status pill. `tone` picks the semantic colour; `dot` adds a leading
 * indicator, and `live` makes that indicator pulse — reserved for states that
 * are genuinely updating, so motion always means something.
 */
const TONE_CLASS = {
  ok: 'badge-ok',
  warn: 'badge-warn',
  bad: 'badge-bad',
  quiet: 'badge-quiet',
};

export function Badge({ children, tone = '', dot = false, live = false }) {
  const className = ['badge', TONE_CLASS[tone] ?? ''].filter(Boolean).join(' ');
  return (
    <span className={className}>
      {dot ? <StatusDot tone={tone} live={live} /> : null}
      {children}
    </span>
  );
}

const DOT_CLASS = {
  ok: 'dot-ok',
  warn: 'dot-warn',
  bad: 'dot-bad',
  idle: 'dot-idle',
  quiet: 'dot-idle',
};

export function StatusDot({ tone = '', live = false }) {
  const className = ['dot', DOT_CLASS[tone] ?? 'dot-idle', live ? 'dot-live' : '']
    .filter(Boolean)
    .join(' ');
  return <span className={className} aria-hidden="true" />;
}
