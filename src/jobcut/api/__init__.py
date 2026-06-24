"""FastAPI bridge over the jobcut package (PRD §8.2).

A thin backend that imports the Python core and exposes it to the Next.js console.
The package + SQLite remain the single source of truth; this layer adds no business
logic of its own. See docs/ADR-001 for the architecture.
"""

from .app import create_app

__all__ = ["create_app"]
