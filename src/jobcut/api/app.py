"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import jobcut

from .routers import applications, cv, jobs, market, runs, schedule, scoring, searches, settings


def web_build_dir() -> Path | None:
    """The exported Next.js build (web/out), if present in a clone/editable install."""
    d = Path(jobcut.__file__).resolve().parents[2] / "web" / "out"
    return d if d.is_dir() else None


def mount_web(app: FastAPI, directory: Path) -> None:
    """Serve the static console at / (registered after the API routers)."""
    app.mount("/", StaticFiles(directory=str(directory), html=True), name="web")


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
              scoring.router, schedule.router):
        app.include_router(r, prefix="/api")

    # When a static build exists, `jobcut serve` is a single process (no Node).
    if serve_web:
        build = web_build_dir()
        if build:
            mount_web(app, build)
    return app


app = create_app()
