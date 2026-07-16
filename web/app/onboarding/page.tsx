"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ApiError,
  createStructuredSearch,
  draftProfile,
  extractCv,
  getHealth,
  getProfileStructured,
  getScoringBackends,
  putConfig,
  putCredentials,
  putProfile,
  putProfileStructured,
  updateStructuredSearch,
  validateCredentials,
  type ProfileFields,
  type ScoringBackend,
  type StructuredSearch,
  type Validation,
} from "@/lib/api";
import { Icon } from "@/components/icons";
import TagInput from "@/components/TagInput";
import RunControls from "@/components/RunControls";
import { ErrorNote } from "@/components/States";

const STEPS = ["Connect", "Profile", "Searches", "Scoring", "First run"];
const WORK_TYPES = [
  { value: "remote", label: "Remote" },
  { value: "hybrid", label: "Hybrid" },
  { value: "office", label: "On-site" }, // actor enum is "office"; label stays user-friendly
];
const EMPTY_FIELDS: ProfileFields = {
  target_roles: [],
  locations: [],
  work_types: [],
  seniority: null,
  must_haves: [],
  dealbreakers: [],
  skills: [],
  gaps: [],
};

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Connect
  const [apify, setApify] = useState("");
  const [llm, setLlm] = useState("");
  const [validation, setValidation] = useState<Validation | null>(null);

  // Profile (B1)
  const [fields, setFields] = useState<ProfileFields>(EMPTY_FIELDS);
  const [cvBusy, setCvBusy] = useState("");

  // Searches (B2)
  const [search, setSearch] = useState({ name: "main", titles: [] as string[], locations: [] as string[], work_types: [] as string[], geo_ids: [] as string[] });
  const [searchResult, setSearchResult] = useState<StructuredSearch | null>(null);

  // Scoring (B3)
  const [backends, setBackends] = useState<ScoringBackend[]>([]);
  const [backend, setBackend] = useState("rule_based");

  useEffect(() => {
    getProfileStructured().then((f) => setFields(f)).catch(() => {});
    getScoringBackends()
      .then((b) => {
        setBackends(b);
        const rec = b.find((x) => x.recommended);
        if (rec) setBackend(rec.id);
      })
      .catch(() => {});
  }, []);

  async function leave() {
    // Namespace the "dismissed" flag by data dir so it only affects this install.
    try {
      const h = await getHealth();
      localStorage.setItem(`jp_onboarded:${h.data_dir}`, "1");
    } catch {
      localStorage.setItem("jp_onboarded", "1");
    }
    router.push("/");
  }

  async function saveStep(i: number) {
    if (i === 0) {
      if (apify || llm) await putCredentials({ apify_token: apify || undefined, llm_key: llm || undefined });
    } else if (i === 1) {
      await putProfileStructured(fields);
    } else if (i === 2) {
      const payload = { name: search.name || "main", titles: search.titles, locations: search.locations, work_types: search.work_types, geo_ids: search.geo_ids };
      let res: StructuredSearch;
      try {
        res = await createStructuredSearch(payload);
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) res = await updateStructuredSearch(payload.name, payload);
        else throw e;
      }
      setSearchResult(res);
    } else if (i === 3) {
      await putConfig({ scoring: { backend } });
    }
  }

  async function next() {
    setError(null);
    setBusy(true);
    try {
      await saveStep(step);
      setStep((s) => Math.min(STEPS.length - 1, s + 1));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong — your work isn't lost, try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <div className="overflow-hidden rounded-card border border-border bg-surface shadow-card">
        <div className="px-6 pt-8 pb-4 text-center">
          <h1 className="text-2xl font-semibold tracking-tight text-on-surface">Let&apos;s set up your job hunt</h1>
          <p className="mt-1 text-on-surface-variant">
            From zero to your first ranked shortlist — everything stays on your computer.
          </p>
        </div>

        <Stepper step={step} />

        <div className="space-y-6 bg-bg px-6 py-7 md:px-8">
          {step === 0 && (
            <Connect apify={apify} llm={llm} setApify={setApify} setLlm={setLlm} validation={validation} setValidation={setValidation} />
          )}
          {step === 1 && <Profile fields={fields} setFields={setFields} cvBusy={cvBusy} onCv={onCv} hasLlm={!!llm} />}
          {step === 2 && <Searches search={search} setSearch={setSearch} result={searchResult} />}
          {step === 3 && <Scoring backends={backends} backend={backend} setBackend={setBackend} />}
          {step === 4 && <FirstRun />}

          {error && <ErrorNote>{error}</ErrorNote>}
        </div>

        <div className="flex flex-wrap-reverse items-center justify-between gap-3 border-t border-border bg-surface px-6 py-4 md:flex-nowrap">
          <button
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            disabled={step === 0 || busy}
            className="rounded-lg px-4 py-2 text-sm font-medium text-on-surface-variant transition-colors hover:bg-surface-sunken disabled:opacity-40"
          >
            Back
          </button>
          <div className="flex w-full gap-2 md:w-auto md:justify-end">
            <button onClick={leave} className="flex-1 rounded-lg px-4 py-2 text-sm font-medium text-on-surface-variant transition-colors hover:bg-surface-sunken md:flex-none">
              Skip setup
            </button>
            {step < STEPS.length - 1 ? (
              <button
                onClick={next}
                disabled={busy}
                className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-primary px-5 py-2 text-sm font-medium text-on-primary shadow-card transition-colors hover:bg-primary-hover disabled:opacity-60 md:flex-none"
              >
                {busy ? "Saving…" : "Next step"}
                {!busy && <Icon name="arrow-right" size={16} />}
              </button>
            ) : (
              <button
                onClick={leave}
                className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-primary px-5 py-2 text-sm font-medium text-on-primary shadow-card transition-colors hover:bg-primary-hover md:flex-none"
              >
                Go to my shortlist
                <Icon name="arrow-right" size={16} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );

  async function onCv(file: File | undefined) {
    if (!file) return;
    setCvBusy("Reading your CV…");
    setError(null);
    try {
      const { text } = await extractCv(file);
      const { profile_md, source } = await draftProfile(text);
      if (source === "ai") {
        // Only the AI draft has structured content worth filling the form with.
        await putProfile(profile_md);
        setFields(await getProfileStructured());
      } else {
        // No LLM key: we read the CV but can't fill the fields. Don't overwrite the
        // profile silently — tell the user the truth and let them fill it in.
        setError("We read your CV, but filling the fields automatically needs an LLM key (add it in Connect). Fill them in below — it only takes a minute.");
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) {
        setError(e.message); // the backend's real reason (unsupported/corrupt file, missing support)
      } else {
        setError("Couldn't read your CV — make sure jobcut is running. You can fill the fields below by hand.");
      }
    } finally {
      setCvBusy("");
    }
  }
}

// --- stepper ----------------------------------------------------------------

function Stepper({ step }: { step: number }) {
  return (
    <div className="border-b border-border bg-surface px-6 py-4">
      <div className="relative mx-auto flex max-w-xl items-start justify-between">
        <div className="absolute left-0 top-4 -z-0 h-0.5 w-full bg-surface-sunken" />
        <div
          className="absolute left-0 top-4 -z-0 h-0.5 bg-primary transition-all duration-500"
          style={{ width: `${(step / (STEPS.length - 1)) * 100}%` }}
        />
        {STEPS.map((label, i) => {
          const done = i < step;
          const active = i === step;
          return (
            <div key={label} className="z-10 flex flex-col items-center gap-1.5">
              <div
                className={`grid h-8 w-8 place-items-center rounded-full text-xs font-semibold shadow-card ${
                  done
                    ? "bg-primary text-on-primary"
                    : active
                    ? "bg-primary-tint text-primary ring-4 ring-surface"
                    : "bg-surface-sunken text-on-surface-faint"
                }`}
              >
                {done ? <Icon name="check" size={16} /> : i + 1}
              </div>
              <span className={`text-xs ${active ? "font-bold text-primary" : "text-on-surface-variant"}`}>{label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// --- shared bits ------------------------------------------------------------

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium text-on-surface">{label}</label>
      {children}
      {hint && <p className="text-xs text-on-surface-variant">{hint}</p>}
    </div>
  );
}

function Reassure({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-center gap-2 rounded-lg border border-border bg-surface-alt p-2.5 text-on-surface-variant">
      <span className="text-primary">
        <Icon name="lock" size={16} />
      </span>
      <span className="text-xs font-medium">{children}</span>
    </div>
  );
}

const inputCls =
  "w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-on-surface outline-none transition-colors focus:border-primary placeholder:text-on-surface-faint";

function SegmentToggle({ values, onChange }: { values: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="inline-flex w-full gap-1 rounded-lg bg-surface-sunken p-1 md:w-auto">
      {WORK_TYPES.map((wt) => {
        const on = values.includes(wt.value);
        return (
          <button
            key={wt.value}
            type="button"
            onClick={() => onChange(on ? values.filter((v) => v !== wt.value) : [...values, wt.value])}
            className={`flex-1 rounded-md px-5 py-1.5 text-sm font-medium transition-all md:flex-none ${
              on ? "bg-surface text-on-surface shadow-card" : "text-on-surface-variant hover:bg-surface-alt"
            }`}
          >
            {wt.label}
          </button>
        );
      })}
    </div>
  );
}

// --- steps ------------------------------------------------------------------

function Connect({
  apify,
  llm,
  setApify,
  setLlm,
  validation,
  setValidation,
}: {
  apify: string;
  llm: string;
  setApify: (v: string) => void;
  setLlm: (v: string) => void;
  validation: Validation | null;
  setValidation: (v: Validation | null) => void;
}) {
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);
  async function check() {
    setChecking(true);
    setCheckError(null);
    try {
      setValidation(await validateCredentials({ apify_token: apify, llm_key: llm || undefined }));
    } catch {
      setValidation(null);
      setCheckError("Couldn't run the check — make sure jobcut is running, then try again.");
    } finally {
      setChecking(false);
    }
  }
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-on-surface">Connect your job source</h2>
        <p className="mt-1 text-sm text-on-surface-variant">
          jobcut pulls listings through Apify. Paste your token to connect — checking it is free and runs nothing.
        </p>
      </div>
      <Field label="Apify token" hint="Powers the daily job pull. Find it in your Apify account settings.">
        <input value={apify} onChange={(e) => setApify(e.target.value)} placeholder="apify_api_…" className={inputCls} />
      </Field>
      <Field label="LLM key (optional)" hint="Unlocks smarter scoring and auto-filling your profile from a CV. You can add it later.">
        <input value={llm} onChange={(e) => setLlm(e.target.value)} placeholder="sk-… / anthropic key" className={inputCls} />
      </Field>
      <div className="flex items-center gap-3">
        <button
          onClick={check}
          disabled={checking || !apify}
          className="rounded-lg border border-border bg-surface px-4 py-2 text-sm font-medium text-on-surface transition-colors hover:bg-surface-alt disabled:opacity-50"
        >
          {checking ? "Checking…" : "Check connection"}
        </button>
        {validation && (
          <span className="inline-flex items-center gap-1.5 text-sm">
            <span style={{ color: validation.apify.valid ? "var(--color-primary)" : "var(--color-accent-red)" }}>
              <Icon name={validation.apify.valid ? "check-circle" : "x"} size={16} />
            </span>
            {validation.apify.valid
              ? `Connected${validation.apify.username ? ` as ${validation.apify.username}` : ""}`
              : "Couldn't connect — check the token"}
          </span>
        )}
        {checkError && (
          <span className="inline-flex items-center gap-1.5 text-sm" style={{ color: "var(--color-accent-red)" }}>
            <Icon name="x" size={16} />
            {checkError}
          </span>
        )}
      </div>
      <Reassure>100% local — your data never leaves your computer.</Reassure>
    </div>
  );
}

function Profile({
  fields,
  setFields,
  cvBusy,
  onCv,
  hasLlm,
}: {
  fields: ProfileFields;
  setFields: (f: ProfileFields) => void;
  cvBusy: string;
  onCv: (f: File | undefined) => void;
  hasLlm: boolean;
}) {
  const set = <K extends keyof ProfileFields>(k: K, v: ProfileFields[K]) => setFields({ ...fields, [k]: v });
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-on-surface">Tell us what you&apos;re after</h2>
        <p className="mt-1 text-sm text-on-surface-variant">This is what we match every job against. Upload a CV to fill it fast, or add things by hand.</p>
      </div>

      <label className="group flex cursor-pointer flex-col items-center justify-center rounded-card border-2 border-dashed border-border bg-surface p-6 text-center transition-colors hover:border-primary">
        <input
          type="file"
          accept=".txt,.md,.pdf,.docx"
          className="hidden"
          onChange={(e) => onCv(e.target.files?.[0])}
        />
        <span className="mb-2 grid h-12 w-12 place-items-center rounded-full bg-primary-tint text-primary transition-transform group-hover:scale-110">
          <Icon name="upload" size={24} />
        </span>
        <span className="font-semibold text-on-surface">{cvBusy || "Upload your CV"}</span>
        <span className="mt-0.5 text-sm text-on-surface-variant">
          PDF, DOCX or TXT — {hasLlm ? "we'll auto-fill the fields below" : "add an LLM key in Connect to auto-fill; otherwise fill the fields by hand"}
        </span>
      </label>

      <Field label="Target roles" hint="We filter out listings that don't match these.">
        <TagInput values={fields.target_roles} onChange={(v) => set("target_roles", v)} placeholder="Type a role and press Enter…" />
      </Field>
      <Field label="Preferred locations">
        <TagInput values={fields.locations} onChange={(v) => set("locations", v)} placeholder="e.g. Madrid, Spain — press Enter…" />
      </Field>
      <Field label="Work type">
        <SegmentToggle values={fields.work_types} onChange={(v) => set("work_types", v)} />
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
        <TagInput values={fields.skills} onChange={(v) => set("skills", v)} placeholder="Skills you can do today…" />
      </Field>
      <Field label="Nice-to-haves" hint="Bonus signals that nudge a score up.">
        <TagInput values={fields.must_haves} onChange={(v) => set("must_haves", v)} placeholder="Skills you have some exposure to…" />
      </Field>
      <Field label="Dealbreakers" hint="Hard no's — jobs requiring these get penalized.">
        <TagInput values={fields.dealbreakers} onChange={(v) => set("dealbreakers", v)} placeholder="e.g. security clearance…" />
      </Field>

      <Reassure>100% local — and we never apply to anything for you.</Reassure>
    </div>
  );
}

function Searches({
  search,
  setSearch,
  result,
}: {
  search: { name: string; titles: string[]; locations: string[]; work_types: string[]; geo_ids: string[] };
  setSearch: (s: typeof search) => void;
  result: StructuredSearch | null;
}) {
  const [advanced, setAdvanced] = useState(false);
  const set = <K extends keyof typeof search>(k: K, v: (typeof search)[K]) => setSearch({ ...search, [k]: v });
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-on-surface">Set up your first search</h2>
        <p className="mt-1 text-sm text-on-surface-variant">
          Plain words — job titles and places. We translate them into what the job source needs; no codes to look up.
        </p>
      </div>
      <Field label="Search name" hint="Just a label for this search.">
        <input value={search.name} onChange={(e) => set("name", e.target.value)} placeholder="main" className={inputCls} />
      </Field>
      <Field label="Job titles">
        <TagInput values={search.titles} onChange={(v) => set("titles", v)} placeholder="e.g. your target job title — press Enter…" />
      </Field>
      <Field label="Locations">
        <TagInput values={search.locations} onChange={(v) => set("locations", v)} placeholder="e.g. European Economic Area — press Enter…" />
      </Field>
      <Field label="Work type">
        <SegmentToggle values={search.work_types} onChange={(v) => set("work_types", v)} />
      </Field>

      {result?.needs_geoid && (
        <div className="rounded-lg border border-[color:var(--color-accent-amber)]/40 bg-[color:var(--color-accent-amber)]/10 p-3 text-sm text-on-surface">
          <p className="font-medium">We couldn&apos;t match a location to the job source automatically.</p>
          <p className="mt-1 text-on-surface-variant">
            The search is saved — you can still continue. To target precisely, open a LinkedIn jobs search for your area and
            paste the <code>geoId</code> from the URL below.
          </p>
          <button onClick={() => setAdvanced(true)} className="mt-2 text-sm font-medium text-primary hover:underline">
            Add a geoId manually
          </button>
        </div>
      )}

      {(advanced || search.geo_ids.length > 0) && (
        <Field label="Advanced: geoIds" hint="Only if a location didn't resolve. Numeric LinkedIn geo IDs.">
          <TagInput values={search.geo_ids} onChange={(v) => set("geo_ids", v)} placeholder="e.g. 91000000 — press Enter…" />
        </Field>
      )}
    </div>
  );
}

function Scoring({
  backends,
  backend,
  setBackend,
}: {
  backends: ScoringBackend[];
  backend: string;
  setBackend: (id: string) => void;
}) {
  const sorted = [...backends].sort((a, b) => a.order - b.order);
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-on-surface">How should we score jobs?</h2>
        <p className="mt-1 text-sm text-on-surface-variant">Pick how each job gets matched to your profile. You can change this anytime.</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {sorted.map((b) => {
          const selected = backend === b.id;
          return (
            <button
              key={b.id}
              type="button"
              onClick={() => setBackend(b.id)}
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
        {sorted.length === 0 && <p className="text-sm text-on-surface-variant">Loading options…</p>}
      </div>
    </div>
  );
}

function FirstRun() {
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-on-surface">Run your first search</h2>
        <p className="mt-1 text-sm text-on-surface-variant">
          This pulls fresh listings and scores them. Running the scraper uses Apify (a few cents) — you&apos;ll confirm first.
          Re-scoring what you already have is free.
        </p>
      </div>
      <RunControls />
      <Reassure>100% local — and we never apply to anything for you.</Reassure>
      <p className="text-sm text-on-surface-variant">
        When it finishes, hit <strong>Go to my shortlist</strong> to see your ranked matches.
      </p>
    </div>
  );
}
