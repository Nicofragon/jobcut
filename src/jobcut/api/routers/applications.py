"""Applications CRUD + status + funnel (the core loop)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ... import db, ingest, process, status as status_mod
from ..deps import get_conn

router = APIRouter(prefix="/applications", tags=["applications"])


class StatusIn(BaseModel):
    status: str
    notes: str | None = None
    source: str = "manual"


class EventIn(BaseModel):
    kind: str = "note"
    body: str = ""
    meta: str = ""


class FieldsIn(BaseModel):
    priority: str | None = None
    next_action: str | None = None
    next_action_date: str | None = None
    contact: str | None = None
    cv_version: str | None = None


class ProcessIn(BaseModel):
    stages: list[str]
    current: int | None = None


class AdvanceIn(BaseModel):
    note: str = ""
    date: str | None = None


class ManualJobIn(BaseModel):
    url: str = ""
    company: str = ""
    title: str = ""
    location: str = ""
    description: str = ""
    status: str = "applied"


# Caller-writable event kinds (status_change is internal — written by set_status only).
EVENT_KINDS = {"note", "interview", "next_action"}


@router.get("")
def list_applications(conn: sqlite3.Connection = Depends(get_conn)):
    # Enriched with each job's title/company (server-side join) so the console
    # renders in ONE call instead of fetching every job separately (old N+1).
    df = db.read_applications_enriched(conn)
    if df.empty:
        return []
    # All-NULL columns (e.g. the v5 structured fields) come back from pandas as
    # float NaN, which isn't JSON-serializable — coerce to None before returning.
    records = df.astype(object).where(df.notna(), None).to_dict("records")
    # Phase 3: enrich each row with time-in-stage + stalled flag (derived from the
    # status-change timeline) so the console can surface "needs attention" client-side.
    durations = db.stage_durations(conn)
    for r in records:
        d = durations.get(str(r["job_id"]), {})
        r["days_in_stage"] = d.get("days_in_stage")
        r["stalled"] = bool(d.get("stalled"))
        r["dormant"] = bool(d.get("dormant"))
    return records


@router.get("/funnel")
def funnel(conn: sqlite3.Connection = Depends(get_conn)):
    return db.application_funnel(conn)


@router.get("/statuses")
def statuses():
    """The canonical status vocabulary the dashboard writes."""
    return {"statuses": status_mod.STATUSES, "categories": status_mod.CATEGORIES}


@router.get("/interview-funnel")
def interview_funnel(conn: sqlite3.Connection = Depends(get_conn)):
    return db.interview_funnel(conn)


@router.get("/process-timing")
def process_timing_agg(conn: sqlite3.Connection = Depends(get_conn)):
    return db.process_timing_summary(conn)


@router.post("/manual")
def add_manual(body: ManualJobIn, conn: sqlite3.Connection = Depends(get_conn)):
    """Create an offer manually (source='manual') and link an application (the web
    "+ Add application" form). Returns the enriched application row (title/company)."""
    try:
        result = ingest.add_job(body.model_dump(exclude={"status"}), conn)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    jid = result["job_id"]
    db.set_application_status(conn, jid, body.status, source="manual")
    df = db.read_applications_enriched(conn)
    rows = df[df.job_id == str(jid)]
    if rows.empty:
        raise HTTPException(status_code=500, detail="application not found after create")
    rec = rows.astype(object).where(rows.notna(), None).to_dict("records")[0]
    return rec


@router.get("/{job_id}")
def get_one(job_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    app = db.get_application(conn, job_id)
    if app is None:
        raise HTTPException(status_code=404, detail="application not found")
    return app


@router.put("/{job_id}")
def set_status(job_id: str, body: StatusIn, conn: sqlite3.Connection = Depends(get_conn)):
    db.set_application_status(conn, job_id, body.status, notes=body.notes, source=body.source)
    return db.get_application(conn, job_id)


@router.patch("/{job_id}")
def patch_fields(job_id: str, body: FieldsIn, conn: sqlite3.Connection = Depends(get_conn)):
    """Update structured tracking fields without touching status (PATCH semantics:
    only fields present in the body are changed)."""
    fields = body.model_dump(exclude_unset=True)
    updated = db.update_application_fields(conn, job_id, fields)
    if updated is None:
        raise HTTPException(status_code=404, detail="application not found")
    return updated


@router.delete("/{job_id}")
def delete(job_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    n = db.delete_application(conn, job_id)
    if n == 0:
        raise HTTPException(status_code=404, detail="application not found")
    return {"deleted": job_id}


@router.get("/{job_id}/events")
def list_events(job_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    """The application's timeline (status changes + notes + rounds), most-recent first."""
    return db.get_events(conn, job_id)


@router.post("/{job_id}/events")
def post_event(job_id: str, body: EventIn, conn: sqlite3.Connection = Depends(get_conn)):
    """Append a timeline event. A note needs no status — the solo-note write-path
    that never fabricates an 'applied' application."""
    if body.kind not in EVENT_KINDS:
        raise HTTPException(status_code=422, detail=f"kind must be one of {sorted(EVENT_KINDS)}")
    # Same round-identity rule as the CLI bridge: one row per interview round, and the
    # plan pointer follows. Every write path has to agree or the funnel drifts again.
    if body.kind == "interview":
        return db.record_interview_round(conn, job_id, body=body.body, meta=body.meta)
    return db.add_event(conn, job_id, body.kind, body=body.body, meta=body.meta)


@router.get("/{job_id}/documents")
def list_documents(job_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    """Prep/debrief/study documents for this application (excludes archived). Bodies are
    small markdown, so the list carries them — no second round-trip to open one. Read-only;
    writes go through the `ingest-documents` CLI bridge, never the API."""
    return db.get_documents(conn, job_id)


@router.get("/{job_id}/documents/{doc_id}")
def get_document(job_id: str, doc_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    """One document including its body. 404s if it's absent or belongs to another offer."""
    doc = db.get_document(conn, doc_id)
    if doc is None or doc["job_id"] != job_id:
        raise HTTPException(status_code=404, detail="document not found")
    return doc


@router.put("/{job_id}/process")
def set_process(job_id: str, body: ProcessIn, conn: sqlite3.Connection = Depends(get_conn)):
    updated = db.set_process(conn, job_id, body.stages, current=body.current)
    if updated is None:
        raise HTTPException(status_code=404, detail="application not found")
    return updated


@router.post("/{job_id}/process/suggest")
def suggest_process(job_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    job = db.get_job_row(conn, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    stages, source = process.extract_process(job["description"] or "")
    return {"stages": stages, "source": source}


@router.post("/{job_id}/process/advance")
def advance_process(job_id: str, body: AdvanceIn, conn: sqlite3.Connection = Depends(get_conn)):
    result = db.advance_process(conn, job_id, note=body.note, date=body.date)
    if result is None:
        raise HTTPException(status_code=404, detail="application or process not found")
    return result


@router.get("/{job_id}/process/timing")
def process_timing(job_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    # Returns the timing dict, or null when the job has no application / fewer than two
    # rounds. NOT a 404 for "no application": the job detail page opens this for shortlist
    # roles you haven't applied to yet, and a 404 there would break the whole page.
    return db.process_timing(conn, job_id)  # dict or null
