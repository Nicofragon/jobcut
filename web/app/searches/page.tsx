"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  createStructuredSearch,
  deleteSearch,
  listStructuredSearches,
  previewActorInput,
  setSearchPaused,
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
  const counts = {
    active: items.filter((s) => !s.paused && isReady(s)).length,
    paused: items.filter((s) => s.paused).length,
    needsSetup: items.filter((s) => !s.paused && !isReady(s)).length,
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-on-surface">Searches</h1>
          <p className="mt-1 text-on-surface-variant">
            Tell us what to look for in plain words — job titles and places. No codes to look up.
          </p>
          {items.length > 0 && (
            <p className="mt-1 text-xs text-on-surface-variant">
              <span className="font-medium text-[color:var(--color-accent-green)]">{counts.active} active</span>
              {" "}— these run on each pull
              {counts.paused > 0 && ` · ${counts.paused} paused`}
              {counts.needsSetup > 0 && ` · ${counts.needsSetup} need setup`}
            </p>
          )}
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
        {[...items].sort((a, b) => rank(a) - rank(b)).map((s) => (
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

function isReady(s: StructuredSearch): boolean {
  return s.titles.length > 0 && !s.needs_geoid;
}

// Sort so the active, configured, real searches surface first; paused ones and
// examples sink — the top of the page reads as "here's what's actually running".
function rank(s: StructuredSearch): number {
  return (s.paused ? 4 : 0) + (isExample(s.name) ? 2 : 0) + (isReady(s) ? 0 : 1);
}

function SearchCard({ search, onChanged }: { search: StructuredSearch; onChanged: () => void }) {
  const name = search.name ?? "";
  const [form, setForm] = useState<Form>(formFrom(search));
  const [needsGeoid, setNeedsGeoid] = useState(search.needs_geoid);
  const [paused, setPaused] = useState(search.paused);
  const [msg, setMsg] = useState<string | null>(null);
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm({ ...form, [k]: v });
  const patch = (p: Partial<Form>) => setForm({ ...form, ...p });

  const ready = form.titles.length > 0 && !needsGeoid;

  async function save() {
    try {
      const res = await updateStructuredSearch(name, { name, ...form, paused });
      setNeedsGeoid(res.needs_geoid);
      flash("Saved ✓");
    } catch {
      flash("Save failed");
    }
  }
  async function togglePaused(e: React.MouseEvent) {
    e.stopPropagation();
    const next = !paused;
    setPaused(next);
    try {
      await setSearchPaused(name, next);
      onChanged();
    } catch {
      setPaused(!next);
      flash("Couldn't update");
    }
  }
  function flash(m: string) {
    setMsg(m);
    setTimeout(() => setMsg(null), 2000);
  }

  const [open, setOpen] = useState(false);

  return (
    <div className={`rounded-card border border-border bg-surface shadow-card ${paused ? "opacity-75" : ""}`}>
      {/* Always-visible header: name, run state, and a one-line summary — scannable when collapsed. */}
      <div className="flex items-center gap-2 p-5">
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex min-w-0 flex-1 items-center gap-3 text-left"
          aria-expanded={open}
        >
          <Icon name="chevron-right" size={18} className={`shrink-0 text-on-surface-faint transition-transform ${open ? "rotate-90" : ""}`} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="font-semibold text-on-surface">{name}</h3>
              {isExample(name) && <Badge tone="neutral">Example</Badge>}
              <RunBadge paused={paused} ready={ready} />
            </div>
            <p className="mt-1 truncate text-xs text-on-surface-variant">{summarize(form)}</p>
          </div>
        </button>
        <button
          onClick={togglePaused}
          className="shrink-0 rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-on-surface-variant transition-colors hover:bg-surface-alt"
          title={paused ? "Resume — include in the next pull" : "Pause — keep but skip on pulls"}
        >
          {paused ? "Resume" : "Pause"}
        </button>
      </div>

      {open && (
        <div className="border-t border-border p-5 pt-4">
          <div className="mb-4 flex items-center justify-end gap-2">
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
          <SearchFields form={form} set={set} patch={patch} needsGeoid={needsGeoid} />
          <ActorPreview form={form} />
        </div>
      )}
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
  patch,
  needsGeoid,
}: {
  form: Form;
  set: <K extends keyof Form>(k: K, v: Form[K]) => void;
  patch: (p: Partial<Form>) => void;
  needsGeoid: boolean;
}) {
  const [advanced, setAdvanced] = useState(form.geo_ids.length > 0);
  return (
    <div className="space-y-4">
      <ImportFromUrl form={form} patch={patch} onUsedGeoid={() => setAdvanced(true)} />
      <Labeled label="Job titles">
        <TagInput values={form.titles} onChange={(v) => set("titles", v)} placeholder="e.g. your target job title — press Enter…" />
      </Labeled>
      <Labeled label="Locations">
        <TagInput values={form.locations} onChange={(v) => set("locations", v)} placeholder="e.g. European Economic Area — press Enter…" />
      </Labeled>
      {form.geo_ids.length > 0 && form.locations.length > 0 && (
        <p className="-mt-2 text-xs text-[color:var(--color-accent-amber)]">
          A geoId is set, so this search targets the geoId and these typed names are ignored. Remove the
          geoId (under Advanced) to search by name instead.
        </p>
      )}
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
          <p className="font-medium">Add a location to target this search.</p>
          <p className="mt-1 text-on-surface-variant">
            Type a city or country above (e.g. <code>Madrid</code> or <code>Spain</code>) — plain names work, no codes needed.
          </p>
        </div>
      )}

      <details className="text-sm" open={advanced || form.geo_ids.length > 0}>
        <summary className="cursor-pointer text-on-surface-faint hover:text-on-surface-variant" onClick={() => setAdvanced(true)}>
          Advanced: geoIds (optional)
        </summary>
        <div className="mt-2 space-y-1.5">
          <TagInput values={form.geo_ids} onChange={(v) => set("geo_ids", v)} placeholder="e.g. 91000000 — press Enter…" />
          <p className="text-xs text-on-surface-variant">
            Optional precision: numeric LinkedIn geo IDs. Easiest way to get one — use{" "}
            <strong>Import from a LinkedIn URL</strong> above. Or open a LinkedIn jobs search for your
            city and copy the number after <code>geoId=</code> in the address bar (e.g.{" "}
            <code>geoId=100994331</code> → Madrid). A plain location name above is enough on its own.
          </p>
        </div>
      </details>
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
  const patch = (p: Partial<Form>) => setForm({ ...form, ...p });

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
        <SearchFields form={form} set={set} patch={patch} needsGeoid={false} />
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

// LinkedIn jobs-search URL → the actor fields. Pulls geoId, keywords (→ title) and
// work type (f_WT: 1 office · 2 remote · 3 hybrid) out of the query string so users
// don't have to decode the URL by hand.
function parseLinkedInSearch(url: string): { geoId?: string; title?: string; workType?: string } {
  let q: URLSearchParams;
  try {
    q = new URL(url.trim()).searchParams;
  } catch {
    return {};
  }
  const WT: Record<string, string> = { "1": "office", "2": "remote", "3": "hybrid" };
  return {
    geoId: q.get("geoId") || undefined,
    title: q.get("keywords")?.trim() || undefined,
    workType: WT[(q.get("f_WT") || "").split(",")[0]] || undefined,
  };
}

function ImportFromUrl({
  form,
  patch,
  onUsedGeoid,
}: {
  form: Form;
  patch: (p: Partial<Form>) => void;
  onUsedGeoid: () => void;
}) {
  const [url, setUrl] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  function importUrl() {
    const { geoId, title, workType } = parseLinkedInSearch(url);
    if (!geoId && !title && !workType) {
      setMsg("Couldn't read that — paste a full linkedin.com/jobs/search URL.");
      return;
    }
    const p: Partial<Form> = {};
    const added: string[] = [];
    if (title && form.titles.length === 0) {
      p.titles = [title];
      added.push(`title “${title}”`);
    }
    if (workType && !form.work_types.includes(workType)) {
      p.work_types = [...form.work_types, workType];
      added.push(`work type ${workType}`);
    }
    if (geoId && !form.geo_ids.includes(geoId)) {
      p.geo_ids = [...form.geo_ids, geoId];
      added.push(`geoId ${geoId}`);
      onUsedGeoid();
    }
    patch(p);
    setUrl("");
    setMsg(added.length ? `Added ${added.join(" · ")}.` : "Those fields are already set — nothing to add.");
  }

  return (
    <details className="rounded-lg border border-border bg-surface-alt p-3">
      <summary className="cursor-pointer text-sm font-medium text-on-surface">Import from a LinkedIn URL</summary>
      <p className="mt-2 text-xs text-on-surface-variant">
        On LinkedIn, search jobs for your role and city, then copy the page URL from the address bar and
        paste it here — we&apos;ll fill in the title, the location code (geoId) and the work type. Your
        existing fields are kept.
      </p>
      <div className="mt-2 flex gap-2">
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              importUrl();
            }
          }}
          placeholder="https://www.linkedin.com/jobs/search/?keywords=…&geoId=…"
          className={inputCls}
        />
        <button onClick={importUrl} disabled={!url.trim()} className={btnPrimary}>
          Import
        </button>
      </div>
      {msg && <p className="mt-1.5 text-xs text-on-surface-variant">{msg}</p>}
    </details>
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

// Run state, in priority order: a paused search never runs; an unconfigured one can't;
// otherwise it's Active and will be scraped on the next pull.
function RunBadge({ paused, ready }: { paused: boolean; ready: boolean }) {
  if (paused) return <Badge tone="neutral">Paused</Badge>;
  if (!ready) return <Badge tone="amber">Needs setup</Badge>;
  return <Badge tone="green">● Active</Badge>;
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
