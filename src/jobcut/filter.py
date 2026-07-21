#!/usr/bin/env python3
"""filter.py — Stage 4: route the funnel, drop title mismatches, collapse reposts.

Reads the jobs table (db.py), applies the geo router, the config-driven title
pre-filter, and incremental exclusion (already-scored rows), then collapses
reposts by a canonical_id. Returns the work to score plus the metadata the
aggregation step needs — all in-process, no disk batches.
"""

from __future__ import annotations

import re

import pandas as pd

from . import config, db
from .route import funnel_series


def norm(x):
    return re.sub(r"\s+", " ", str(x).strip().lower())


# fields surfaced to an external scorer (a Claude/Cowork skill reads these to score)
UNSCORED_FIELDS = ["job_id", "title", "company_name", "company_size",
                   "location", "workplace_type", "description"]


def unscored(conn, include_scored: bool = False,
             ids: list[str] | None = None, needs_backend: str | None = None) -> list[dict]:
    """Jobs to score, each with its **full** ``description`` (never truncated).

    Read-only. Lets an external scorer (a Claude/Cowork skill) read the job text and
    score it against the profile; pair with `jobcut ingest-scores`. No title
    pre-filter (the scorer judges relevance) and no repost collapse. Returns a list
    of plain-str dicts.

    Four modes feed the scoring paths (always with full descriptions):
      - default: geo funnel **minus** anything already scored (new jobs — incremental).
      - ``needs_backend="claude_skills"``: geo funnel minus jobs already scored *by that
        backend* — i.e. jobs still needing Claude, INCLUDING ones the rule_based floor
        already scored (they'd be hidden by the default, which treats any score as done).
      - ``include_scored=True``: the whole geo funnel, including already-scored rows
        (re-score everything).
      - ``ids=[...]``: exactly those ``job_id``s, regardless of funnel or scored state
        (targeted re-score of specific roles).
    """
    df = db.read_jobs(conn)
    if df.empty:
        return []
    if ids is not None:
        wanted = {str(i) for i in ids}
        df = df[df.job_id.astype(str).isin(wanted)]
    else:
        df = df[funnel_series(df.location, df.workplace_type)]
        if needs_backend is not None:
            # jobs still lacking a score from THIS backend (rule_based floor counts as unscored)
            done = db.scored_ids(conn, backend=needs_backend)
            df = df[~df.job_id.astype(str).isin(done)]
        elif not include_scored:
            already = db.scored_ids(conn)
            df = df[~df.job_id.astype(str).isin(already)]
    cols = [c for c in UNSCORED_FIELDS if c in df.columns]
    return [{c: ("" if pd.isna(r[c]) else str(r[c])) for c in cols}
            for _, r in df[cols].iterrows()]


def _canonical(df: pd.DataFrame) -> pd.Series:
    return df.company_name.map(norm) + "|" + df.title.map(norm) + "|" + df.location.map(norm)


def select(conn, incremental: bool = True) -> dict:
    """Pick what to score this run.

    Returns a dict:
      - reps:          DataFrame of unique representatives to score (one per canonical_id)
      - reposts:       [{job_id, canonical_id}] that inherit their canonical's score
      - discard_title: [{job_id, canonical_id}] dropped by the title pre-filter
      - n_funnel:      count of new funnel rows considered

    ``incremental=True`` (the default, production scoring) skips anything already in
    the scores table. ``incremental=False`` (calibration / compare mode) considers
    the whole funnel so every backend scores the same representatives.
    """
    df = db.read_jobs(conn)
    empty = {"reps": df.iloc[0:0] if not df.empty else df, "reposts": [], "discard_title": [], "n_funnel": 0}
    if df.empty:
        return empty

    df["funnel"] = funnel_series(df.location, df.workplace_type)
    f = df[df.funnel].copy()

    include = re.compile(config.load()["filter"]["include_titles"], re.I)
    f["to_score"] = f.title.astype(str).map(lambda t: include.search(t) is not None)
    f["canonical_id"] = _canonical(f)

    # incremental: skip anything already scored
    if incremental:
        already = db.scored_ids(conn)
        f = f[~f.job_id.astype(str).isin(already)].copy()
    if f.empty:
        return empty

    to_score = f[f.to_score].copy()
    discard = f[~f.to_score].copy()

    # collapse reposts: score one representative per canonical (oldest first_seen)
    to_score = to_score.sort_values("first_seen")
    reps = to_score.drop_duplicates("canonical_id", keep="first")
    dup_reposts = to_score[to_score.duplicated("canonical_id", keep="first")]

    return {
        "reps": reps,
        "reposts": [{"job_id": r.job_id, "canonical_id": r.canonical_id} for r in dup_reposts.itertuples()],
        "discard_title": [{"job_id": r.job_id, "canonical_id": r.canonical_id} for r in discard.itertuples()],
        "n_funnel": len(f),
    }
