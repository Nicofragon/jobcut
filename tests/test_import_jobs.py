"""Tests for `jobcut import-jobs` — injecting scraped rows into SQLite (A4.1)."""

import json

import pytest

from jobcut import config, db, ingest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(tmp_path))
    config.reset_cache()
    yield
    config.reset_cache()


def _write(tmp_path, data):
    p = tmp_path / "jobs.json"
    p.write_text(json.dumps(data))
    return str(p)


def test_import_flattened_rows(tmp_path):
    conn = db.connect()
    path = _write(tmp_path, [
        {"job_id": "100", "title": "Data Analyst", "company_name": "Acme", "location": "Madrid, Spain"},
    ])
    summary = ingest.import_jobs(path, conn)
    assert summary == {"new": 1, "updated": 0, "skipped": 0, "invalid": 0}
    row = db.read_jobs(conn).iloc[0]
    assert row.job_id == "100" and row.title == "Data Analyst" and row.company_name == "Acme"
    conn.close()


def test_import_nested_actor_rows(tmp_path):
    conn = db.connect()
    item = {"id": "200", "title": "ML Engineer",
            "company": {"name": "Globex", "employeeCount": "500"},
            "location": {"linkedinText": "Remote"}, "descriptionText": "PyTorch and SQL"}
    summary = ingest.import_jobs(_write(tmp_path, [item]), conn)
    assert summary["new"] == 1 and summary["invalid"] == 0
    row = db.read_jobs(conn).iloc[0]
    assert row.job_id == "200" and row.title == "ML Engineer" and row.company_name == "Globex"
    assert "PyTorch" in row.description
    conn.close()


def test_import_envelope_and_mixed_formats(tmp_path):
    conn = db.connect()
    data = {"jobs": [
        {"job_id": "1", "title": "Flat One"},
        {"id": "2", "title": "Nested Two", "company": {"name": "X"}},
    ]}
    summary = ingest.import_jobs(_write(tmp_path, data), conn)
    assert summary["new"] == 2
    assert set(db.read_jobs(conn).job_id) == {"1", "2"}
    conn.close()


def test_import_dedupes_within_file(tmp_path):
    conn = db.connect()
    data = [{"job_id": "5", "title": "A"}, {"job_id": "5", "title": "B"}]
    summary = ingest.import_jobs(_write(tmp_path, data), conn)
    assert summary["new"] == 1 and summary["skipped"] == 1
    assert db.count_jobs(conn) == 1
    conn.close()


def test_import_dedupes_across_imports_and_updates(tmp_path):
    conn = db.connect()
    ingest.import_jobs(_write(tmp_path, [{"job_id": "7", "title": "First", "source_searches": "a"}]), conn)
    summary = ingest.import_jobs(
        _write(tmp_path, [{"job_id": "7", "title": "Second", "source_searches": "b", "applicants": "3"}]), conn)
    assert summary == {"new": 0, "updated": 1, "skipped": 0, "invalid": 0}
    row = db.read_jobs(conn).iloc[0]
    assert row.title == "First"                              # stable field not overwritten (pull semantics)
    assert set(row.source_searches.split("|")) == {"a", "b"}  # sources unioned
    assert str(row.applicants) == "3"                        # volatile refreshed
    conn.close()


def test_import_skips_invalid_entries(tmp_path):
    conn = db.connect()
    data = [{"title": "no id"}, "a bare string", {"id": "", "title": "empty id"}, {"job_id": "9", "title": "ok"}]
    summary = ingest.import_jobs(_write(tmp_path, data), conn)
    assert summary["new"] == 1 and summary["invalid"] == 3
    assert set(db.read_jobs(conn).job_id) == {"9"}
    conn.close()


def test_import_bad_shape_raises(tmp_path):
    conn = db.connect()
    with pytest.raises(ValueError):
        ingest.import_jobs(_write(tmp_path, "not a list or jobs-envelope"), conn)
    conn.close()
