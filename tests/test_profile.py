"""Tests for profile.py — parsing + role-agnostic derivation of the targeting."""

import json
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


def test_gap_and_partial_skills_derive_to_taxonomy():
    md = NURSE_MD + "\n## Skill gaps\n- Ventilator management\n"
    pd = profile.parse(md)
    assert pd.gap_skills == ["Ventilator management"]
    tax = profile.derive_taxonomy(pd)
    gap = tax["skills"]["Ventilator management"]
    assert gap["status"] == "gap" and gap["close_via"]             # gap carries a close_via
    # nice-to-have now becomes a `partial` taxonomy skill (not just a scoring signal)
    assert tax["skills"]["Pediatric care"]["status"] == "partial"
    assert tax["skills"]["Patient care"]["status"] == "have"


def test_derive_searches_respects_remote_mode():
    s = profile.derive_searches(profile.parse(NURSE_MD))
    assert "remote" not in s                         # on-site only -> no remote search
    only = next(iter(s.values()))
    assert only["workplaceType"] == ["office"]   # actor enum: remote|hybrid|office (no "on-site")
    assert only["jobTitles"] == ["Registered Nurse", "ICU Nurse"]
    assert only["locations"] == ["Boston, USA"] and "geoIds" not in only  # plain name, no geoId to hunt


def test_apply_merges_and_preserves_manual_edits(tmp_path):
    (tmp_path / "profile.md").write_text(NURSE_MD)
    r1 = profile.apply(force=False)
    assert r1["written"] and not r1["skipped"]

    # hand-tune the derived kit: add a pattern to a skill + a skill the profile never mentions
    tax_path = config.taxonomy_file()
    tax = json.loads(tax_path.read_text())
    tax["skills"]["Patient care"]["patterns"].append("bedside")
    tax["skills"]["Manual-only"] = {"cat": "core", "status": "gap", "close_via": "course",
                                    "patterns": ["manualonly"]}
    tax_path.write_text(json.dumps(tax))

    # a second apply MERGES (re-derives config/taxonomy, skips tuned searches) and keeps edits
    r2 = profile.apply(force=False)
    assert any("searches" in p for p in r2["skipped"])              # tuned searches untouched
    merged = json.loads(tax_path.read_text())
    assert "bedside" in merged["skills"]["Patient care"]["patterns"]  # manual pattern survived
    assert "Manual-only" in merged["skills"]                          # manual skill survived

    # force regenerates straight from the profile (the manual-only skill is dropped)
    profile.apply(force=True)
    assert "Manual-only" not in json.loads(tax_path.read_text())["skills"]


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
