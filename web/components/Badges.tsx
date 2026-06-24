import { CATEGORY_COLOR, scoreColor } from "@/lib/ui";

export function ScoreBadge({ score }: { score: number | null }) {
  const c = scoreColor(score);
  return (
    <span
      className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-semibold tabular-nums"
      style={{ color: c, background: `${c}1a`, border: `1.5px solid ${c}40` }}
      title={score != null ? `match score ${score}` : "not scored"}
    >
      {score ?? "–"}
    </span>
  );
}

export function CategoryBadge({ category }: { category: string }) {
  const c = CATEGORY_COLOR[category] ?? "#8b949e";
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium"
      style={{ color: c, background: `${c}1f`, border: `1px solid ${c}40` }}
    >
      {category}
    </span>
  );
}
