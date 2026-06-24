// jobcut diamond mark — from the Stitch design system (jobcut_diamond_logo).
// fill is currentColor so callers tint it via text-* (e.g. text-primary).
export default function Logo({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden className={className}>
      <path d="M12 2L4 12L12 22L20 12L12 2Z" fill="currentColor" />
    </svg>
  );
}
