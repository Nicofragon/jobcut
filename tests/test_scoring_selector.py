"""Tests for the choice-card scoring selector (recommended/order + set-backend)."""

import os

import pytest
from fastapi.testclient import TestClient

from jobcut import config
from jobcut.api import create_app
from jobcut.scoring import backend_status


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(tmp_path))
    # The claude_skills probe sniffs the environment, and this suite may itself be run
    # from Claude Code — clear the markers so "not in Claude" is the deterministic
    # default. (test_recommended_is_claude_skills_inside_claude sets them back.)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    for k in [k for k in os.environ if k.startswith("CLAUDE_CODE")]:
        monkeypatch.delenv(k, raising=False)
    config.reset_cache()
    yield
    config.reset_cache()


def test_backend_status_is_choice_card_ready():
    rows = backend_status()
    for r in rows:
        assert isinstance(r["recommended"], bool)
        assert isinstance(r["order"], int)
    order = {r["id"]: r["order"] for r in rows}
    assert order["rule_based"] < order["claude_skills"]     # Free → Claude


def test_exactly_one_recommended_outside_claude():
    rows = backend_status()
    assert [r["id"] for r in rows if r["recommended"]] == ["rule_based"]


def test_recommended_is_claude_skills_inside_claude(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    rows = backend_status()
    assert [r["id"] for r in rows if r["recommended"]] == ["claude_skills"]


def test_claude_skills_is_offered_even_outside_claude():
    """`available` only drives the recommendation — it must never gate selection:
    you can pick Claude scoring from a plain terminal and drive it from Claude later."""
    cs = next(r for r in backend_status() if r["id"] == "claude_skills")
    assert cs["available"] is False
    assert cs["recommended"] is False
    assert cs in backend_status()          # still listed as a card


def test_endpoint_exposes_recommended_and_order():
    c = TestClient(create_app(serve_web=False))
    rows = c.get("/api/scoring/backends").json()
    assert all({"recommended", "order", "live", "note"} <= set(r) for r in rows)
    assert [r["id"] for r in rows] == ["rule_based", "claude_skills"]
    assert [r["id"] for r in rows if r["recommended"]] == ["rule_based"]


def test_set_backend_via_config_put():
    c = TestClient(create_app(serve_web=False))
    r = c.put("/api/config", json={"config": {"scoring": {"backend": "claude_skills"}}})
    assert r.status_code == 200
    assert c.get("/api/config").json()["scoring"]["backend"] == "claude_skills"
