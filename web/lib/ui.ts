// Shared visual helpers. Colors come from the D1 theme tokens (Stitch),
// tuned for legibility on the light (#f8f9ff / white) surfaces.

export const CATEGORY_COLOR: Record<string, string> = {
  Interview: "#16a34a",
  Screen: "#0891b2",
  Active: "#2563eb",
  Reviewing: "#7c3aed",
  Applied: "#64748b",
  Offer: "#9333ea",
  "No response": "#94a3b8",
  Closed: "#64748b",
  Withdrawn: "#d97706",
  Rejected: "#dc2626",
  Saved: "#6366f1",
  Other: "#64748b",
};

// Match-score scale: high green / mid amber / low gray (--color-score-*).
export function scoreColor(score: number | null): string {
  if (score == null) return "#6e7b6c";
  if (score >= 75) return "#16a34a";   // high
  if (score >= 50) return "#d97706";   // mid
  return "#6e7b6c";                    // low
}

// Friendly label for the scoring backend that produced a score (db `scores.backend`).
// Returns null when unknown/empty so the UI can skip the badge.
const SCORER_LABELS: Record<string, string> = {
  rule_based: "Rule-based",
  local: "Local AI",
  llm_api: "API",
  claude_skills: "Claude",
};
export function scorerLabel(backend: string | null | undefined): string | null {
  if (!backend) return null;
  return SCORER_LABELS[backend] ?? backend;
}

export function offerLink(item: {
  linkedin_url: string | null;
  apply_url: string | null;
  easy_apply_url: string | null;
}): string | null {
  return item.linkedin_url || item.apply_url || item.easy_apply_url || null;
}
