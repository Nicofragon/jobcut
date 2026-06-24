"""Scoring backends — read-only capability listing (for Settings/onboarding)."""

from __future__ import annotations

from fastapi import APIRouter

from ...scoring import backend_status

router = APIRouter(prefix="/scoring", tags=["scoring"])


@router.get("/backends")
def get_backends():
    """List the known scoring backends with availability/usability flags."""
    return backend_status()
