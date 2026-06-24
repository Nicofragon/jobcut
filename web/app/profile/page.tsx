"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  deriveProfile,
  getConfig,
  getDerived,
  getProfile,
  getProfileStructured,
  putConfig,
  putProfile,
  putProfileStructured,
  type Derived,
  type ProfileFields,
} from "@/lib/api";
import TagInput from "@/components/TagInput";
import WorkTypeToggle from "@/components/WorkTypeToggle";

const WEIGHTS = ["title", "stack", "location", "signals", "employer", "reachable", "dealbreaker"];
const EMPTY: ProfileFields = {
  target_roles: [],
  locations: [],
  work_types: [],
  seniority: null,
  must_haves: [],
  dealbreakers: [],
  skills: [],
};

export default function ProfilePage() {
  const [fields, setFields] = useState<ProfileFields>(EMPTY);
  const [savedProfile, setSavedProfile] = useState(false);
  const [derived, setDerived] = useState<Derived | null>(null);
  const [report, setReport] = useState<string | null>(null);
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [savedWeights, setSavedWeights] = useState(false);

  useEffect(() => {
    getProfileStructured().then(setFields).catch(() => {});
    getDerived().then(setDerived).catch(() => {});
    getConfig().then((c) =>
      setWeights((c as { scoring?: { weights?: Record<string, number> } }).scoring?.weights ?? {}),
    );
  }, []);

  const set = <K extends keyof ProfileFields>(k: K, v: ProfileFields[K]) => setFields({ ...fields, [k]: v });

  async function saveProfile() {
    await putProfileStructured(fields);
    setSavedProfile(true);
    setTimeout(() => setSavedProfile(false), 2000);
    getDerived().then(setDerived).catch(() => {});
  }
  async function generate() {
    const r = await deriveProfile(false);
    setReport(`Wrote ${r.written.length}, kept ${r.skipped.length} existing.`);
    getDerived().then(setDerived).catch(() => {});
  }
  async function saveWeights() {
    await putConfig({ scoring: { weights } });
    setSavedWeights(true);
    setTimeout(() => setSavedWeights(false), 2000);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-on-surface">Your profile</h1>
          <p className="mt-1 text-on-surface-variant">This is what every job gets matched against.</p>
        </div>
        <Link href="/settings" className="text-sm font-medium text-primary hover:underline">
          Settings →
        </Link>
      </div>

      <Card title="What you're after">
        <div className="space-y-4">
          <Field label="Target roles" hint="We filter out listings that don't match these.">
            <TagInput values={fields.target_roles} onChange={(v) => set("target_roles", v)} placeholder="Type a role and press Enter…" />
          </Field>
          <Field label="Preferred locations">
            <TagInput values={fields.locations} onChange={(v) => set("locations", v)} placeholder="e.g. Madrid, Spain — press Enter…" />
          </Field>
          <Field label="Work type">
            <WorkTypeToggle values={fields.work_types} onChange={(v) => set("work_types", v)} />
          </Field>
          <Field label="Seniority" hint="Optional.">
            <input
              value={fields.seniority ?? ""}
              onChange={(e) => set("seniority", e.target.value || null)}
              placeholder="e.g. senior / ~8 years"
              className={inputCls}
            />
          </Field>
          <Field label="Must-have skills" hint="Things you bring — they boost matching jobs.">
            <TagInput values={fields.skills} onChange={(v) => set("skills", v)} placeholder="e.g. SQL, Python…" />
          </Field>
          <Field label="Nice-to-haves" hint="Bonus signals that nudge a score up.">
            <TagInput values={fields.must_haves} onChange={(v) => set("must_haves", v)} placeholder="e.g. dbt, BigQuery…" />
          </Field>
          <Field label="Dealbreakers" hint="Hard no's — jobs requiring these get penalized.">
            <TagInput values={fields.dealbreakers} onChange={(v) => set("dealbreakers", v)} placeholder="e.g. security clearance…" />
          </Field>
          <button onClick={saveProfile} className={btnPrimary}>
            {savedProfile ? "Saved ✓" : "Save profile"}
          </button>
        </div>
      </Card>

      <Card title="Searches & rubric">
        <p className="mb-3 text-sm text-on-surface-variant">
          Your saved searches and scoring rubric are generated from this profile (non-destructive — existing files are kept).
        </p>
        {derived && (
          <div className="mb-3 space-y-1 text-sm text-on-surface-variant">
            <p>Searches: <b className="text-on-surface">{Object.keys(derived.searches).join(", ") || "—"}</b></p>
            <p>Skills tracked: <b className="text-on-surface">{Object.keys(derived.taxonomy.skills ?? {}).length}</b></p>
          </div>
        )}
        <button onClick={generate} className={btnGhost}>
          Regenerate searches &amp; rubric
        </button>
        {report && <span className="ml-2 text-xs text-primary">{report}</span>}
      </Card>

      <Card title="Scoring weights" subtitle="How much each signal counts toward a match score.">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {WEIGHTS.map((k) => (
            <label key={k} className="space-y-1">
              <span className="text-xs text-on-surface-variant">{k}</span>
              <input
                type="number"
                value={weights[k] ?? 0}
                onChange={(e) => setWeights((w) => ({ ...w, [k]: Number(e.target.value) }))}
                className={inputCls}
              />
            </label>
          ))}
        </div>
        <button onClick={saveWeights} className={`${btnGhost} mt-3`}>
          {savedWeights ? "Saved ✓" : "Save weights"}
        </button>
      </Card>

      <RawAdvanced />
    </div>
  );
}

function RawAdvanced() {
  const [content, setContent] = useState("");
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (open && !content) getProfile().then((p) => setContent(p.content)).catch(() => {});
  }, [open, content]);

  async function save() {
    await putProfile(content);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  return (
    <details className="rounded-card border border-border bg-surface p-5 shadow-card" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary className="cursor-pointer text-sm font-medium text-on-surface-faint hover:text-on-surface-variant">
        Advanced: edit raw profile.md (power users)
      </summary>
      <p className="mt-2 text-xs text-on-surface-variant">
        The structured form above round-trips with these headings. Edit here only if you need full control.
      </p>
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        rows={16}
        className="mt-2 w-full rounded-lg border border-border bg-surface-alt px-3 py-2 font-mono text-xs text-on-surface outline-none focus:border-primary"
      />
      <button onClick={save} className={`${btnGhost} mt-2`}>
        {saved ? "Saved ✓" : "Save raw"}
      </button>
    </details>
  );
}

const inputCls =
  "w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-on-surface outline-none transition-colors focus:border-primary placeholder:text-on-surface-faint";
const btnPrimary =
  "rounded-lg bg-primary px-4 py-2 text-sm font-medium text-on-primary shadow-card transition-colors hover:bg-primary-hover";
const btnGhost =
  "rounded-lg border border-border bg-surface px-3 py-1.5 text-sm font-medium text-on-surface transition-colors hover:bg-surface-alt";

function Card({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-card border border-border bg-surface p-5 shadow-card">
      <h2 className="text-lg font-semibold text-on-surface">{title}</h2>
      {subtitle && <p className="mb-3 mt-0.5 text-sm text-on-surface-variant">{subtitle}</p>}
      <div className={subtitle ? "" : "mt-4"}>{children}</div>
    </section>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="block text-sm font-medium text-on-surface">{label}</label>
      {children}
      {hint && <p className="text-xs text-on-surface-variant">{hint}</p>}
    </div>
  );
}
