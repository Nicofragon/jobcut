"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import {
  createManualApplication,
  deleteApplication,
  getApplications,
  getFunnel,
  getInterviewFunnel,
  getProcessTimingSummary,
  type Application,
  type Funnel,
  type InterviewFunnelRow,
  type ProcessTimingSummary,
} from "@/lib/api";
import { CATEGORY_COLOR } from "@/lib/ui";
import { Icon } from "@/components/icons";
import { InfoDot } from "@/components/InfoDot";
import { ErrorNote, SkeletonRows } from "@/components/States";
import StatusSelect from "@/components/StatusSelect";

type Row = Application;

export default function ApplicationsPage() {
  const [funnel, setFunnel] = useState<Funnel | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [ivFunnel, setIvFunnel] = useState<InterviewFunnelRow[]>([]);
  const [timing, setTiming] = useState<ProcessTimingSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => {
    // One call each — the list endpoint already carries title/company (server-side
    // join), so no per-row job fetch (that N+1 cost ~6.75s for 62 rows).
    Promise.all([getFunnel(), getApplications(), getInterviewFunnel(), getProcessTimingSummary()])
      .then(([f, apps, iv, t]) => {
        setFunnel(f);
        setRows(apps);
        setIvFunnel(iv);
        setTiming(t);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "failed to load"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  async function remove(jobId: string) {
    setRows((rs) => rs.filter((r) => r.job_id !== jobId)); // optimistic: drop the row now
    try {
      await deleteApplication(jobId);
    } finally {
      load(); // reconcile funnel counts (cheap; the delete cleared the read cache)
    }
  }

  if (error) return <ErrorNote>{error}. Is the API running on :8000?</ErrorNote>;
  if (loading && !funnel)
    return (
      <div className="space-y-8">
        <header>
          <h1 className="text-3xl font-semibold tracking-tight text-on-surface">Application Tracker</h1>
          <p className="mt-1 text-on-surface-variant">Keep an eye on your progress.</p>
        </header>
        <SkeletonRows count={4} />
      </div>
    );
  if (!funnel) return null;

  const m = deriveMetrics(funnel);

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-on-surface">Application Tracker</h1>
          <p className="mt-1 text-on-surface-variant">How your search is actually going — at a glance.</p>
        </div>
        <button
          onClick={() => setAdding((v) => !v)}
          className="shrink-0 rounded-lg border border-border px-3 py-2 text-sm font-medium text-on-surface transition-colors hover:border-primary hover:text-primary"
        >
          + Add application
        </button>
      </header>

      {adding && (
        <AddApplicationForm onDone={() => { setAdding(false); load(); }} onCancel={() => setAdding(false)} />
      )}

      {m.total === 0 ? (
        <EmptyState />
      ) : (
        <>
          <KpiRow m={m} />
          <ActivityTrend labels={m.weekLabels} values={m.weekSeries} />
          <FunnelPanel m={m} stalled={funnel.stalled_count ?? 0} dormant={funnel.dormant_count ?? 0} />
          <InterviewFunnelPanel rows={ivFunnel} timing={timing} />
        </>
      )}

      {rows.length === 0 ? (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-on-surface">Active Applications</h2>
          <EmptyState />
        </section>
      ) : (
        <>
          {/* Lead the list with "what needs action" — metrics stay on top as the overview. */}
          <NeedsAttention rows={rows} />
          <TrackerList rows={rows} onRemove={remove} onChanged={load} />
        </>
      )}
    </div>
  );
}

// ---- Add application (B-1): a role outside the scraper ----------------------

const ADD_INPUT =
  "rounded-lg border border-border bg-bg px-3 py-2 text-sm text-on-surface outline-none transition-colors placeholder:text-on-surface-faint focus:border-primary focus:ring-1 focus:ring-primary";
const ADD_STATUSES = [
  { value: "applied", label: "Applied" },
  { value: "saved", label: "Saved" },
  { value: "screen", label: "Screening" },
  { value: "interview", label: "Interview" },
  { value: "offer", label: "Offer" },
];

function AddApplicationForm({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const [url, setUrl] = useState("");
  const [company, setCompany] = useState("");
  const [title, setTitle] = useState("");
  const [location, setLocation] = useState("");
  const [status, setStatus] = useState("applied");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const canSave = company.trim().length > 0 && title.trim().length > 0;

  async function save() {
    if (!canSave || busy) return;
    setBusy(true);
    setErr(null);
    try {
      await createManualApplication({
        url: url.trim() || undefined,
        company: company.trim(),
        title: title.trim(),
        location: location.trim() || undefined,
        status,
      });
      onDone();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Couldn't add it");
      setBusy(false);
    }
  }

  return (
    <section className="space-y-3 rounded-card border border-border/40 bg-surface p-5 shadow-card">
      <div>
        <h2 className="text-sm font-semibold text-on-surface">Add an application</h2>
        <p className="mt-0.5 text-xs text-on-surface-variant">
          For a role outside the scraper — a company site, Lever/Greenhouse, or an expired posting.
          Company and title are required; the URL is optional.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <input className={ADD_INPUT} placeholder="Company *" value={company} onChange={(e) => setCompany(e.target.value)} />
        <input className={ADD_INPUT} placeholder="Title *" value={title} onChange={(e) => setTitle(e.target.value)} />
        <input className={ADD_INPUT} placeholder="Location" value={location} onChange={(e) => setLocation(e.target.value)} />
        <input className={ADD_INPUT} placeholder="URL (any ATS)" value={url} onChange={(e) => setUrl(e.target.value)} />
      </div>
      <label className="flex items-center gap-2 text-sm text-on-surface-variant">
        Status
        <select value={status} onChange={(e) => setStatus(e.target.value)} className={ADD_INPUT}>
          {ADD_STATUSES.map((s) => (
            <option key={s.value} value={s.value}>{s.label}</option>
          ))}
        </select>
      </label>
      {err && <p className="text-sm text-[color:var(--color-accent-red,#dc2626)]">{err}</p>}
      <div className="flex gap-2">
        <button
          onClick={save}
          disabled={!canSave || busy}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "Adding…" : "Add"}
        </button>
        <button
          onClick={onCancel}
          disabled={busy}
          className="rounded-lg border border-border px-4 py-2 text-sm disabled:opacity-50"
        >
          Cancel
        </button>
      </div>
    </section>
  );
}

// ---- Needs attention: follow-ups due + stalled, the "act this week" list -----

type Attn = {
  row: Row;
  reason: string;
  tone: "overdue" | "due" | "stall";
  urgency: number; // days overdue / days stalled — higher = sooner in its group
};

function ymd(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function attentionItems(rows: Row[]): Attn[] {
  const todayKey = ymd(new Date());
  const items: Attn[] = [];
  for (const r of rows) {
    const nad = r.next_action_date ? r.next_action_date.slice(0, 10) : null;
    const step = r.next_action || "Follow up";
    if (nad && nad < todayKey) {
      const over = daysBetween(nad, todayKey);
      items.push({ row: r, reason: `Follow-up overdue · ${step}`, tone: "overdue", urgency: over });
    } else if (nad && nad === todayKey) {
      items.push({ row: r, reason: `Follow-up due today · ${step}`, tone: "due", urgency: 0 });
    } else if (r.stalled) {
      const d = r.days_in_stage ?? 0;
      items.push({ row: r, reason: `No movement in ${d}d · ${r.status_category}`, tone: "stall", urgency: d });
    }
  }
  const rank = { overdue: 0, due: 1, stall: 2 } as const;
  return items.sort((a, b) => {
    if (rank[a.tone] !== rank[b.tone]) return rank[a.tone] - rank[b.tone];
    // Within follow-ups: most-overdue first. Within stalled: freshest first — the
    // one that just went quiet is still worth a nudge; the 200-day-old one isn't.
    return a.tone === "stall" ? a.urgency - b.urgency : b.urgency - a.urgency;
  });
}

function daysBetween(a: string, b: string): number {
  return Math.round((new Date(b).getTime() - new Date(a).getTime()) / 86_400_000);
}

const ATTN_COLOR = { overdue: "#dc2626", due: "#d97706", stall: "#d97706" } as const;
const ATTN_CAP = 6;

function NeedsAttention({ rows }: { rows: Row[] }) {
  const router = useRouter();
  const items = attentionItems(rows);
  const dormant = rows.filter((r) => r.dormant).length;
  // B-7: "Needs attention" is the act-now list. With nothing actionable, hide the whole
  // section (no empty "all clear" card). The dormant count still shows in the Pipeline panel.
  if (items.length === 0) return null;
  const shown = items.slice(0, ATTN_CAP);
  const overdue = items.filter((i) => i.tone === "overdue").length;

  return (
    <section className="rounded-card border border-[color:var(--color-accent-amber,#d97706)]/30 bg-[#fffbeb] p-5 shadow-card dark:bg-surface">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-on-surface">
          <Icon name="clock" size={18} />
          Needs attention
          <span className="font-normal text-on-surface-faint">· {items.length}</span>
        </h2>
        {overdue > 0 && (
          <span className="text-sm font-medium" style={{ color: ATTN_COLOR.overdue }}>
            {overdue} overdue
          </span>
        )}
      </div>
      <ul className="space-y-1.5">
        {shown.map((it) => (
          <li key={it.row.job_id}>
            <button
              type="button"
              onClick={() => router.push(`/job?id=${it.row.job_id}`)}
              className="flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-surface-sunken"
            >
              <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: ATTN_COLOR[it.tone] }} />
              <span className="min-w-0 flex-1">
                <span className="truncate font-medium text-on-surface">{it.row.title || it.row.job_id}</span>
                <span className="text-on-surface-faint"> · {it.row.company_name || "—"}</span>
              </span>
              <span className="shrink-0 text-sm" style={{ color: ATTN_COLOR[it.tone] }}>
                {it.reason}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {items.length > ATTN_CAP && (
        <p className="mt-2 px-2.5 text-sm text-on-surface-faint">
          +{items.length - ATTN_CAP} more below in the list.
        </p>
      )}
      {dormant > 0 && (
        <p className="mt-3 border-t border-border pt-3 px-2.5 text-sm text-on-surface-faint">
          {dormant} dormant ({">"}90d, no movement) — probably dead. Mark them rejected or withdrawn to clear the funnel.
        </p>
      )}
    </section>
  );
}

function EmptyState() {
  return (
    <div className="rounded-card border border-dashed border-border bg-surface p-8 text-center">
      <p className="text-on-surface">No applications yet.</p>
      <p className="mt-1 text-sm text-on-surface-variant">
        When you mark a job as applied from{" "}
        <Link href="/" className="font-medium text-primary hover:underline">
          Today
        </Link>
        , it shows up here so you can track it through to an offer.
      </p>
    </div>
  );
}

// ---- derived metrics (all client-side from what /funnel already returns) -----

type Stage = { key: string; label: string; count: number; active: number; color: string };

type Metrics = {
  total: number;
  pending: number; // applied, no signal back yet
  stages: Stage[]; // cumulative "reached at least this stage"
  leaks: { label: string; count: number; color: string }[];
  traction: { from: string; to: string; dropPct: number } | null;
  responseRate: number;
  replied: number;
  interviewsSecured: number; // reached an interview — the real success metric
  interviewRate: number;
  offers: number;
  ghosted: number;
  ghostRate: number;
  thisWeek: number;
  weekDelta: number;
  weekSeries: number[];
  weekLabels: string[];
};

function deriveMetrics(f: Funnel): Metrics {
  const c = f.counts ?? {};
  const g = (k: string) => c[k] ?? 0;

  const offer = g("Offer");
  const interview = g("Interview");
  const screening = g("Screen") + g("Active") + g("Reviewing");
  const pending = g("Applied"); // applied, still waiting
  const rejected = g("Rejected");
  const noResponse = g("No response") + g("Closed");
  const withdrawn = g("Withdrawn");
  const total = f.total;

  // Cumulative funnel = how many EVER reached each stage, from the event history (B-12):
  // a role rejected after an interview still counts. Falls back to the current-state
  // approximation ("everyone at X or beyond") when the backend doesn't send `reached`.
  const reachedApplied = f.reached?.applied ?? total;
  const reachedScreen = f.reached?.screen ?? screening + interview + offer;
  const reachedInterview = f.reached?.interview ?? interview + offer;
  const reachedOffer = f.reached?.offer ?? offer;

  const stages: Stage[] = [
    { key: "applied", label: "Applied", count: reachedApplied, active: pending, color: CATEGORY_COLOR.Applied },
    { key: "screening", label: "Screening", count: reachedScreen, active: screening, color: CATEGORY_COLOR.Screen },
    { key: "interview", label: "Interview", count: reachedInterview, active: interview, color: CATEGORY_COLOR.Interview },
    { key: "offer", label: "Offer", count: reachedOffer, active: offer, color: CATEGORY_COLOR.Offer },
  ];

  const leaks = [
    { label: "No response", count: noResponse, color: CATEGORY_COLOR["No response"] },
    { label: "Rejected", count: rejected, color: CATEGORY_COLOR.Rejected },
    { label: "Withdrawn", count: withdrawn, color: CATEGORY_COLOR.Withdrawn },
  ].filter((l) => l.count > 0);

  // "Where you lose traction": the biggest drop among the gates you can actually
  // influence (Applied → Screening, Screening → Interview). The Interview → Offer step
  // is excluded — offers are rare and terminal, so it would always "win" and tell you
  // nothing actionable.
  let traction: Metrics["traction"] = null;
  for (let i = 1; i < stages.length; i++) {
    const cur = stages[i];
    if (cur.key === "offer") continue;
    const prev = stages[i - 1];
    if (prev.count <= 0) continue;
    const dropPct = (prev.count - cur.count) / prev.count;
    if (!traction || dropPct > traction.dropPct) {
      traction = { from: prev.label, to: cur.label, dropPct };
    }
  }

  // Any signal back from the other side = everyone who isn't still-waiting (Applied) or
  // ghosted (No response). Defined this way (not reachedScreen + rejected) so it can't
  // double-count a role that reached screening and was then rejected (B-12 cumulative).
  const responses = Math.max(0, total - pending - noResponse);
  const responseRate = total ? responses / total : 0;
  const interviewRate = total ? reachedInterview / total : 0;
  const ghostRate = total ? noResponse / total : 0;

  // Weekly activity from by_week (honest ISO week, matching the backend). Show a
  // fixed window of the last N weeks, filling empty weeks with 0 — so the chart
  // renders (and reads as a rhythm) even for a brand-new user whose applications
  // are all in the current week.
  const WEEKS_SHOWN = 8;
  const now = new Date();
  const weekKeys = Array.from({ length: WEEKS_SHOWN }, (_, i) =>
    isoWeekKey(new Date(now.getTime() - (WEEKS_SHOWN - 1 - i) * 7 * 86_400_000)),
  );
  const thisKey = weekKeys[weekKeys.length - 1];
  const prevKey = weekKeys[weekKeys.length - 2];
  const thisWeek = f.by_week?.[thisKey] ?? 0;
  const weekDelta = thisWeek - (f.by_week?.[prevKey] ?? 0);
  const weekSeries = weekKeys.map((k) => f.by_week?.[k] ?? 0);
  const weekLabels = weekKeys.map((k) => (k.includes("-W") ? `W${k.split("-W")[1]}` : k));

  return {
    total,
    pending,
    stages,
    leaks,
    traction,
    responseRate,
    replied: responses,
    interviewsSecured: reachedInterview,
    interviewRate,
    offers: offer,
    ghosted: noResponse,
    ghostRate,
    thisWeek,
    weekDelta,
    weekSeries,
    weekLabels,
  };
}

function isoWeekKey(d: Date): string {
  const dt = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = dt.getUTCDay() || 7;
  dt.setUTCDate(dt.getUTCDate() + 4 - day); // nearest Thursday
  const yearStart = new Date(Date.UTC(dt.getUTCFullYear(), 0, 1));
  const week = Math.ceil(((dt.getTime() - yearStart.getTime()) / 86_400_000 + 1) / 7);
  return `${dt.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
}

const pct = (x: number) => `${Math.round(x * 100)}%`;

// ---- KPIs (ratios, not raw counts) ------------------------------------------

function KpiRow({ m }: { m: Metrics }) {
  const delta =
    m.weekDelta === 0 ? "same as last week" : `${m.weekDelta > 0 ? "+" : ""}${m.weekDelta} vs last week`;
  return (
    // Two questions a job seeker actually has: "how much am I doing?" (effort) and
    // "is it working?" (traction → interviews). Offers aren't the scoreboard.
    <section className="grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-4">
      <Kpi
        label="Applications sent"
        accent="#64748b"
        value={String(m.total)}
        sub={delta}
        info="Total roles you've applied to. The line under it is how many you sent this week vs last — momentum matters more than any single week."
      >
        <Sparkline values={m.weekSeries} color="#64748b" />
      </Kpi>
      <Kpi
        label="Response rate"
        accent="#16a34a"
        value={pct(m.responseRate)}
        sub={`${m.replied} replied · ${m.ghosted} ghosted`}
        info="Share of applications that got any reply back — a screening, interview, or rejection. Low here means your applications aren't landing (CV / targeting)."
      />
      <Kpi
        label="Interviews secured"
        accent="#16a34a"
        value={String(m.interviewsSecured)}
        sub={`${pct(m.interviewRate)} of ${m.total} reached interview`}
        goal
        info="How many applications reached an interview — your real goal. An offer usually follows just one or two, and once you accept, the search is done."
      />
      <Kpi
        label="No response"
        accent="#d97706"
        value={pct(m.ghostRate)}
        sub={`${m.ghosted} never heard back`}
        tone="warn"
        info="Share of applications you never heard back on (incl. auto-aged after 30 days). High here points to top-of-funnel fit / targeting."
      />
    </section>
  );
}

function Kpi({
  label,
  value,
  sub,
  accent,
  tone,
  goal,
  info,
  children,
}: {
  label: string;
  value: string;
  sub: string;
  accent: string;
  tone?: "warn";
  goal?: boolean;
  info?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="rounded-card border border-border bg-surface p-4 shadow-card transition-shadow hover:shadow-pop md:p-5">
      <div className="mb-2 flex items-center gap-2 text-on-surface-variant">
        <span className="h-2 w-2 rounded-full" style={{ background: accent }} />
        <span className="text-sm font-medium">{label}</span>
        {goal && <span title="Your goal">🎯</span>}
        {info && <span className="ml-auto"><InfoDot text={info} align="right" /></span>}
      </div>
      <div className="flex items-end justify-between gap-2">
        <div
          className="text-4xl font-bold tabular-nums"
          style={{ color: tone === "warn" ? accent : "var(--color-on-surface)" }}
        >
          {value}
        </div>
        {children}
      </div>
      <p className="mt-1 truncate text-sm text-on-surface-variant" title={sub}>
        {sub}
      </p>
    </div>
  );
}

// ---- weekly activity trend (effort over time) -------------------------------

const TREND_H = 104; // px of vertical room for the tallest bar

function ActivityTrend({ labels, values }: { labels: string[]; values: number[] }) {
  if (values.length < 2) return null;
  const max = Math.max(...values, 1);
  return (
    <section className="rounded-card border border-border bg-surface p-5 shadow-card">
      <div className="mb-4 flex items-center gap-2">
        <h2 className="text-lg font-semibold text-on-surface">Weekly activity</h2>
        <InfoDot text="Applications you sent each week (last 10). This is your effort rhythm — keeping a steady cadence is the part fully in your control." />
      </div>
      {/* Pixel heights off the max — percentage heights collapse inside an items-end
          flex row (no defined parent height), which made every bar look identical. */}
      <div className="flex items-end gap-2" style={{ height: TREND_H + 18 }}>
        {values.map((v, i) => (
          <div key={i} className="flex flex-1 flex-col items-center justify-end">
            <span className="mb-1 text-xs font-semibold tabular-nums text-on-surface-faint">{v || ""}</span>
            <div
              className="w-full rounded-t bg-primary/70"
              style={{ height: Math.round((v / max) * TREND_H), minHeight: v > 0 ? 4 : 0 }}
              aria-label={`${labels[i]}: ${v}`}
            />
          </div>
        ))}
      </div>
      <div className="mt-1 flex gap-2">
        {labels.map((l, i) => (
          <span key={i} className="flex-1 text-center text-[10px] tabular-nums text-on-surface-faint">
            {l}
          </span>
        ))}
      </div>
    </section>
  );
}

function Sparkline({ values, color }: { values: number[]; color: string }) {
  if (values.length < 2) return null;
  const w = 72;
  const h = 24;
  const max = Math.max(...values, 1);
  const pts = values
    .map((v, i) => `${(i / (values.length - 1)) * w},${h - (v / max) * (h - 2) - 1}`)
    .join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden className="shrink-0">
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        opacity={0.7}
      />
    </svg>
  );
}

// ---- Funnel (exclusive cumulative buckets + conversion + leaks) --------------

function FunnelPanel({ m, stalled, dormant }: { m: Metrics; stalled: number; dormant: number }) {
  const top = m.stages[0].count || 1;
  return (
    <section className="rounded-card border border-border bg-surface p-5 shadow-card">
      <div className="mb-4 flex items-baseline justify-between gap-4">
        <h2 className="flex items-baseline gap-2 text-lg font-semibold text-on-surface">
          Pipeline
          <InfoDot text="Your applications by how far they got — counted across your whole history, so a role you interviewed for and were then rejected still counts toward 'reached interview'. The faint 'N active' is how many are in that stage right now. The goal is interviews — offers are rare and end the search." />
          {stalled > 0 && (
            <span className="ml-1 text-sm font-medium" style={{ color: CATEGORY_COLOR.Withdrawn }}>
              {stalled} stalled
            </span>
          )}
          {dormant > 0 && (
            <span className="text-sm font-normal text-on-surface-faint">{dormant} dormant</span>
          )}
        </h2>
        {m.traction && m.traction.dropPct > 0 && (
          <p className="flex items-center gap-1.5 text-sm text-on-surface-variant">
            Where you lose traction:{" "}
            <span className="font-semibold text-on-surface">
              {m.traction.from} → {m.traction.to}
            </span>{" "}
            <span className="font-semibold" style={{ color: CATEGORY_COLOR.Rejected }}>
              −{pct(m.traction.dropPct)}
            </span>
            <InfoDot
              align="right"
              text="The biggest fall-off among the gates you can influence (getting a response, then converting it). Interview → Offer is left out on purpose — offers are rare, so it would always look like the worst step."
            />
          </p>
        )}
      </div>

      {m.offers > 0 && (
        <div className="mb-4 rounded-lg border border-[color:var(--color-accent-green,#16a34a)]/30 bg-[#f0fdf4] px-4 py-2.5 text-sm font-medium text-on-surface dark:bg-surface-sunken">
          🎉 You have {m.offers === 1 ? "an offer" : `${m.offers} offers`} — jobcut&apos;s job is basically done. Congrats!
        </div>
      )}

      <div className="space-y-2.5">
        {m.stages.map((s) => {
          const ofApplied = m.total ? s.count / m.total : 0;
          return (
            <div key={s.key} className="flex items-center gap-3">
              <div className="flex w-20 shrink-0 items-center gap-1 text-sm font-medium text-on-surface">
                {s.label}
                {s.key === "interview" && <span title="Your goal">🎯</span>}
              </div>
              <div className="relative h-7 flex-1 overflow-hidden rounded-lg bg-surface-sunken">
                <div
                  className="h-full rounded-lg transition-all"
                  style={{ width: `${Math.max((100 * s.count) / top, s.count > 0 ? 2 : 0)}%`, background: s.color }}
                  aria-label={`${s.label}: ${s.count}`}
                />
              </div>
              <div className="flex w-36 shrink-0 items-baseline justify-end gap-2">
                {s.active > 0 && s.key !== "applied" && (
                  <span className="text-xs tabular-nums text-on-surface-faint" title="active in this stage now">
                    {s.active} active
                  </span>
                )}
                <span className="text-sm font-semibold tabular-nums text-on-surface">{s.count}</span>
                <span className="w-10 text-right text-xs tabular-nums text-on-surface-faint">
                  {pct(ofApplied)}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* step conversions read out (Applied → Screening = X%) */}
      <p className="mt-3 text-xs text-on-surface-faint">
        {m.stages
          .slice(1)
          .map((s, i) => {
            const prev = m.stages[i];
            const conv = prev.count > 0 ? Math.round((100 * s.count) / prev.count) : 0;
            return `${prev.label} → ${s.label} ${conv}%`;
          })
          .join("   ·   ")}
      </p>

      {m.leaks.length > 0 && (
        <div className="mt-4 border-t border-border pt-3">
          <div className="mb-2 text-xs font-medium uppercase tracking-wide text-on-surface-faint">
            Closed / leaked
          </div>
          <div className="flex flex-wrap gap-x-5 gap-y-2">
            {m.leaks.map((l) => (
              <span key={l.label} className="inline-flex items-center gap-2 text-sm text-on-surface-variant">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: l.color }} />
                {l.label}
                <span className="font-semibold tabular-nums text-on-surface">{l.count}</span>
                <span className="tabular-nums text-on-surface-faint">
                  ({pct(m.total ? l.count / m.total : 0)})
                </span>
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

// ---- Interview funnel (by interview stage index) ----------------------------

function InterviewFunnelPanel({
  rows,
  timing,
}: {
  rows: InterviewFunnelRow[];
  timing: ProcessTimingSummary | null;
}) {
  const hasTiming = !!timing && timing.processes > 0;
  if (rows.length === 0 && !hasTiming) return null;
  const max = rows[0]?.reached || 1;
  return (
    <section className="mt-8 rounded-card border border-border/40 bg-surface p-6">
      <h3 className="text-sm font-semibold">Interview funnel</h3>
      <p className="text-xs text-on-surface-variant">Where your processes convert, by interview stage.</p>
      <div className="mt-4 space-y-2">
        {rows.map((row) => (
          <div key={row.stage} className="flex items-center gap-3 text-sm">
            <span className="w-10 text-on-surface-variant">{row.stage}ª</span>
            <div className="h-5 flex-1 rounded bg-surface-sunken">
              <div className="h-5 rounded bg-primary" style={{ width: `${(row.reached / max) * 100}%` }} />
            </div>
            <span className="w-24 text-right text-on-surface-variant">
              {row.reached}{row.conversion != null ? ` · ${Math.round(row.conversion * 100)}% →` : ""}
            </span>
          </div>
        ))}
      </div>
      {hasTiming && (
        <div className="mt-4 border-t border-border/40 pt-3 text-xs text-on-surface-variant">
          <span className="font-medium text-on-surface">Timing</span> · avg{" "}
          {Math.round(timing!.avg_duration_days!)} days end-to-end · {Math.round(timing!.avg_gap_days!)} days
          between rounds · {timing!.processes} {timing!.processes === 1 ? "process" : "processes"}
        </div>
      )}
    </section>
  );
}

// ---- actionable list: inline status edit + filter + sort + group-by-stage ---

// Display buckets group the raw status_category vocabulary into the funnel order
// a job seeker thinks in. Order = most advanced first, then the leaks.
const BUCKETS = [
  { key: "offer", label: "Offer", cats: ["Offer"] },
  { key: "in_process", label: "In process", cats: ["Interview", "Screen", "Active", "Reviewing"] },
  { key: "applied", label: "Applied", cats: ["Applied"] },
  { key: "no_response", label: "No response", cats: ["No response", "Closed"] },
  { key: "rejected", label: "Rejected", cats: ["Rejected"] },
  { key: "withdrawn", label: "Withdrawn", cats: ["Withdrawn"] },
  { key: "saved", label: "Saved", cats: ["Saved"] },
  { key: "other", label: "Other", cats: ["Other"] },
] as const;

function bucketOf(cat: string): string {
  return BUCKETS.find((b) => (b.cats as readonly string[]).includes(cat))?.key ?? "other";
}
function bucketColor(key: string): string {
  const b = BUCKETS.find((x) => x.key === key);
  return (b && CATEGORY_COLOR[b.cats[0]]) || "#64748b";
}

type SortKey = "active" | "updated" | "company";

// B-10: rank by how "in play" a role is, so what's actually moving floats to the top.
// 0 = in process (interviewing / with movement), 1 = sent or saved, 2 = terminal.
const ACTIVE_RANK: Record<string, number> = {
  Interview: 0, Screen: 0, Active: 0, Reviewing: 0, Offer: 0,
  Applied: 1, Saved: 1,
  "No response": 2, Closed: 2, Rejected: 2, Withdrawn: 2, Other: 2,
};
const activeRank = (cat: string) => ACTIVE_RANK[cat] ?? 1;

function TrackerList({
  rows,
  onRemove,
  onChanged,
}: {
  rows: Row[];
  onRemove: (jobId: string) => void;
  onChanged: () => void;
}) {
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState<SortKey>("active");

  const counts = new Map<string, number>();
  for (const r of rows) {
    const k = bucketOf(r.status_category);
    counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  const presentBuckets = BUCKETS.filter((b) => counts.has(b.key));

  const visible = rows.filter((r) => filter === "all" || bucketOf(r.status_category) === filter);
  const byRecent = (a: Row, b: Row) => (b.updated_at ?? "").localeCompare(a.updated_at ?? "");
  const sorter = (a: Row, b: Row) => {
    if (sort === "company") return (a.company_name ?? "").localeCompare(b.company_name ?? "");
    if (sort === "updated") return byRecent(a, b);
    // "active": in-process first, then most-recently-updated within each tier.
    const dr = activeRank(a.status_category) - activeRank(b.status_category);
    return dr !== 0 ? dr : byRecent(a, b);
  };

  // One flat row per application (B-6) — they're all already-applied roles, so grouping by
  // category just fragments the list. The status pill on each row shows its current stage;
  // the chips above filter, the dropdown sorts.
  const sorted = visible.slice().sort(sorter);

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-on-surface">
          Active Applications <span className="font-normal text-on-surface-faint">· {visible.length}</span>
        </h2>
        <label className="flex items-center gap-2 text-sm text-on-surface-variant">
          Sort
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
            className="rounded-lg border border-border bg-surface px-2.5 py-1.5 text-sm font-medium text-on-surface outline-none focus:border-primary"
          >
            <option value="active">Active first</option>
            <option value="updated">Recently updated</option>
            <option value="company">Company A–Z</option>
          </select>
        </label>
      </div>

      <div className="flex flex-wrap gap-2">
        <Chip active={filter === "all"} onClick={() => setFilter("all")} label="All" count={rows.length} color="#64748b" />
        {presentBuckets.map((b) => (
          <Chip
            key={b.key}
            active={filter === b.key}
            onClick={() => setFilter(b.key)}
            label={b.label}
            count={counts.get(b.key) ?? 0}
            color={bucketColor(b.key)}
          />
        ))}
      </div>

      <div className="space-y-2.5">
        {sorted.map((r) => (
          <AppRow key={r.job_id} row={r} onRemove={onRemove} onChanged={onChanged} />
        ))}
        {sorted.length === 0 && (
          <p className="text-sm text-on-surface-variant">No applications in this stage.</p>
        )}
      </div>
    </section>
  );
}

function Chip({
  active,
  onClick,
  label,
  count,
  color,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
  color: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm font-medium transition-colors ${
        active
          ? "border-primary bg-primary-tint text-primary"
          : "border-border bg-surface text-on-surface-variant hover:border-primary/40"
      }`}
    >
      <span className="h-2 w-2 rounded-full" style={{ background: color }} />
      {label}
      <span className="tabular-nums text-on-surface-faint">{count}</span>
    </button>
  );
}

function AppRow({
  row,
  onRemove,
  onChanged,
}: {
  row: Row;
  onRemove: (jobId: string) => void;
  onChanged: () => void;
}) {
  const router = useRouter();
  const go = () => router.push(`/job?id=${row.job_id}`);

  return (
    <div
      role="link"
      tabIndex={0}
      onClick={go}
      onKeyDown={(e) => e.key === "Enter" && go()}
      className="group flex cursor-pointer flex-col gap-3 rounded-card border border-border bg-surface p-4 shadow-card transition-all hover:border-primary hover:shadow-pop md:flex-row md:items-center md:justify-between"
    >
      <div className="flex min-w-0 items-center gap-3">
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-lg bg-primary-tint text-primary">
          <Icon name="building" size={20} />
        </span>
        <div className="min-w-0">
          <h3 className="truncate font-semibold text-on-surface group-hover:text-primary">
            {row.title || row.job_id}
          </h3>
          <p className="truncate text-sm text-on-surface-variant">{row.company_name || "—"}</p>
        </div>
      </div>

      <div className="flex items-center justify-between gap-4 md:justify-end">
        <StatusSelect key={row.status} jobId={row.job_id} value={row.status} onChanged={onChanged} />
        <span className="whitespace-nowrap text-sm text-on-surface-faint">{updatedAgo(row.updated_at)}</span>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onRemove(row.job_id);
          }}
          title="Remove from tracker"
          aria-label="Remove from tracker"
          className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-on-surface-faint opacity-0 transition-opacity hover:bg-surface-sunken hover:text-[color:var(--color-accent-red)] focus-visible:opacity-100 group-hover:opacity-100"
        >
          ✕
        </button>
      </div>
    </div>
  );
}

function updatedAgo(iso: string | null): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return "—";
  const days = Math.floor(ms / 86_400_000);
  if (days <= 0) return "Updated today";
  if (days === 1) return "Updated 1d ago";
  return `Updated ${days}d ago`;
}
