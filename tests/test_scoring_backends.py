"""Tests for the backend registry, capability probes and resolve_scorer fallback (A1)."""

import pytest

from jobcut import config
from jobcut.scoring import ResolveInfo, backend_status, resolve_scorer
from jobcut.scoring.rule_based import RuleBasedScorer


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(tmp_path))
    config.reset_cache()
    yield
    config.reset_cache()


_KEYS = {"id", "label", "description", "available", "usable", "reason"}


def test_backend_status_shape():
    rows = backend_status()
    assert [r["id"] for r in rows] == ["rule_based", "llm_api", "local", "claude_skills"]
    for r in rows:
        assert _KEYS <= set(r)
        assert isinstance(r["available"], bool)
        assert isinstance(r["usable"], bool)
        assert isinstance(r["reason"], str)


def test_rule_based_always_usable():
    rule = next(r for r in backend_status() if r["id"] == "rule_based")
    assert rule["available"] is True
    assert rule["usable"] is True


def test_resolve_rule_based_no_fallback():
    scorer, info = resolve_scorer({"scoring": {"backend": "rule_based"}})
    assert isinstance(scorer, RuleBasedScorer)
    assert isinstance(info, ResolveInfo)
    assert info.requested == "rule_based"
    assert info.effective == "rule_based"
    assert info.fell_back is False


def test_resolve_llm_api_without_key_falls_back(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    scorer, info = resolve_scorer({"scoring": {"backend": "llm_api"}})
    assert isinstance(scorer, RuleBasedScorer)
    assert info.requested == "llm_api"
    assert info.effective == "rule_based"
    assert info.fell_back is True
    assert info.reason


@pytest.mark.parametrize("backend", ["claude_skills"])
def test_resolve_unimplemented_falls_back(backend):
    # implemented=False -> never usable, even if the env probe says available.
    # (local is implemented since A2 and has its own tests in test_scoring_local.py.)
    scorer, info = resolve_scorer({"scoring": {"backend": backend}})
    assert isinstance(scorer, RuleBasedScorer)
    assert info.requested == backend
    assert info.effective == "rule_based"
    assert info.fell_back is True
    assert info.reason
