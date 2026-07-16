"""Market gaps — demand vs profile (Discovery section)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from ... import market as market_mod
from ... import surface
from ..deps import get_conn

router = APIRouter(prefix="/market", tags=["market"])


def _payload(conn: sqlite3.Connection) -> dict:
    """The Discovery payload: enriched market summary + the score distribution.

    One shape for both GET and POST so the console never loses fields after a refresh.
    `market.summary` is pure (jobs/taxonomy); the score histogram comes from `surface`
    (the scored pipeline), composed here so `market.py` stays scores-free.
    """
    dist = surface.score_distribution(conn)
    shortlist_gaps = surface.shortlist_skill_gaps(conn)
    data = market_mod.summary(conn)
    if data is None:
        return {"total": 0, "relevant": 0, "segments": {}, "seg_keys": [],
                "coverage": {"pct": 0, "by_segment": {}}, "top_demand": [], "gaps": [],
                "salary_pct": 0, "score_distribution": dist,
                "freshness": {"n": 0, "median_age_days": 0, "weekly": []},
                "shortlist_gaps": shortlist_gaps, "empty": True}
    data["score_distribution"] = dist
    data["shortlist_gaps"] = shortlist_gaps
    return data


@router.get("")
def get_market(conn: sqlite3.Connection = Depends(get_conn)):
    """Read-only market summary (no file writes). Empty payload when no jobs yet."""
    return _payload(conn)


@router.post("")
def regenerate_market(conn: sqlite3.Connection = Depends(get_conn)):
    """Regenerate out/market-* artifacts (+ append today's history snapshot), then return
    the same payload GET returns — so the refresh button never changes the shape."""
    market_mod.main(conn)
    return _payload(conn)
