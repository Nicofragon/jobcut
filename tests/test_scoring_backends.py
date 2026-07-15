"""Tests for the backend registry, capability probes and resolve_scorer."""

import os

import pytest

from jobcut import config
from jobcut.scoring import ResolveInfo, backend_status, get_scorer, known_backends, resolve_scorer
from jobcut.scoring.claude_skills import ClaudeSkillsScorer
from jobcut.scoring.rule_based import RuleBasedScorer


def _clear_claude_env(monkeypatch):
    """Make the claude_skills probe deterministic (the suite itself may run in Claude Code)."""
    monkeypatch.delenv("CLAUDECODE", raising=False)
    for k in [k for k in os.environ if k.startswith("CLAUDE_CODE")]:
        monkeypatch.delenv(k, raising=False)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(tmp_path))
    _clear_claude_env(monkeypatch)
    config.reset_cache()
    yield
    config.reset_cache()


_KEYS = {"id", "label", "description", "live", "available", "note", "order", "recommended"}


def test_backend_status_shape():
    rows = backend_status()
    assert [r["id"] for r in rows] == ["rule_based", "claude_skills"]
    for r in rows:
        assert _KEYS <= set(r)
        assert isinstance(r["live"], bool)
        assert isinstance(r["available"], bool)
        assert isinstance(r["note"], str)


def test_known_backends_matches_status_order():
    assert known_backends() == [r["id"] for r in backend_status()]


def test_rule_based_is_the_live_floor():
    rule = next(r for r in backend_status() if r["id"] == "rule_based")
    assert rule["available"] is True
    assert rule["live"] is True


def test_claude_skills_is_selectable_but_not_live():
    cs = next(r for r in backend_status() if r["id"] == "claude_skills")
    assert cs["live"] is False
    assert cs["note"]                       # the card explains where scoring happens


def test_resolve_rule_based_no_fallback():
    scorer, info = resolve_scorer({"scoring": {"backend": "rule_based"}})
    assert isinstance(scorer, RuleBasedScorer)
    assert isinstance(info, ResolveInfo)
    assert info.requested == "rule_based"
    assert info.effective == "rule_based"
    assert info.live is True
    assert info.fell_back is False


def test_resolve_claude_skills_yields_no_scorer():
    """The point of the whole change: claude_skills must NOT silently become rule_based."""
    scorer, info = resolve_scorer({"scoring": {"backend": "claude_skills"}})
    assert scorer is None
    assert info.requested == "claude_skills"
    assert info.effective == "claude_skills"      # not rewritten to the floor
    assert info.live is False
    assert info.fell_back is False
    assert info.reason                            # tells the user where to score


def test_resolve_claude_skills_stays_non_live_inside_claude(monkeypatch):
    """Being in Claude Code makes it *recommended*, never *live* — it's still ingest-first."""
    monkeypatch.setenv("CLAUDECODE", "1")
    scorer, info = resolve_scorer({"scoring": {"backend": "claude_skills"}})
    assert scorer is None and info.live is False


def test_resolve_unknown_backend_falls_back_to_the_floor():
    scorer, info = resolve_scorer({"scoring": {"backend": "ollama"}})
    assert isinstance(scorer, RuleBasedScorer)
    assert info.requested == "ollama"
    assert info.effective == "rule_based"
    assert info.live is True
    assert info.fell_back is True
    assert "unknown backend" in info.reason


def test_resolve_missing_scoring_config_defaults_to_rule_based():
    scorer, info = resolve_scorer({})
    assert isinstance(scorer, RuleBasedScorer)
    assert info.effective == "rule_based"
    assert info.fell_back is False


def test_get_scorer_rejects_removed_backends():
    for gone in ("local", "llm_api"):
        with pytest.raises(ValueError, match="Unknown scoring backend"):
            get_scorer(gone)


def test_claude_skills_scorer_points_at_ingest():
    with pytest.raises(RuntimeError, match="ingest-scores"):
        get_scorer("claude_skills").score({}, "profile")
    assert isinstance(get_scorer("claude_skills"), ClaudeSkillsScorer)
