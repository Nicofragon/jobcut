"""Tests for B3 — choice-card-ready scoring selector (recommended/order + set-backend)."""

import pytest
from fastapi.testclient import TestClient

from jobcut import config
from jobcut.api import create_app
from jobcut.scoring import backend_status


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JOBCUT_OLLAMA_URL", raising=False)

    # Default: pretend Ollama is unreachable so the local probe is deterministic
    # regardless of whether a real server happens to be running on this machine.
    # (test_recommended_prefers_local_when_reachable overrides this.)
    def _unreachable(*a, **k):
        raise OSError("no Ollama in tests")
    monkeypatch.setattr("urllib.request.urlopen", _unreachable)

    config.reset_cache()
    yield
    config.reset_cache()


class _Resp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b"ok"


def test_backend_status_is_choice_card_ready():
    rows = backend_status()
    for r in rows:
        assert isinstance(r["recommended"], bool)
        assert isinstance(r["order"], int)
    # choice-card order: Free → Local → API → Claude
    order = {r["id"]: r["order"] for r in rows}
    assert order["rule_based"] < order["local"] < order["llm_api"] < order["claude_skills"]


def test_exactly_one_recommended_defaults_to_rule_based():
    # no Ollama, no key -> only rule_based is usable -> it's the recommendation
    rows = backend_status()
    rec = [r["id"] for r in rows if r["recommended"]]
    assert rec == ["rule_based"]


def test_recommended_prefers_local_when_reachable(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _Resp())
    rows = backend_status()
    rec = [r["id"] for r in rows if r["recommended"]]
    assert rec == ["local"]                       # free + private + usable beats the floor
    assert next(r for r in rows if r["id"] == "local")["usable"] is True


def test_recommended_is_never_an_unusable_backend():
    # claude_skills is implemented=False -> never usable -> never recommended
    rows = backend_status()
    cs = next(r for r in rows if r["id"] == "claude_skills")
    assert cs["usable"] is False and cs["recommended"] is False


def test_endpoint_exposes_recommended_and_order():
    c = TestClient(create_app(serve_web=False))
    rows = c.get("/api/scoring/backends").json()
    assert all({"recommended", "order"} <= set(r) for r in rows)
    assert [r["id"] for r in rows if r["recommended"]] == ["rule_based"]


def test_set_backend_via_config_put():
    c = TestClient(create_app(serve_web=False))
    r = c.put("/api/config", json={"config": {"scoring": {"backend": "local"}}})
    assert r.status_code == 200
    assert c.get("/api/config").json()["scoring"]["backend"] == "local"
