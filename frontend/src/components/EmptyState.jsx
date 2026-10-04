import { Icon } from './Icon';

/**
 * Shown wherever there is no data yet. Always names what will appear here and,
 * where it helps, what to do about it — an empty panel should never be a dead
 * end or a bare em dash.
 */
export function EmptyState({ icon = 'sparkle', title, hint, children }) {
  return (
    <div className="empty">
      {icon ? (
        <span className="empty-icon">
          <Icon name={icon} size={18} />
        </span>
      ) : null}
      {title ? <p className="empty-title">{title}</p> : null}
      {hint ? <p>{hint}</p> : null}
      {children}
    </div>
  );
}
