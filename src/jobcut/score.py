#!/usr/bin/env python3
"""score.py — Stage 5/6: filter the funnel, score it, write scores to SQLite.

In-process orchestration (replaces the old build_batches + aggregate disk flow):
  1. filter.select() picks the representatives to score + repost/discard metadata.
  2. The configured Scorer scores the representatives against your profile.
  3. Reposts inherit their canonical's score; title-discards get a low fixed score.
  4. Everything is upserted into the scores table (db.py).
"""

from __future__ import annotations

import datetime

from . import config, db, filter as _filter
from . import paths
from .scoring import get_scorer, resolve_scorer

TITLE_DISCARD_SCORE = 20


def load_profile() -> str:
    """Read profile.md from the data dir (empty string if absent)."""
    p = paths.data_dir() / "profile.md"
    return p.read_text() if p.exists() else ""


def _rule_based_kwargs(cfg: dict) -> dict:
    """The kwargs the rule_based scorer (the floor / fallback) is built with."""
    sc = cfg["scoring"]
    return {
        "taxonomy": config.load_taxonomy(),
        "weights": sc.get("weights"),
        "include_titles": cfg["filter"]["include_titles"],
        "out_of_profile_cap": sc.get("out_of_profile_cap", 30),
        "signals": sc.get("signals"),
        "dealbreakers": sc.get("dealbreakers") or None,
    }


def build_scorer(cfg: dict):
    """Resolve the configured backend to a Scorer.

    None when the configured backend is ingest-first (claude_skills) and so has
    no live scorer — see scoring.resolve_scorer.
    """
    return resolve_scorer(cfg, **_rule_based_kwargs(cfg))[0]


def _row(job_id, canonical_id, score, reasons, status, today, backend=""):
    return {"job_id": str(job_id), "canonical_id": canonical_id, "match_score": score,
            "match_reasons": reasons, "status": status, "scored_date": today, "backend": backend}


def _write_selection(conn, scorer, backend_tag, sel, today) -> dict:
    """Score a funnel selection with `scorer`, tag every row `backend_tag`, upsert.

    Shared by the live path and the rule_based floor path so both produce identical
    row shapes (reps + inherited reposts + title-discards). Returns the run summary.
    """
    reps = sel["reps"]
    profile = load_profile()
    jid2canon = {str(r.job_id): r.canonical_id for r in reps.itertuples()} if len(reps) else {}
    results = scorer.score_batch(reps.to_dict("records"), profile) if len(reps) else []

    canon_score = {}
    rows = []
    for js in results:
        cid = jid2canon.get(str(js.job_id), "")
        canon_score[cid] = (js.match_score, js.match_reasons)
        rows.append(_row(js.job_id, cid, js.match_score, js.match_reasons, js.status, today, backend_tag))

    for rp in sel["reposts"]:
        src = canon_score.get(rp["canonical_id"])
        if src:
            rows.append(_row(rp["job_id"], rp["canonical_id"], src[0], (src[1][:140] + " (repost)"), "scored", today, backend_tag))
        else:
            rows.append(_row(rp["job_id"], rp["canonical_id"], None, "repost", "scored", today, backend_tag))

    for d in sel["discard_title"]:
        rows.append(_row(d["job_id"], d["canonical_id"], TITLE_DISCARD_SCORE,
                         "title out of profile (doesn't match your target roles)", "discarded", today, backend_tag))

    n = db.upsert_scores(conn, rows)
    return {"scored": len(results), "reposts": len(sel["reposts"]),
            "discarded": len(sel["discard_title"]), "rows_written": n}


def run(conn=None, progress=None) -> dict:
    emit = progress or (lambda e: None)
    own = conn is None
    conn = conn or db.connect()
    today = datetime.date.today().isoformat()
    cfg = config.load()

    scorer, info = resolve_scorer(cfg, **_rule_based_kwargs(cfg))

    if scorer is None:
        # Ingest-first backend (claude_skills): the *real* score comes from your Claude
        # skill via `jobcut ingest-scores`. But a bare pull would leave newly-pulled jobs
        # invisible in the shortlist until then, so we lay a rule_based FLOOR on the new
        # (unscored) funnel — they show up immediately, tagged honestly as `rule_based`
        # (never masquerading as Claude). Selection is incremental, so the floor only
        # touches jobs with *no* score yet: existing claude_skills AND rule_based rows are
        # left untouched — Claude scores are never downgraded, and the "today batch"
        # (keyed on scored_date) isn't disturbed. Claude scoring later upserts on top.
        floor = get_scorer("rule_based", **_rule_based_kwargs(cfg))
        emit({"stage": "filter", "message": "selecting new jobs to floor-score"})
        sel = _filter.select(conn)
        summary = _write_selection(conn, floor, "rule_based", sel, today)
        summary.update({"floor": True, "backend": info.requested})
        msg = (f"backend {info.requested!r} scores in Claude — laid a rule_based floor on "
               f"{summary['scored']} new job(s) so they're visible now; run your Claude "
               f"Code / Cowork scoring skill to upgrade them")
        emit({"stage": "done", "message": msg, "floor": True, "counts": summary})
        print(f"score · floor (rule_based under {info.requested}): "
              f"{summary['scored']} new reps, {summary['reposts']} reposts, "
              f"{summary['discarded']} title-discards -> {summary['rows_written']} score rows "
              f"· run your Claude Code / Cowork scoring skill to upgrade them")
        if own:
            conn.close()
        return summary

    emit({"stage": "filter", "message": "selecting the funnel to score"})
    sel = _filter.select(conn)
    if info.fell_back:
        msg = f"{info.reason}; using {info.effective}"
        emit({"stage": "score", "message": msg, "fell_back": True})
        print(f"score · fallback: {msg}")

    emit({"stage": "score", "message": f"scoring {len(sel['reps'])} representatives "
          f"(backend={info.effective})", "counts": {"reps": len(sel['reps'])}})
    summary = _write_selection(conn, scorer, info.effective, sel, today)
    emit({"stage": "done", "message": f"wrote {summary['rows_written']} score rows", "counts": summary})
    print(f"score · backend={info.effective} · "
          f"scored {summary['scored']} reps, {summary['reposts']} reposts, "
          f"{summary['discarded']} title-discards -> {summary['rows_written']} score rows")
    if own:
        conn.close()
    return summary


def main():
    run()


if __name__ == "__main__":
    main()
