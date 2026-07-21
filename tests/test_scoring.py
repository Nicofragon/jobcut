"""Tests for the rule_based scorer and the filter→score orchestration."""

import json

import pytest

from jobcut import config, db
from jobcut.scoring import get_scorer

# These tests use data-analyst job fixtures, so they declare their OWN target-title
# filter — the engine ships no field default (include_titles is derived from a profile).
INCLUDE_TITLES = r"data analyst|analyst|machine learning"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(tmp_path))
    config.reset_cache()
    (tmp_path / "config").mkdir()
    config.config_file().write_text(json.dumps({"filter": {"include_titles": INCLUDE_TITLES}}))
    yield
    config.reset_cache()


TAXONOMY = {
    "skills": {
        "SQL": {"cat": "core", "status": "have", "patterns": [r"\bsql\b"]},
        "Python": {"cat": "core", "status": "have", "patterns": [r"\bpython\b"]},
    },
    "role_segments": {"data-analyst": ["data analyst"]},
}


def _scorer():
    cfg = config.load()
    return get_scorer("rule_based", taxonomy=TAXONOMY, weights=cfg["scoring"]["weights"],
                      include_titles=cfg["filter"]["include_titles"],
                      out_of_profile_cap=cfg["scoring"]["out_of_profile_cap"])


def test_strong_match_scores_high():
    s = _scorer()
    job = {"job_id": "1", "title": "Senior Data Analyst", "company_name": "Acme",
           "company_size": "200", "location": "Madrid, Spain", "workplace_type": "hybrid",
           "applicants": "12", "recruiter_name": "Jane",
           "description": "SQL, Python and LLM experimentation for our analytics team."}
    js = s.score(job, "")
    assert js.match_score >= 80
    assert js.status == "scored"
    assert "title match" in js.match_reasons


def test_out_of_profile_title_capped():
    s = _scorer()
    job = {"job_id": "2", "title": "Senior UX Designer", "company_name": "Acme",
           "company_size": "200", "location": "Madrid, Spain", "workplace_type": "hybrid",
           "applicants": "5", "description": "Figma and design systems."}
    js = s.score(job, "")
    assert js.match_score <= config.load()["scoring"]["out_of_profile_cap"]


def test_dealbreaker_penalizes():
    s = _scorer()
    base = {"job_id": "3", "title": "Data Analyst", "company_name": "Acme", "company_size": "200",
            "location": "Madrid, Spain", "workplace_type": "remote", "applicants": "5"}
    clean = s.score({**base, "description": "SQL and Python."}, "")
    dealbroke = s.score({**base, "description": "SQL and Python. Active security clearance required."}, "")
    assert dealbroke.match_score < clean.match_score


def test_score_orchestration_end_to_end():
    from jobcut import score

    conn = db.connect()
    rows = {
        # representative: strong data role in home geo
        "100": {c: "" for c in db.JOB_COLS},
        # repost of the same canonical (same company/title/location)
        "101": {c: "" for c in db.JOB_COLS},
        # off-profile title -> title discard
        "200": {c: "" for c in db.JOB_COLS},
        # foreign on-site -> not funnel, should not be scored
        "300": {c: "" for c in db.JOB_COLS},
    }
    rows["100"].update(job_id="100", title="Data Analyst", company_name="Acme", location="Madrid, Spain",
                       workplace_type="hybrid", description="SQL Python", first_seen="2026-01-01", last_seen="2026-01-01")
    rows["101"].update(job_id="101", title="Data Analyst", company_name="Acme", location="Madrid, Spain",
                       workplace_type="hybrid", description="SQL Python", first_seen="2026-01-02", last_seen="2026-01-02")
    rows["200"].update(job_id="200", title="Sales Manager", company_name="Acme", location="Madrid, Spain",
                       workplace_type="hybrid", description="quota", first_seen="2026-01-01", last_seen="2026-01-01")
    rows["300"].update(job_id="300", title="Data Analyst", company_name="Globex", location="Tokyo, Japan",
                       workplace_type="on_site", description="SQL", first_seen="2026-01-01", last_seen="2026-01-01")
    db.upsert_jobs(conn, rows, "2026-01-02")

    # taxonomy on disk so the scorer can award stack points
    import json
    (config.taxonomy_file()).parent.mkdir(parents=True, exist_ok=True)
    config.taxonomy_file().write_text(json.dumps(TAXONOMY))

    summary = score.run(conn)
    assert summary["scored"] == 1        # one representative (100)
    assert summary["reposts"] == 1       # 101 inherits
    assert summary["discarded"] == 1     # 200 dropped by title

    sc = db.read_scores(conn)
    assert set(sc.job_id) == {"100", "101", "200"}   # 300 never scored (not funnel)
    assert sc[sc.job_id == "200"].iloc[0].status == "discarded"
    # repost inherited the representative's score
    assert int(sc[sc.job_id == "101"].iloc[0].match_score) == int(sc[sc.job_id == "100"].iloc[0].match_score)
    assert sc[sc.job_id == "100"].iloc[0].backend == "rule_based"   # rows carry their provenance
    conn.close()


def test_score_floors_new_jobs_under_claude_skills(capsys):
    """Under claude_skills, a bare pull would leave new jobs invisible until Claude runs.
    So `jobcut score` lays a rule_based FLOOR on the new funnel: rows land immediately,
    tagged honestly as `rule_based` (never as claude_skills), and the user is still told
    to run their skill to upgrade them."""
    from jobcut import score

    conn = db.connect()
    rows = {"100": {c: "" for c in db.JOB_COLS}}
    rows["100"].update(job_id="100", title="Data Analyst", company_name="Acme", location="Madrid, Spain",
                       workplace_type="hybrid", description="SQL Python",
                       first_seen="2026-01-01", last_seen="2026-01-01")
    db.upsert_jobs(conn, rows, "2026-01-01")
    config.update({"scoring": {"backend": "claude_skills"}})

    summary = score.run(conn)
    assert summary["floor"] is True
    assert summary["backend"] == "claude_skills"     # the configured backend is unchanged
    assert summary["scored"] == 1
    assert summary["rows_written"] >= 1

    sc = db.read_scores(conn)
    assert set(sc.job_id) == {"100"}
    # the floor is honest about its provenance — it never masquerades as Claude
    assert sc[sc.job_id == "100"].iloc[0].backend == "rule_based"
    assert "scoring skill" in capsys.readouterr().out
    conn.close()


def test_floor_never_downgrades_an_existing_claude_score():
    """The floor is incremental — a job Claude already scored keeps its claude_skills
    score and reason; re-running `jobcut score` under claude_skills must not clobber it
    with the rubric."""
    from jobcut import score

    conn = db.connect()
    rows = {"100": {c: "" for c in db.JOB_COLS}}
    rows["100"].update(job_id="100", title="Data Analyst", company_name="Acme", location="Madrid, Spain",
                       workplace_type="hybrid", description="SQL Python",
                       first_seen="2026-01-01", last_seen="2026-01-01")
    db.upsert_jobs(conn, rows, "2026-01-01")
    config.update({"scoring": {"backend": "claude_skills"}})

    # Claude scored it first (as `jobcut ingest-scores` would): 95, tagged claude_skills.
    db.upsert_scores(conn, [{"job_id": "100", "canonical_id": "", "match_score": 95,
                             "match_reasons": "great fit", "status": "scored",
                             "scored_date": "2026-01-02", "backend": "claude_skills"}])

    summary = score.run(conn)
    assert summary["scored"] == 0                     # nothing new to floor
    row = db.read_scores(conn)
    row = row[row.job_id == "100"].iloc[0]
    assert int(row.match_score) == 95                 # untouched
    assert row.backend == "claude_skills"             # provenance preserved, not downgraded
    conn.close()
