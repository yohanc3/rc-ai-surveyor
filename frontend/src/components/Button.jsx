/**
 * The one button in the app. `variant` is 'default', 'primary' or 'ghost';
 * hover, active, disabled and focus states are defined once in styles.css so
 * every control in the interface behaves identically.
 */
const VARIANT_CLASS = {
  primary: 'btn-primary',
  ghost: 'btn-ghost',
};

export function Button({
  children,
  variant = 'default',
  type = 'button',
  className = '',
  ...rest
}) {
  const classes = ['btn', VARIANT_CLASS[variant] ?? '', className]
    .filter(Boolean)
    .join(' ');
  return (
    <button type={type} className={classes} {...rest}>
      {children}
    </button>
  );
}
