"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  createStructuredSearch,
  deleteSearch,
  listStructuredSearches,
  previewActorInput,
  updateStructuredSearch,
  type StructuredSearch,
} from "@/lib/api";
import RunControls from "@/components/RunControls";
import TagInput from "@/components/TagInput";
import WorkTypeToggle from "@/components/WorkTypeToggle";
import { Icon } from "@/components/icons";
import { ErrorNote } from "@/components/States";

export default function SearchesPage() {
  const [items, setItems] = useState<StructuredSearch[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    listStructuredSearches()
      .then((structured) => {
        setItems(structured);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "failed to load"));
  }, []);
  useEffect(load, [load]);

  const examples = items.filter((s) => isExample(s.name));
  const real = items.filter((s) => !isExample(s.name));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-on-surface">Searches</h1>
          <p className="mt-1 text-on-surface-variant">
            Tell us what to look for in plain words — job titles and places. No codes to look up.
          </p>
        </div>
        <RunControls onDone={load} />
      </div>

      {error && <ErrorNote>{error}</ErrorNote>}

      {examples.length > 0 && real.length === 0 && (
        <div className="rounded-card border border-[color:var(--color-accent-amber)]/40 bg-[color:var(--color-accent-amber)]/10 p-4 text-sm text-on-surface">
          <p className="font-medium">These are example searches to get you started.</p>
          <p className="mt-1 text-on-surface-variant">
            Edit one to make it yours (change the titles and add your locations), or delete it and
            create your own below. Your real searches stay private — only the examples are shipped.
          </p>
        </div>
      )}

      <div className="grid gap-3">
        {items.map((s) => (
          <SearchCard key={s.name} search={s} onChanged={load} />
        ))}
        {items.length === 0 && !error && (
          <p className="rounded-card border border-dashed border-border bg-surface p-6 text-center text-sm text-on-surface-variant">
            No searches yet — create one below to start finding jobs.
          </p>
        )}
      </div>

      <NewSearch onCreated={load} />
    </div>
  );
}

type Form = {
  titles: string[];
  locations: string[];
  work_types: string[];
  employment_types: string[];
  posted_within: string;
  max_items: number | null;
  geo_ids: string[];
};

function formFrom(s: StructuredSearch): Form {
  return {
    titles: s.titles,
    locations: s.locations,
    work_types: s.work_types,
    employment_types: s.employment_types,
    posted_within: s.posted_within || "24h",
    max_items: s.max_items,
    geo_ids: s.geo_ids,
  };
}

function isExample(name: string | null): boolean {
  return !!name && name.startsWith("example-");
}

function SearchCard({ search, onChanged }: { search: StructuredSearch; onChanged: () => void }) {
  const name = search.name ?? "";
  const [form, setForm] = useState<Form>(formFrom(search));
  const [needsGeoid, setNeedsGeoid] = useState(search.needs_geoid);
  const [msg, setMsg] = useState<string | null>(null);
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm({ ...form, [k]: v });

  const ready = form.titles.length > 0 && !needsGeoid;

  async function save() {
    try {
      const res = await updateStructuredSearch(name, { name, ...form });
      setNeedsGeoid(res.needs_geoid);
      flash("Saved ✓");
    } catch {
      flash("Save failed");
    }
  }
  function flash(m: string) {
    setMsg(m);
    setTimeout(() => setMsg(null), 2000);
  }

  return (
    <div className="rounded-card border border-border bg-surface p-5 shadow-card">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="font-semibold text-on-surface">{name}</h3>
          {isExample(name) && <Badge tone="neutral">Example</Badge>}
          <StatusPill ready={ready} />
        </div>
        <div className="flex items-center gap-2">
          {msg && <span className="text-xs text-on-surface-variant">{msg}</span>}
          <button onClick={save} className={btnPrimary}>
            Save
          </button>
          <button
            onClick={() => deleteSearch(name).then(onChanged)}
            className="rounded-lg border border-border px-3 py-1.5 text-sm text-on-surface-variant transition-colors hover:text-[color:var(--color-accent-red)]"
          >
            Delete
          </button>
        </div>
      </div>
      <p className="mb-4 text-xs text-on-surface-variant">{summarize(form)}</p>
      <SearchFields form={form} set={set} needsGeoid={needsGeoid} />
      <ActorPreview form={form} />
    </div>
  );
}

function summarize(form: Form): string {
  const titles = form.titles.length
    ? `${form.titles.length} title${form.titles.length > 1 ? "s" : ""}`
    : "no titles yet";
  const where = form.locations.length
    ? form.locations.join(", ")
    : form.geo_ids.length
      ? `${form.geo_ids.length} geoId${form.geo_ids.length > 1 ? "s" : ""}`
      : "no location yet";
  const work = form.work_types.length ? form.work_types.join(" / ") : "any work type";
  return `${titles} · ${where} · ${work}`;
}

const POSTED_OPTIONS = [
  { value: "1h", label: "Last hour" },
  { value: "24h", label: "Last 24 hours" },
  { value: "week", label: "Last week" },
  { value: "month", label: "Last month" },
];
const EMPLOYMENT_OPTIONS = [
  { value: "full-time", label: "Full-time" },
  { value: "part-time", label: "Part-time" },
  { value: "contract", label: "Contract" },
  { value: "internship", label: "Internship" },
  { value: "temporary", label: "Temporary" },
];

function SearchFields({
  form,
  set,
  needsGeoid,
}: {
  form: Form;
  set: <K extends keyof Form>(k: K, v: Form[K]) => void;
  needsGeoid: boolean;
}) {
  const [advanced, setAdvanced] = useState(form.geo_ids.length > 0);
  return (
    <div className="space-y-4">
      <Labeled label="Job titles">
        <TagInput values={form.titles} onChange={(v) => set("titles", v)} placeholder="e.g. Data Analyst — press Enter…" />
      </Labeled>
      <Labeled label="Locations">
        <TagInput values={form.locations} onChange={(v) => set("locations", v)} placeholder="e.g. European Economic Area — press Enter…" />
      </Labeled>
      <Labeled label="Work type">
        <WorkTypeToggle values={form.work_types} onChange={(v) => set("work_types", v)} />
      </Labeled>
      <Labeled label="Employment type">
        <MultiToggle
          options={EMPLOYMENT_OPTIONS}
          values={form.employment_types}
          onChange={(v) => set("employment_types", v)}
        />
      </Labeled>
      <div className="grid gap-4 sm:grid-cols-2">
        <Labeled label="Posted within">
          <select
            value={form.posted_within}
            onChange={(e) => set("posted_within", e.target.value)}
            className={inputCls}
          >
            {POSTED_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </Labeled>
        <Labeled label="Max results per run" hint="Higher = more coverage, slightly higher Apify cost.">
          <input
            type="number"
            min={1}
            value={form.max_items ?? 50}
            onChange={(e) => set("max_items", e.target.value ? Number(e.target.value) : null)}
            className={inputCls}
          />
        </Labeled>
      </div>

      {needsGeoid && (
        <div className="rounded-lg border border-[color:var(--color-accent-amber)]/40 bg-[color:var(--color-accent-amber)]/10 p-3 text-sm text-on-surface">
          <p className="font-medium">A location didn&apos;t match the job source automatically.</p>
          <p className="mt-1 text-on-surface-variant">
            The search still works — to target precisely, add a LinkedIn <code>geoId</code> (from a jobs-search URL) under Advanced.
          </p>
          <button onClick={() => setAdvanced(true)} className="mt-1.5 text-sm font-medium text-primary hover:underline">
            Add a geoId
          </button>
        </div>
      )}

      {advanced && (
        <Labeled label="Advanced: geoIds" hint="Only if a location didn't resolve. Numeric LinkedIn geo IDs.">
          <TagInput values={form.geo_ids} onChange={(v) => set("geo_ids", v)} placeholder="e.g. 91000000 — press Enter…" />
        </Labeled>
      )}
    </div>
  );
}

// Live, read-only "what we send" preview. Updates (debounced) as the form changes, so
// the JSON always reflects the typed/selected fields — geoIds resolved server-side.
function ActorPreview({ form }: { form: Form }) {
  const [json, setJson] = useState<string>("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let alive = true;
    const t = setTimeout(() => {
      previewActorInput(form)
        .then((a) => alive && setJson(JSON.stringify(a, null, 2)))
        .catch(() => alive && setJson("// preview unavailable"));
    }, 400);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [form]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(json);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable — ignore */
    }
  }

  return (
    <details className="mt-4 border-t border-border pt-3">
      <summary className="cursor-pointer text-sm text-on-surface-faint hover:text-on-surface-variant">
        What we send to the job source (updates as you edit)
      </summary>
      <div className="mt-2 flex items-center justify-between">
        <p className="text-xs text-on-surface-variant">Read-only — generated from the fields above.</p>
        <button onClick={copy} className="text-xs font-medium text-primary hover:underline">
          {copied ? "Copied ✓" : "Copy"}
        </button>
      </div>
      <pre className="mt-2 w-full overflow-x-auto rounded-lg border border-border bg-surface-alt px-3 py-2 font-mono text-xs text-on-surface-variant">
        {json || "…"}
      </pre>
    </details>
  );
}

function NewSearch({ onCreated }: { onCreated: () => void }) {
  const empty: Form = {
    titles: [],
    locations: [],
    work_types: [],
    employment_types: [],
    posted_within: "24h",
    max_items: null,
    geo_ids: [],
  };
  const [name, setName] = useState("");
  const [form, setForm] = useState<Form>(empty);
  const [msg, setMsg] = useState<string | null>(null);
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm({ ...form, [k]: v });

  async function create() {
    try {
      await createStructuredSearch({ name: name.trim(), ...form });
      setName("");
      setForm(empty);
      setMsg(null);
      onCreated();
    } catch (e) {
      setMsg(e instanceof ApiError && e.status === 409 ? "a search with that name already exists" : "couldn't create");
    }
  }

  return (
    <div className="rounded-card border border-dashed border-border bg-surface p-5">
      <h3 className="mb-3 flex items-center gap-2 font-semibold text-on-surface">
        <Icon name="plus" size={18} /> New search
      </h3>
      <div className="space-y-4">
        <Labeled label="Name" hint="A short label (letters, digits, - and _).">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. main"
            className={inputCls}
          />
        </Labeled>
        <SearchFields form={form} set={set} needsGeoid={false} />
        <div className="flex items-center gap-2">
          <button onClick={create} disabled={!name.trim()} className={btnPrimary}>
            Create search
          </button>
          {msg && <span className="text-xs text-[color:var(--color-accent-red)]">{msg}</span>}
        </div>
      </div>
    </div>
  );
}

// --- small UI bits ----------------------------------------------------------

function MultiToggle({
  options,
  values,
  onChange,
}: {
  options: { value: string; label: string }[];
  values: string[];
  onChange: (v: string[]) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const on = values.includes(o.value);
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(on ? values.filter((v) => v !== o.value) : [...values, o.value])}
            className={`rounded-full border px-3 py-1 text-sm font-medium transition-colors ${
              on
                ? "border-primary bg-primary/10 text-primary"
                : "border-border text-on-surface-variant hover:bg-surface-alt"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

function StatusPill({ ready }: { ready: boolean }) {
  return ready ? (
    <Badge tone="green">Ready</Badge>
  ) : (
    <Badge tone="amber">Needs setup</Badge>
  );
}

function Badge({ tone, children }: { tone: "green" | "amber" | "neutral"; children: React.ReactNode }) {
  const cls = {
    green: "border-[color:var(--color-accent-green)]/40 bg-[color:var(--color-accent-green)]/10 text-[color:var(--color-accent-green)]",
    amber: "border-[color:var(--color-accent-amber)]/40 bg-[color:var(--color-accent-amber)]/10 text-[color:var(--color-accent-amber)]",
    neutral: "border-border bg-surface-alt text-on-surface-variant",
  }[tone];
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${cls}`}>{children}</span>
  );
}

const inputCls =
  "w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-on-surface outline-none transition-colors focus:border-primary placeholder:text-on-surface-faint";
const btnPrimary =
  "rounded-lg bg-primary px-4 py-1.5 text-sm font-medium text-on-primary shadow-card transition-colors hover:bg-primary-hover disabled:opacity-50";

function Labeled({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="block text-sm font-medium text-on-surface">{label}</label>
      {children}
      {hint && <p className="text-xs text-on-surface-variant">{hint}</p>}
    </div>
  );
}
