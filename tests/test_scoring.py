"""Tests for the rule_based scorer and the filter→score orchestration."""

import pytest

from jobcut import config, db
from jobcut.scoring import get_scorer


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(tmp_path))
    config.reset_cache()
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


def test_llm_api_parse_tolerates_fences_and_clamps():
    from jobcut.scoring.llm_api import _parse
    js = _parse('```json\n{"score": 142, "reason": "great fit"}\n```', "9")
    assert js.job_id == "9" and js.match_score == 100 and "great fit" in js.match_reasons
    assert _parse('blah {"score": -5, "reason": ""} trailing', "1").match_score == 0


def test_llm_api_requires_a_key(monkeypatch):
    from jobcut.scoring import get_scorer
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    scorer = get_scorer("llm_api")
    with pytest.raises(RuntimeError, match="llm_api"):
        scorer.score({"job_id": "1", "title": "x"}, "profile")


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
    conn.close()
