"""Market gaps — demand vs profile (Discovery section)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from ... import market as market_mod
from ..deps import get_conn

router = APIRouter(prefix="/market", tags=["market"])


@router.get("")
def get_market(conn: sqlite3.Connection = Depends(get_conn)):
    """Read-only market summary (no file writes). Empty payload when no jobs yet."""
    data = market_mod.summary(conn)
    if data is None:
        return {"total": 0, "relevant": 0, "segments": {}, "top_demand": [],
                "gaps": [], "salary_pct": 0, "empty": True}
    return data


@router.post("")
def regenerate_market(conn: sqlite3.Connection = Depends(get_conn)):
    """Regenerate out/market-* artifacts and return the summary."""
    return market_mod.main(conn) or {"empty": True}
