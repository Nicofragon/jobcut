"""Tests for `jobcut ingest-scores` — loading Cowork/Claude scores into SQLite (A3)."""

import datetime
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
    p = tmp_path / "scores.json"
    p.write_text(json.dumps(data))
    return str(p)


def test_ingest_list_writes_scores(tmp_path):
    conn = db.connect()
    path = _write(tmp_path, [
        {"job_id": "100", "match_score": 87, "match_reasons": "strong match", "status": "scored"},
        {"job_id": "200", "match_score": 10, "status": "discarded"},
    ])
    summary = ingest.ingest_scores(path, conn)
    assert summary["ingested"] == 2 and summary["skipped"] == 0

    sc = db.read_scores(conn)
    assert set(sc.job_id) == {"100", "200"}
    row = sc[sc.job_id == "100"].iloc[0]
    assert int(row.match_score) == 87 and "strong match" in row.match_reasons
    assert sc[sc.job_id == "200"].iloc[0].status == "discarded"
    conn.close()


def test_ingest_tags_backend(tmp_path):
    conn = db.connect()
    # default backend is claude_skills; a per-entry backend overrides it
    path = _write(tmp_path, [
        {"job_id": "1", "match_score": 80},
        {"job_id": "2", "match_score": 60, "backend": "local"},
    ])
    ingest.ingest_scores(path, conn)
    sc = db.read_scores(conn)
    assert sc[sc.job_id == "1"].iloc[0].backend == "claude_skills"
    assert sc[sc.job_id == "2"].iloc[0].backend == "local"
    conn.close()


def test_ingest_backend_arg_overrides_default(tmp_path):
    conn = db.connect()
    path = _write(tmp_path, [{"job_id": "1", "match_score": 80}])
    ingest.ingest_scores(path, conn, backend="llm_api")
    assert db.read_scores(conn).iloc[0].backend == "llm_api"
    conn.close()


def test_ingest_scores_envelope_form(tmp_path):
    conn = db.connect()
    path = _write(tmp_path, {"scores": [{"job_id": "1", "match_score": 50}]})
    summary = ingest.ingest_scores(path, conn)
    assert summary["ingested"] == 1
    conn.close()


def test_ingest_clamps_and_defaults(tmp_path):
    conn = db.connect()
    path = _write(tmp_path, [{"job_id": "1", "match_score": 142}])
    ingest.ingest_scores(path, conn)
    row = db.read_scores(conn).iloc[0]
    assert int(row.match_score) == 100              # clamped
    assert row.status == "scored"                   # default
    assert row.scored_date == datetime.date.today().isoformat()
    conn.close()


def test_ingest_unknown_status_normalized(tmp_path):
    conn = db.connect()
    path = _write(tmp_path, [{"job_id": "1", "match_score": 60, "status": "weird"}])
    ingest.ingest_scores(path, conn)
    assert db.read_scores(conn).iloc[0].status == "scored"
    conn.close()


def test_ingest_skips_invalid_entries(tmp_path):
    conn = db.connect()
    path = _write(tmp_path, [
        {"match_score": 50},                         # no job_id
        {"job_id": "2", "match_score": "abc"},       # bad score
        {"job_id": "3", "match_score": 70},          # valid
    ])
    summary = ingest.ingest_scores(path, conn)
    assert summary["ingested"] == 1
    assert summary["skipped"] == 2 and len(summary["errors"]) == 2
    assert set(db.read_scores(conn).job_id) == {"3"}
    conn.close()


def test_ingest_last_write_wins(tmp_path):
    conn = db.connect()
    ingest.ingest_scores(_write(tmp_path, [{"job_id": "1", "match_score": 30}]), conn)
    ingest.ingest_scores(_write(tmp_path, [{"job_id": "1", "match_score": 90}]), conn)
    sc = db.read_scores(conn)
    assert len(sc) == 1 and int(sc.iloc[0].match_score) == 90
    conn.close()


def test_ingest_reports_unknown_job_ids(tmp_path):
    conn = db.connect()
    rows = {"500": {c: "" for c in db.JOB_COLS}}
    rows["500"].update(job_id="500", title="Data Analyst", first_seen="2026-01-01", last_seen="2026-01-01")
    db.upsert_jobs(conn, rows, "2026-01-01")
    path = _write(tmp_path, [{"job_id": "500", "match_score": 80}, {"job_id": "999", "match_score": 80}])
    summary = ingest.ingest_scores(path, conn)
    assert summary["ingested"] == 2
    assert summary["unknown_job_ids"] == ["999"]
    conn.close()


def test_ingest_bad_json_shape_raises(tmp_path):
    conn = db.connect()
    path = _write(tmp_path, "not a list or scores-envelope")
    with pytest.raises(ValueError):
        ingest.ingest_scores(path, conn)
    conn.close()


def test_claude_skills_scorer_points_to_ingest():
    from jobcut.scoring.claude_skills import ClaudeSkillsScorer
    with pytest.raises(RuntimeError, match="ingest-scores"):
        ClaudeSkillsScorer().score({"job_id": "1"}, "")
