"""In-memory run registry + SSE for long/costly pipeline runs (pull, score).

A run executes a `runner(emit)` callable on a background thread. Progress events are
pushed onto a queue; the SSE endpoint drains it. Single-user local app, so an
in-process dict is enough (no persistence, no cross-process sharing).

Each runner opens its OWN db connection — the request-scoped connection is closed
when the POST returns, long before the background thread finishes.
"""

from __future__ import annotations

import json
import queue
import threading
import uuid
from typing import Callable

# run_id -> {kind, status, summary, error, queue}
_RUNS: dict[str, dict] = {}
_SENTINEL = object()


def start_run(kind: str, runner: Callable[[Callable[[dict], None]], dict]) -> str:
    """Start `runner` on a background thread. Returns a run_id immediately."""
    run_id = uuid.uuid4().hex
    q: queue.Queue = queue.Queue()
    rec = {"kind": kind, "status": "running", "summary": None, "error": None, "queue": q}
    _RUNS[run_id] = rec

    def emit(event: dict) -> None:
        q.put(event)

    def worker() -> None:
        try:
            summary = runner(emit)
            rec["summary"] = summary
            rec["status"] = "done"
            q.put({"event": "done", "summary": summary})
        except BaseException as exc:  # incl. SystemExit (pull.main calls sys.exit)
            rec["error"] = str(exc)
            rec["status"] = "error"
            q.put({"event": "error", "error": str(exc)})
        finally:
            q.put(_SENTINEL)

    threading.Thread(target=worker, name=f"run-{kind}-{run_id[:8]}", daemon=True).start()
    return run_id


def get_run(run_id: str) -> dict | None:
    rec = _RUNS.get(run_id)
    if rec is None:
        return None
    return {"run_id": run_id, "kind": rec["kind"], "status": rec["status"],
            "summary": rec["summary"], "error": rec["error"]}


def _sse(event: dict) -> str:
    name = event.get("event") or event.get("stage") or "progress"
    return f"event: {name}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


def stream(run_id: str):
    """Generator of SSE strings for a run. Ends after the terminal (done/error) event."""
    rec = _RUNS.get(run_id)
    if rec is None:
        yield _sse({"event": "error", "error": "unknown run_id"})
        return
    q: queue.Queue = rec["queue"]
    while True:
        item = q.get()
        if item is _SENTINEL:
            break
        yield _sse(item)
