"use client";

import { useEffect, useState } from "react";
import { getMarket, regenerateMarket, type Market } from "@/lib/api";
import { Icon } from "@/components/icons";
import { ErrorNote, Loading } from "@/components/States";

// Skill status → theme colors (have green / partial amber / gap red).
const STATUS_COLOR: Record<string, string> = {
  have: "var(--color-score-high)",
  partial: "var(--color-accent-amber)",
  gap: "var(--color-accent-red)",
};
const STATUS_LABEL: Record<string, string> = { have: "Have", partial: "Partial", gap: "Gap" };

// Human labels for raw segment keys; unknown keys are prettified (snake/kebab → Title).
const SEGMENT_LABEL: Record<string, string> = {
  "data-analyst": "Data Analyst",
  "product-analyst": "Product Analyst",
  "ds-ai": "Data Science / AI",
  "analytics-eng": "Analytics Engineering",
  data_analytics: "Data & Analytics",
  ai_ml: "AI / ML",
  other: "Other",
};
function humanizeSeg(key: string): string {
  return SEGMENT_LABEL[key] ?? key.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function DiscoveryPage() {
  const [data, setData] = useState<Market | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    getMarket().then(setData).catch((e) => setError(e instanceof Error ? e.message : "failed to load"));
  }, []);

  async function refresh() {
    setRefreshing(true);
    try {
      setData(await regenerateMarket());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to refresh");
    } finally {
      setRefreshing(false);
    }
  }

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!data) return <Loading label="Reading the market…" />;

  if (data.empty || data.total === 0)
    return (
      <div className="space-y-3">
        <Header onRefresh={refresh} refreshing={refreshing} />
        <div className="rounded-card border border-dashed border-border bg-surface p-8 text-center">
          <p className="text-on-surface">No market data yet.</p>
          <p className="mt-1 text-sm text-on-surface-variant">
            Run a search to build up a dataset — then we&apos;ll show what skills the market is asking for.
          </p>
        </div>
      </div>
    );

  const smallSample = data.relevant < 100;

  return (
    <div className="space-y-6">
      <Header smallSample={smallSample} onRefresh={refresh} refreshing={refreshing} />

      <section className="grid grid-cols-2 gap-3 md:grid-cols-3 md:gap-4">
        <Stat icon="building" label="Offers analyzed" value={String(data.total)} />
        <Stat icon="search" label="In your market" value={String(data.relevant)} />
        <Stat icon="banknote" label="Disclose salary" value={`${data.salary_pct}%`} />
      </section>

      <section className="rounded-card border border-border bg-surface p-5 shadow-card">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold text-on-surface">Skill demand vs your profile</h2>
          <div className="flex gap-3 text-xs text-on-surface-variant">
            <Legend color={STATUS_COLOR.have} label="have" />
            <Legend color={STATUS_COLOR.partial} label="partial" />
            <Legend color={STATUS_COLOR.gap} label="gap" />
          </div>
        </div>
        <div className="space-y-2.5">
          {data.top_demand.map((d) => {
            const color = STATUS_COLOR[d.status] ?? "var(--color-on-surface-faint)";
            const statusLabel = STATUS_LABEL[d.status] ?? d.status;
            return (
              <div
                key={d.skill}
                className="flex items-center gap-3"
                role="img"
                aria-label={`${d.skill}: ${d.pct}% of offers, ${statusLabel}`}
              >
                <span className="w-36 shrink-0 truncate text-sm text-on-surface">{d.skill}</span>
                <div className="h-5 flex-1 overflow-hidden rounded-full bg-surface-sunken">
                  <div className="h-full rounded-full" style={{ width: `${Math.min(d.pct, 100)}%`, background: color }} />
                </div>
                <span className="w-10 shrink-0 text-right text-sm font-medium tabular-nums text-on-surface">{d.pct}%</span>
                <span className="w-14 shrink-0 text-right text-xs font-medium" style={{ color }}>
                  {statusLabel}
                </span>
              </div>
            );
          })}
        </div>
      </section>

      <div className="grid gap-4 md:grid-cols-2">
        <section className="rounded-card border border-border bg-surface p-5 shadow-card">
          <h2 className="mb-3 text-lg font-semibold text-on-surface">Skills to close</h2>
          {data.gaps.length ? (
            <div className="flex flex-wrap gap-2">
              {data.gaps.map((g) => (
                <span
                  key={g}
                  className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-medium"
                  style={{
                    color: "var(--color-accent-red)",
                    background: "color-mix(in srgb, var(--color-accent-red) 12%, transparent)",
                  }}
                >
                  {g}
                </span>
              ))}
            </div>
          ) : (
            <p className="text-sm text-on-surface-variant">No gaps — your profile already covers the demand. 🎉</p>
          )}
        </section>

        <section className="rounded-card border border-border bg-surface p-5 shadow-card">
          <h2 className="mb-3 text-lg font-semibold text-on-surface">Segment mix</h2>
          <ul className="space-y-1.5 text-sm">
            {Object.entries(data.segments).map(([seg, n]) => (
              <li key={seg} className="flex justify-between">
                <span
                  className="text-on-surface-variant"
                  title={seg === "other" ? "Roles that didn't match a known segment" : undefined}
                >
                  {humanizeSeg(seg)}
                </span>
                <span className="font-medium tabular-nums text-on-surface">{n}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}

function Header({
  smallSample = false,
  onRefresh,
  refreshing = false,
}: {
  smallSample?: boolean;
  onRefresh?: () => void;
  refreshing?: boolean;
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-on-surface">Discovery</h1>
        <p className="mt-1 text-on-surface-variant">
          What the market is asking for — and where your profile has gaps.
        </p>
      </div>
      <div className="flex items-center gap-2">
        {smallSample && (
          <span
            className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium"
            style={{
              color: "var(--color-accent-amber)",
              background: "color-mix(in srgb, var(--color-accent-amber) 12%, transparent)",
            }}
            title="Fewer than 100 relevant offers — treat these numbers as directional."
          >
            <Icon name="sparkles" size={12} /> Small sample — directional
          </span>
        )}
        {onRefresh && (
          <button
            onClick={onRefresh}
            disabled={refreshing}
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-1.5 text-sm font-medium text-on-surface transition-colors hover:border-primary/40 disabled:opacity-50"
          >
            <Icon name="refresh" size={16} /> {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        )}
      </div>
    </header>
  );
}

function Stat({ icon, label, value }: { icon: "building" | "search" | "banknote"; label: string; value: string }) {
  return (
    <div className="rounded-card border border-border bg-surface p-4 shadow-card">
      <div className="mb-2 flex items-center gap-2 text-on-surface-variant">
        <span className="grid h-8 w-8 place-items-center rounded-full bg-primary-tint text-primary">
          <Icon name={icon} size={18} />
        </span>
        <span className="text-sm font-medium">{label}</span>
      </div>
      <div className="text-3xl font-bold tabular-nums text-on-surface">{value}</div>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}
