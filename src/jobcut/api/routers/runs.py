"""Long/costly pipeline runs (pull, score) with SSE progress."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ... import pull, score
from .. import runs

router = APIRouter(prefix="/runs", tags=["runs"])


class RunIn(BaseModel):
    kind: str                       # "pull" | "score"
    mode: str = "read"              # pull only: "read" (free) | "trigger" (paid)
    confirm: bool = False           # required for the paid path


def _runner(body: RunIn):
    if body.kind == "score":
        return lambda emit: score.run(progress=emit)
    if body.kind == "pull":
        argv = [] if body.mode == "trigger" else ["--read"]

        def pull_then_score(emit):
            # A pull on its own leaves the jobs unscored, so the shortlist looks
            # empty — score right after so "Find new jobs" lands a ranked list.
            pull.main(argv, progress=emit)
            score.run(progress=emit)

        return pull_then_score
    raise HTTPException(status_code=400, detail=f"unknown run kind: {body.kind!r}")


@router.post("")
def start(body: RunIn):
    # Cost guard: a paid Apify scrape requires explicit confirmation.
    if body.kind == "pull" and body.mode == "trigger" and not body.confirm:
        raise HTTPException(status_code=409, detail="confirmation_required: paid Apify run")
    run_id = runs.start_run(body.kind, _runner(body))
    return {"run_id": run_id, "kind": body.kind, "status": "running"}


@router.get("/{run_id}")
def status(run_id: str):
    rec = runs.get_run(run_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="unknown run_id")
    return rec


@router.get("/{run_id}/events")
def events(run_id: str):
    return StreamingResponse(runs.stream(run_id), media_type="text/event-stream")
