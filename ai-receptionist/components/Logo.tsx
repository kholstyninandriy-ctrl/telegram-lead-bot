/**
 * The agency mark: a roofline over a horizon.
 *
 * Drawn in `currentColor` so it always matches the brand colour, and kept to
 * two strokes so it stays readable at favicon size.
 */
export default function Logo({ size = 32 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      role="img"
      aria-label="Harborview Realty"
    >
      <rect width="32" height="32" rx="8" fill="currentColor" />
      <path
        d="M7.5 15.8 16 8.4l8.5 7.4"
        stroke="white"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M10.6 20.6h10.8" stroke="white" strokeWidth="2.2" strokeLinecap="round" />
    </svg>
  );
}
