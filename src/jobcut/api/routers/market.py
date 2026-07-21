"""Market gaps — demand vs profile (Discovery section).

The Discovery payload is expensive to compute (regex skill-matching over every
relevant offer's full description — seconds on a few thousand rows), but it only
changes when the underlying data does: a pull (new/updated jobs), a score, or a
kit/taxonomy edit. So we compute it once per data-state and serve a cache on every
repeat load. The cache key is a cheap DB+taxonomy signature; an in-process cache
makes repeat navigations instant, and a disk cache (`out/market-cache.json`) both
survives a restart and lets the daily pipeline warm it so even the first load is
fast. Any pull/score/edit changes the signature and transparently recomputes.
"""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends

from ... import config, db, paths
from ... import market as market_mod
from ... import surface
from ..deps import get_conn

router = APIRouter(prefix="/market", tags=["market"])

# In-process cache: {"sig": [...], "payload": {...}}. Persisted to disk too (below).
_CACHE: dict = {}


def _signature(conn: sqlite3.Connection) -> list[str]:
    """Cheap fingerprint of everything the Discovery payload depends on.

    Changes on a pull (jobs count / MAX(last_seen)), a score (scores count /
    MAX(scored_date) / SUM(match_score) — the sum catches same-day re-scores that
    keep the count and date), and a kit edit (taxonomy.json mtime).
    """
    row = conn.execute(
        "SELECT (SELECT COUNT(*) FROM jobs), "
        "(SELECT COALESCE(MAX(last_seen), '') FROM jobs), "
        "(SELECT COUNT(*) FROM scores), "
        "(SELECT COALESCE(MAX(scored_date), '') FROM scores), "
        "(SELECT COALESCE(SUM(match_score), 0) FROM scores)"
    ).fetchone()
    tax = config.taxonomy_file()
    tax_mtime = tax.stat().st_mtime if tax.exists() else 0.0
    return [*(str(x) for x in row), f"{tax_mtime:.3f}"]


def _cache_path():
    return paths.out_dir() / "market-cache.json"


def _compute_payload(conn: sqlite3.Connection) -> dict:
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


def _payload(conn: sqlite3.Connection) -> dict:
    """Cached Discovery payload — recomputes only when the DB/taxonomy signature changes."""
    sig = _signature(conn)
    if _CACHE.get("sig") == sig and _CACHE.get("payload") is not None:
        return _CACHE["payload"]

    # Cross-process / cross-restart: a disk cache warmed by the daily pipeline (or a
    # prior run) serves the live server instantly without recomputing.
    path = _cache_path()
    if path.exists():
        try:
            disk = json.loads(path.read_text())
            if disk.get("sig") == sig:
                _CACHE["sig"], _CACHE["payload"] = sig, disk["payload"]
                return disk["payload"]
        except Exception:
            pass  # corrupt/old cache — just recompute

    payload = _compute_payload(conn)
    _CACHE["sig"], _CACHE["payload"] = sig, payload
    try:
        path.write_text(json.dumps({"sig": sig, "payload": payload}, default=str))
    except Exception:
        pass  # cache is an optimization, never fail the request over it
    return payload


def warm(conn: sqlite3.Connection | None = None) -> dict:
    """Precompute + persist the Discovery cache. Called by the daily pipeline so the
    first Discovery load after a pull/score is instant instead of multi-second."""
    own = conn is None
    conn = conn or db.connect()
    try:
        return _payload(conn)
    finally:
        if own:
            conn.close()


@router.get("")
def get_market(conn: sqlite3.Connection = Depends(get_conn)):
    """Read-only market summary (no file writes beyond the cache). Empty payload when no jobs."""
    return _payload(conn)


@router.post("")
def regenerate_market(conn: sqlite3.Connection = Depends(get_conn)):
    """Regenerate out/market-* artifacts (+ append today's history snapshot), then return
    the same payload GET returns — so the refresh button never changes the shape."""
    market_mod.main(conn)
    _CACHE.clear()          # main() appends a history snapshot → trend changes; force recompute
    return _payload(conn)
