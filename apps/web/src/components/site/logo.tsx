/** A soft lens mark. Deliberately abstract: no face outlines or scanning motifs. */
export function Logo({ className = "size-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true" focusable="false">
      <circle cx="16" cy="16" r="14" fill="var(--primary)" opacity="0.14" />
      <circle cx="16" cy="16" r="9" fill="none" stroke="var(--primary)" strokeWidth="2.5" />
      <circle cx="19.5" cy="12.5" r="2.2" fill="var(--primary)" />
    </svg>
  );
}
