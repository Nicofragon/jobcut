"""local — scorer backed by a local LLM (Ollama / LM Studio), no API key.

Talks to the OpenAI-compatible endpoint both servers expose
(``POST {base_url}/v1/chat/completions``), so the same code works for either.
Free, private, runs on localhost. Uses only the stdlib (``urllib``) — no extra
dependency — and reuses the system prompt + tolerant JSON parser from llm_api.

The server URL is ``JOBCUT_OLLAMA_URL`` (default http://localhost:11434, the
*root*; we append the OpenAI path). The model is ``config.scoring.local.model``
(default ``qwen2.5``); the user must ``ollama pull`` it first.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .. import config
from .base import JobScore, Scorer
from .llm_api import _SYSTEM, _parse
from .registry import OLLAMA_DEFAULT_URL


def _default_model() -> str:
    return (config.load().get("scoring") or {}).get("local", {}).get("model", "qwen2.5")


def _timeout() -> float:
    """Per-request timeout (seconds). CPU inference on big descriptions can be slow,
    so allow JOBCUT_OLLAMA_TIMEOUT / config scoring.local.timeout to raise it."""
    env = os.environ.get("JOBCUT_OLLAMA_TIMEOUT")
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    return float((config.load().get("scoring") or {}).get("local", {}).get("timeout", 120))


class LocalScorer(Scorer):
    def __init__(self, model: str | None = None, base_url: str | None = None):
        self.model = model or _default_model()
        self.base_url = (base_url or os.environ.get("JOBCUT_OLLAMA_URL")
                         or OLLAMA_DEFAULT_URL).rstrip("/")

    @property
    def _endpoint(self) -> str:
        return f"{self.base_url}/v1/chat/completions"

    def _prompt(self, job: dict, profile: str) -> str:
        return (
            f"CANDIDATE PROFILE:\n{profile or '(empty)'}\n\n"
            f"JOB:\n"
            f"Title: {job.get('title', '')}\n"
            f"Company: {job.get('company_name', '')} ({job.get('company_size', '')})\n"
            f"Location: {job.get('location', '')} · {job.get('workplace_type', '')}\n"
            f"Description:\n{str(job.get('description', ''))[:6000]}"
        )

    def score(self, job: dict, profile: str = "") -> JobScore:
        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": self._prompt(job, profile)},
            ],
            "stream": False,
            "temperature": 0,
        }).encode()
        req = urllib.request.Request(
            self._endpoint, data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=_timeout()) as resp:
                data = json.loads(resp.read())
        except (urllib.error.URLError, OSError) as exc:
            raise RuntimeError(
                f"local backend could not reach Ollama at {self.base_url} ({exc}). "
                "Is the server running? (or use the default rule_based backend)."
            ) from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                f"local backend got an unexpected reply from {self.base_url}: {data!r:.200}. "
                f"Is model {self.model!r} pulled? Try `ollama pull {self.model}`."
            ) from exc
        return _parse(content, job.get("job_id", ""))
