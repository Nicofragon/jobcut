"""Tests for the application-tracker loader/classifier."""

import pytest

from jobcut import tracker


@pytest.mark.parametrize("status,expected", [
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
])
def test_classify(status, expected):
    assert tracker.classify(status) == expected


def test_load_and_summarize_from_csv(tmp_path, monkeypatch):
    csv = tmp_path / "tracker.csv"
    csv.write_text(
        "Company,Role Title,Tier,LinkedIn URL,Status,Date Applied\n"
        "Acme,Data Analyst,1,https://www.linkedin.com/jobs/view/1,Applied - active,2026-06-01\n"
        "Globex,Product Analyst,2,,R1 interview ✅,2026-06-08\n"
        "Initech,BI Analyst,3,https://x/2,Rejected,2026-05-20\n"
        ",,,,,\n"  # blank row must be dropped
    )
    monkeypatch.setenv("JOBCUT_TRACKER", str(csv))

    df = tracker.load()
    assert len(df) == 3                       # blank row dropped
    # every cell is a real str (no NaN floats leaking through)
    assert all(isinstance(x, str) for col in df.columns for x in df[col])
    assert df[df.company == "Globex"].iloc[0].url == ""   # blank URL -> ""
    assert set(df.category) == {"Active", "Interview", "Rejected"}

    s = tracker.summarize(df)
    assert s["total"] == 3
    assert s["live"] == 2                      # Active + Interview
    assert s["interview"] == 1
    assert s["rejected"] == 1
    assert s["funnel"][0] == ("Applied", 3, "#58a6ff")
    assert len(s["by_week"]) >= 1


def test_load_empty_when_no_tracker(monkeypatch):
    monkeypatch.delenv("JOBCUT_TRACKER", raising=False)
    df = tracker.load()
    assert df.empty
    assert list(df.columns) == ["company", "role", "tier", "url", "status", "date", "category"]
