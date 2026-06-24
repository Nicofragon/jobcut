"""compare.py — calibration mode: score the funnel with several backends side-by-side.

Production scoring (`score.run`) uses exactly ONE backend and writes the `scores`
table. Compare mode runs every *usable live* backend over the same representatives
and writes the additive `score_runs` table (one row per job × backend), leaving
`scores` (and the normal single-backend flow) completely untouched.

It's a calibration aid: eyeball `rule_based` vs `local` to decide whether to tune
the rubric or the local model's prompt.

`claude_skills` is ingest-first (not a live-pipeline scorer), so it never runs
here; its scores arrive separately via `jobcut ingest-scores` tagged
`backend=claude_skills` and would simply appear as another column if present.
"""

from __future__ import annotations

import datetime

import pandas as pd

from .. import config, db
from .. import filter as _filter
from . import get_scorer
from .registry import _CARD_ORDER, backend_status

# The pair the summary stats (agreement, correlation, disagreements) are computed on.
PRIMARY_PAIR = ("rule_based", "local")
AGREE_TOL = 5        # |delta| <= this counts as "agree"
DISAGREE_GAP = 20    # |delta| > this counts as a hard disagreement


def usable_live_backends() -> list[str]:
    """Live (implemented AND available) backend ids, in friendly card order.

    Excludes ingest-first backends (claude_skills, implemented=False) automatically,
    since those are never *usable* in `backend_status()`.
    """
    rows = sorted(backend_status(), key=lambda b: b["order"])
    return [b["id"] for b in rows if b["usable"]]


def resolve_backends(requested: list[str] | None = None) -> tuple[list[str], list[str]]:
    """(to_run, skipped) for a requested list, intersected with usable live backends.

    With no request, run every usable live backend. Requested-but-unusable ids
    (e.g. `local` when Ollama is down) are reported as `skipped`, not run.
    """
    usable = usable_live_backends()
    if not requested:
        return usable, []
    to_run = [b for b in requested if b in usable]
    skipped = [b for b in requested if b not in usable]
    return to_run, skipped


def _scorer_for(backend: str, cfg: dict):
    """Build a Scorer for `backend`. rule_based gets the full rubric kwargs (the floor)."""
    from ..score import _rule_based_kwargs
    if backend == "rule_based":
        return get_scorer("rule_based", **_rule_based_kwargs(cfg))
    return get_scorer(backend)


def run_compare(conn=None, backends: list[str] | None = None, limit: int | None = None,
                progress=None) -> dict:
    """Score the funnel with each usable live backend; write `score_runs`.

    ``limit`` caps the run to the first N representatives (a calibration sample —
    handy when a slow local backend would otherwise take hours over the whole
    funnel). ``None`` scores every representative.

    Returns a summary dict: {backends, skipped, jobs, rows_written, per_backend}.
    """
    emit = progress or (lambda e: None)
    own = conn is None
    conn = conn or db.connect()
    try:
        from ..score import load_profile
        cfg = config.load()
        profile = load_profile()
        to_run, skipped = resolve_backends(backends)
        if skipped:
            emit({"stage": "compare", "message": f"skipping unusable backend(s): {', '.join(skipped)}",
                  "skipped": skipped})

        now = datetime.datetime.now().isoformat(timespec="seconds")
        sel = _filter.select(conn, incremental=False)   # whole funnel, every backend sees the same reps
        reps = sel["reps"]
        reps_records = reps.to_dict("records") if len(reps) else []
        if limit is not None and limit >= 0:
            reps_records = reps_records[:limit]   # calibration sample (first N reps)
        emit({"stage": "compare", "message": f"comparing {len(to_run)} backend(s) over "
              f"{len(reps_records)} representatives", "counts": {"reps": len(reps_records)}})

        rows: list[dict] = []
        per_backend: dict[str, dict] = {}
        total = len(reps_records)
        for backend in to_run:
            scorer = _scorer_for(backend, cfg)
            be_rows: list[dict] = []
            ok = failed = 0
            # Score per job (not score_batch) so one slow/failed call — e.g. a local
            # backend timing out on CPU — is logged and skipped instead of aborting
            # the whole run and losing every prior result.
            for job in reps_records:
                try:
                    js = scorer.score(job, profile)
                except Exception as exc:   # noqa: BLE001 — resilience: keep going, report the job
                    failed += 1
                    emit({"stage": "compare", "backend": backend,
                          "message": f"{backend}: job {job.get('job_id')} failed ({exc})"})
                    continue
                be_rows.append({
                    "job_id": str(js.job_id), "backend": backend,
                    "match_score": js.match_score, "match_reasons": js.match_reasons,
                    "scored_at": now,
                })
                ok += 1
                if ok % 10 == 0:
                    emit({"stage": "compare", "backend": backend,
                          "message": f"{backend}: {ok}/{total} scored"})
            db.upsert_score_runs(conn, be_rows)   # write per backend so partial progress survives
            rows.extend(be_rows)
            per_backend[backend] = {"ok": ok, "failed": failed}
            emit({"stage": "compare", "backend": backend,
                  "message": f"{backend}: scored {ok}/{total}" + (f", {failed} failed" if failed else "")})

        n = len(rows)
        summary = {"backends": to_run, "skipped": skipped, "jobs": len(reps_records),
                   "rows_written": n, "per_backend": per_backend}
        emit({"stage": "done", "message": f"wrote {n} score_runs rows "
              f"({len(reps_records)} jobs × {len(to_run)} backends)", "counts": summary})
        return summary
    finally:
        if own:
            conn.close()


# --- comparison report (read score_runs → side-by-side table + summary) ------

def _ordered_backends(present: list[str]) -> list[str]:
    return sorted(present, key=lambda b: _CARD_ORDER.get(b, 99))


def compare_report(conn) -> dict:
    """Build the side-by-side comparison from `score_runs`.

    Returns {backends, rows, summary, empty}. Each row has job_id, title, company,
    score_<backend> + reason_<backend> for every backend present, and (when the
    PRIMARY_PAIR is both present) a `delta` = score_local - score_rule_based.
    """
    runs = db.read_score_runs(conn)
    if runs.empty:
        return {"backends": [], "rows": [], "summary": {"note": "no score_runs yet — run `jobcut score --compare` first"},
                "empty": True}

    backends = _ordered_backends(list(runs.backend.unique()))
    score_p = runs.pivot(index="job_id", columns="backend", values="match_score")
    reason_p = runs.pivot(index="job_id", columns="backend", values="match_reasons")

    jobs = db.read_jobs(conn)
    meta = (jobs.set_index("job_id")[["title", "company_name"]] if not jobs.empty
            else pd.DataFrame(columns=["title", "company_name"]))

    rows = []
    a, b = PRIMARY_PAIR
    have_pair = a in backends and b in backends
    for jid in score_p.index:
        row = {"job_id": str(jid)}
        row["title"] = str(meta.title.get(jid, "")) if jid in meta.index else ""
        row["company"] = str(meta.company_name.get(jid, "")) if jid in meta.index else ""
        for be in backends:
            sc = score_p.at[jid, be] if be in score_p.columns else None
            row[f"score_{be}"] = None if pd.isna(sc) else int(sc)
            rs = reason_p.at[jid, be] if be in reason_p.columns else None
            row[f"reason_{be}"] = "" if (rs is None or pd.isna(rs)) else str(rs)
        if have_pair and row.get(f"score_{a}") is not None and row.get(f"score_{b}") is not None:
            row["delta"] = row[f"score_{b}"] - row[f"score_{a}"]   # local - rule_based
        else:
            row["delta"] = None
        rows.append(row)

    rows.sort(key=lambda r: (-(abs(r["delta"]) if r["delta"] is not None else -1), r["job_id"]))
    return {"backends": backends, "rows": rows, "summary": _summary(rows, backends), "empty": False}


def _summary(rows: list[dict], backends: list[str]) -> dict:
    """Footer stats over the PRIMARY_PAIR: agreement, correlation, hard disagreements."""
    a, b = PRIMARY_PAIR
    out: dict = {"jobs": len(rows), "backends": backends}
    if not (a in backends and b in backends):
        out["note"] = f"only one comparable backend present ({', '.join(backends)}); nothing to correlate"
        return out
    pairs = [(r[f"score_{a}"], r[f"score_{b}"]) for r in rows
             if r.get(f"score_{a}") is not None and r.get(f"score_{b}") is not None]
    out["compared"] = len(pairs)
    if not pairs:
        out["note"] = "no jobs scored by both backends"
        return out
    deltas = [bb - aa for aa, bb in pairs]
    agree = sum(1 for d in deltas if abs(d) <= AGREE_TOL)
    disagree = sum(1 for d in deltas if abs(d) > DISAGREE_GAP)
    out.update({
        "pair": f"{b} vs {a}",
        "agree_within_5": agree,
        "agree_pct": round(100 * agree / len(pairs), 1),
        "disagreements_over_20": disagree,
        "mean_delta": round(sum(deltas) / len(deltas), 1),
        "correlation": _pearson([aa for aa, _ in pairs], [bb for _, bb in pairs]),
    })
    return out


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation without numpy (None if undefined — <2 points or zero variance)."""
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return round(sxy / (sxx ** 0.5 * syy ** 0.5), 3)


# --- exports (CSV + xlsx in out/) -------------------------------------------

def report_dataframe(report: dict) -> pd.DataFrame:
    """Flatten a compare_report into the export table (ordered columns)."""
    backends = report["backends"]
    cols = ["job_id", "title", "company"]
    for be in backends:
        cols.append(f"score_{be}")
    cols.append("delta")
    for be in backends:
        cols.append(f"reason_{be}")
    df = pd.DataFrame(report["rows"])
    if df.empty:
        return pd.DataFrame(columns=cols)
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols]


def write_exports(report: dict, out_dir=None) -> dict:
    """Write out/compare.csv and out/compare.xlsx. Returns {csv, xlsx} paths (str)."""
    from .. import paths
    out = out_dir or paths.out_dir()
    df = report_dataframe(report)
    csv_path = out / "compare.csv"
    xlsx_path = out / "compare.xlsx"
    df.to_csv(csv_path, index=False)
    df.to_excel(xlsx_path, index=False, sheet_name="compare")   # openpyxl is a core dep
    return {"csv": str(csv_path), "xlsx": str(xlsx_path)}
