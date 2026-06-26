"""B-15 salary estimates: own table (never touches jobs/scores) + the ingest bridge."""

import json

import pytest

from jobcut import db, ingest


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def _job(job_id, **over):
    row = {col: "" for col in db.JOB_COLS}
    row.update(job_id=job_id, source_searches="city", title=f"Job {job_id}",
               company_name="Acme", location="Madrid, Spain",
               first_seen="2026-01-01", last_seen="2026-01-01")
    row.update(over)
    return row


def test_upsert_and_get(conn):
    db.upsert_jobs(conn, {"1": _job("1")}, "2026-01-01")
    n = db.upsert_salary_estimates(conn, [{
        "job_id": "1", "est_min": 45000, "est_max": 55000, "currency": "EUR",
        "period": "year", "basis": "Glassdoor", "source": "cowork_web",
        "estimated_at": "2026-06-26",
    }])
    assert n == 1
    row = db.get_salary_estimate_row(conn, "1")
    assert row is not None
    assert row["est_min"] == 45000 and row["est_max"] == 55000
    assert row["currency"] == "EUR"
    assert db.get_salary_estimate_row(conn, "nope") is None


def test_reestimate_overwrites_and_leaves_jobs_and_scores_untouched(conn):
    db.upsert_jobs(conn, {"1": _job("1", salary_text="80k disclosed")}, "2026-01-01")
    db.upsert_scores(conn, [{"job_id": "1", "canonical_id": "c1", "match_score": 90,
                             "match_reasons": "good", "status": "scored", "scored_date": "2026-01-01"}])
    db.upsert_salary_estimates(conn, [{"job_id": "1", "est_min": 40000, "est_max": 50000}])
    db.upsert_salary_estimates(conn, [{"job_id": "1", "est_min": 42000, "est_max": 52000}])
    # last write wins
    assert db.get_salary_estimate_row(conn, "1")["est_min"] == 42000
    # disclosed salary (jobs) and the score are never touched by an estimate
    assert db.get_job_row(conn, "1")["salary_text"] == "80k disclosed"
    assert db.get_score_row(conn, "1")["match_score"] == 90


def test_estimates_invisible_to_read_jobs(conn):
    # estimates live in their own table → read_jobs (and thus market.salary_pct) never sees them
    db.upsert_jobs(conn, {"1": _job("1")}, "2026-01-01")  # no disclosed salary
    db.upsert_salary_estimates(conn, [{"job_id": "1", "est_min": 40000, "est_max": 50000}])
    jobs = db.read_jobs(conn)
    assert "est_min" not in jobs.columns
    assert not str(jobs.loc[jobs.job_id == "1", "salary_min"].iloc[0]).strip()


def test_ingest_salary_validates_and_normalizes(tmp_path, conn):
    payload = {"estimates": [
        {"job_id": "1", "est_min": 45000, "est_max": 55000, "currency": "eur"},
        {"job_id": "2", "est_max": 60000},                    # only a max — allowed
        {"est_min": 1},                                        # missing job_id — skip
        {"job_id": "3"},                                       # no bounds — skip
        {"job_id": "4", "est_min": "abc"},                     # non-numeric — skip
        {"job_id": "5", "est_min": 50000, "est_max": 40000},   # swapped — tolerated
    ]}
    p = tmp_path / "est.json"
    p.write_text(json.dumps(payload))
    summary = ingest.ingest_salary(str(p), conn=conn)
    assert summary["ingested"] == 3   # jobs 1, 2, 5
    assert summary["skipped"] == 3    # missing id, no bounds, non-numeric
    assert db.get_salary_estimate_row(conn, "1")["currency"] == "EUR"  # upper-cased
    r2 = db.get_salary_estimate_row(conn, "2")
    assert r2["est_min"] is None and r2["est_max"] == 60000
    r5 = db.get_salary_estimate_row(conn, "5")  # swapped bounds fixed to min<=max
    assert r5["est_min"] == 40000 and r5["est_max"] == 50000


def test_ingest_salary_accepts_bare_list(tmp_path, conn):
    p = tmp_path / "est.json"
    p.write_text(json.dumps([{"job_id": "9", "est_min": 30000, "est_max": 35000}]))
    summary = ingest.ingest_salary(str(p), conn=conn)
    assert summary["ingested"] == 1
    assert db.get_salary_estimate_row(conn, "9")["est_max"] == 35000
