#!/usr/bin/env python3
"""export.py — SQLite → CSV/JSON for dashboards and humans.

The canonical store is SQLite (db.py). This writes neutral, forkable exports to
out/ for the Streamlit dashboard, a spreadsheet, or GitHub Pages:
  - out/jobs.csv        full jobs table
  - out/scores.csv      full scores table
  - out/dashboard.json  compact summary (funnel counts, score buckets)
"""

from __future__ import annotations

import json
import datetime

import pandas as pd

from . import db, paths
from .route import funnel_series


def main(conn=None) -> dict:
    own = conn is None
    conn = conn or db.connect()
    jobs = db.read_jobs(conn)
    scores = db.read_scores(conn)
    if own:
        conn.close()

    out = paths.out_dir()
    jobs.to_csv(out / "jobs.csv", index=False)
    scores.to_csv(out / "scores.csv", index=False)

    summary = {"generated": datetime.date.today().isoformat(), "total_jobs": int(len(jobs))}
    if not jobs.empty:
        merged = jobs.merge(scores, on="job_id", how="left")
        merged["funnel"] = funnel_series(merged.location, merged.workplace_type)
        merged["score"] = pd.to_numeric(merged.match_score, errors="coerce")
        summary.update(
            funnel=int(merged.funnel.sum()),
            scored=int((merged.status == "scored").sum()),
            discarded=int((merged.status == "discarded").sum()),
            strong_matches=int((merged.score >= 80).sum()),
            buckets={
                "80-100": int(((merged.score >= 80)).sum()),
                "60-79": int(((merged.score >= 60) & (merged.score < 80)).sum()),
                "40-59": int(((merged.score >= 40) & (merged.score < 60)).sum()),
                "0-39": int((merged.score < 40).sum()),
            },
        )
    (out / "dashboard.json").write_text(json.dumps(summary, indent=2))
    print(f"export · {summary['total_jobs']} jobs -> {out}/jobs.csv, scores.csv, dashboard.json")
    return summary


if __name__ == "__main__":
    main()
