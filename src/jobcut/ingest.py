"""ingest.py — load externally-produced data into SQLite (A3 scores, A4.1 jobs).

The bridge to external agents (Claude Cowork / cron) is *ingest-first*: an agent
runs outside the pipeline and emits JSON; jobcut validates and upserts it
through `db.upsert_scores` / `db.upsert_jobs` — the single schema authority — so
no one writes raw SQL.

- `ingest_scores` (A3, `jobcut ingest-scores`): a list or ``{"scores": [...]}``.
  Each item needs ``job_id`` + ``match_score`` (0–100, clamped); ``match_reasons``,
  ``status`` (scored|discarded, default scored), ``canonical_id``, ``scored_date``
  optional.
- `import_jobs` (A4.1, `jobcut import-jobs`): a list or ``{"jobs": [...]}`` of
  scraped rows in either the flattened `pull.flatten()` shape (has ``job_id``) or
  the nested harvestapi actor shape (has ``id``). Deduped by job_id via
  `pull.aggregate_today` + `db.upsert_jobs`.

Invalid items are skipped and reported; the rest are written.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from . import db

_REASON_MAX = 240


def load_entries(data) -> list[dict]:
    """Coerce the parsed JSON into a list of score entries (list or {"scores": [...]})."""
    if isinstance(data, dict):
        data = data.get("scores", [])
    if not isinstance(data, list):
        raise ValueError('expected a JSON list of scores or {"scores": [...]}')
    return data


def _normalize(entries: list[dict], today: str, backend: str = "claude_skills") -> tuple[list[dict], list[str]]:
    """Validate entries into SCORE_COLS rows; return (rows, errors). Lenient: skip + report.

    Each row is tagged with `backend` (per-entry ``backend`` wins, else the default —
    ingest is the Claude/Cowork bridge, so the default is ``claude_skills``).
    """
    rows, errors = [], []
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            errors.append(f"entry {i}: not an object")
            continue
        jid = str(e.get("job_id", "")).strip()
        if not jid:
            errors.append(f"entry {i}: missing job_id")
            continue
        try:
            score = max(0, min(100, int(round(float(e["match_score"])))))
        except (KeyError, TypeError, ValueError):
            errors.append(f"entry {i} (job {jid}): missing or non-numeric match_score")
            continue
        status = e.get("status") or "scored"
        if status not in ("scored", "discarded"):
            status = "scored"
        rows.append({
            "job_id": jid,
            "canonical_id": str(e.get("canonical_id", "") or ""),
            "match_score": score,
            "match_reasons": str(e.get("match_reasons", "") or "")[:_REASON_MAX],
            "status": status,
            "scored_date": str(e.get("scored_date") or today),
            "backend": str(e.get("backend") or backend),
        })
    return rows, errors


def ingest_scores(path, conn=None, backend: str = "claude_skills") -> dict:
    """Read a scores JSON file and upsert it. Returns a summary dict.

    `backend` tags each ingested row (per-entry ``backend`` overrides). Defaults to
    ``claude_skills`` since ingest is the Claude/Cowork bridge.
    """
    own = conn is None
    conn = conn or db.connect()
    try:
        today = datetime.date.today().isoformat()
        entries = load_entries(json.loads(Path(path).read_text()))
        rows, errors = _normalize(entries, today, backend)

        known = {r["job_id"] for r in conn.execute("SELECT job_id FROM jobs").fetchall()}
        unknown = sorted({r["job_id"] for r in rows if r["job_id"] not in known})

        n = db.upsert_scores(conn, rows)
        return {"ingested": n, "skipped": len(errors), "errors": errors,
                "unknown_job_ids": unknown}
    finally:
        if own:
            conn.close()


# --- jobs (A4.1) ------------------------------------------------------------

def load_jobs(data) -> list:
    """Coerce the parsed JSON into a list of job rows (list or {"jobs": [...]})."""
    if isinstance(data, dict):
        data = data.get("jobs", [])
    if not isinstance(data, list):
        raise ValueError('expected a JSON list of jobs or {"jobs": [...]}')
    return data


def _to_flat_row(item, default_source="import"):
    """Normalize a job entry to a flatten()-style row (with _source), or None if invalid."""
    if not isinstance(item, dict):
        return None
    jid = str(item.get("job_id", "")).strip()
    if jid:  # already flattened (pull.flatten / db.JOB_COLS shape)
        row = {c: item[c] for c in db.JOB_COLS if c in item}
        for k in ("source_searches", "first_seen", "last_seen"):
            row.pop(k, None)  # owned by aggregate_today
        row["job_id"] = jid
        row["_source"] = str(item.get("source_searches") or item.get("_source") or default_source)
        return row
    if str(item.get("id", "")).strip():  # nested harvestapi actor item
        from . import pull
        flat = pull.flatten(item, default_source)
        return flat if str(flat.get("job_id", "")).strip() else None
    return None


def import_jobs(path, conn=None) -> dict:
    """Read a scraped-jobs JSON file and upsert it (dedupe by job_id). Returns a summary."""
    from . import pull
    own = conn is None
    conn = conn or db.connect()
    try:
        today = datetime.date.today().isoformat()
        items = load_jobs(json.loads(Path(path).read_text()))
        flat_rows, invalid = [], 0
        for it in items:
            row = _to_flat_row(it)
            if row is None:
                invalid += 1
            else:
                flat_rows.append(row)
        today_agg = pull.aggregate_today(flat_rows, today)
        inserted, updated = db.upsert_jobs(conn, today_agg, today)
        # rows that collapsed onto an already-counted job_id within this file
        skipped = len(flat_rows) - len(today_agg)
        return {"new": inserted, "updated": updated, "skipped": skipped, "invalid": invalid}
    finally:
        if own:
            conn.close()
