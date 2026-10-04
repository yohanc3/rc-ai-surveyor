/**
 * Compact figure tiles. A stat is a label and a value; `tone` colours the
 * value when it carries meaning (a fault, a warning), and is left off
 * otherwise so colour stays informative rather than decorative.
 */
export function StatList({ children }) {
  return <div className="stats">{children}</div>;
}

const TONE_CLASS = {
  ok: 'is-ok',
  warn: 'is-warn',
  bad: 'is-bad',
};

export function Stat({ label, value, tone = '' }) {
  const valueClass = ['stat-value', TONE_CLASS[tone] ?? '']
    .filter(Boolean)
    .join(' ');
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className={valueClass}>{value}</span>
    </div>
  );
}
