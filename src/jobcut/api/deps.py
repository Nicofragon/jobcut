"""Shared FastAPI dependencies."""

from __future__ import annotations

from .. import db


def get_conn():
    """Per-request SQLite connection (WAL is not safe to share across threads)."""
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()
