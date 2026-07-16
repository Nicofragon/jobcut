#!/usr/bin/env python3
"""surface.py — Stage 7: write the ranked shortlist to out/.

Reads jobs + scores from SQLite (db.py), joins them, applies the geo funnel,
collapses reposts, optionally excludes already-applied roles, and writes:
  - out/shortlist.md   (human-readable: today's top + backlog)
  - out/shortlist.csv  (machine-readable)

The "exclude already-applied" feature is OPTIONAL: set $JOBCUT_TRACKER to a
CSV/xlsx with columns Company, Role Title, LinkedIn URL. If unset, it's skipped.
"""

from __future__ import annotations

import datetime
import os
import re

import pandas as pd

from . import db, paths
from .route import funnel_series

TOP_N = 10          # CLI markdown digest: a tight "top N" highlight list
FEED_LIMIT = 300    # web feed per list: a safety ceiling only — the min-match slider is
                    # the real filter, so the feed returns ~everything above the floor
                    # (the frontend reveals them progressively with "Show more").

# match_score bands for the Discovery histogram, aligned to the shortlist thresholds
# (min_score=60 = shortlist floor, backlog_min=75 = "top"). [lo, hi) except the last.
SCORE_BANDS = [(0, 60, "Below bar"), (60, 75, "Shortlist"), (75, 101, "Top")]


def score_distribution(conn) -> dict:
    """How your scored offers spread across match-score bands (a pipeline-quality view).

    Deduped by canonical_id (reposts collapsed, best score kept) so a role posted five
    times counts once. Out-of-profile titles are already pre-discarded before scoring, so
    this is the shape of your *in-profile* pipeline. Empty-safe: zeroed bands, no jobs.
    """
    s = db.read_scores(conn)
    zero = {"total": 0, "median": 0,
            "bands": [{"label": lbl, "min": lo, "max": hi, "count": 0} for lo, hi, lbl in SCORE_BANDS]}
    if s.empty:
        return zero
    s = s.copy()
    s["score"] = pd.to_numeric(s.match_score, errors="coerce")
    s = s.dropna(subset=["score"])
    if s.empty:
        return zero
    # collapse reposts: prefer canonical_id, fall back to job_id; keep the best score
    cid = s.get("canonical_id")
    s["key"] = (cid.astype(str).str.strip() if cid is not None else "").replace("", pd.NA)
    s["key"] = s["key"].fillna(s["job_id"])
    s = s.sort_values("score", ascending=False).drop_duplicates("key")

    bands = [{"label": lbl, "min": lo, "max": hi,
              "count": int(((s.score >= lo) & (s.score < hi)).sum())}
             for lo, hi, lbl in SCORE_BANDS]
    return {"total": int(len(s)), "median": int(s.score.median()), "bands": bands}


def norm(x):
    return re.sub(r"\s+", " ", str(x).strip().lower())


def blank(v):
    return v in (None, "") or (isinstance(v, float) and pd.isna(v)) or str(v).strip().lower() in ("", "nan", "none", "nat")


def offer_link(r):
    for c in (r.linkedin_url, r.apply_url, r.easy_apply_url):
        if not blank(c):
            return str(c)
    return ""


def nextstep(r):
    if not blank(r.apply_url):
        return f"apply via [ATS]({r.apply_url})"
    if not blank(r.recruiter_name):
        return (f"contact recruiter [{r.recruiter_name}]({r.recruiter_url})"
                if not blank(r.recruiter_url) else f"contact recruiter {r.recruiter_name}")
    if not blank(r.easy_apply_url):
        return "Easy Apply on LinkedIn"
    if blank(r.linkedin_url):
        return "search on LinkedIn (no direct link)"
    return "review and apply on LinkedIn"


def line(i, r):
    fire = "🔥 " if (r.score or 0) >= 80 else ""
    return (f"{i}. {fire}**{str(r.title)[:70]} — {r.company_name}** ({int(r.score)}) · "
            f"[offer]({offer_link(r)}) — {str(r.match_reasons or '').strip()} — → {nextstep(r)}")


def load_applied():
    """Optional already-applied exclusion via $JOBCUT_TRACKER (CSV or xlsx)."""
    applied_ids, applied_ct = set(), set()
    tp = os.environ.get("JOBCUT_TRACKER")
    if not tp:
        return applied_ids, applied_ct
    from pathlib import Path
    p = Path(tp).expanduser()
    if not p.exists():
        print(f"  note: JOBCUT_TRACKER set but {p} not found — skipping applied-exclusion")
        return applied_ids, applied_ct
    ap = pd.read_csv(p) if p.suffix.lower() == ".csv" else pd.read_excel(p)
    for _, r in ap.iterrows():
        u = str(r.get("LinkedIn URL", ""))
        mt = re.search(r"/jobs/view/(\d+)", u)
        if mt:
            applied_ids.add(mt.group(1))
        applied_ct.add((norm(r.get("Company", "")), norm(r.get("Role Title", ""))))
    return applied_ids, applied_ct


# columns surfaced to JSON/CSV consumers (the API and shortlist.csv)
RECORD_FIELDS = ["job_id", "title", "company_name", "location", "score", "match_reasons",
                 "linkedin_url", "apply_url", "easy_apply_url", "scored_date",
                 "workplace_type", "status", "backend"]

# jobs columns the shortlist actually needs (drops `description` + other heavy text);
# the rest of a shortlist row comes from the scores table. Used by the API path only —
# the CLI .md export (main) reads full rows for recruiter/salary fields.
SHORTLIST_JOB_COLS = ["job_id", "title", "company_name", "location", "workplace_type",
                      "linkedin_url", "apply_url", "easy_apply_url", "expire_at"]


def _ranked_funnel(conn, applied_ids, applied_ct, today, light=False):
    """Shared selection: funnel ∩ scored, reposts collapsed, applied/expired removed.

    Returns (m, df, f, n_excluded). `f` is the cleaned, ranked frame; `m`/`df` feed counts.
    `f` is None when there are no jobs. `light=True` reads only the columns the API
    shortlist needs (skips `description`); the CLI export keeps the full read.
    """
    m = db.read_jobs(conn, columns=SHORTLIST_JOB_COLS if light else None)
    s = db.read_scores(conn)
    if m.empty:
        return m, None, None, 0

    df = m.merge(s, on="job_id", how="left")
    df["funnel"] = funnel_series(df.location, df.workplace_type)   # vectorized (no per-row apply)
    f = df[df.funnel].copy()
    f["score"] = pd.to_numeric(f.match_score, errors="coerce")

    if "canonical_id" not in f.columns:
        f["canonical_id"] = ""
    f["canonical_id"] = f.canonical_id.fillna("").replace("", pd.NA)
    f["canonical_id"] = f.canonical_id.fillna(f.company_name.map(norm) + "|" + f.title.map(norm) + "|" + f.location.map(norm))

    f["_ct"] = list(zip(f.company_name.map(norm), f.title.map(norm)))
    before = len(f)
    f = f[~(f.job_id.isin(applied_ids) | f._ct.isin(applied_ct))].copy()
    n_excl = before - len(f)

    f["has_link"] = (~f.linkedin_url.map(blank)) | (~f.apply_url.map(blank)) | (~f.easy_apply_url.map(blank))
    f["_exp"] = pd.to_datetime(f.expire_at, errors="coerce")
    f["expired"] = f._exp.notna() & (f._exp.dt.strftime("%Y-%m-%d") < today)
    f["has_url"] = (~f.linkedin_url.map(blank)).astype(int)

    # collapse reposts, keep best score / with link
    f = f.sort_values(["score", "has_url"], ascending=False).drop_duplicates("canonical_id", keep="first").drop_duplicates("_ct", keep="first")
    f = f[f.has_link & ~f.expired].copy()
    return m, df, f, n_excl


def _records(frame):
    """A ranked frame -> JSON-safe list of dicts (numpy/NaN scrubbed)."""
    cols = [c for c in RECORD_FIELDS if c in frame.columns]
    rows = []
    for _, r in frame[cols].iterrows():
        d = {}
        for c in cols:
            if c == "score":
                d[c] = int(r.score) if pd.notna(r.score) else None
            else:
                d[c] = None if blank(r[c]) else str(r[c])
        rows.append(d)
    return rows


def shortlist_data(conn, *, min_score=60, backlog_min=75, q=None, location=None,
                   recency_days=None, include_applied=False, today=None,
                   limit=FEED_LIMIT) -> dict:
    """The ranked shortlist as data (the GET /api/shortlist payload).

    Excludes already-applied roles by `applications.job_id` (not the CSV tracker)
    unless `include_applied`. Returns {today, backlog, meta}. `limit` caps each list
    high enough that lowering `min_score` visibly adds cards (the CLI digest uses the
    tighter TOP_N instead).
    """
    today = today or datetime.date.today().isoformat()
    if include_applied:
        applied_ids = set()
    else:
        apps = db.read_applications(conn)
        applied_ids = set(apps.job_id) if not apps.empty else set()

    m, df, f, n_excl = _ranked_funnel(conn, applied_ids, set(), today, light=True)
    meta = {"db_count": int(len(m)), "funnel_count": 0, "excluded": int(n_excl)}
    if f is None or f.empty:
        return {"today": [], "backlog": [], "meta": meta}
    meta["funnel_count"] = int(df.funnel.sum())

    if q:
        ql = q.lower()
        f = f[f.title.str.lower().str.contains(ql, na=False) | f.company_name.str.lower().str.contains(ql, na=False)]
    if location:
        f = f[f.location.str.lower().str.contains(location.lower(), na=False)]
    if recency_days is not None:
        cutoff = (datetime.date.fromisoformat(today) - datetime.timedelta(days=recency_days)).isoformat()
        f = f[f.scored_date.astype(str) >= cutoff]

    sd = f.scored_date.astype(str)
    # "Latest batch" = the most recent scoring date present, NOT the literal calendar
    # day. Scoring is batched (the user doesn't score every day), so a strict `== today`
    # left the top list perpetually empty. The user-facing `min_score` is the floor for
    # BOTH lists — the control filters the whole feed, not just the fresh batch.
    # (`backlog_min` kept in the signature for API back-compat; superseded by min_score.)
    latest = sd.max() if len(sd) else today
    today_top = f[(sd == latest) & (f.score >= min_score)].sort_values("score", ascending=False).head(limit)
    backlog = f[(sd < latest) & (f.score >= min_score)].sort_values("score", ascending=False).head(limit)
    return {"today": _records(today_top), "backlog": _records(backlog), "meta": meta}


def main(conn=None):
    own = conn is None
    conn = conn or db.connect()
    today = datetime.date.today().isoformat()

    applied_ids, applied_ct = load_applied()
    m, df, f, n_excl = _ranked_funnel(conn, applied_ids, applied_ct, today)
    if own:
        conn.close()

    md_path = paths.out_dir() / "shortlist.md"
    if m.empty:
        md_path.write_text(f"# 🎯 Shortlist\n\n*Generated {today} — no jobs yet. Run `jobcut pull` first.*\n")
        print(f"wrote {md_path}: empty (no jobs in the database)")
        return

    scored = f[f.status == "scored"]
    sd = f.scored_date.astype(str)
    n_today = int((sd == today).sum())
    today_top = f[(sd == today) & (f.score >= 60)].sort_values("score", ascending=False).head(TOP_N)
    backlog = f[(sd < today) & (f.score >= 75)].sort_values("score", ascending=False).head(TOP_N)

    out = [
        "# 🎯 Shortlist\n",
        f"*Generated {today} · DB {len(m)} · funnel {int(df.funnel.sum())} · "
        f"{len(scored)} scored unapplied · {n_excl} excluded (already in tracker) · "
        f"reposts collapsed, valid link only.*\n",
        f"**Summary:** {n_today} scored in today's batch · top {TOP_N} ≥60 below · "
        f"{int((scored.score >= 60).sum())} in backlog ≥60.\n",
        f"## New in today's batch — top {TOP_N} (score ≥60)\n",
    ]
    out += [line(i, r) for i, (_, r) in enumerate(today_top.iterrows(), 1)] or ["_None ≥60 in today's batch._"]
    out += ["", f"## 🗂️ Backlog highlights — top {TOP_N} (≥75, prior days, unapplied)\n"]
    out += [line(i, r) for i, (_, r) in enumerate(backlog.iterrows(), 1)] or ["_None ≥75 in the backlog._"]
    out += ["\n> Set $JOBCUT_TRACKER to a CSV/xlsx to exclude already-applied roles."]
    md_path.write_text("\n".join(out))

    surfaced = pd.concat([today_top, backlog]).drop_duplicates("job_id")
    csv_cols = ["job_id", "title", "company_name", "location", "score", "match_reasons",
                "linkedin_url", "apply_url", "scored_date"]
    surfaced[[c for c in csv_cols if c in surfaced.columns]].to_csv(paths.out_dir() / "shortlist.csv", index=False)

    print(f"wrote {md_path}: {len(today_top)} today-batch (top {TOP_N}), {len(backlog)} backlog, {n_excl} already-applied excluded")


if __name__ == "__main__":
    main()
