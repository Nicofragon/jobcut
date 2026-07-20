"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  exportData,
  getConfig,
  getHealth,
  getKit,
  getSchedule,
  getScoringBackends,
  getUpdateStatus,
  putConfig,
  putCredentials,
  putSchedule,
  updateApp,
  validateCredentials,
  type Health,
  type Schedule,
  type ScoringBackend,
  type SkillsKit,
  type UpdateResult,
  type Validation,
} from "@/lib/api";
import { Icon } from "@/components/icons";
import { ThemeSegmented } from "@/components/ThemeToggle";

export default function SettingsPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [apify, setApify] = useState("");
  const [llm, setLlm] = useState("");
  const [validation, setValidation] = useState<Validation | null>(null);
  const [backends, setBackends] = useState<ScoringBackend[]>([]);
  const [backend, setBackend] = useState("rule_based");
  const [kit, setKit] = useState<SkillsKit | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => {});
    getConfig().then((c) => setBackend((c as { scoring?: { backend?: string } }).scoring?.backend ?? "rule_based"));
    getScoringBackends().then(setBackends).catch(() => {});
    getKit().then(setKit).catch(() => {});
  }, []);

  function flash(m: string) {
    setMsg(m);
    setTimeout(() => setMsg(null), 2500);
  }

  async function pickBackend(id: string) {
    setBackend(id);
    await putConfig({ scoring: { backend: id } });
    flash("Scoring updated");
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-on-surface">Settings</h1>
          <p className="mt-1 text-on-surface-variant">Connections, scoring, and your data.</p>
        </div>
        <Link href="/profile" className="text-sm font-medium text-primary hover:underline">
          Edit profile →
        </Link>
      </div>

      <Card title="Your profile & skills kit" subtitle="The kit is what every job is scored against and what Discovery reports on.">
        {kit && kit.skills.length > 0 ? (
          <div className="flex flex-wrap items-center gap-4">
            {(
              [
                ["have", "var(--color-score-high)"],
                ["partial", "var(--color-accent-amber)"],
                ["gap", "var(--color-accent-red)"],
              ] as const
            ).map(([s, color]) => (
              <span key={s} className="inline-flex items-center gap-2 text-sm text-on-surface">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} />
                <b className="tabular-nums">{kit.counts[s]}</b>
                <span className="text-on-surface-variant">{s}</span>
              </span>
            ))}
            <Link href="/profile" className="ml-auto text-sm font-medium text-primary hover:underline">
              View &amp; edit →
            </Link>
          </div>
        ) : (
          <p className="text-sm text-on-surface-variant">
            No skills kit yet.{" "}
            <Link href="/profile" className="font-medium text-primary hover:underline">
              Build your profile →
            </Link>
          </p>
        )}
      </Card>

      <Card title="Appearance" subtitle="Choose how the console looks. Your choice is remembered on this computer.">
        <ThemeSegmented />
      </Card>

      <Card title="How jobs are scored" subtitle="Pick how each job gets matched to your profile. You can change this anytime.">
        <div className="grid gap-3 sm:grid-cols-2">
          {[...backends]
            .sort((a, b) => a.order - b.order)
            .map((b) => {
              const selected = backend === b.id;
              return (
                <button
                  key={b.id}
                  type="button"
                  onClick={() => pickBackend(b.id)}
                  className={`relative rounded-card border p-4 text-left transition-all ${
                    selected ? "border-primary bg-primary-tint shadow-card" : "border-border bg-surface hover:border-primary/50"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold text-on-surface">{b.label}</span>
                    {b.recommended && (
                      <span className="rounded-full bg-primary px-2 py-0.5 text-xs font-semibold text-on-primary">Recommended</span>
                    )}
                  </div>
                  <p className="mt-1 text-sm text-on-surface-variant">{b.description}</p>
                  {b.note && <p className="mt-2 text-xs text-on-surface-faint">{b.note}</p>}
                </button>
              );
            })}
          {backends.length === 0 && <p className="text-sm text-on-surface-variant">Loading options…</p>}
        </div>
      </Card>

      <Card title="Connections" subtitle="Your job source (Apify) and an optional LLM key for smarter scoring.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={`Apify token${health?.apify_token_set ? " · connected" : ""}`}>
            <input value={apify} onChange={(e) => setApify(e.target.value)} placeholder="apify_api_…" className={inputCls} />
          </Field>
          <Field label={`LLM key${health?.llm_key_set ? " · set" : " · optional"}`}>
            <input value={llm} onChange={(e) => setLlm(e.target.value)} placeholder="sk-… / anthropic key" className={inputCls} />
          </Field>
        </div>
        <div className="mt-3 flex items-center gap-2">
          <button
            onClick={async () => setValidation(await validateCredentials({ apify_token: apify, llm_key: llm || undefined }))}
            disabled={!apify}
            className={btnGhost}
          >
            Check connection
          </button>
          <button
            onClick={async () => {
              await putCredentials({ apify_token: apify || undefined, llm_key: llm || undefined });
              setHealth(await getHealth());
              flash("Saved");
            }}
            className={btnPrimary}
          >
            Save
          </button>
          {validation && (
            <span className="inline-flex items-center gap-1.5 text-sm">
              <span style={{ color: validation.apify.valid ? "var(--color-primary)" : "var(--color-accent-red)" }}>
                <Icon name={validation.apify.valid ? "check-circle" : "x"} size={16} />
              </span>
              {validation.apify.valid ? "Connected" : "Couldn't connect"}
            </span>
          )}
        </div>
      </Card>

      <Automation />

      <Card title="Your data" subtitle="Everything lives on your computer.">
        <p className="text-sm text-on-surface-variant">
          {health ? `${health.jobs} jobs · ${health.applications} applications tracked` : "—"}
        </p>
        <button
          onClick={async () => {
            const r = await exportData();
            flash(`Exported to ${r.out_dir}`);
          }}
          className={`${btnGhost} mt-3`}
        >
          Export to CSV / JSON
        </button>
      </Card>

      <UpdateCard />

      <details className="rounded-card border border-border bg-surface p-5 shadow-card">
        <summary className="cursor-pointer text-sm font-medium text-on-surface-faint hover:text-on-surface-variant">
          Diagnostics
        </summary>
        <dl className="mt-3 grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-xs text-on-surface-faint">Data directory</dt>
            <dd className="break-all font-mono text-xs text-on-surface-variant">{health?.data_dir ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs text-on-surface-faint">Database schema</dt>
            <dd className="font-mono text-xs text-on-surface-variant">v{health?.schema_version ?? "—"}</dd>
          </div>
        </dl>
      </details>

      {msg && (
        <p className="inline-flex items-center gap-1.5 text-sm text-primary">
          <Icon name="check" size={16} /> {msg}
        </p>
      )}
    </div>
  );
}

const inputCls =
  "w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-on-surface outline-none transition-colors focus:border-primary placeholder:text-on-surface-faint";
const btnPrimary =
  "rounded-lg bg-primary px-4 py-1.5 text-sm font-medium text-on-primary shadow-card transition-colors hover:bg-primary-hover disabled:opacity-50";
const btnGhost =
  "rounded-lg border border-border bg-surface px-3 py-1.5 text-sm font-medium text-on-surface transition-colors hover:bg-surface-alt disabled:opacity-50";

function UpdateCard() {
  const [status, setStatus] = useState<UpdateResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<UpdateResult | null>(null);

  useEffect(() => {
    getUpdateStatus().then(setStatus).catch(() => {});
  }, []);

  async function run() {
    setBusy(true);
    setResult(null);
    try {
      const r = await updateApp();
      setResult(r);
      getUpdateStatus().then(setStatus).catch(() => {});
    } catch (e) {
      setResult({
        ok: false,
        step: "error",
        blocked: false,
        message: e instanceof Error ? e.message : "Update failed — is `jobcut serve` running?",
      });
    } finally {
      setBusy(false);
    }
  }

  const notGit = status != null && status.is_git === false;
  const subtitle = status?.is_git
    ? `On ${status.branch ?? "?"} · ${status.sha ?? "?"}${status.clean === false ? " · local changes" : ""}`
    : "Bring in the newest code and rebuild the console.";

  return (
    <Card title="Update jobcut" subtitle={subtitle}>
      {notGit ? (
        <p className="text-sm text-on-surface-variant">
          This install isn’t a git checkout, so there’s nothing to update from.
        </p>
      ) : (
        <>
          <p className="text-sm text-on-surface-variant">
            Pulls the latest code from the repo and rebuilds the console. Runs on this
            computer and is read-only on your data — it never scrapes, scores, or deletes.
          </p>
          <button onClick={run} disabled={busy} className={`${btnPrimary} mt-3`}>
            {busy ? "Updating…" : "Update from repo"}
          </button>
          {result && (
            <div
              className={`mt-3 rounded-lg border p-3 text-sm text-on-surface ${
                result.ok
                  ? "border-primary/30 bg-primary-tint"
                  : "border-accent-amber/40 bg-accent-amber/10"
              }`}
            >
              <p>{result.message}</p>
              {result.blocked && result.dirty_files && result.dirty_files.length > 0 && (
                <ul className="mt-2 list-inside list-disc font-mono text-xs text-on-surface-variant">
                  {result.dirty_files.slice(0, 12).map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                  {result.dirty_files.length > 12 && (
                    <li>+{result.dirty_files.length - 12} more</li>
                  )}
                </ul>
              )}
            </div>
          )}
        </>
      )}
    </Card>
  );
}

function Automation() {
  const [s, setS] = useState<Schedule | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    getSchedule().then(setS).catch(() => {});
  }, []);

  if (!s) {
    return (
      <Card title="Automation" subtitle="Run your job search on a schedule.">
        <p className="text-sm text-on-surface-variant">Loading…</p>
      </Card>
    );
  }

  const time = `${String(s.hour).padStart(2, "0")}:${String(s.minute).padStart(2, "0")}`;
  const upd = (patch: Partial<Schedule>) => setS({ ...s, ...patch });

  async function save(next: Schedule) {
    setBusy(true);
    setNote(null);
    try {
      const res = await putSchedule({
        enabled: next.enabled,
        frequency: next.frequency,
        interval_days: next.interval_days,
        hour: next.hour,
        minute: next.minute,
        claude_score: next.claude_score,
      });
      setS(res);
      setNote(res.installed ? "Schedule saved" : "Automation turned off");
    } catch (e) {
      setNote(e instanceof Error ? e.message : "Couldn't update the schedule");
    } finally {
      setBusy(false);
    }
  }

  if (!s.supported) {
    return (
      <Card title="Automation" subtitle="Run your job search on a schedule.">
        <p className="text-sm text-on-surface-variant">
          Installing a schedule from here isn&apos;t supported on {s.platform} yet. On Windows, use Task
          Scheduler to run <code className="rounded bg-surface-sunken px-1 font-mono text-xs">jobcut daily</code> each
          morning — see the <code className="font-mono text-xs">scheduler/</code> templates in the repo.
        </p>
      </Card>
    );
  }

  return (
    <Card title="Automation" subtitle="Let jobcut find and score new jobs on a schedule — no clicking.">
      <label className="flex items-center gap-3">
        <input
          type="checkbox"
          checked={s.enabled}
          onChange={(e) => {
            const next = { ...s, enabled: e.target.checked };
            setS(next);
            save(next);
          }}
          className="h-4 w-4 accent-[var(--color-primary)]"
        />
        <span className="text-sm font-medium text-on-surface">Daily automatic job search</span>
        {s.installed && (
          <span className="rounded-full bg-primary-tint px-2 py-0.5 text-xs font-semibold text-primary">On</span>
        )}
      </label>

      {s.enabled && (
        <>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Field label="How often">
              <select
                value={s.frequency}
                onChange={(e) => upd({ frequency: e.target.value as Schedule["frequency"] })}
                className={inputCls}
              >
                <option value="daily">Every day</option>
                <option value="weekdays">Weekdays (Mon–Fri)</option>
                <option value="every_n">Every N days</option>
              </select>
            </Field>
            {s.frequency === "every_n" && (
              <Field label="Every how many days">
                <input
                  type="number"
                  min={2}
                  max={30}
                  value={s.interval_days}
                  onChange={(e) => upd({ interval_days: Number(e.target.value) || 2 })}
                  className={inputCls}
                />
              </Field>
            )}
            <Field label="Time of day">
              <input
                type="time"
                value={time}
                onChange={(e) => {
                  const [h, m] = e.target.value.split(":").map(Number);
                  upd({ hour: h || 0, minute: m || 0 });
                }}
                className={inputCls}
              />
            </Field>
          </div>

          <label className="mt-4 flex items-start gap-3">
            <input
              type="checkbox"
              checked={s.claude_score}
              onChange={(e) => upd({ claude_score: e.target.checked })}
              className="mt-0.5 h-4 w-4 accent-[var(--color-primary)]"
            />
            <span className="text-sm">
              <span className="font-medium text-on-surface">Score new jobs with Claude</span>
              <span className="block text-xs text-on-surface-faint">
                After each run, a local headless Claude scores the new jobs against your profile (runs the
                jobcut-score skill). Requires the <code className="font-mono">claude</code> CLI installed and signed in
                on this machine.
              </span>
            </span>
          </label>

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button onClick={() => save(s)} disabled={busy} className={btnPrimary}>
              {busy ? "Saving…" : "Save schedule"}
            </button>
            <span className="text-xs text-on-surface-faint">
              Each run downloads new jobs (~$0.04–0.18 via Apify), scores them, and updates your shortlist.
            </span>
          </div>
        </>
      )}

      {s.installed && (
        <p className="mt-3 text-sm text-on-surface-variant">
          ✓ Scheduled:{" "}
          {s.frequency === "weekdays"
            ? "weekdays"
            : s.frequency === "every_n"
              ? `every ${s.interval_days} days`
              : "every day"}{" "}
          at {time}.
        </p>
      )}
      {note && <p className="mt-2 text-sm text-primary">{note}</p>}
    </Card>
  );
}

function Card({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-card border border-border bg-surface p-5 shadow-card">
      <h2 className="text-lg font-semibold text-on-surface">{title}</h2>
      {subtitle && <p className="mb-4 mt-0.5 text-sm text-on-surface-variant">{subtitle}</p>}
      {children}
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm font-medium text-on-surface">{label}</span>
      {children}
    </label>
  );
}
