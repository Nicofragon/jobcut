"""The Scorer interface — the contract every scoring backend implements.

A job is a flat dict of the columns produced by pull.flatten() (title,
description, company_name, location, workplace_type, applicants, ...). The
profile is the parsed contents of the user's profile.md (free-form for now).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class JobScore:
    """The result of scoring one job."""

    job_id: str
    match_score: int          # 0–100
    match_reasons: str        # one-line human-readable explanation
    status: str = "scored"    # "scored" | "discarded"


class Scorer(ABC):
    """Scores a job 0–100 against a profile and explains why in one line."""

    @abstractmethod
    def score(self, job: dict, profile: str) -> JobScore:
        """Score a single job. Must return a JobScore with 0 <= match_score <= 100."""
        raise NotImplementedError

    def score_batch(self, jobs: list[dict], profile: str) -> list[JobScore]:
        """Score many jobs. Default: call score() per job; backends may override
        with a more efficient bulk path (e.g. one LLM call per batch)."""
        return [self.score(job, profile) for job in jobs]
