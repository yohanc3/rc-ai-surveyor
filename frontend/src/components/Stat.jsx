export function StatList({ children }) {
  return <dl className="stats">{children}</dl>;
}

export function Stat({ label, value, kind = '' }) {
  return (
    <>
      <dt>{label}</dt>
      <dd className={kind}>{value}</dd>
    </>
  );
}
