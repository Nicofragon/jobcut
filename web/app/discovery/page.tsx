"use client";

import { useEffect, useState } from "react";
import {
  getMarket,
  regenerateMarket,
  type Market,
  type SkillDemand,
  type SkillGap,
  type ScoreDistribution,
  type Freshness,
} from "@/lib/api";
import { Icon } from "@/components/icons";
import { ErrorNote, Loading } from "@/components/States";

// Skill status → theme colors (have green / partial amber / gap red).
const STATUS_COLOR: Record<string, string> = {
  have: "var(--color-score-high)",
  partial: "var(--color-accent-amber)",
  gap: "var(--color-accent-red)",
};
const STATUS_LABEL: Record<string, string> = { have: "Have", partial: "Partial", gap: "Gap" };

// How you'd close a gap → a human action label (from taxonomy `close_via`).
const CLOSE_VIA: Record<string, string> = {
  course: "Take a course",
  portfolio: "Build a portfolio piece",
  "cv-reframe": "Reframe on your CV",
  skip: "Skip",
};
function closeViaLabel(v: string): string {
  return CLOSE_VIA[v] ?? (v ? v.replace(/[_-]+/g, " ") : "—");
}

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

// Round trend to a "+3pp" / "−2pp" string; null/0 → null (nothing to show).
function trendText(pp: number | null): string | null {
  if (pp == null || Math.round(pp) === 0) return null;
  const r = Math.round(pp);
  return `${r > 0 ? "▲" : "▼"} ${r > 0 ? "+" : "−"}${Math.abs(r)}pp`;
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
  const learn = data.gaps.filter((g) => g.status === "gap");
  const reframe = data.gaps.filter((g) => g.status === "partial");

  return (
    <div className="space-y-6">
      <Header smallSample={smallSample} onRefresh={refresh} refreshing={refreshing} />

      <section className="grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-4">
        <CoverageCard coverage={data.coverage} segments={data.segments} />
        <Stat icon="building" label="Offers analyzed" value={String(data.total)} />
        <Stat icon="search" label="In your market" value={String(data.relevant)} />
        <Stat icon="banknote" label="Disclose salary" value={`${data.salary_pct}%`} />
      </section>

      <Quadrant skills={data.top_demand} />

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
            const tt = trendText(d.trend);
            return (
              <div
                key={d.skill}
                className="flex items-center gap-3"
                role="img"
                aria-label={`${d.skill}: ${d.pct}% of offers, ${statusLabel}${tt ? `, trend ${tt}` : ""}`}
              >
                <span className="w-36 shrink-0 truncate text-sm text-on-surface">{d.skill}</span>
                <div className="h-5 flex-1 overflow-hidden rounded-full bg-surface-sunken">
                  <div className="h-full rounded-full" style={{ width: `${Math.min(d.pct, 100)}%`, background: color }} />
                </div>
                <span className="w-10 shrink-0 text-right text-sm font-medium tabular-nums text-on-surface">{d.pct}%</span>
                <span
                  className="hidden w-16 shrink-0 text-right text-xs font-medium tabular-nums sm:inline"
                  style={{ color: d.trend && d.trend > 0 ? "var(--color-score-high)" : "var(--color-accent-red)" }}
                  title="Change vs the previous market snapshot"
                >
                  {tt ?? ""}
                </span>
                <span className="w-14 shrink-0 text-right text-xs font-medium" style={{ color }}>
                  {statusLabel}
                </span>
              </div>
            );
          })}
        </div>
      </section>

      <Heatmap skills={data.top_demand} segKeys={data.seg_keys} segments={data.segments} />

      <div className="grid gap-4 md:grid-cols-2">
        <GapPlan
          title="Learn / build"
          hint="High-demand skills you don't have yet — sorted by how many offers they'd unlock."
          gaps={learn}
          emptyNote="No hard gaps — your profile already covers the demand. 🎉"
        />
        <GapPlan
          title="Reframe on your CV"
          hint="You already have some exposure — surface it in your CV instead of studying from scratch."
          gaps={reframe}
          emptyNote="Nothing to reframe right now."
        />
      </div>

      <FreshnessCard fresh={data.freshness} />

      <div className="grid gap-4 md:grid-cols-2">
        <Histogram dist={data.score_distribution} />

        <section className="rounded-card border border-border bg-surface p-5 shadow-card">
          <h2 className="mb-3 text-lg font-semibold text-on-surface">Segment mix</h2>
          <ul className="grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
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

// Skill (rows) × role segment (cols) demand heatmap. Answers "what to learn depends
// on which segment I target" — dbt may be 40% in analytics-eng but 5% in data-analyst.
function Heatmap({
  skills,
  segKeys,
  segments,
}: {
  skills: SkillDemand[];
  segKeys: string[];
  segments: Record<string, number>;
}) {
  const cols = segKeys.filter((s) => (segments[s] ?? 0) > 0);
  const rows = skills.slice(0, 12);
  if (!cols.length || !rows.length) return null;
  const max = Math.max(1, ...rows.flatMap((r) => cols.map((c) => r.by_seg[c] ?? 0)));

  return (
    <section className="rounded-card border border-border bg-surface p-5 shadow-card">
      <h2 className="mb-1 text-lg font-semibold text-on-surface">Demand by segment</h2>
      <p className="mb-4 text-sm text-on-surface-variant">
        The same skill can matter far more in one role than another — target the column you&apos;re aiming for.
      </p>
      <div className="overflow-x-auto">
        <div
          className="grid min-w-max gap-1"
          style={{ gridTemplateColumns: `minmax(9rem,1fr) repeat(${cols.length}, minmax(4.5rem,1fr))` }}
        >
          <div aria-hidden />
          {cols.map((c) => (
            <div key={c} className="px-1 pb-1 text-center text-xs font-medium text-on-surface-variant" title={humanizeSeg(c)}>
              {humanizeSeg(c)}
            </div>
          ))}
          {rows.map((r) => (
            <div key={r.skill} className="contents">
              <div className="flex items-center gap-1.5 py-1 pr-2 text-sm text-on-surface">
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: STATUS_COLOR[r.status] }} />
                <span className="truncate" title={r.skill}>
                  {r.skill}
                </span>
              </div>
              {cols.map((c) => {
                const v = r.by_seg[c] ?? 0;
                const alpha = v / max; // 0–1 intensity within the shown range
                return (
                  <div
                    key={c}
                    className="grid place-items-center rounded-md py-1.5 text-xs tabular-nums"
                    style={{
                      background: `color-mix(in srgb, var(--color-primary) ${Math.round(alpha * 85)}%, transparent)`,
                      color: alpha > 0.55 ? "var(--color-on-primary, #fff)" : "var(--color-on-surface)",
                    }}
                    title={`${r.skill} · ${humanizeSeg(c)}: ${v}% of offers`}
                  >
                    {v ? `${v}%` : "·"}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// Match-score distribution of your scored offers — pipeline quality at a glance.
function Histogram({ dist }: { dist: ScoreDistribution }) {
  const BAND_COLOR: Record<string, string> = {
    "Below bar": "var(--color-score-low)",
    Shortlist: "var(--color-accent-amber)",
    Top: "var(--color-score-high)",
  };
  const maxCount = Math.max(1, ...dist.bands.map((b) => b.count));
  return (
    <section className="rounded-card border border-border bg-surface p-5 shadow-card">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold text-on-surface">Your pipeline</h2>
        <span className="text-xs text-on-surface-variant">
          {dist.total} scored · median match {dist.median}
        </span>
      </div>
      <p className="mb-4 text-sm text-on-surface-variant">
        How your scored offers spread by match — the shortlist floor is 60.
      </p>
      {dist.total === 0 ? (
        <p className="text-sm text-on-surface-variant">Nothing scored yet — run scoring to see your pipeline.</p>
      ) : (
        <div className="space-y-2.5">
          {dist.bands.map((b) => {
            const pct = Math.round((100 * b.count) / dist.total);
            const color = BAND_COLOR[b.label] ?? "var(--color-primary)";
            return (
              <div key={b.label} className="flex items-center gap-3" role="img" aria-label={`${b.label}: ${b.count} offers`}>
                <span className="w-20 shrink-0 text-sm text-on-surface" title={`match ${b.min}–${b.max - 1}`}>
                  {b.label}
                </span>
                <div className="h-5 flex-1 overflow-hidden rounded-full bg-surface-sunken">
                  <div className="h-full rounded-full" style={{ width: `${(100 * b.count) / maxCount}%`, background: color }} />
                </div>
                <span className="w-16 shrink-0 text-right text-sm tabular-nums text-on-surface">
                  {b.count}
                  <span className="ml-1 text-xs text-on-surface-variant">{pct}%</span>
                </span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

// Big "you cover X% of the demand" tile with a per-segment breakdown on the tooltip.
function CoverageCard({
  coverage,
  segments,
}: {
  coverage: Market["coverage"];
  segments: Record<string, number>;
}) {
  const color =
    coverage.pct >= 70 ? "var(--color-score-high)" : coverage.pct >= 45 ? "var(--color-accent-amber)" : "var(--color-accent-red)";
  const bySeg = Object.entries(coverage.by_segment)
    .filter(([seg]) => (segments[seg] ?? 0) > 0)
    .sort((a, b) => b[1] - a[1]);
  return (
    <div className="rounded-card border border-border bg-surface p-4 shadow-card">
      <div className="mb-2 flex items-center gap-2 text-on-surface-variant">
        <span className="grid h-8 w-8 place-items-center rounded-full bg-primary-tint text-primary">
          <Icon name="check-circle" size={18} />
        </span>
        <span className="text-sm font-medium">Profile coverage</span>
      </div>
      <div className="flex items-baseline gap-2">
        <div className="text-3xl font-bold tabular-nums" style={{ color }}>
          {coverage.pct}%
        </div>
        <span className="text-xs text-on-surface-variant">of demand</span>
      </div>
      {bySeg.length > 0 && (
        <ul className="mt-2 space-y-1">
          {bySeg.map(([seg, pct]) => (
            <li key={seg} className="flex items-center gap-2 text-xs">
              <span className="w-24 shrink-0 truncate text-on-surface-variant" title={humanizeSeg(seg)}>
                {humanizeSeg(seg)}
              </span>
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-sunken">
                <div className="h-full rounded-full bg-primary" style={{ width: `${Math.min(pct, 100)}%` }} />
              </div>
              <span className="w-8 shrink-0 text-right tabular-nums text-on-surface">{pct}%</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Demand (x) × your status (y). Bottom-right = learn now; top-right = your edge.
function Quadrant({ skills }: { skills: SkillDemand[] }) {
  if (!skills.length) return null;
  // Y bands, top→bottom. Each dot sits in its status band, x = demand %.
  const BANDS: { status: string; label: string }[] = [
    { status: "have", label: "Have" },
    { status: "partial", label: "Partial" },
    { status: "gap", label: "Gap" },
  ];
  const demands = skills.map((s) => s.pct).sort((a, b) => a - b);
  const median = demands[Math.floor(demands.length / 2)] || 0;
  const threshold = Math.max(30, median); // "high demand" line — never below 30%

  return (
    <section className="rounded-card border border-border bg-surface p-5 shadow-card">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-on-surface">Where to invest</h2>
        <span className="text-xs text-on-surface-variant">demand → · your status ↑</span>
      </div>
      <p className="mb-4 text-sm text-on-surface-variant">
        Skills to the right of the line are in high demand. High demand + a gap is what to learn next; high demand you
        already have is your edge to sell.
      </p>
      <div className="relative h-64 rounded-lg border border-border bg-surface-sunken">
        {/* high-demand threshold line */}
        <div
          className="absolute inset-y-0 border-l border-dashed border-border"
          style={{ left: `${threshold}%` }}
          aria-hidden
        />
        <span
          className="absolute top-1 text-[10px] font-medium text-on-surface-faint"
          style={{ left: `calc(${threshold}% + 4px)` }}
          aria-hidden
        >
          high demand →
        </span>
        {/* status band guides + labels */}
        {BANDS.map((b, i) => (
          <div
            key={b.status}
            className="absolute inset-x-0 flex items-start"
            style={{ top: `${(i / BANDS.length) * 100}%`, height: `${100 / BANDS.length}%` }}
          >
            <span className="pl-1.5 pt-1 text-[10px] font-medium" style={{ color: STATUS_COLOR[b.status] }}>
              {b.label}
            </span>
            {i > 0 && <div className="absolute inset-x-0 top-0 border-t border-dashed border-border/60" aria-hidden />}
          </div>
        ))}
        {/* dots */}
        {skills.map((s, idx) => {
          const bandIdx = BANDS.findIndex((b) => b.status === s.status);
          const band = bandIdx < 0 ? 1 : bandIdx;
          // vertical jitter inside the band so co-located dots don't fully overlap
          const jitter = 30 + ((idx * 37) % 40); // 30–70% within the band
          const top = ((band + jitter / 100) / BANDS.length) * 100;
          const color = STATUS_COLOR[s.status] ?? "var(--color-on-surface-faint)";
          const tt = trendText(s.trend);
          return (
            <div
              key={s.skill}
              className="group absolute -translate-x-1/2 -translate-y-1/2"
              style={{ left: `${Math.min(Math.max(s.pct, 2), 98)}%`, top: `${top}%` }}
            >
              <span
                className="block h-2.5 w-2.5 rounded-full ring-2 ring-surface"
                style={{ background: color }}
                role="img"
                aria-label={`${s.skill}: ${s.pct}% of offers, ${STATUS_LABEL[s.status] ?? s.status}`}
              />
              <span className="pointer-events-none absolute left-1/2 top-4 z-10 hidden -translate-x-1/2 whitespace-nowrap rounded-md border border-border bg-surface px-2 py-1 text-[11px] text-on-surface shadow-card group-hover:block">
                {s.skill} · {s.pct}%{tt ? ` · ${tt}` : ""}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// A prioritized, actionable gap list (one column). Each row: demand, action, offers unlocked.
function GapPlan({
  title,
  hint,
  gaps,
  emptyNote,
}: {
  title: string;
  hint: string;
  gaps: SkillGap[];
  emptyNote: string;
}) {
  return (
    <section className="rounded-card border border-border bg-surface p-5 shadow-card">
      <h2 className="text-lg font-semibold text-on-surface">{title}</h2>
      {gaps.length ? (
        <>
          <p className="mb-3 mt-1 text-sm text-on-surface-variant">{hint}</p>
          <ul className="space-y-2.5">
            {gaps.map((g) => (
              <li key={g.skill} className="flex items-center gap-3">
                <span className="w-28 shrink-0 truncate text-sm font-medium text-on-surface" title={g.skill}>
                  {g.skill}
                </span>
                <div className="h-4 flex-1 overflow-hidden rounded-full bg-surface-sunken">
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${Math.min(g.pct, 100)}%`, background: STATUS_COLOR[g.status] }}
                  />
                </div>
                <span className="w-9 shrink-0 text-right text-sm tabular-nums text-on-surface">{g.pct}%</span>
                <span
                  className="hidden shrink-0 rounded-full px-2 py-0.5 text-xs font-medium text-primary sm:inline"
                  style={{ background: "var(--color-primary-tint)" }}
                  title={`${g.n} offers in your market mention this`}
                >
                  {closeViaLabel(g.close_via)}
                </span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="mt-3 text-sm text-on-surface-variant">{emptyNote}</p>
      )}
    </section>
  );
}

// Posting velocity — offers per ISO week (last 10) with the median offer age.
function FreshnessCard({ fresh }: { fresh: Freshness }) {
  const max = Math.max(1, ...fresh.weekly.map((w) => w.count));
  const wk = (label: string) => label.replace(/^\d{4}-/, ""); // "2026-W23" → "W23"
  return (
    <section className="rounded-card border border-border bg-surface p-5 shadow-card">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold text-on-surface">Market velocity</h2>
        <span className="text-xs text-on-surface-variant">median age {fresh.median_age_days}d</span>
      </div>
      <p className="mb-4 text-sm text-on-surface-variant">New offers posted per week — is your market heating up or cooling?</p>
      {fresh.weekly.length === 0 ? (
        <p className="text-sm text-on-surface-variant">No posting dates yet.</p>
      ) : (
        <>
          <div className="flex h-28 items-end gap-1.5">
            {fresh.weekly.map((w) => (
              <div
                key={w.week}
                className="group relative flex-1"
                role="img"
                aria-label={`${wk(w.week)}: ${w.count} offers`}
                style={{ height: "100%" }}
              >
                <div className="absolute bottom-0 w-full rounded-t bg-primary" style={{ height: `${(100 * w.count) / max}%` }} />
                <span className="pointer-events-none absolute -top-5 left-1/2 hidden -translate-x-1/2 whitespace-nowrap rounded-md border border-border bg-surface px-1.5 py-0.5 text-[10px] text-on-surface shadow-card group-hover:block">
                  {wk(w.week)}: {w.count}
                </span>
              </div>
            ))}
          </div>
          <div className="mt-1.5 flex justify-between text-[10px] text-on-surface-variant">
            <span>{wk(fresh.weekly[0].week)}</span>
            <span>{wk(fresh.weekly[fresh.weekly.length - 1].week)}</span>
          </div>
        </>
      )}
    </section>
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
