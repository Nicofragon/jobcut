"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import {
  addEvent,
  getEvents,
  getJob,
  patchApplication,
  setStatus,
  type ApplicationFields,
  type AppEvent,
  type JobDetail,
} from "@/lib/api";
import ScoreRing from "@/components/ScoreRing";
import StatusSelect from "@/components/StatusSelect";
import { Icon } from "@/components/icons";
import { ErrorNote, Loading } from "@/components/States";
import { CATEGORY_COLOR, offerLink, scorerLabel } from "@/lib/ui";

export default function JobPage() {
  return (
    <Suspense fallback={<Loading />}>
      <JobDetailView />
    </Suspense>
  );
}

// Application tracker steps. `status` is the backend status set when the step is
// clicked; "Saved" is the baseline (no application yet).
const STEPS = [
  { label: "Saved", status: null as string | null, icon: "check" as const },
  { label: "Applied", status: "applied", icon: "send" as const },
  { label: "Screening", status: "screen", icon: "user" as const },
  { label: "Interview", status: "interview", icon: "users" as const },
  { label: "Offer", status: "offer", icon: "check-circle" as const },
];

function stepIndex(status: string | null | undefined): number {
  switch (status) {
    case "offer": return 4;
    case "interview": return 3;
    case "screen": return 2;
    case "applied": case "rejected": case "withdrawn": case "no_response": return 1;
    default: return 0;
  }
}

// Terminal outcomes don't sit on the linear path — they get an explicit chip
// (mapped to the same CATEGORY_COLOR the funnel uses), not a fake "Applied".
const TERMINAL: Record<string, string> = {
  rejected: "Rejected",
  withdrawn: "Withdrawn",
  no_response: "No response",
};

function fmtDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function fmtWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

const STATUS_LABEL: Record<string, string> = {
  applied: "Applied",
  screen: "Screening",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
  no_response: "No response",
};

// Timeline dot color per event kind.
const EVENT_DOT: Record<string, string> = {
  note: "#16a34a",
  status_change: "#64748b",
  interview: "#2563eb",
  next_action: "#d97706",
};

function eventLabel(e: AppEvent): string {
  if (e.kind === "status_change") {
    const to = STATUS_LABEL[e.to_status ?? ""] ?? e.to_status ?? "";
    return e.from_status ? `Moved to ${to}` : `Started tracking — ${to}`;
  }
  return e.body || e.kind;
}

function salaryText(job: Record<string, string | null>): string | null {
  if (job.salary_text) return job.salary_text;
  const parts = [job.salary_min, job.salary_max].filter(Boolean);
  return parts.length ? parts.join(" – ") : null;
}

function JobDetailView() {
  const id = useSearchParams().get("id") ?? "";
  const [data, setData] = useState<JobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<AppEvent[]>([]);
  const [draft, setDraft] = useState("");
  const [status, setLocalStatus] = useState<string | null>(null); // optimistic

  const load = useCallback(() => {
    if (!id) return;
    Promise.all([getJob(id), getEvents(id)])
      .then(([d, ev]) => {
        setData(d);
        setLocalStatus(d.application?.status ?? null);
        setEvents(ev);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "failed to load"));
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  if (!id) return <p className="text-sm text-on-surface-faint">No job selected.</p>;
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!data) return <Loading label="Loading this role…" />;

  const { job, score } = data;
  const appOnly = job === null; // imported/manual row with no jobs data
  const link = job
    ? offerLink({ linkedin_url: job.linkedin_url, apply_url: job.apply_url, easy_apply_url: job.easy_apply_url })
    : null;
  const reasons = (score?.match_reasons ?? "").split(",").map((r) => r.trim()).filter(Boolean);
  const sal = job ? salaryText(job) : null;
  const description = job?.description ?? null;
  const wp = job?.workplace_type
    ? job.workplace_type.replace(/_/g, "-").replace(/\b\w/g, (c) => c.toUpperCase())
    : null;
  const current = stepIndex(status);
  const terminal = status ? TERMINAL[status] ?? null : null;
  const terminalColor = terminal ? CATEGORY_COLOR[terminal] : null;
  const accent = terminal && terminalColor ? terminalColor : "var(--color-primary)";

  async function setStep(next: string) {
    setLocalStatus(next); // optimistic
    await setStatus(id, next); // status-only write-path; also records a status_change event
    load();
  }

  async function addNote() {
    const body = draft.trim();
    if (!body) return;
    // Solo-note write-path: appends to the timeline, never fabricates an 'applied' row.
    await addEvent(id, { kind: "note", body });
    setDraft("");
    load();
  }

  async function patchField(key: keyof ApplicationFields, value: string) {
    await patchApplication(id, { [key]: value }); // structured fields; never touches status
  }

  return (
    <div className="space-y-8">
      <Link
        href="/"
        className="inline-flex items-center gap-2 text-sm font-medium text-primary transition-colors hover:text-primary-hover"
      >
        <Icon name="arrow-left" size={18} /> Back to shortlist
      </Link>

      {/* hero */}
      <div className="flex flex-col items-start justify-between gap-6 rounded-card border border-border/40 bg-surface p-6 shadow-card md:flex-row">
        <div className="flex flex-col gap-4">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight text-on-surface md:text-4xl">
              {job?.title ?? "Role added manually"}
            </h1>
            {job?.company_name ? (
              <p className="mt-1 flex items-center gap-2 text-xl text-on-surface-variant">
                <Icon name="building" size={20} /> {job.company_name}
              </p>
            ) : (
              appOnly && (
                <p className="mt-1 text-sm text-on-surface-faint">
                  In your tracker but not in the market dataset — no scoring or company data.
                </p>
              )
            )}
          </div>
          {!appOnly && (
            <div className="flex flex-wrap gap-2">
              {job?.location && <Chip icon="map-pin">{job.location}</Chip>}
              {wp && <Chip icon="briefcase" tone="primary">{wp}</Chip>}
              {sal && <Chip icon="banknote">{sal}</Chip>}
            </div>
          )}
        </div>
        <div className="flex flex-col items-center gap-1.5">
          {appOnly ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-sunken px-3 py-1.5 text-xs font-medium text-on-surface-variant">
              <Icon name="building" size={12} /> No market data
            </span>
          ) : (
            <>
              <ScoreRing score={score?.match_score ?? null} size={96} label />
              {scorerLabel(score?.backend) && (
                <span className="inline-flex items-center gap-1 rounded-full bg-surface-sunken px-2.5 py-1 text-xs font-medium text-on-surface-variant">
                  <Icon name="sparkles" size={12} /> Scored {fmtDate(score?.scored_date) ?? "—"} by{" "}
                  {scorerLabel(score?.backend)}
                </span>
              )}
            </>
          )}
          {data.application?.updated_at && (
            <span className="text-xs text-on-surface-faint">
              Updated {fmtDate(data.application.updated_at)}
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
        {/* left: description + tracker */}
        <div className="space-y-8 lg:col-span-2">
          {description ? (
            <Panel title="Description">
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-on-surface-variant">
                {description}
              </p>
            </Panel>
          ) : (
            // Imported tracker rows carry no description (the spreadsheet never had one).
            // Show an honest empty-state instead of silently dropping the panel.
            (appOnly || data.application) && (
              <Panel title="Description">
                <p className="text-sm leading-relaxed text-on-surface-variant">
                  No description on file — this role came from your tracker.
                  {link ? " Open the posting to read it." : " No posting link saved either."}
                </p>
                {link && (
                  <a
                    href={link}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-3 inline-flex items-center gap-2 rounded-lg border border-border px-3 py-1.5 text-sm font-semibold text-on-surface transition-colors hover:border-primary hover:text-primary"
                  >
                    <Icon name="external" size={16} /> Open posting
                  </a>
                )}
              </Panel>
            )
          )}

          <Panel title="Application tracker">
            {terminal && terminalColor && (
              <div
                className="mb-5 inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-semibold"
                style={{
                  color: terminalColor,
                  background: `${terminalColor}1f`,
                  border: `1px solid ${terminalColor}40`,
                }}
              >
                Closed · {terminal}
              </div>
            )}
            <div className="relative mb-8 flex items-center justify-between">
              <div className="absolute left-0 top-4 -z-10 h-1 w-full bg-surface-sunken" />
              <div
                className="absolute left-0 top-4 -z-10 h-1 transition-all"
                style={{ width: `${(Math.max(current, 0) / (STEPS.length - 1)) * 100}%`, background: accent }}
              />
              {STEPS.map((s, i) => {
                const done = i <= current;
                const isCurrent = i === current && !terminal;
                const clickable = s.status != null;
                return (
                  <div key={s.label} className="flex flex-col items-center gap-2">
                    <button
                      disabled={!clickable}
                      onClick={() => clickable && s.status && setStep(s.status)}
                      title={clickable ? `Mark as ${s.label}` : "Saved"}
                      style={done ? { background: accent, color: "var(--color-on-primary)" } : undefined}
                      className={`flex h-8 w-8 items-center justify-center rounded-full transition-colors ${
                        done ? "" : "bg-surface-sunken text-on-surface-variant"
                      } ${isCurrent ? "ring-4 ring-primary/20" : ""} ${
                        clickable ? "cursor-pointer hover:opacity-90" : "cursor-default"
                      }`}
                    >
                      <Icon name={s.icon} size={16} />
                    </button>
                    <span className={`text-xs font-semibold ${done ? "text-on-surface" : "text-on-surface-variant"}`}>
                      {s.label}
                    </span>
                  </div>
                );
              })}
            </div>

            <div className="flex flex-col items-stretch justify-end gap-3 sm:flex-row sm:items-center">
              <StatusSelect key={status ?? "none"} jobId={id} value={status} onChanged={load} />
              {link && (
                <a
                  href={link}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center justify-center gap-2 rounded-lg bg-surface-sunken px-4 py-2 text-sm font-medium text-on-surface transition-colors hover:border-primary/40"
                >
                  <Icon name="external" size={18} /> Open posting
                </a>
              )}
            </div>
          </Panel>

          <Panel title="Notes & activity">
            <div className="space-y-3">
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") addNote();
                }}
                placeholder="Add a note — recruiter call, interview prep, a reminder…"
                rows={3}
                className="w-full rounded-lg border border-border bg-bg p-4 text-sm text-on-surface outline-none transition-colors placeholder:text-on-surface-faint focus:border-primary focus:ring-1 focus:ring-primary"
              />
              <div className="flex items-center justify-between">
                <span className="text-xs text-on-surface-faint">⌘/Ctrl + Enter to add</span>
                <button
                  onClick={addNote}
                  disabled={!draft.trim()}
                  className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-on-primary shadow-sm transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-primary"
                >
                  <Icon name="check" size={18} /> Add note
                </button>
              </div>
            </div>
            <div className="mt-5 border-t border-border pt-4">
              {events.length === 0 ? (
                <p className="text-sm text-on-surface-faint">
                  No activity yet — your notes and status changes appear here, newest first.
                </p>
              ) : (
                <ul className="space-y-4">
                  {events.map((e) => (
                    <TimelineRow key={e.event_id} e={e} />
                  ))}
                </ul>
              )}
            </div>
          </Panel>
        </div>

        {/* right: tracking details + why it matches + company */}
        <div className="space-y-8">
          {data.application && (
            <Panel title="Tracking details">
              <div className="space-y-4">
                <FieldRow label="Priority">
                  <select
                    defaultValue={data.application.priority ?? ""}
                    onChange={(e) => patchField("priority", e.target.value)}
                    className={FIELD_CLS}
                  >
                    <option value="">—</option>
                    <option value="high">High</option>
                    <option value="normal">Normal</option>
                    <option value="low">Low</option>
                  </select>
                </FieldRow>
                <FieldRow label="Next action">
                  <input
                    defaultValue={data.application.next_action ?? ""}
                    onBlur={(e) => patchField("next_action", e.target.value)}
                    placeholder="e.g. send portfolio"
                    className={FIELD_CLS}
                  />
                </FieldRow>
                <FieldRow label="Due date">
                  <input
                    type="date"
                    defaultValue={data.application.next_action_date ?? ""}
                    onChange={(e) => patchField("next_action_date", e.target.value)}
                    className={FIELD_CLS}
                  />
                </FieldRow>
                <FieldRow label="Contact">
                  <input
                    defaultValue={data.application.contact ?? ""}
                    onBlur={(e) => patchField("contact", e.target.value)}
                    placeholder="recruiter / hiring manager"
                    className={FIELD_CLS}
                  />
                </FieldRow>
                <FieldRow label="CV version">
                  <input
                    defaultValue={data.application.cv_version ?? ""}
                    onBlur={(e) => patchField("cv_version", e.target.value)}
                    placeholder="which CV you sent"
                    className={FIELD_CLS}
                  />
                </FieldRow>
              </div>
            </Panel>
          )}

          {!appOnly && reasons.length > 0 && (
            <div className="rounded-card border border-border/60 bg-surface-alt p-6">
              <h3 className="mb-4 text-lg font-semibold text-on-surface">Why this matches you</h3>
              <ul className="space-y-3">
                {reasons.map((r, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-on-surface-variant">
                    <span className="mt-0.5 shrink-0 text-primary">
                      <Icon name="check-circle" size={18} />
                    </span>
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {!appOnly && job && (
            <Panel title="Company details">
              <div className="grid grid-cols-2 gap-3">
                <Fact icon="building" label="Size" value={job.company_size} />
                <Fact icon="users" label="Applicants" value={job.applicants} />
                <Fact icon="calendar" label="Posted" value={job.posted_date} />
                <Fact icon="user" label="Recruiter" value={job.recruiter_name} />
              </div>
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}

function Chip({
  icon,
  tone = "default",
  children,
}: {
  icon: "map-pin" | "briefcase" | "banknote";
  tone?: "default" | "primary";
  children: React.ReactNode;
}) {
  const cls =
    tone === "primary"
      ? "bg-primary-tint text-primary-strong"
      : "bg-surface-sunken text-on-surface-variant";
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-sm font-medium ${cls}`}>
      <Icon name={icon} size={16} /> {children}
    </span>
  );
}

const FIELD_CLS =
  "w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-on-surface outline-none transition-colors placeholder:text-on-surface-faint focus:border-primary focus:ring-1 focus:ring-primary";

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold text-on-surface-variant">{label}</span>
      {children}
    </label>
  );
}

function TimelineRow({ e }: { e: AppEvent }) {
  const dot = EVENT_DOT[e.kind] ?? "#64748b";
  const isNote = e.kind === "note";
  return (
    <li className="flex gap-3">
      <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full" style={{ background: dot }} />
      <div className="min-w-0 flex-1">
        <p
          className={`text-sm ${
            isNote ? "whitespace-pre-wrap text-on-surface" : "font-medium text-on-surface-variant"
          }`}
        >
          {eventLabel(e)}
        </p>
        <p className="mt-0.5 text-xs text-on-surface-faint">{fmtWhen(e.ts)}</p>
      </div>
    </li>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-card border border-border/40 bg-surface p-6 shadow-card">
      <h2 className="mb-4 text-xl font-semibold text-on-surface">{title}</h2>
      {children}
    </section>
  );
}

function Fact({
  icon,
  label,
  value,
}: {
  icon: "building" | "users" | "calendar" | "user";
  label: string;
  value: string | null;
}) {
  return (
    <div className="flex flex-col gap-1 rounded-lg bg-surface-alt p-3">
      <span className="text-on-surface-faint">
        <Icon name={icon} size={18} />
      </span>
      <span className="text-xs font-semibold text-on-surface-variant">{label}</span>
      <span className="text-sm font-medium text-on-surface">{value || "—"}</span>
    </div>
  );
}
