"""Phase D — end-to-end connection of the profile → kit chain.

Proves the single guarantee the whole revamp rests on: one `profile.md`, built with
have/partial/gap skills and *no hand editing of the kit*, drives BOTH the rule_based
scorer AND the Discovery (market) view off the same derived taxonomy — and that an
existing hand-tuned taxonomy survives an upgrade + re-derive without loss.
"""

import json

import pytest

from jobcut import config, db, market, profile, score

# A profile with all three skill statuses: core (have), nice-to-have (partial), gap.
PROFILE_MD = """# My profile

## Target roles
- Registered Nurse
- ICU Nurse

## Core skills
- Patient care
- Triage

## Nice-to-have / learning
- Pediatric care

## Skill gaps
- Ventilator management

## Location & work mode
- Based in: Boston, USA
- Remote: on-site only

## Dealbreakers
- Active state license you don't hold
"""


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(tmp_path))
    config.reset_cache()
    yield tmp_path
    config.reset_cache()


def _job(jid, title, description):
    r = {c: "" for c in db.JOB_COLS}
    r.update(job_id=jid, title=title, company_name="City Hospital", company_size="500",
             location="Boston, USA", workplace_type="on_site", applicants="5",
             posted_date="2026-06-10", description=description)
    return r


def test_profile_drives_both_scoring_and_discovery(tmp_path):
    """profile.md → derive(kit) → rule_based scorer + market Discovery, no hand editing."""
    (tmp_path / "profile.md").write_text(PROFILE_MD)
    profile.apply(force=True)
    config.reset_cache()

    # 1. the kit derived from the profile carries every status straight through
    tax = config.load_taxonomy()
    assert tax["skills"]["Patient care"]["status"] == "have"
    assert tax["skills"]["Pediatric care"]["status"] == "partial"
    assert tax["skills"]["Ventilator management"]["status"] == "gap"

    # 2. the SAME kit drives rule_based scoring — an on-profile role scores high
    scorer = score.build_scorer(config.load())
    nurse = _job("1", "Registered Nurse",
                 "Patient care, triage and pediatric care on the ward.")
    assert scorer.score(nurse, "").match_score >= 70

    # 3. the SAME kit drives Discovery — coverage + gaps computed off the derived taxonomy
    conn = db.connect()
    db.upsert_jobs(conn, {
        "1": _job("1", "Registered Nurse", "Patient care, ACLS and triage on the floor."),
        "2": _job("2", "ICU Nurse", "Ventilator management and patient care in the ICU."),
    }, "2026-06-16")
    s = market.summary(conn)
    conn.close()

    assert s is not None
    # a `have` skill the market demands lifts coverage; the demanded `gap` keeps it < 100
    assert 0 < s["coverage"]["pct"] < 100
    gaps = {g["skill"]: g for g in s["gaps"]}
    assert gaps["Ventilator management"]["status"] == "gap"      # gap surfaced in Discovery
    demand = {d["skill"]: d for d in s["top_demand"]}
    assert demand["Patient care"]["pct"] > 0                     # have skill shows as demand


def test_old_grammar_profile_without_gap_section_still_derives(tmp_path):
    """A profile written before Phase A (no `## Skill gaps`) parses and derives cleanly."""
    old = PROFILE_MD.replace("## Skill gaps\n- Ventilator management\n\n", "")
    (tmp_path / "profile.md").write_text(old)
    pd = profile.parse(old)
    assert pd.gap_skills == []                                   # no gaps, no crash
    profile.apply(force=True)
    tax = config.load_taxonomy()
    assert tax["skills"]["Patient care"]["status"] == "have"
    assert tax["skills"]["Pediatric care"]["status"] == "partial"
    assert not any(v["status"] == "gap" for v in tax["skills"].values())


def test_upgrade_preserves_hand_tuned_taxonomy_with_custom_profile(tmp_path):
    """The real owner's situation: a custom-heading (non-managed) profile + a hand-authored
    kit. The auto-derive that runs on upgrade/save must be a NO-OP on the kit — a custom
    profile parses empty, and an empty merge preserves every hand-tuned skill and pattern."""
    (tmp_path / "profile.md").write_text(
        "# Perfil\n\n## Identidad de candidato\n- Data Analyst\n\n"
        "## Stack técnico\n- SQL avanzado\n- Tableau\n")

    hand = {
        "skills": {
            "SQL": {"cat": "core", "status": "have", "patterns": [r"\bsql\b", "postgres"]},
            "Tableau": {"cat": "viz", "status": "partial", "close_via": "cv-reframe",
                        "patterns": [r"\btableau\b"]},
            "dbt": {"cat": "dataeng", "status": "gap", "close_via": "course",
                    "patterns": [r"\bdbt\b"]},
        },
        "role_segments": {"data": [r"data analyst"]},
    }
    tax_path = config.taxonomy_file()
    tax_path.parent.mkdir(parents=True, exist_ok=True)
    tax_path.write_text(json.dumps(hand))
    config.reset_cache()

    profile.apply(force=False)          # the merge that runs on every save / on upgrade

    merged = json.loads(tax_path.read_text())
    assert set(merged["skills"]) == {"SQL", "Tableau", "dbt"}    # nothing dropped
    assert "postgres" in merged["skills"]["SQL"]["patterns"]     # hand pattern survives
    assert merged["skills"]["Tableau"]["close_via"] == "cv-reframe"
    assert merged["skills"]["dbt"]["status"] == "gap"           # hand status untouched
    assert merged["role_segments"]["data"] == [r"data analyst"]
