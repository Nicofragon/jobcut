"""Tests for profile.py — parsing + role-agnostic derivation of the targeting."""

import re

import pytest

from jobcut import config, profile, score

NURSE_MD = """# My profile

## Target roles
- Registered Nurse
- ICU Nurse
- (add yours)

## Core skills
- Patient care
- ACLS
- Triage

## Nice-to-have / learning
- Pediatric care

## Location & work mode
- Based in: Boston, USA
- Remote: on-site only

## Dealbreakers
- Active state license you don't hold

## Notes for the scorer
Prefer teaching hospitals.
"""


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(tmp_path))
    config.reset_cache()
    yield tmp_path
    config.reset_cache()


# --- parsing ----------------------------------------------------------------

def test_parse_example_profile():
    md = (__import__("importlib").resources.files("jobcut")
          / "templates" / "profile.example.md").read_text()
    pd = profile.parse(md)
    assert "Senior Data Analyst" in pd.target_titles
    assert "SQL" in pd.core_skills
    assert "dbt" in pd.nice_skills
    assert pd.remote_mode and pd.dealbreakers
    # placeholder bullets like "(add yours)" are dropped
    assert "(add yours)" not in pd.target_titles


def test_parse_is_tolerant_of_missing_sections():
    pd = profile.parse("# Empty\n\nnothing here")
    assert pd.target_titles == [] and pd.core_skills == [] and pd.based_in == ""


def test_parse_nurse():
    pd = profile.parse(NURSE_MD)
    assert pd.target_titles == ["Registered Nurse", "ICU Nurse"]
    assert pd.core_skills == ["Patient care", "ACLS", "Triage"]
    assert pd.based_in == "Boston, USA"
    assert "on-site only" in pd.remote_mode.lower()


# --- derivation -------------------------------------------------------------

def test_derive_include_titles_strips_seniority():
    inc = profile.derive_include_titles(profile.parse(NURSE_MD))
    rx = re.compile(inc, re.I)
    assert rx.search("Registered Nurse") and rx.search("ICU Nurse")
    assert not rx.search("Data Analyst")


def test_derive_routing_from_location():
    home, region = profile.derive_routing(profile.parse(NURSE_MD))
    assert re.search(home, "Boston, USA", re.I)
    assert re.search(region, "remote in usa", re.I)


def test_derive_taxonomy_and_signals():
    pd = profile.parse(NURSE_MD)
    tax = profile.derive_taxonomy(pd)
    assert "Patient care" in tax["skills"]
    assert tax["role_segments"]                      # one segment per target title
    cfg = profile.derive_config(pd)
    assert cfg["scoring"]["signals"]                 # from nice-to-have
    assert cfg["scoring"]["dealbreakers"]            # best-effort from dealbreakers


def test_derive_searches_respects_remote_mode():
    s = profile.derive_searches(profile.parse(NURSE_MD))
    assert "remote" not in s                         # on-site only -> no remote search
    only = next(iter(s.values()))
    assert only["workplaceType"] == ["on-site"]
    assert only["jobTitles"] == ["Registered Nurse", "ICU Nurse"]
    assert only["geoIds"] == ["REPLACE_ME"]


def test_apply_is_non_destructive(tmp_path):
    (tmp_path / "profile.md").write_text(NURSE_MD)
    r1 = profile.apply(force=False)
    assert r1["written"] and not r1["skipped"]
    # second run skips everything (does not clobber edits)
    r2 = profile.apply(force=False)
    assert r2["written"] == [] and r2["skipped"]
    # force overwrites
    r3 = profile.apply(force=True)
    assert r3["written"] and r3["skipped"] == []


# --- role-agnostic acceptance (KR2) -----------------------------------------

def test_role_agnostic_nurse_scoring(tmp_path):
    (tmp_path / "profile.md").write_text(NURSE_MD)
    profile.apply(force=True)
    config.reset_cache()
    scorer = score.build_scorer(config.load())

    nurse = {"job_id": "1", "title": "Registered Nurse", "company_name": "City Hospital",
             "company_size": "500", "location": "Boston, USA", "workplace_type": "on_site",
             "applicants": "5", "description": "Patient care, ACLS and triage in the ICU."}
    data = {"job_id": "2", "title": "Data Analyst", "company_name": "Acme", "company_size": "500",
            "location": "Boston, USA", "workplace_type": "on_site", "applicants": "5",
            "description": "SQL and Python for dashboards."}

    assert scorer.score(nurse, "").match_score >= 70    # the nurse role scores high
    cap = config.load()["scoring"]["out_of_profile_cap"]
    assert scorer.score(data, "").match_score <= cap    # off-profile title capped
