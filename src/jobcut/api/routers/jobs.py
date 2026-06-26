"""Shortlist + job detail (the 'Hoy' and 'Detalle' sections)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ... import db, surface
from ..deps import get_conn

router = APIRouter(tags=["jobs"])


@router.get("/shortlist")
def get_shortlist(
    min_score: int = 60,
    backlog_min: int = 75,
    q: str | None = None,
    location: str | None = None,
    recency_days: int | None = None,
    include_applied: bool = False,
    conn: sqlite3.Connection = Depends(get_conn),
):
    return surface.shortlist_data(
        conn, min_score=min_score, backlog_min=backlog_min, q=q, location=location,
        recency_days=recency_days, include_applied=include_applied,
    )


def _scrub_row(row) -> dict:
    return {k: (None if surface.blank(v) else str(v)) for k, v in dict(row).items()}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    # Targeted lookups by primary key — O(1). (Reading the whole jobs+scores tables
    # into pandas to find one row cost ~340ms on a 2k-row DB.)
    row = db.get_job_row(conn, job_id)
    srow = db.get_score_row(conn, job_id)
    application = db.get_application(conn, job_id)
    estrow = db.get_salary_estimate_row(conn, job_id)

    # Never 404 a row the user owns: an imported application (or a score) with no
    # jobs row still opens with job:null so notes + status stay reachable (KR-v2-5).
    if row is None and srow is None and application is None:
        raise HTTPException(status_code=404, detail="job not found")

    job = _scrub_row(row) if row is not None else None

    score = None
    if srow is not None:
        s = dict(srow)
        ms = s.get("match_score")
        score = {
            "match_score": int(ms) if str(ms).strip() not in ("", "nan", "None") else None,
            "match_reasons": None if surface.blank(s.get("match_reasons")) else str(s["match_reasons"]),
            "status": None if surface.blank(s.get("status")) else str(s["status"]),
            "scored_date": None if surface.blank(s.get("scored_date")) else str(s["scored_date"]),
            "backend": None if surface.blank(s.get("backend")) else str(s["backend"]),
        }

    salary_estimate = None
    if estrow is not None:
        e = dict(estrow)
        def _int(v):
            return int(v) if str(v).strip() not in ("", "None", "nan") else None
        salary_estimate = {
            "est_min": _int(e.get("est_min")),
            "est_max": _int(e.get("est_max")),
            "currency": None if surface.blank(e.get("currency")) else str(e["currency"]),
            "period": None if surface.blank(e.get("period")) else str(e["period"]),
            "basis": None if surface.blank(e.get("basis")) else str(e["basis"]),
            "source": None if surface.blank(e.get("source")) else str(e["source"]),
            "estimated_at": None if surface.blank(e.get("estimated_at")) else str(e["estimated_at"]),
        }

    return {"job": job, "score": score, "application": application, "salary_estimate": salary_estimate}
