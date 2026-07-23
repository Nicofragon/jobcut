import { ScoreBadge } from "web";

// The compact match-score pill: color encodes the band (high green ≥75,
// mid amber ≥50, low gray), "–" when a job hasn't been scored yet.
export function Scale() {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
      <ScoreBadge score={92} />
      <ScoreBadge score={78} />
      <ScoreBadge score={63} />
      <ScoreBadge score={41} />
      <ScoreBadge score={null} />
    </div>
  );
}
