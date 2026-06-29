"""Update jobcut from the repo (B-20): localhost-only endpoints over update.run_update.

`jobcut serve` binds 127.0.0.1, so these are reachable only from the user's machine —
the same posture as the build step `serve` already runs on startup. GET inspects the
checkout (clean? which sha?); POST does the pull + rebuild.
"""
from fastapi import APIRouter

from ... import update as _update

router = APIRouter(prefix="/update", tags=["update"])


@router.get("")
def update_status() -> dict:
    """Pre-flight: is this a git checkout, on which branch/sha, and is the tree clean?"""
    return _update.preflight()


@router.post("")
def do_update() -> dict:
    """Pull the latest code and rebuild the console. Blocks on a dirty tree (non-destructive)."""
    return _update.run_update()
