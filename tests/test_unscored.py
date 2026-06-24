"""Tests for `jobcut unscored --json` — hireable jobs that still need scoring (A4.2.0)."""

import json

import pytest

from jobcut import config, db, filter as _filter


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(tmp_path))
    config.reset_cache()
    yield
    config.reset_cache()


def _job(jid, **over):
    row = {c: "" for c in db.JOB_COLS}
    row.update(job_id=jid, first_seen="2026-01-01", last_seen="2026-01-01")
    row.update(over)
    return row


REQUIRED = {"job_id", "title", "company_name", "location", "workplace_type", "description"}


def _seed(conn):
    jobs = {
        # home + unscored -> included
        "1": _job("1", title="Data Analyst", company_name="Acme", location="Madrid, Spain",
                  workplace_type="hybrid", description="SQL and Python"),
        # foreign on-site -> not hireable -> excluded
        "2": _job("2", title="Data Analyst", company_name="Globex", location="Tokyo, Japan",
                  workplace_type="on_site", description="foreign role"),
        # home but already scored -> excluded
        "3": _job("3", title="ML Engineer", company_name="Initech", location="Madrid, Spain",
                  workplace_type="remote", description="already scored"),
        # region + remote -> hireable -> included
        "4": _job("4", title="BI Analyst", company_name="Umbrella", location="European Union",
                  workplace_type="remote", description="Power BI"),
    }
    db.upsert_jobs(conn, jobs, "2026-01-01")
    db.upsert_scores(conn, [{"job_id": "3", "canonical_id": "", "match_score": 80,
                             "match_reasons": "x", "status": "scored", "scored_date": "2026-01-01"}])


def test_unscored_excludes_scored_and_foreign():
    conn = db.connect()
    _seed(conn)
    rows = _filter.unscored(conn)
    assert {r["job_id"] for r in rows} == {"1", "4"}   # foreign(2) + scored(3) excluded
    conn.close()


def test_unscored_includes_description_and_stable_shape():
    conn = db.connect()
    _seed(conn)
    rows = _filter.unscored(conn)
    by_id = {r["job_id"]: r for r in rows}
    assert by_id["1"]["description"] == "SQL and Python"
    for r in rows:
        assert REQUIRED <= set(r)
        assert all(isinstance(v, str) for v in r.values())
    conn.close()


def test_unscored_empty_db_is_empty_list():
    conn = db.connect()
    assert _filter.unscored(conn) == []
    conn.close()


def test_unscored_cli_json():
    conn = db.connect()
    _seed(conn)
    conn.close()
    from jobcut.cli import main
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["unscored", "--json"])
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert sorted(r["job_id"] for r in out) == ["1", "4"]
    assert all(REQUIRED <= set(r) for r in out)
