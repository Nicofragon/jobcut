"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import jobcut

from .routers import (
    applications,
    cv,
    jobs,
    market,
    runs,
    schedule,
    scoring,
    searches,
    settings,
    update,
)


def web_build_dir() -> Path | None:
    """The exported Next.js build (web/out), if present in a clone/editable install."""
    d = Path(jobcut.__file__).resolve().parents[2] / "web" / "out"
    return d if d.is_dir() else None


class _Console(StaticFiles):
    """Static console that revalidates HTML but lets hashed assets cache forever.

    Without this, browsers heuristically cache the HTML documents, so after a
    rebuild (e.g. a `git pull` + new build) the old page keeps showing. The HTML
    references content-hashed chunks, so `no-cache` on HTML (revalidate every
    load) + `immutable` on `/_next/static/*` gives instant updates with no stale UI.
    """

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        ct = resp.headers.get("content-type", "")
        if ct.startswith("text/html"):
            resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        elif "/_next/static/" in scope.get("path", ""):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp


def mount_web(app: FastAPI, directory: Path) -> None:
    """Serve the static console at / (registered after the API routers)."""
    app.mount("/", _Console(directory=str(directory), html=True), name="web")


def create_app(serve_web: bool = True) -> FastAPI:
    app = FastAPI(
        title="jobcut API",
        version="0.1.0",
        description="Thin FastAPI bridge over the jobcut package (local-first).",
    )
    # Local-first single user: the Next.js dev server runs on another port.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for r in (settings.router, jobs.router, applications.router,
              searches.router, market.router, runs.router, cv.router,
              scoring.router, schedule.router, update.router):
        app.include_router(r, prefix="/api")

    @app.get("/api/health")
    def health() -> dict:
        """Liveness + which code revision this process is running.

        `serve` stamps JOBCUT_RUNNING_SHA with the checkout sha it started on. The
        desktop launcher reads `running_sha` to decide reuse-vs-replace: after a
        `git pull` the checkout moves ahead of a still-running server, so the launcher
        knows to replace it (loading the new code) instead of just reopening the old one.
        """
        import os

        return {"ok": True, "running_sha": os.environ.get("JOBCUT_RUNNING_SHA") or None}

    # When a static build exists, `jobcut serve` is a single process (no Node).
    if serve_web:
        build = web_build_dir()
        if build:
            mount_web(app, build)
    return app


app = create_app()
