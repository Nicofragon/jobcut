import { ScoreRing } from "web";

// The circular match-score indicator used on job cards. Arc length + color
// encode the score; sizes scale from the inline 48px card ring to the hero.
export function Sizes() {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
      <ScoreRing score={91} />
      <ScoreRing score={67} />
      <ScoreRing score={38} />
      <ScoreRing score={null} />
    </div>
  );
}

// The large labelled "Match" variant for a job-detail hero.
export function Hero() {
  return <ScoreRing score={88} size={96} label />;
}
