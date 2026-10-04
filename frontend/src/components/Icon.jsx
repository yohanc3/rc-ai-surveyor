/**
 * Inline icon set.
 *
 * Drawn on a 24px grid and rendered at any size via the `size` prop; stroke
 * uses `currentColor` so an icon always matches the text beside it. Kept
 * inline rather than pulled from a package so the interface has no runtime
 * dependency and still renders with no network.
 */
const PATHS = {
  camera: (
    <>
      <path d="M3 8.5A2.5 2.5 0 0 1 5.5 6h1.2a1.5 1.5 0 0 0 1.25-.67l.6-.9A1.5 1.5 0 0 1 9.8 3.75h4.4a1.5 1.5 0 0 1 1.25.68l.6.9A1.5 1.5 0 0 0 17.3 6h1.2A2.5 2.5 0 0 1 21 8.5v8A2.5 2.5 0 0 1 18.5 19h-13A2.5 2.5 0 0 1 3 16.5Z" />
      <circle cx="12" cy="12" r="3.25" />
    </>
  ),
  video: (
    <>
      <rect x="2.75" y="6.75" width="12.5" height="10.5" rx="2.5" />
      <path d="m15.25 10.5 4.3-2.6a.75.75 0 0 1 1.2.64v6.92a.75.75 0 0 1-1.2.64l-4.3-2.6Z" />
    </>
  ),
  sparkle: (
    <>
      <path d="M12 3.5l1.6 4.3a3 3 0 0 0 1.8 1.8l4.3 1.6-4.3 1.6a3 3 0 0 0-1.8 1.8L12 18.9l-1.6-4.3a3 3 0 0 0-1.8-1.8L4.3 11.2l4.3-1.6a3 3 0 0 0 1.8-1.8Z" />
      <path d="M18.5 16.5l.6 1.6 1.6.6-1.6.6-.6 1.6-.6-1.6-1.6-.6 1.6-.6Z" />
    </>
  ),
  speaker: (
    <>
      <path d="M11 5.5 6.75 9H4.5A1.5 1.5 0 0 0 3 10.5v3A1.5 1.5 0 0 0 4.5 15h2.25L11 18.5Z" />
      <path d="M15.2 9.3a3.8 3.8 0 0 1 0 5.4" />
      <path d="M17.9 6.6a7.6 7.6 0 0 1 0 10.8" />
    </>
  ),
  speakerOff: (
    <>
      <path d="M11 5.5 6.75 9H4.5A1.5 1.5 0 0 0 3 10.5v3A1.5 1.5 0 0 0 4.5 15h2.25L11 18.5Z" />
      <path d="m16 10 4 4" />
      <path d="m20 10-4 4" />
    </>
  ),
  activity: <path d="M3 12h3.5l2.5-7 4 14 2.5-7H21" />,
  clock: (
    <>
      <circle cx="12" cy="12" r="8.75" />
      <path d="M12 7.25V12l3 1.75" />
    </>
  ),
  image: (
    <>
      <rect x="3.25" y="4.75" width="17.5" height="14.5" rx="2.5" />
      <circle cx="8.5" cy="10" r="1.5" />
      <path d="m4 17 4.8-4.3a2 2 0 0 1 2.7 0L16 17" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 11.5a8 8 0 1 0-.8 4.5" />
      <path d="M20 5.5v6h-6" />
    </>
  ),
  alert: (
    <>
      <path d="M12 4.75 2.9 19.25h18.2Z" />
      <path d="M12 10v4" />
      <path d="M12 16.75h.01" />
    </>
  ),
  radio: (
    <>
      <circle cx="12" cy="12" r="2.75" />
      <path d="M7.4 7.4a6.5 6.5 0 0 0 0 9.2" />
      <path d="M16.6 16.6a6.5 6.5 0 0 0 0-9.2" />
    </>
  ),
  list: (
    <>
      <path d="M8.5 6.75h12" />
      <path d="M8.5 12h12" />
      <path d="M8.5 17.25h12" />
      <path d="M4 6.75h.01M4 12h.01M4 17.25h.01" />
    </>
  ),
  check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  compass: (
    <>
      <circle cx="12" cy="12" r="8.75" />
      <path d="m14.8 9.2-1.6 4.1-4.1 1.6 1.6-4.1Z" />
    </>
  ),
};

export function Icon({ name, size = 16, className = '', ...rest }) {
  const path = PATHS[name];
  if (!path) return null;
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {path}
    </svg>
  );
}

/** Three bars that animate only while narration is playing. */
export function SoundBars() {
  return (
    <span className="bars" aria-hidden="true">
      <span />
      <span />
      <span />
    </span>
  );
}
