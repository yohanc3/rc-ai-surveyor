export function Badge({ children, kind = '' }) {
  return <span className={`badge ${kind}`.trim()}>{children}</span>;
}
