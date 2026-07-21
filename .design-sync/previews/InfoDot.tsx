import { InfoDot } from "web";

// A small "?" affordance that reveals a plain-language definition on hover/focus.
// Sits inline next to field labels and metric captions. (The tooltip bubble
// shows on hover; here the dots appear beside their labels as in the settings UI.)
export function InlineWithLabels() {
  const row = { display: "flex", alignItems: "center", gap: 6, color: "var(--color-on-surface)", fontSize: 14, fontWeight: 500 };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <span style={row}>Match score <InfoDot text="How well a job fits your profile (0–100), from the scorer." /></span>
      <span style={row}>Must-haves <InfoDot text="Requirements a job must meet to be shown, e.g. remote or a salary floor." align="left" /></span>
      <span style={row}>Dealbreakers <InfoDot text="Signals that push a job down or hide it, e.g. on-site only." align="left" /></span>
    </div>
  );
}
