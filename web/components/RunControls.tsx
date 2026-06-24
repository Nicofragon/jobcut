"use client";

import { useRef, useState } from "react";
import { runEventsUrl, startRun, type RunKind } from "@/lib/api";
import { Icon } from "./icons";

type Progress = { stage?: string; message?: string } | null;

export default function RunControls({ onDone }: { onDone?: () => void }) {
  const [progress, setProgress] = useState<Progress>(null);
  const [running, setRunning] = useState<RunKind | null>(null);
  const [confirming, setConfirming] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  async function run(kind: RunKind, mode = "read", confirm = false) {
    setConfirming(false);
    setRunning(kind);
    setProgress({ message: "starting…" });
    try {
      const { run_id } = await startRun(kind, mode, confirm);
      const es = new EventSource(runEventsUrl(run_id));
      esRef.current = es;
      es.onmessage = (e) => {
        try {
          setProgress(JSON.parse(e.data));
        } catch {
          /* ignore keepalives */
        }
      };
      const finish = () => {
        es.close();
        esRef.current = null;
        setRunning(null);
        onDone?.();
        setTimeout(() => setProgress(null), 4000);
      };
      es.addEventListener("done", finish);
      es.addEventListener("error", () => {
        setProgress({ message: "run failed — see API logs" });
        finish();
      });
    } catch (err) {
      setProgress({ message: err instanceof Error ? err.message : "failed to start" });
      setRunning(null);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <button
        onClick={() => run("score")}
        disabled={!!running}
        className="inline-flex items-center gap-2 rounded-lg bg-surface-sunken px-4 py-2 text-sm font-medium text-on-surface shadow-sm transition-colors hover:border-primary/40 disabled:opacity-50"
      >
        <Icon name="refresh" size={18} className={running === "score" ? "animate-spin" : ""} />
        {running === "score" ? "Re-scoring…" : "Re-score"}
      </button>
      <button
        onClick={() => setConfirming(true)}
        disabled={!!running}
        className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-on-primary shadow-sm transition-colors hover:bg-primary-hover disabled:opacity-50"
      >
        <Icon name="search" size={18} />
        {running === "pull" ? "Scraping…" : "Find new jobs"}
      </button>

      {progress && (
        <span className="text-xs text-on-surface-faint">
          {progress.stage ? `${progress.stage}: ` : ""}
          {progress.message}
        </span>
      )}

      {confirming && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-card border border-border bg-surface p-6 shadow-pop">
            <h3 className="text-lg font-semibold text-on-surface">Find new jobs?</h3>
            <p className="mt-2 text-sm text-on-surface-variant">
              This runs your saved searches on LinkedIn via Apify and costs a little money
              (~$0.15/day typical). Already have jobs? “Re-score” re-evaluates them for free.
            </p>
            <div className="mt-5 flex justify-end gap-3">
              <button
                onClick={() => setConfirming(false)}
                className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-on-surface transition-colors hover:bg-surface-alt"
              >
                Cancel
              </button>
              <button
                onClick={() => run("pull", "trigger", true)}
                className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-on-primary shadow-sm transition-colors hover:bg-primary-hover"
              >
                Yes, find new jobs
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
