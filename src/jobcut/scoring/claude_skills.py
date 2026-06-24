"""claude_skills — adapter for Claude Code / Cowork users (ingest-first, A3).

Delegates scoring to the user's own job-scoring skill/subagents (zero marginal
cost for a Claude subscriber, highest quality). Not portable as a default — it's
a tier, not the floor.

This backend is **ingest-first**: it does NOT score inside the live pipeline.
The skill runs outside jobcut and emits a JSON of scores, loaded with
``jobcut ingest-scores``. So `claude_skills` stays implemented=False in the
registry — `jobcut score` degrades to rule_based — and score() below is only a
signpost for anyone who constructs the scorer directly.
"""

from __future__ import annotations

from .base import JobScore, Scorer


class ClaudeSkillsScorer(Scorer):
    def score(self, job: dict, profile: str) -> JobScore:
        raise RuntimeError(
            "The claude_skills backend doesn't score inside the live pipeline. "
            "Run your Claude Code / Cowork scoring skill, then load the results with "
            "`jobcut ingest-scores <scores.json>`."
        )
