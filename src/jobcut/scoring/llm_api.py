"""llm_api — OPTIONAL scorer that calls an LLM with your own key.

Higher quality than rule_based, at a per-job API cost. Uses the shared llm.py
helper (Anthropic or OpenAI, whichever is installed + keyed). Requires the
optional extra and a key:  ``pip install 'jobcut[llm]'`` + ANTHROPIC_API_KEY
or OPENAI_API_KEY (env or <data>/.env).

The model is asked to return strict JSON {score, reason}; parsing is defensive
(tolerates code fences / surrounding prose). If no LLM is configured the scorer
fails loudly — rule_based remains the keyless default.
"""

from __future__ import annotations

import json
import re

from .. import llm
from .base import JobScore, Scorer

_SYSTEM = (
    "You are a job-matching assistant. Score how well a single job fits the "
    "candidate's profile from 0 to 100 and explain why in one short line. "
    'Reply with ONLY a JSON object: {"score": <int 0-100>, "reason": "<one line>"}.'
)


def _parse(text: str, job_id: str) -> JobScore:
    """Extract {score, reason} from the model's reply (tolerant of fences/prose)."""
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        raise ValueError(f"LLM reply had no JSON object: {text!r:.120}")
    data = json.loads(m.group(0))
    score = max(0, min(100, int(round(float(data.get("score", 0))))))
    reason = str(data.get("reason", "")).strip()[:160] or "llm score"
    return JobScore(job_id=str(job_id), match_score=score, match_reasons=reason, status="scored")


class LLMApiScorer(Scorer):
    def __init__(self, provider: str = "auto", model: str | None = None):
        self.provider = provider
        self.model = model

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
        reply = llm.complete(self._prompt(job, profile), system=_SYSTEM, max_tokens=200)
        if reply is None:
            raise RuntimeError(
                "llm_api backend needs an LLM: install 'jobcut[llm]' and set "
                "ANTHROPIC_API_KEY or OPENAI_API_KEY (or use the default rule_based backend)."
            )
        return _parse(reply, job.get("job_id", ""))
