"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  createStructuredSearch,
  deleteSearch,
  listSearches,
  listStructuredSearches,
  updateSearch,
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
  const [raw, setRaw] = useState<Record<string, unknown>>({});
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    Promise.all([listStructuredSearches(), listSearches()])
      .then(([structured, rawList]) => {
        setItems(structured);
        setRaw(Object.fromEntries(rawList.map((r) => [r.name, r.input])));
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "failed to load"));
  }, []);
  useEffect(load, [load]);

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

      <div className="grid gap-3">
        {items.map((s) => (
          <SearchCard key={s.name} search={s} raw={raw[s.name ?? ""]} onChanged={load} />
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

type Form = { titles: string[]; locations: string[]; work_types: string[]; geo_ids: string[] };

function SearchCard({
  search,
  raw,
  onChanged,
}: {
  search: StructuredSearch;
  raw: unknown;
  onChanged: () => void;
}) {
  const name = search.name ?? "";
  const [form, setForm] = useState<Form>({
    titles: search.titles,
    locations: search.locations,
    work_types: search.work_types,
    geo_ids: search.geo_ids,
  });
  const [needsGeoid, setNeedsGeoid] = useState(search.needs_geoid);
  const [msg, setMsg] = useState<string | null>(null);
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm({ ...form, [k]: v });

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
      <div className="mb-4 flex items-center justify-between">
        <h3 className="font-semibold text-on-surface">{name}</h3>
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
      <SearchFields form={form} set={set} needsGeoid={needsGeoid} />
      <RawAdvanced name={name} raw={raw} onSaved={onChanged} />
    </div>
  );
}

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

function RawAdvanced({ name, raw, onSaved }: { name: string; raw: unknown; onSaved: () => void }) {
  const [text, setText] = useState(JSON.stringify(raw ?? {}, null, 2));
  const [msg, setMsg] = useState<string | null>(null);
  async function save() {
    try {
      await updateSearch(name, JSON.parse(text));
      setMsg("saved ✓");
      onSaved();
    } catch (e) {
      setMsg(e instanceof SyntaxError ? "invalid JSON" : "save failed");
    }
    setTimeout(() => setMsg(null), 2000);
  }
  return (
    <details className="mt-4 border-t border-border pt-3">
      <summary className="cursor-pointer text-sm text-on-surface-faint hover:text-on-surface-variant">
        Advanced: edit raw JSON (power users)
      </summary>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={8}
        className="mt-2 w-full rounded-lg border border-border bg-surface-alt px-3 py-2 font-mono text-xs text-on-surface outline-none focus:border-primary"
      />
      <div className="mt-2 flex items-center gap-2">
        <button onClick={save} className={btnGhost}>
          Save raw
        </button>
        {msg && <span className="text-xs text-on-surface-variant">{msg}</span>}
      </div>
    </details>
  );
}

function NewSearch({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [form, setForm] = useState<Form>({ titles: [], locations: [], work_types: [], geo_ids: [] });
  const [msg, setMsg] = useState<string | null>(null);
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm({ ...form, [k]: v });

  async function create() {
    try {
      await createStructuredSearch({ name: name.trim(), ...form });
      setName("");
      setForm({ titles: [], locations: [], work_types: [], geo_ids: [] });
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

const inputCls =
  "w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-on-surface outline-none transition-colors focus:border-primary placeholder:text-on-surface-faint";
const btnPrimary =
  "rounded-lg bg-primary px-4 py-1.5 text-sm font-medium text-on-primary shadow-card transition-colors hover:bg-primary-hover disabled:opacity-50";
const btnGhost =
  "rounded-lg border border-border bg-surface px-3 py-1.5 text-sm font-medium text-on-surface transition-colors hover:bg-surface-alt";

function Labeled({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="block text-sm font-medium text-on-surface">{label}</label>
      {children}
      {hint && <p className="text-xs text-on-surface-variant">{hint}</p>}
    </div>
  );
}
