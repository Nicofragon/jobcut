import { Spinner } from "web";

// The bare loading spinner (inherits color via currentColor). Shown here at a
// few sizes in the primary green.
export function Sizes() {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 24, color: "var(--color-primary)" }}>
      <Spinner size={16} />
      <Spinner size={24} />
      <Spinner size={40} />
    </div>
  );
}
