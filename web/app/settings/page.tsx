"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  exportData,
  getConfig,
  getHealth,
  getScoringBackends,
  putConfig,
  putCredentials,
  validateCredentials,
  type Health,
  type ScoringBackend,
  type Validation,
} from "@/lib/api";
import { Icon } from "@/components/icons";

export default function SettingsPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [apify, setApify] = useState("");
  const [llm, setLlm] = useState("");
  const [validation, setValidation] = useState<Validation | null>(null);
  const [backends, setBackends] = useState<ScoringBackend[]>([]);
  const [backend, setBackend] = useState("rule_based");
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => {});
    getConfig().then((c) => setBackend((c as { scoring?: { backend?: string } }).scoring?.backend ?? "rule_based"));
    getScoringBackends().then(setBackends).catch(() => {});
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
                  {!b.usable && b.reason && <p className="mt-2 text-xs text-on-surface-faint">{b.reason}</p>}
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
