"""claude_skills — the Claude Code / Cowork scoring path (ingest-first).

Delegates scoring to your own job-scoring skill: it reads each job, judges it
against your profile, and loads the results with ``jobcut ingest-scores``. Zero
marginal cost on a Claude subscription, and the best judgement jobcut can offer.

This backend is **ingest-first**: it does NOT score inside the live pipeline, so
`registry` marks it ``live=False`` and `resolve_scorer` returns no scorer for it.
That is deliberate — selecting it makes `jobcut score` stand aside and point you
at your skill, rather than quietly rubric-scoring rows you expected Claude to
judge. `score()` below is only a signpost for anyone constructing it directly.
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
