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
- `add_job` (B-1, `jobcut add-job` / `POST /applications/manual`): create ONE offer
  manually from ``{url?, company, title, location?, description?, job_id?}``. The
  ``job_id`` is derived (explicit > `jobid.job_id_from_url` > `jobid.job_id_from_fields`)
  so it's stable/deterministic, then upserted (``source_searches='manual'``) through the
  SAME path import_jobs uses (`pull.aggregate_today` + `db.upsert_jobs`).
- `ingest_events` (B-5, `jobcut ingest-events`): the *write-path bridge* — a list or
  ``{"events": [...]}`` of application write-ops. One op per item, dispatched by the
  fields present (``status`` → `db.set_application_status`; ``fields`` →
  `db.update_application_fields`; ``kind`` in note/interview/next_action →
  `db.add_event`). Lets Claude/Cowork update applications (notes, rounds, status,
  structured fields) through the same db.py choke-points — no raw SQL.

Invalid items are skipped and reported; the rest are written.
"""

from __future__ import annotations

import datetime
import json
import re
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


# --- manual job entry (B-1) -------------------------------------------------

def add_job(fields: dict, conn=None) -> dict:
    """Create one offer manually and upsert it (source='manual'). Returns {job_id, created}.

    `fields`: {url?, company, title, location?, description?, job_id?}. The job_id is
    derived (explicit ``job_id`` > `jobid.job_id_from_url(url)` >
    `jobid.job_id_from_fields(company, title)`) so it's stable/deterministic — a later
    LinkedIn scrape dedupes onto it, and an orphan application's id can be repaired.

    Requires at least (company AND title) OR a url that yields a job_id — raises
    ValueError otherwise. The URL is stored in `apply_url` (and `linkedin_url` when it's
    a LinkedIn url). Routes through the SAME path import_jobs uses (`pull.aggregate_today`
    + `db.upsert_jobs`), so first_seen/last_seen and idempotent re-adds are handled there.
    """
    from . import jobid, pull

    url = str(fields.get("url", "") or "").strip()
    company = str(fields.get("company", "") or "").strip()
    title = str(fields.get("title", "") or "").strip()
    explicit_id = str(fields.get("job_id", "") or "").strip()

    if explicit_id:
        jid = explicit_id
    elif url and jobid.job_id_from_url(url):
        jid = jobid.job_id_from_url(url)
    elif company and title:
        jid = jobid.job_id_from_fields(company, title)
    else:
        raise ValueError(
            "add_job needs at least (company AND title) or a URL that yields a job_id"
        )

    is_linkedin = "linkedin.com" in url.lower()
    row = {
        "job_id": jid,
        "_source": "manual",
        "title": title,
        "company_name": company,
        "location": str(fields.get("location", "") or "").strip(),
        "description": str(fields.get("description", "") or ""),
        "apply_url": url,
        "linkedin_url": url if is_linkedin else "",
    }

    own = conn is None
    conn = conn or db.connect()
    try:
        today = datetime.date.today().isoformat()
        today_agg = pull.aggregate_today([row], today)
        inserted, _updated = db.upsert_jobs(conn, today_agg, today)
        return {"job_id": jid, "created": inserted > 0}
    finally:
        if own:
            conn.close()


# --- application write-ops (B-5) --------------------------------------------

_EVENT_KINDS = ("note", "interview", "next_action")


def _norm_date(value):
    """date-only 'YYYY-MM-DD' -> '...T12:00:00' (stable same-day ordering, matches
    advance_process); pass through full ISO; None -> None (db defaults to now)."""
    v = str(value or "").strip()
    if not v:
        return None
    return f"{v}T12:00:00" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else v


def load_events(data) -> list[dict]:
    """Coerce the parsed JSON into a list of write-ops (list or {"events": [...]})."""
    if isinstance(data, dict):
        data = data.get("events", [])
    if not isinstance(data, list):
        raise ValueError('expected a JSON list of events or {"events": [...]}')
    return data


def ingest_events(path, conn=None) -> dict:
    """Apply a JSON list of write ops to applications. One op per item, dispatched by
    the fields present: status -> set_application_status; else fields -> update_application_fields;
    else kind -> add_event. Lenient: skip + report. Returns a summary."""
    own = conn is None
    conn = conn or db.connect()
    try:
        entries = load_events(json.loads(Path(path).read_text()))
        known = {r["job_id"] for r in conn.execute("SELECT job_id FROM jobs").fetchall()}
        written, errors, unknown = 0, [], set()
        for i, e in enumerate(entries):
            if not isinstance(e, dict):
                errors.append(f"entry {i}: not an object")
                continue
            jid = str(e.get("job_id", "")).strip()
            if not jid:
                errors.append(f"entry {i}: missing job_id")
                continue
            when = _norm_date(e.get("date"))
            if jid not in known:
                unknown.add(jid)
            # (a) status change — the funnel choke-point (records status_change itself)
            if e.get("status"):
                db.set_application_status(conn, jid, str(e["status"]), now=when)
                written += 1
                continue
            # (b) structured fields patch
            if isinstance(e.get("fields"), dict):
                updated = db.update_application_fields(conn, jid, e["fields"], now=when)
                if updated is None:
                    errors.append(f"entry {i} (job {jid}): no application to patch")
                else:
                    written += 1
                continue
            # (c) timeline event
            kind = str(e.get("kind", "")).strip()
            if kind in _EVENT_KINDS:
                meta = e.get("meta")
                meta_s = json.dumps(meta, ensure_ascii=False) if isinstance(meta, dict) else ""
                db.add_event(conn, jid, kind, body=str(e.get("body", "") or ""),
                             meta=meta_s, now=when)
                written += 1
                continue
            errors.append(f"entry {i} (job {jid}): no actionable op "
                          "(need status, fields, or kind in note/interview/next_action)")
        return {"written": written, "skipped": len(errors), "errors": errors,
                "unknown_job_ids": sorted(unknown)}
    finally:
        if own:
            conn.close()
