# tests/test_process_api.py — reuse the `client` fixture pattern from tests/test_api.py
import json
import pytest
from fastapi.testclient import TestClient
from jobcut import config, db
from jobcut.api import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("JOBCUT_TRACKER", raising=False)
    config.reset_cache()
    conn = db.connect()
    r = {c: "" for c in db.JOB_COLS}
    r.update(job_id="1", title="Senior Data Analyst", company_name="Acme",
             location="Madrid, Spain", description="SQL, Python.")
    db.upsert_jobs(conn, {"1": r}, "2026-06-16")
    db.set_application_status(conn, "1", "interview")
    conn.close()
    return TestClient(create_app(serve_web=False))


def test_put_and_advance_and_funnel(client):
    put = client.put("/api/applications/1/process",
                     json={"stages": ["Recruiter", "Técnica", "HM"], "current": 0})
    assert put.status_code == 200
    assert json.loads(put.json()["process_stages"]) == ["Recruiter", "Técnica", "HM"]

    adv = client.post("/api/applications/1/process/advance", json={"note": "ok"})
    assert adv.status_code == 200
    assert adv.json()["application"]["process_current"] == 1
    assert adv.json()["completed"] is False

    funnel = client.get("/api/applications/interview-funnel")
    assert funnel.status_code == 200
    assert funnel.json()[0] == {"stage": 1, "reached": 1, "conversion": None}


def test_put_process_404(client):
    assert client.put("/api/applications/999/process", json={"stages": ["A"]}).status_code == 404


def test_advance_404_when_no_process(client):
    # the seeded app "1" has no process defined → advance must 404
    assert client.post("/api/applications/1/process/advance", json={}).status_code == 404


def test_advance_404_when_no_application(client):
    assert client.post("/api/applications/999/process/advance", json={}).status_code == 404


def test_suggest_returns_stages(client, monkeypatch):
    from jobcut import process
    monkeypatch.setattr(process.llm, "available", lambda: True)
    monkeypatch.setattr(process.llm, "complete", lambda *a, **k: '["Recruiter", "Onsite"]')
    r = client.post("/api/applications/1/process/suggest")
    assert r.status_code == 200
    assert r.json() == {"stages": ["Recruiter", "Onsite"], "source": "llm"}


def test_suggest_404_when_no_job(client):
    assert client.post("/api/applications/999/process/suggest").status_code == 404


def _seed_two_dated_rounds(client):
    client.put("/api/applications/1/process",
               json={"stages": ["R1", "R2", "R3"], "current": 0})
    client.post("/api/applications/1/process/advance", json={"date": "2026-06-01"})
    client.post("/api/applications/1/process/advance", json={"date": "2026-06-15"})


def test_process_timing_per_app(client):
    _seed_two_dated_rounds(client)
    r = client.get("/api/applications/1/process/timing")
    assert r.status_code == 200
    body = r.json()
    assert body["rounds"] == 2
    assert body["duration_days"] == 14
    assert body["avg_gap_days"] == 14.0
    assert body["gaps_days"] == [14]


def test_process_timing_per_app_null_under_two_rounds(client):
    client.put("/api/applications/1/process",
               json={"stages": ["R1", "R2"], "current": 0})
    client.post("/api/applications/1/process/advance", json={"date": "2026-06-01"})
    r = client.get("/api/applications/1/process/timing")
    assert r.status_code == 200
    assert r.json() is None


def test_process_timing_per_app_404(client):
    assert client.get("/api/applications/999/process/timing").status_code == 404


def test_process_timing_summary(client):
    _seed_two_dated_rounds(client)
    r = client.get("/api/applications/process-timing")
    assert r.status_code == 200
    body = r.json()
    assert body["processes"] == 1
    assert body["avg_duration_days"] == 14.0
    assert body["avg_gap_days"] == 14.0


def test_process_timing_summary_not_swallowed_by_job_id_route(client):
    # The static /process-timing route must win over /{job_id}; with no qualifying
    # process it returns the summary shape (processes=0), never a 404 or an app row.
    r = client.get("/api/applications/process-timing")
    assert r.status_code == 200
    assert r.json() == {
        "processes": 0, "avg_duration_days": None, "avg_gap_days": None}
