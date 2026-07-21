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


def test_unscored_include_scored_keeps_scored_with_description():
    conn = db.connect()
    _seed(conn)
    rows = _filter.unscored(conn, include_scored=True)
    by_id = {r["job_id"]: r for r in rows}
    assert "3" in by_id                       # already-scored funnel job now included
    assert by_id["3"]["description"] == "already scored"  # full text, not dropped
    assert "2" not in by_id                    # foreign still excluded (still funnel-gated)
    for r in rows:
        assert REQUIRED <= set(r)
        assert all(isinstance(v, str) for v in r.values())
    conn.close()


def test_unscored_ids_returns_exactly_those_with_description():
    conn = db.connect()
    _seed(conn)
    rows = _filter.unscored(conn, ids=["2", "3"])
    by_id = {r["job_id"]: r for r in rows}
    assert set(by_id) == {"2", "3"}            # foreign(2) + scored(3), funnel/scored ignored
    assert by_id["2"]["description"] == "foreign role"
    assert by_id["3"]["description"] == "already scored"
    for r in rows:
        assert REQUIRED <= set(r)
        assert all(isinstance(v, str) for v in r.values())
    conn.close()


def test_unscored_needs_backend_surfaces_floored_but_not_claude():
    """The rule_based floor makes a new job 'scored', so a plain `unscored` hides it.
    `needs_backend="claude_skills"` must resurface floored + never-scored jobs (they still
    need Claude) while leaving jobs Claude already scored alone."""
    conn = db.connect()
    jobs = {
        "10": _job("10", title="Data Analyst", company_name="A", location="Madrid, Spain",
                   workplace_type="remote", description="floored by rule_based"),
        "11": _job("11", title="Data Analyst", company_name="B", location="Madrid, Spain",
                   workplace_type="remote", description="already claude-scored"),
        "12": _job("12", title="Data Analyst", company_name="C", location="Madrid, Spain",
                   workplace_type="remote", description="never scored"),
    }
    db.upsert_jobs(conn, jobs, "2026-01-01")
    db.upsert_scores(conn, [
        {"job_id": "10", "canonical_id": "", "match_score": 55, "match_reasons": "floor",
         "status": "scored", "scored_date": "2026-01-02", "backend": "rule_based"},
        {"job_id": "11", "canonical_id": "", "match_score": 90, "match_reasons": "claude",
         "status": "scored", "scored_date": "2026-01-02", "backend": "claude_skills"},
    ])
    # plain unscored: 10 (rule_based) and 11 (claude) both count as scored -> only 12
    assert {r["job_id"] for r in _filter.unscored(conn)} == {"12"}
    # needs claude: floored(10) + never-scored(12); claude-scored(11) excluded
    got = _filter.unscored(conn, needs_backend="claude_skills")
    assert {r["job_id"] for r in got} == {"10", "12"}
    assert {r["job_id"]: r for r in got}["10"]["description"] == "floored by rule_based"
    conn.close()


def test_unscored_cli_needs_backend():
    conn = db.connect()
    db.upsert_jobs(conn, {"20": _job("20", title="Data Analyst", company_name="A",
                                     location="Madrid, Spain", workplace_type="remote",
                                     description="floored")}, "2026-01-01")
    db.upsert_scores(conn, [{"job_id": "20", "canonical_id": "", "match_score": 50,
                             "match_reasons": "floor", "status": "scored",
                             "scored_date": "2026-01-02", "backend": "rule_based"}])
    conn.close()
    from jobcut.cli import main
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["unscored", "--needs-backend", "claude_skills", "--json"])
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert {r["job_id"] for r in out} == {"20"}      # rule_based floor still needs Claude
    # a plain unscored would hide it
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["unscored", "--json"])
    assert json.loads(buf.getvalue()) == []


def test_unscored_cli_include_scored_and_ids():
    conn = db.connect()
    _seed(conn)
    conn.close()
    from jobcut.cli import main
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["unscored", "--include-scored", "--json"])
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert "3" in {r["job_id"] for r in out}   # scored job surfaced for re-score

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["unscored", "--ids", "1,3", "--json"])
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert {r["job_id"] for r in out} == {"1", "3"}
    assert all(r["description"] for r in out)  # non-empty descriptions


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
