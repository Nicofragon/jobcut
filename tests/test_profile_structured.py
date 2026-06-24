"""Tests for the structured profile layer (B1): round-trip with profile.md + endpoints."""

import pytest
from fastapi.testclient import TestClient

from jobcut import config, profile
from jobcut.api import create_app

NURSE_MD = """# My profile

## Target roles
- Registered Nurse
- ICU Nurse

## Core skills
- Patient care
- ACLS

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


def _fields(**over):
    base = dict(
        target_roles=["Senior Data Analyst", "Product Analyst"],
        locations=["Madrid", "Spain"],
        work_types=["hybrid", "remote"],
        seniority="~8 years, targeting senior IC",
        must_haves=["dbt", "BigQuery"],
        dealbreakers=["fluent German required"],
        skills=["SQL", "Python"],
    )
    base.update(over)
    return profile.ProfileFields(**base)


# --- round-trip -------------------------------------------------------------

def test_round_trip_is_stable():
    f = _fields()
    assert profile.to_structured(profile.from_structured(f)) == f


@pytest.mark.parametrize("over", [
    {"seniority": None},                       # optional seniority omitted
    {"work_types": [], "locations": []},       # empty lists
    {"target_roles": [], "skills": [], "must_haves": [], "dealbreakers": []},
])
def test_round_trip_edge_cases(over):
    f = _fields(**over)
    assert profile.to_structured(profile.from_structured(f)) == f


# --- mapping onto the canonical headings ------------------------------------

def test_to_structured_maps_existing_headings():
    f = profile.to_structured(NURSE_MD)
    assert f.target_roles == ["Registered Nurse", "ICU Nurse"]
    assert f.skills == ["Patient care", "ACLS"]
    assert f.must_haves == ["Pediatric care"]
    assert f.locations == ["Boston", "USA"]
    assert "on-site only" in (f.work_types[0].lower() if f.work_types else "")
    assert f.dealbreakers == ["Active state license you don't hold"]


def test_from_structured_writes_canonical_headings_parse_reads_back():
    f = _fields(work_types=["hybrid"], locations=["Madrid"])
    md = profile.from_structured(f)
    pd = profile.parse(md)                       # the canonical parser must read it
    assert pd.target_titles == f.target_roles
    assert pd.core_skills == f.skills
    assert pd.nice_skills == f.must_haves
    assert pd.based_in == "Madrid"
    assert pd.remote_mode == "hybrid"
    assert pd.dealbreakers == f.dealbreakers


def test_from_structured_preserves_unmodeled_sections():
    f = profile.to_structured(NURSE_MD)
    out = profile.from_structured(f, base_md=NURSE_MD)
    assert "## Notes for the scorer" in out
    assert "Prefer teaching hospitals." in out


# --- derive still works after a structured write ----------------------------

def test_derive_still_works_after_structured_write():
    import re
    f = _fields(target_roles=["Registered Nurse"], skills=["ACLS"], work_types=["on-site only"])
    md = profile.from_structured(f)
    pd = profile.parse(md)
    inc = profile.derive_include_titles(pd)
    assert re.search(inc, "Registered Nurse", re.I)
    tax = profile.derive_taxonomy(pd)
    assert "ACLS" in tax["skills"]


# --- API --------------------------------------------------------------------

def _client():
    return TestClient(create_app(serve_web=False))


def test_put_then_get_structured_round_trips():
    c = _client()
    payload = _fields().model_dump()
    r = c.put("/api/profile/structured", json=payload)
    assert r.status_code == 200
    got = c.get("/api/profile/structured").json()
    assert got == payload
    # the raw editor sees a real markdown file with canonical headings
    raw = c.get("/api/profile").json()["content"]
    assert "## Target roles" in raw and "Senior Data Analyst" in raw


def test_raw_profile_endpoints_still_work():
    c = _client()
    md = "# My profile\n\n## Target roles\n- Data Analyst\n"
    assert c.put("/api/profile", json={"content": md}).status_code == 200
    assert c.get("/api/profile").json()["content"] == md
    # and the structured view reflects the raw edit
    assert c.get("/api/profile/structured").json()["target_roles"] == ["Data Analyst"]


def test_structured_put_is_derivable():
    c = _client()
    c.put("/api/profile/structured", json=_fields(target_roles=["Data Analyst"]).model_dump())
    derived = c.get("/api/profile/derived").json()
    assert derived["searches"]            # searches derived from the written profile
