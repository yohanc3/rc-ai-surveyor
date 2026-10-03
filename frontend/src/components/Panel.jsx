export function Panel({ title, actions, children, className = '' }) {
  return (
    <section className={`panel ${className}`.trim()}>
      <div className="panel-head">
        <h2>{title}</h2>
        {actions ? <div className="panel-actions">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}
