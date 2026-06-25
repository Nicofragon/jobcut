"""Applications CRUD + status + funnel (the core loop)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ... import db, process, status as status_mod
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
    return db.add_event(conn, job_id, body.kind, body=body.body, meta=body.meta)


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
