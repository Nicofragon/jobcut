"use client";

import { useState } from "react";
import { setStatus } from "@/lib/api";
import { Icon } from "@/components/icons";

// Canonical statuses the dashboard writes (mirror status.STATUSES) + human labels.
const STATUSES = ["saved", "applied", "screen", "interview", "offer", "rejected", "withdrawn", "no_response"];
const LABELS: Record<string, string> = {
  saved: "Saved",
  applied: "Applied",
  screen: "Screening",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
  no_response: "No response",
};

// B-10: an at-a-glance icon for the current status, beside the selector.
const STATUS_ICON: Record<string, { icon: "users" | "send" | "sparkles" | "clock" | "x" | "arrow-left" | "briefcase"; color: string }> = {
  saved: { icon: "briefcase", color: "#a371f7" },
  applied: { icon: "send", color: "#8b949e" },
  screen: { icon: "users", color: "#39c5cf" },
  interview: { icon: "users", color: "#3fb950" },
  offer: { icon: "sparkles", color: "#d2a8ff" },
  no_response: { icon: "clock", color: "#6e7681" },
  rejected: { icon: "x", color: "#f85149" },
  withdrawn: { icon: "arrow-left", color: "#d29922" },
};

export default function StatusSelect({
  jobId,
  value,
  onChanged,
}: {
  jobId: string;
  value?: string | null;
  onChanged?: (status: string) => void;
}) {
  const [current, setCurrent] = useState(value ?? "");
  const [busy, setBusy] = useState(false);
  // External reloads are reflected by remounting via key={row.status} at the call site.

  async function change(next: string) {
    if (!next || next === current) return;
    const prev = current;
    setCurrent(next); // optimistic
    setBusy(true);
    try {
      await setStatus(jobId, next);
      onChanged?.(next);
    } catch {
      setCurrent(prev); // revert on failure
    } finally {
      setBusy(false);
    }
  }

  const meta = STATUS_ICON[current];

  return (
    <span className="inline-flex items-center gap-1.5">
      {meta && (
        <span
          className="inline-flex shrink-0"
          style={{ color: meta.color }}
          role="img"
          aria-label={`Status: ${LABELS[current] ?? current}`}
        >
          <Icon name={meta.icon} size={15} />
        </span>
      )}
      <select
        value={current}
        disabled={busy}
        onChange={(e) => change(e.target.value)}
        onClick={(e) => e.stopPropagation()}
        aria-label="Application status"
        className="rounded-full border border-border bg-surface-sunken px-3 py-1.5 text-xs font-semibold text-on-surface outline-none transition-colors hover:border-primary/50 focus:border-primary disabled:opacity-50"
      >
        <option value="" disabled>
          {busy ? "saving…" : "set status…"}
        </option>
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {LABELS[s] ?? s}
          </option>
        ))}
      </select>
    </span>
  );
}
