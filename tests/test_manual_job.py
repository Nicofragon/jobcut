"""Tests for B-1 manual job entry: jobid derivation, ingest.add_job, the
`add-job` CLI, the POST /applications/manual endpoint, and surface exclusion."""

import pytest
from fastapi.testclient import TestClient

from jobcut import config, db, ingest, jobid, surface
from jobcut.api import create_app
from jobcut.cli import main


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


# --- jobid derivation -------------------------------------------------------

def test_jobid_linkedin_url_numeric():
    assert jobid.job_id_from_url("https://www.linkedin.com/jobs/view/4414046061") == "4414046061"
    assert jobid.job_id_from_url("https://www.linkedin.com/jobs/search/?currentJobId=3987654321") == "3987654321"


def test_jobid_ats_url_slug():
    assert jobid.job_id_from_url("https://jobs.globex.com/jobs/senior-ba-inventory/") == "globex-senior-ba-inventory"


def test_jobid_noise_host_label_skipped():
    # 'jobs' is a noise label → the company label becomes 'globex', not 'jobs'.
    out = jobid.job_id_from_url("https://jobs.globex.com/jobs/senior-ba-inventory/")
    assert out.startswith("globex-")
    assert not out.startswith("jobs-")


def test_jobid_no_url_uses_fields():
    out = jobid.job_id_from_fields("Acme Corp", "Data Analyst")
    assert out == "manual-acme-corp-data-analyst"


def test_jobid_is_deterministic():
    url = "https://jobs.lever.co/acme/123-data-analyst"
    assert jobid.job_id_from_url(url) == jobid.job_id_from_url(url)


def test_jobid_none_without_host_path():
    assert jobid.job_id_from_url("") is None
    assert jobid.job_id_from_url("not-a-url") is None


# --- ingest.add_job ---------------------------------------------------------

def test_add_job_creates_manual_row(conn):
    res = ingest.add_job({"url": "https://jobs.globex.com/jobs/senior-ba-inventory/",
                          "company": "Globex", "title": "Senior BA"}, conn)
    assert res["created"] is True
    assert res["job_id"] == "globex-senior-ba-inventory"
    row = db.get_job_row(conn, res["job_id"])
    assert row is not None
    assert "manual" in row["source_searches"]
    assert row["company_name"] == "Globex"
    assert row["title"] == "Senior BA"


def test_add_job_explicit_job_id_respected(conn):
    res = ingest.add_job({"job_id": "tracker:60", "company": "Acme", "title": "Analyst"}, conn)
    assert res["job_id"] == "tracker:60"
    assert db.get_job_row(conn, "tracker:60") is not None


def test_add_job_idempotent_no_dup(conn):
    url = "https://jobs.globex.com/jobs/senior-ba-inventory/"
    first = ingest.add_job({"url": url, "company": "Globex", "title": "Senior BA"}, conn)
    assert first["created"] is True
    before = db.count_jobs(conn)
    second = ingest.add_job({"url": url, "company": "Globex", "title": "Senior BA"}, conn)
    assert second["created"] is False
    assert second["job_id"] == first["job_id"]
    assert db.count_jobs(conn) == before  # no duplicate row


def test_add_job_linkedin_stores_both_urls(conn):
    url = "https://www.linkedin.com/jobs/view/4414046061"
    res = ingest.add_job({"url": url, "company": "Acme", "title": "Analyst"}, conn)
    assert res["job_id"] == "4414046061"
    row = db.get_job_row(conn, "4414046061")
    assert row["linkedin_url"] == url
    assert row["apply_url"] == url


def test_add_job_requires_minimum_fields(conn):
    with pytest.raises(ValueError):
        ingest.add_job({"location": "Madrid"}, conn)


def test_add_job_application_cross_references(conn):
    res = ingest.add_job({"url": "https://jobs.globex.com/jobs/senior-ba-inventory/",
                          "company": "Globex", "title": "Senior BA"}, conn)
    db.set_application_status(conn, res["job_id"], "applied", source="manual")
    df = db.read_applications_enriched(conn)
    row = df[df.job_id == res["job_id"]].iloc[0]
    assert row.title == "Senior BA"
    assert row.company_name == "Globex"


def test_add_job_unscored_excluded_from_surface(conn):
    res = ingest.add_job({"company": "Globex", "title": "Senior BA",
                          "location": "Madrid, Spain"}, conn)
    # no score row → surface (min_score floor) must not include it
    assert db.get_score_row(conn, res["job_id"]) is None
    data = surface.shortlist_data(conn)
    ids = {r["job_id"] for r in data["today"] + data["backlog"]}
    assert res["job_id"] not in ids


# --- API: POST /applications/manual -----------------------------------------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(tmp_path))
    config.reset_cache()
    (tmp_path / "config").mkdir()
    (tmp_path / "searches").mkdir()
    db.connect().close()
    yield TestClient(create_app(serve_web=False))
    config.reset_cache()


def test_api_manual_creates_job_and_application(client):
    r = client.post("/api/applications/manual", json={
        "url": "https://jobs.globex.com/jobs/senior-ba-inventory/",
        "company": "Globex", "title": "Senior BA", "location": "Madrid",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["job_id"] == "globex-senior-ba-inventory"
    assert body["title"] == "Senior BA"
    assert body["company_name"] == "Globex"
    assert body["status"] == "applied"


def test_api_manual_missing_data_422(client):
    r = client.post("/api/applications/manual", json={"location": "Madrid"})
    assert r.status_code == 422


# --- CLI: jobcut add-job ----------------------------------------------------

@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    data = tmp_path / "fresh"
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(data))
    config.reset_cache()
    yield data
    config.reset_cache()


def test_cli_add_job_with_apply(_isolated, capsys):
    main(["init", "--no-input"])
    capsys.readouterr()
    rc = main(["add-job", "--url", "https://jobs.lever.co/acme/123-data-analyst",
               "--company", "Acme", "--title", "Data Analyst", "--apply"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "add-job" in out
    assert "linked application" in out

    conn = db.connect()
    try:
        jid = "lever-123-data-analyst"
        assert db.get_job_row(conn, jid) is not None
        assert db.get_application(conn, jid) is not None
    finally:
        conn.close()


def test_cli_add_job_missing_data_returns_1(_isolated, capsys):
    main(["init", "--no-input"])
    capsys.readouterr()
    rc = main(["add-job", "--location", "Madrid"])
    assert rc == 1
    assert "add-job:" in capsys.readouterr().out
