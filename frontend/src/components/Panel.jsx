/**
 * Card wrapper used by every panel.
 *
 * `title` is required; `subtitle` carries a short line of context, `actions`
 * holds controls aligned to the right of the heading, and `className` lets a
 * panel widen itself in the grid with `span-2`.
 */
export function Panel({ title, subtitle, actions, children, className = '' }) {
  return (
    <section className={`panel ${className}`.trim()}>
      <div className="panel-head">
        <div>
          <h2>{title}</h2>
          {subtitle ? <p className="panel-sub">{subtitle}</p> : null}
        </div>
        {actions ? <div className="panel-actions">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}
