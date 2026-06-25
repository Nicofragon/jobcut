"""Tests for B2 — structured searches: mapping, geoId resolution, round-trip, endpoints."""

import json

import pytest
from fastapi.testclient import TestClient

from jobcut import config, geo, paths, pull
from jobcut import searches as sm
from jobcut.api import create_app

# the canonical actor input (the 7 keys pull.py consumes), no human _note
ACTOR_REMOTE = {
    "jobTitles": ["Data Analyst", "Product Analyst"],
    "geoIds": ["91000000"],
    "workplaceType": ["remote"],
    "employmentType": ["full-time"],
    "maxItems": 65,
    "postedLimit": "24h",
    "sortBy": "relevance",
}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(tmp_path))
    config.reset_cache()
    yield tmp_path
    config.reset_cache()


# --- geo resolution ---------------------------------------------------------

def test_geo_resolves_seeded_value():
    assert geo.resolve("European Economic Area") == "91000000"
    assert geo.resolve("  eea ") == "91000000"          # normalized (case/space/alias)


def test_geo_unknown_returns_none():
    assert geo.resolve("Atlantis") is None


# --- mapping structured -> actor input --------------------------------------

def test_to_actor_input_shape():
    s = sm.StructuredSearch(name="x", titles=["Data Analyst"], locations=["European Economic Area"],
                            work_types=["remote"], employment_types=["full-time"],
                            max_items=40, posted_within="24h")
    a = sm.to_actor_input(s)
    assert a["jobTitles"] == ["Data Analyst"]
    assert a["geoIds"] == ["91000000"]                  # resolved from the table
    assert a["workplaceType"] == ["remote"]
    assert a["employmentType"] == ["full-time"]
    assert a["maxItems"] == 40 and a["postedLimit"] == "24h" and a["sortBy"] == "relevance"


def test_geoid_takes_precedence_over_freetext_location():
    # both a typed name and a geoId → send ONLY geoIds (never both — the actor doesn't
    # define how it combines them). This is the LinkedIn-import case (Madrid name + geoId).
    s = sm.StructuredSearch(name="x", titles=["X"],
                            locations=["Madrid, Community of Madrid, Spain"], geo_ids=["100994331"])
    a = sm.to_actor_input(s)
    assert a["geoIds"] == ["100994331"]
    assert "locations" not in a


def test_plain_location_needs_no_geoid():
    s = sm.StructuredSearch(name="x", titles=["X"], locations=["Atlantis"])
    a = sm.to_actor_input(s)
    assert a["locations"] == ["Atlantis"] and "geoIds" not in a   # runnable as text, no REPLACE_ME
    assert sm.from_actor_input("x", a).needs_geoid is False       # has a location → ready


def test_no_location_at_all_flags_needs_geoid():
    a = sm.to_actor_input(sm.StructuredSearch(name="x", titles=["X"]))
    assert "geoIds" not in a and "locations" not in a
    assert sm.from_actor_input("x", a).needs_geoid is True        # nothing to target → needs setup


def test_defaults_when_omitted():
    a = sm.to_actor_input(sm.StructuredSearch(name="x", titles=["X"], locations=["European Economic Area"]))
    assert a["maxItems"] == 50 and a["postedLimit"] == "24h"
    assert a["employmentType"] == ["full-time"]


# --- round-trip actor_input <-> structured ----------------------------------

def test_round_trip_actor_input():
    s = sm.from_actor_input("remote", ACTOR_REMOTE)
    assert s.geo_ids == ["91000000"] and s.needs_geoid is False
    assert sm.to_actor_input(s) == ACTOR_REMOTE


def test_from_actor_input_flags_replace_me():
    s = sm.from_actor_input("city", {**ACTOR_REMOTE, "geoIds": ["REPLACE_ME"]})
    assert s.geo_ids == [] and s.needs_geoid is True


# --- API --------------------------------------------------------------------

def _client():
    return TestClient(create_app(serve_web=False))


def test_structured_post_writes_actor_json_and_raw_reads_it():
    c = _client()
    payload = {"name": "eea", "titles": ["Data Analyst"], "locations": ["European Economic Area"],
               "work_types": ["remote"], "employment_types": ["full-time"],
               "max_items": 65, "posted_within": "24h"}
    r = c.post("/api/searches/structured", json=payload)
    assert r.status_code == 200
    # the raw CRUD sees a real actor-input file with resolved geoIds
    raw = c.get("/api/searches/eea").json()["input"]
    assert raw["geoIds"] == ["91000000"] and raw["workplaceType"] == ["remote"]
    assert raw["sortBy"] == "relevance"
    # and the structured view round-trips
    got = c.get("/api/searches/structured/eea").json()
    assert got["geo_ids"] == ["91000000"] and got["needs_geoid"] is False


def test_structured_put_and_list():
    c = _client()
    c.post("/api/searches/structured", json={"name": "s1", "titles": ["X"],
                                             "locations": ["Atlantis"]})
    # a plain location name is runnable on its own (free-text), so it's NOT needs_geoid
    s1 = c.get("/api/searches/structured/s1").json()
    assert s1["needs_geoid"] is False and s1["locations"] == ["Atlantis"]
    assert c.get("/api/searches/s1").json()["input"]["locations"] == ["Atlantis"]
    c.put("/api/searches/structured/s1", json={"name": "s1", "titles": ["Y"],
                                              "locations": ["Atlantis"], "geo_ids": ["999"]})
    assert c.get("/api/searches/s1").json()["input"]["geoIds"] == ["999"]
    names = [s["name"] for s in c.get("/api/searches/structured").json()]
    assert "s1" in names


def test_raw_crud_still_intact():
    c = _client()
    raw_input = {"jobTitles": ["A"], "geoIds": ["91000000"], "workplaceType": ["remote"],
                 "employmentType": ["full-time"], "maxItems": 50, "postedLimit": "24h", "sortBy": "relevance"}
    assert c.post("/api/searches", json={"name": "raw1", "input": raw_input}).status_code == 200
    assert c.get("/api/searches/raw1").json()["input"] == raw_input
    assert c.delete("/api/searches/raw1").json() == {"deleted": "raw1"}


def test_to_actor_input_omits_paused_flag():
    # the pause flag is local metadata — it must NOT leak into the "what we send" preview
    s = sm.StructuredSearch(name="x", titles=["A"], locations=["Madrid"], paused=True)
    assert "_paused" not in sm.to_actor_input(s)


def test_pause_endpoint_round_trips():
    c = _client()
    c.post("/api/searches/structured", json={"name": "p1", "titles": ["A"], "locations": ["Madrid"]})
    assert c.get("/api/searches/structured/p1").json()["paused"] is False
    # pause → persisted as _paused in the file, surfaced as paused=True
    assert c.put("/api/searches/structured/p1/paused", json={"paused": True}).json()["paused"] is True
    assert c.get("/api/searches/p1").json()["input"]["_paused"] is True
    assert c.get("/api/searches/structured/p1").json()["paused"] is True
    # resume → flag removed
    assert c.put("/api/searches/structured/p1/paused", json={"paused": False}).json()["paused"] is False
    assert "_paused" not in c.get("/api/searches/p1").json()["input"]


def test_load_searches_skips_paused_and_strips_meta():
    d = paths.searches_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "active.json").write_text(json.dumps({"jobTitles": ["A"], "locations": ["Madrid"], "_note": "hi"}))
    (d / "off.json").write_text(json.dumps({"jobTitles": ["B"], "locations": ["Madrid"], "_paused": True}))
    out = pull.load_searches()
    assert [n for n, _ in out] == ["active"]                 # paused one skipped
    sent = out[0][1]
    assert "_note" not in sent and "_paused" not in sent     # local metadata stripped before Apify


def test_preview_returns_actor_input_without_writing():
    c = _client()
    payload = {"name": "scratch", "titles": ["Data Analyst"],
               "locations": ["European Economic Area"], "work_types": ["remote"],
               "employment_types": ["full-time"], "max_items": 65, "posted_within": "week"}
    r = c.post("/api/searches/preview", json=payload)
    assert r.status_code == 200
    actor = r.json()
    # exact actor input, geoIds resolved server-side from the location name
    assert actor["geoIds"] == ["91000000"]
    assert actor["jobTitles"] == ["Data Analyst"]
    assert actor["postedLimit"] == "week" and actor["maxItems"] == 65
    assert actor["sortBy"] == "relevance"
    # preview is read-only — it must not have created a searches/scratch.json
    assert c.get("/api/searches/scratch").status_code == 404
    assert "scratch" not in [s["name"] for s in c.get("/api/searches/structured").json()]
