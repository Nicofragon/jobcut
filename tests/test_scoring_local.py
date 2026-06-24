"""Tests for the local (Ollama / LM Studio, OpenAI-compatible) scorer — A2."""

import json
import urllib.error

import pytest

from jobcut import config
from jobcut.scoring import backend_status, get_scorer, resolve_scorer
from jobcut.scoring.local import LocalScorer
from jobcut.scoring.rule_based import RuleBasedScorer


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("JOBCUT_OLLAMA_URL", raising=False)
    config.reset_cache()
    yield
    config.reset_cache()


class _FakeResp:
    """Minimal stand-in for the urlopen context manager."""

    def __init__(self, body: bytes = b"", status: int = 200):
        self._body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def _chat_body(content: str) -> bytes:
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode()


def _capture_urlopen(monkeypatch, content='{"score": 85, "reason": "great fit"}'):
    """Patch urlopen to record the last request and return a canned chat reply."""
    calls = {}

    def fake(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        calls["url"] = url
        if hasattr(req, "data") and req.data:
            calls["body"] = json.loads(req.data)
        return _FakeResp(_chat_body(content))

    monkeypatch.setattr("urllib.request.urlopen", fake)
    return calls


def test_get_scorer_local_returns_localscorer():
    assert isinstance(get_scorer("local"), LocalScorer)


def test_local_scores_via_openai_compatible_endpoint(monkeypatch):
    calls = _capture_urlopen(monkeypatch)
    scorer = LocalScorer(model="qwen2.5", base_url="http://localhost:11434")
    js = scorer.score({"job_id": "7", "title": "Data Analyst", "description": "SQL Python"}, "profile")

    assert calls["url"].endswith("/v1/chat/completions")
    assert calls["body"]["model"] == "qwen2.5"
    assert js.job_id == "7" and js.match_score == 85 and "great fit" in js.match_reasons


def test_local_tolerates_fenced_json(monkeypatch):
    _capture_urlopen(monkeypatch, content='```json\n{"score": 142, "reason": "x"}\n```')
    js = LocalScorer(model="qwen2.5").score({"job_id": "1", "title": "x"}, "")
    assert js.match_score == 100  # clamped


def test_local_raises_when_unreachable(monkeypatch):
    def boom(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(RuntimeError, match="(?i)ollama|local"):
        LocalScorer(model="qwen2.5").score({"job_id": "1", "title": "x"}, "")


def test_local_model_defaults_from_config():
    assert config.load()["scoring"]["local"]["model"] == "qwen2.5"
    assert LocalScorer().model == "qwen2.5"


def test_backend_status_local_implemented_and_usable_when_reachable(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _FakeResp(b"ok"))
    local = next(b for b in backend_status() if b["id"] == "local")
    assert local["available"] is True
    assert local["usable"] is True
    assert local["reason"] == ""


def test_resolve_local_uses_localscorer_when_reachable(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _FakeResp(b"ok"))
    scorer, info = resolve_scorer({"scoring": {"backend": "local"}})
    assert isinstance(scorer, LocalScorer)
    assert info.effective == "local"
    assert info.fell_back is False


def test_resolve_local_falls_back_when_unreachable(monkeypatch):
    def boom(req, timeout=None):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    scorer, info = resolve_scorer({"scoring": {"backend": "local"}})
    assert isinstance(scorer, RuleBasedScorer)
    assert info.fell_back is True
    assert "not reachable" in info.reason.lower() or "ollama" in info.reason.lower()
