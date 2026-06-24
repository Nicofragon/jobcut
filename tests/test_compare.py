"""Tests for multi-backend calibration mode (E3a): score_runs + compare report.

A stub second backend stands in for `local` so these run without Ollama: we
monkeypatch the backend resolver + scorer factory in compare so two backends are
"usable" and produce deterministic, divergent scores.
"""

import io
import contextlib
import json

import pytest

from jobcut import config, db
from jobcut.scoring import compare
from jobcut.scoring.base import JobScore, Scorer


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


def _seed(conn):
    """Two home, in-profile reps (scored by every backend) + one foreign (not funnel)."""
    jobs = {
        "1": _job("1", title="Data Analyst", company_name="Acme", location="Madrid, Spain",
                  workplace_type="hybrid", description="SQL and Python"),
        "2": _job("2", title="BI Analyst", company_name="Umbrella", location="European Union",
                  workplace_type="remote", description="Power BI and SQL"),
        "3": _job("3", title="Data Analyst", company_name="Globex", location="Tokyo, Japan",
                  workplace_type="on_site", description="foreign role"),
    }
    db.upsert_jobs(conn, jobs, "2026-01-01")


class _StubScorer(Scorer):
    """Deterministic stub: score depends on job_id so it diverges from rule_based."""

    def __init__(self, base=50):
        self.base = base

    def score(self, job, profile=""):
        jid = str(job.get("job_id", "0"))
        bump = (int(jid) * 13) % 40
        return JobScore(jid, self.base + bump, f"stub says {self.base + bump}")


@pytest.fixture()
def _two_backends(monkeypatch):
    """Make compare see rule_based + a 'stub' backend, both usable."""
    monkeypatch.setattr(compare, "usable_live_backends", lambda: ["rule_based", "stub"])
    monkeypatch.setattr(compare, "PRIMARY_PAIR", ("rule_based", "stub"))
    real_scorer_for = compare._scorer_for

    def fake_scorer_for(backend, cfg):
        if backend == "stub":
            return _StubScorer()
        return real_scorer_for(backend, cfg)

    monkeypatch.setattr(compare, "_scorer_for", fake_scorer_for)
    # _CARD_ORDER drives report column order; give 'stub' a slot after rule_based
    monkeypatch.setitem(compare._CARD_ORDER, "stub", 1)


# --- db layer: score_runs upsert by (job_id, backend) -----------------------

def test_score_runs_upsert_by_job_and_backend():
    conn = db.connect()
    rows = [
        {"job_id": "1", "backend": "rule_based", "match_score": 70, "match_reasons": "a", "scored_at": "t0"},
        {"job_id": "1", "backend": "local", "match_score": 85, "match_reasons": "b", "scored_at": "t0"},
    ]
    assert db.upsert_score_runs(conn, rows) == 2
    df = db.read_score_runs(conn)
    assert len(df) == 2
    assert set(zip(df.job_id, df.backend)) == {("1", "rule_based"), ("1", "local")}

    # same (job, backend) overwrites; the other backend's row is untouched
    db.upsert_score_runs(conn, [{"job_id": "1", "backend": "rule_based", "match_score": 99,
                                 "match_reasons": "c", "scored_at": "t1"}])
    df = db.read_score_runs(conn)
    assert len(df) == 2
    rb = df[(df.job_id == "1") & (df.backend == "rule_based")].iloc[0]
    assert int(rb.match_score) == 99
    lo = df[(df.job_id == "1") & (df.backend == "local")].iloc[0]
    assert int(lo.match_score) == 85
    conn.close()


# --- run_compare: N rows per job (one per backend) --------------------------

def test_compare_writes_one_row_per_job_per_backend(_two_backends):
    conn = db.connect()
    _seed(conn)
    summary = compare.run_compare(conn)
    assert summary["backends"] == ["rule_based", "stub"]
    assert summary["jobs"] == 2                       # foreign job (3) is not funnel
    assert summary["rows_written"] == 2 * 2           # 2 jobs × 2 backends

    df = db.read_score_runs(conn)
    assert len(df) == 4
    assert set(df.backend) == {"rule_based", "stub"}
    # every scored job has exactly one row per backend
    per_job = df.groupby("job_id").backend.nunique()
    assert (per_job == 2).all()
    conn.close()


def test_compare_limit_samples_first_n(_two_backends):
    conn = db.connect()
    # three funnel reps; limit to 2 -> only 2 jobs scored, by both backends
    jobs = {
        "1": _job("1", title="Data Analyst", company_name="A", location="Madrid, Spain",
                  workplace_type="hybrid", description="SQL"),
        "2": _job("2", title="BI Analyst", company_name="B", location="European Union",
                  workplace_type="remote", description="BI"),
        "5": _job("5", title="Data Analyst", company_name="C", location="Madrid, Spain",
                  workplace_type="hybrid", description="Python"),
    }
    db.upsert_jobs(conn, jobs, "2026-01-01")
    summary = compare.run_compare(conn, limit=2)
    assert summary["jobs"] == 2
    assert summary["rows_written"] == 4          # 2 jobs × 2 backends
    assert db.read_score_runs(conn).job_id.nunique() == 2
    conn.close()


def test_compare_survives_a_failing_job(monkeypatch):
    """One job raising in a backend must not abort the run or lose the others."""
    monkeypatch.setattr(compare, "usable_live_backends", lambda: ["rule_based", "flaky"])
    monkeypatch.setitem(compare._CARD_ORDER, "flaky", 1)

    class _Flaky(Scorer):
        def score(self, job, profile=""):
            if str(job.get("job_id")) == "2":
                raise TimeoutError("simulated CPU timeout")
            return JobScore(str(job["job_id"]), 50, "ok")

    real = compare._scorer_for
    monkeypatch.setattr(compare, "_scorer_for",
                        lambda be, cfg: _Flaky() if be == "flaky" else real(be, cfg))

    conn = db.connect()
    _seed(conn)                                   # funnel jobs "1" and "2"
    summary = compare.run_compare(conn)
    # flaky scored 1 of 2 (job 2 failed); rule_based scored both
    assert summary["per_backend"]["flaky"] == {"ok": 1, "failed": 1}
    assert summary["per_backend"]["rule_based"]["ok"] == 2
    df = db.read_score_runs(conn)
    assert set(df[df.backend == "flaky"].job_id) == {"1"}          # only the success persisted
    assert set(df[df.backend == "rule_based"].job_id) == {"1", "2"}
    conn.close()


def test_compare_requested_backends_filtered_to_usable(_two_backends):
    conn = db.connect()
    _seed(conn)
    # request a backend that isn't usable -> it's skipped, not run
    summary = compare.run_compare(conn, backends=["rule_based", "llm_api"])
    assert summary["backends"] == ["rule_based"]
    assert "llm_api" in summary["skipped"]
    assert set(db.read_score_runs(conn).backend) == {"rule_based"}
    conn.close()


# --- compare_report: side-by-side table + summary ---------------------------

def test_compare_report_table_and_summary(_two_backends):
    conn = db.connect()
    _seed(conn)
    compare.run_compare(conn)
    report = compare.compare_report(conn)

    assert report["empty"] is False
    assert report["backends"] == ["rule_based", "stub"]
    assert len(report["rows"]) == 2
    row = report["rows"][0]
    for key in ("job_id", "title", "company", "score_rule_based", "score_stub", "delta"):
        assert key in row
    # delta = stub - rule_based (PRIMARY_PAIR), consistent with the per-row scores
    assert row["delta"] == row["score_stub"] - row["score_rule_based"]

    s = report["summary"]
    assert s["compared"] == 2
    assert "agree_within_5" in s and "disagreements_over_20" in s
    assert "correlation" in s
    conn.close()


def test_compare_report_empty_without_runs():
    conn = db.connect()
    report = compare.compare_report(conn)
    assert report["empty"] is True
    assert report["rows"] == []
    conn.close()


def test_compare_export_writes_csv_and_xlsx(_two_backends, tmp_path):
    conn = db.connect()
    _seed(conn)
    compare.run_compare(conn)
    report = compare.compare_report(conn)
    paths = compare.write_exports(report)
    import os
    assert os.path.exists(paths["csv"]) and os.path.exists(paths["xlsx"])
    import pandas as pd
    df = pd.read_csv(paths["csv"])
    assert {"job_id", "score_rule_based", "score_stub", "delta"} <= set(df.columns)
    assert len(df) == 2
    conn.close()


# --- guardrail: compare must NOT disturb the normal single-backend flow ------

def test_compare_does_not_touch_scores_table(_two_backends):
    conn = db.connect()
    _seed(conn)
    # a pre-existing production score
    db.upsert_scores(conn, [{"job_id": "1", "canonical_id": "c", "match_score": 42,
                             "match_reasons": "prod", "status": "scored", "scored_date": "2026-01-01"}])
    compare.run_compare(conn)
    sc = db.read_scores(conn)
    assert len(sc) == 1
    assert int(sc.iloc[0].match_score) == 42          # untouched by compare
    conn.close()


def test_normal_score_still_works_after_compare(_two_backends):
    from jobcut import score
    conn = db.connect()
    _seed(conn)
    compare.run_compare(conn)                          # populate score_runs first
    summary = score.run(conn)                          # normal single-backend flow
    assert summary["scored"] == 2                      # both reps scored normally
    assert set(db.read_scores(conn).job_id) == {"1", "2"}
    conn.close()


def test_score_compare_cli(_two_backends):
    conn = db.connect()
    _seed(conn)
    conn.close()
    from jobcut.cli import main
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["score", "--compare", "--backends", "rule_based,stub"])
    assert rc == 0
    conn = db.connect()
    assert len(db.read_score_runs(conn)) == 4
    conn.close()


def test_compare_cli_json(_two_backends):
    conn = db.connect()
    _seed(conn)
    compare.run_compare(conn)
    conn.close()
    from jobcut.cli import main
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["compare", "--json"])
    assert rc == 0
    report = json.loads(buf.getvalue())
    assert report["empty"] is False
    assert len(report["rows"]) == 2
