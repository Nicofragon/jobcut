import { Logo } from "web";

// The jobcut diamond mark. `fill` is currentColor, so it tints via text color
// and scales via Tailwind sizing classes on `className`.
export function Marks() {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
      <span style={{ color: "var(--color-primary)" }}><Logo className="h-10 w-10" /></span>
      <span style={{ color: "var(--color-primary-strong)" }}><Logo className="h-7 w-7" /></span>
      <span style={{ color: "var(--color-on-surface)" }}><Logo className="h-5 w-5" /></span>
    </div>
  );
}

// The lockup as it appears in the nav: mark + wordmark.
export function Lockup() {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8, fontWeight: 600, color: "var(--color-primary-strong)" }}>
      <span style={{ color: "var(--color-primary)" }}><Logo className="h-6 w-6" /></span>
      jobcut
    </span>
  );
}
