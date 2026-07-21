import { Icon } from "web";

const NAMES = [
  "search", "refresh", "building", "map-pin", "banknote", "briefcase",
  "calendar", "clock", "send", "sparkles", "users", "user",
  "check", "check-circle", "x", "external", "file-text", "sun", "moon",
] as const;

// The local inline-SVG icon set (Lucide-style paths). Sized via `size`, tinted
// via `currentColor`, no icon-font dependency.
export function Gallery() {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(64px, 1fr))",
        gap: 12,
        color: "var(--color-on-surface)",
      }}
    >
      {NAMES.map((n) => (
        <div key={n} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
          <Icon name={n} size={22} />
          <span style={{ fontSize: 10, color: "var(--color-on-surface-faint)" }}>{n}</span>
        </div>
      ))}
    </div>
  );
}

// Icons inherit text color — here the primary green and a muted metadata tone.
export function Tinted() {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
      <span style={{ color: "var(--color-primary)" }}><Icon name="sparkles" size={28} /></span>
      <span style={{ color: "var(--color-on-surface-variant)" }}><Icon name="briefcase" size={28} /></span>
      <span style={{ color: "var(--color-accent-red)" }}><Icon name="x" size={28} /></span>
    </div>
  );
}
