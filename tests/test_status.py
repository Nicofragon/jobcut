"""Tests for status.py — the shared classification + funnel math."""

import pandas as pd
import pytest

from jobcut import status


@pytest.mark.parametrize("text,expected", [
    ("Applied - reviewing", "Reviewing"),
    ("Rejected — other candidates", "Rejected"),
    ("R1 RECRUITER SCREEN ✅", "Interview"),
    ("Screen scheduled 12/06", "Screen"),
    ("Applied - active", "Active"),
    ("Applied - closed", "Closed"),
    ("Stale", "No response"),
    ("Applied — sent", "Applied"),
    ("Descartada (decisión propia)", "Withdrawn"),
    ("", "Other"),
    # new Offer handling
    ("Verbal offer", "Offer"),
    ("Offer received 🎉", "Offer"),
    ("Oferta firmada", "Offer"),
])
def test_classify(text, expected):
    assert status.classify(text) == expected


def test_canonical_statuses_map_to_categories():
    """Every status the dashboard can send must classify to a real category."""
    expected = {
        "saved": "Saved",  # a real category, but deliberately non-funnel (status.NON_FUNNEL)
        "applied": "Applied", "screen": "Screen", "interview": "Interview",
        "offer": "Offer", "rejected": "Rejected", "withdrawn": "Withdrawn",
        "no_response": "No response",
    }
    assert set(status.STATUSES) == set(expected)
    for canonical, category in expected.items():
        assert status.classify(canonical) == category, canonical


def test_summarize_counts_offers():
    df = pd.DataFrame({
        "category": ["Applied", "Interview", "Offer", "Rejected"],
        "date": ["2026-06-01", "2026-06-05", "2026-06-10", "2026-05-20"],
        "status": ["applied", "interview", "offer", "rejected"],
    })
    s = status.summarize(df)
    assert s["total"] == 4
    assert s["offers"] == 1
    assert s["funnel"][3][0] == "Offer" and s["funnel"][3][1] == 1
