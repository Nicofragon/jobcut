import { scoreColor } from "@/lib/ui";

// Circular match-score ring (the Stitch "Circular Score Badge"). The track is a
// soft gray; the arc length + color encode the score (high green / mid amber /
// low gray, via scoreColor). `label` adds the "Match" caption for the hero.
export default function ScoreRing({
  score,
  size = 48,
  label = false,
}: {
  score: number | null;
  size?: number;
  label?: boolean;
}) {
  const c = scoreColor(score);
  const pct = score ?? 0;
  const big = size >= 80;
  return (
    <div
      className="relative shrink-0"
      style={{ width: size, height: size }}
      title={score != null ? `match score ${score}` : "not scored"}
    >
      <svg className="-rotate-90" viewBox="0 0 36 36" width={size} height={size}>
        <path
          d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
          fill="none"
          stroke="var(--color-border)"
          strokeWidth={big ? 2.5 : 3}
        />
        {score != null && (
          <path
            d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
            fill="none"
            stroke={c}
            strokeWidth={big ? 2.5 : 3}
            strokeDasharray={`${Math.max(0, Math.min(100, pct))}, 100`}
            strokeLinecap="round"
          />
        )}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center leading-none">
        <span
          className={`font-bold tabular-nums ${big ? "text-2xl" : "text-xs"}`}
          style={{ color: c }}
        >
          {score != null ? `${score}` : "–"}
          {!big && score != null ? "" : ""}
        </span>
        {label && <span className="mt-0.5 text-[11px] font-semibold text-on-surface-variant">Match</span>}
      </div>
    </div>
  );
}
