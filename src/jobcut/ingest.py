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
- `ingest_documents` (prep-docs, `jobcut ingest-documents`): prep/debrief/study markdown
  attached to an application, optionally anchored to a timeline ``event_id``. Payload is
  ``{"documents": [...], "archive": [...]}``; idempotent per ``client_key``; raw ids only
  (the assistant resolves company/title/round agent-side). Read-only in the console.

Invalid items are skipped and reported; the rest are written.
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

from . import db

_REASON_MAX = 240
_SKILL_MAX = 80      # per skill name
_NOTE_MAX = 160      # per skill note
_SKILLS_MAX = 20     # skills per list


def _norm_skill_list(v) -> str:
    """A per-offer skill list from a scores entry → compact JSON-in-TEXT for the DB.

    Lenient: each item may be a bare name ("Python") or an object ({skill, note}). Free-form
    — skills need not be in the taxonomy. "" when there's nothing usable, so an entry that
    omits skills stays empty (and the API falls back to the taxonomy-regex match).
    """
    if not isinstance(v, list):
        return ""
    items = []
    for it in v:
        if isinstance(it, str):
            sk = it.strip()
            note = ""
        elif isinstance(it, dict):
            sk = str(it.get("skill", "")).strip()
            note = str(it.get("note", "") or "").strip()
        else:
            continue
        if not sk:
            continue
        obj = {"skill": sk[:_SKILL_MAX]}
        if note:
            obj["note"] = note[:_NOTE_MAX]
        items.append(obj)
    return json.dumps(items[:_SKILLS_MAX], ensure_ascii=False) if items else ""


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
            "skills_matched": _norm_skill_list(e.get("skills_matched")),
            "skills_missing": _norm_skill_list(e.get("skills_missing")),
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


# --- salary estimates (B-15) ------------------------------------------------

def _normalize_salary(entries: list[dict], today: str, source: str = "cowork_web") -> tuple[list[dict], list[str]]:
    """Validate entries into SALARY_ESTIMATE_COLS rows; return (rows, errors). Lenient:
    skip + report. Each needs a job_id and at least one numeric bound (est_min/est_max)."""
    def _num(e: dict, key: str):
        v = e.get(key)
        if v in (None, ""):
            return None
        try:
            return int(round(float(v)))
        except (TypeError, ValueError):
            return "ERR"

    rows, errors = [], []
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            errors.append(f"entry {i}: not an object")
            continue
        jid = str(e.get("job_id", "")).strip()
        if not jid:
            errors.append(f"entry {i}: missing job_id")
            continue
        emin, emax = _num(e, "est_min"), _num(e, "est_max")
        if emin == "ERR" or emax == "ERR":
            errors.append(f"entry {i} (job {jid}): est_min/est_max must be numeric")
            continue
        if emin is None and emax is None:
            errors.append(f"entry {i} (job {jid}): needs est_min and/or est_max")
            continue
        if emin is not None and emax is not None and emin > emax:
            emin, emax = emax, emin  # tolerate swapped bounds
        cur = str(e.get("currency") or "").strip().upper() or None
        rows.append({
            "job_id": jid,
            "est_min": emin,
            "est_max": emax,
            "currency": cur,
            "period": str(e.get("period") or "year"),
            "basis": str(e.get("basis", "") or "")[:_REASON_MAX],
            "source": str(e.get("source") or source),
            "estimated_at": str(e.get("estimated_at") or today),
        })
    return rows, errors


def ingest_salary(path, conn=None, source: str = "cowork_web") -> dict:
    """Read a salary-estimate JSON file and upsert it. Returns a summary dict.

    Shape: a list of {job_id, est_min?, est_max?, currency?, period?, basis?} or
    {"estimates": [...]}. Writes only to salary_estimates (never the disclosed
    jobs.salary_*), tagged `source` (default cowork_web — ingest is the Cowork bridge).
    """
    own = conn is None
    conn = conn or db.connect()
    try:
        today = datetime.date.today().isoformat()
        data = json.loads(Path(path).read_text())
        entries = data.get("estimates", []) if isinstance(data, dict) else data
        if not isinstance(entries, list):
            entries = []
        rows, errors = _normalize_salary(entries, today, source)

        known = {r["job_id"] for r in conn.execute("SELECT job_id FROM jobs").fetchall()}
        unknown = sorted({r["job_id"] for r in rows if r["job_id"] not in known})

        n = db.upsert_salary_estimates(conn, rows)
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


# --- prep documents (B-21, prep-docs) ---------------------------------------

def load_documents(data) -> tuple[list[dict], list[dict]]:
    """Coerce the parsed JSON into (documents, archive_ops).

    Accepts ``{"documents": [...], "archive": [...]}`` or a bare list (treated as
    ``documents`` with no archive ops). Raises ValueError on a non-list/dict payload.
    """
    if isinstance(data, list):
        return data, []
    if isinstance(data, dict):
        docs = data.get("documents", [])
        arch = data.get("archive", [])
        if not isinstance(docs, list):
            docs = []
        if not isinstance(arch, list):
            arch = []
        return docs, arch
    raise ValueError('expected a JSON list of documents or {"documents": [...], "archive": [...]}')


def ingest_documents(path, conn=None) -> dict:
    """Ingest prep/debrief/study documents and archive ops. Raw ids only — the assistant
    resolves company/title/round to job_id/event_id agent-side (like jobcut-track), never here.

    Each document needs a non-empty ``job_id``, ``title`` and ``body``. ``doc_type`` is
    coerced to db.DOC_TYPES; ``client_key`` makes re-ingest idempotent; ``meta`` (dict) is
    JSON-encoded. A given ``event_id`` must belong to ``job_id`` (else the entry is skipped —
    never silently mis-link a doc to another offer's round). Archive ops set/clear a doc's
    soft-delete: ``{"doc_id": N, "restore": false}``. Lenient: skip + report. Returns a summary.
    """
    return ingest_documents_data(json.loads(Path(path).read_text()), conn)


def ingest_documents_data(data, conn=None) -> dict:
    """Core of `ingest_documents`, but from already-parsed data (a list or
    ``{"documents": [...], "archive": [...]}``) instead of a file path. Lets in-process
    callers — the docs-inbox importer (`docsinbox`) — reuse the exact same validation,
    idempotency and reporting without round-tripping through a temp JSON file.
    """
    own = conn is None
    conn = conn or db.connect()
    try:
        documents, archive_ops = load_documents(data)
        known = {r["job_id"] for r in conn.execute("SELECT job_id FROM jobs").fetchall()}
        written, archived, errors, unknown = 0, 0, [], set()

        for i, e in enumerate(documents):
            if not isinstance(e, dict):
                errors.append(f"document {i}: not an object")
                continue
            jid = str(e.get("job_id", "")).strip()
            if not jid:
                errors.append(f"document {i}: missing job_id")
                continue
            title = str(e.get("title", "") or "").strip()
            body = str(e.get("body", "") or "")
            if not title or not body.strip():
                errors.append(f"document {i} (job {jid}): missing title or body")
                continue
            event_id = e.get("event_id")
            if event_id is not None:
                try:
                    event_id = int(event_id)
                except (TypeError, ValueError):
                    errors.append(f"document {i} (job {jid}): event_id must be an integer")
                    continue
                owns = conn.execute(
                    "SELECT 1 FROM application_events WHERE event_id = ? AND job_id = ?",
                    (event_id, jid),
                ).fetchone()
                if owns is None:
                    errors.append(f"document {i} (job {jid}): event_id {event_id} "
                                  "is not an event of this application")
                    continue
            if jid not in known:
                unknown.add(jid)
            meta = e.get("meta")
            meta_s = json.dumps(meta, ensure_ascii=False) if isinstance(meta, dict) else ""
            db.upsert_document(
                conn, job_id=jid, title=title, body=body, event_id=event_id,
                doc_type=str(e.get("doc_type") or "prep"),
                supersedes_id=e.get("supersedes_id"),
                client_key=(str(e["client_key"]) if e.get("client_key") else None),
                meta=meta_s,
            )
            written += 1

        for i, op in enumerate(archive_ops):
            if not isinstance(op, dict) or op.get("doc_id") is None:
                errors.append(f"archive {i}: missing doc_id")
                continue
            try:
                did = int(op["doc_id"])
            except (TypeError, ValueError):
                errors.append(f"archive {i}: doc_id must be an integer")
                continue
            restore = bool(op.get("restore"))
            res = db.set_document_archived(conn, did, archived=not restore)
            if res is None:
                errors.append(f"archive {i}: no document with doc_id {did}")
            else:
                archived += 1

        return {"written": written, "archived": archived, "skipped": len(errors),
                "errors": errors, "unknown_job_ids": sorted(unknown)}
    finally:
        if own:
            conn.close()
