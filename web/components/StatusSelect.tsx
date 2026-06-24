"use client";

import { useState } from "react";
import { setStatus } from "@/lib/api";

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

  return (
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
  );
}
