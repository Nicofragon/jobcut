"""Pluggable scoring backends.

A `Scorer` takes a job (dict of flattened columns) + the user's profile and
returns a `JobScore` (0–100 + a one-line reason). Two backends ship, selected by
``config.scoring.backend``:

  - rule_based    — the floor: pure Python, no key, scores inside `jobcut score`.
  - claude_skills — ingest-first: your Claude skill scores outside jobcut and the
                    results arrive via `jobcut ingest-scores`.

Only `rule_based` is *live* (see registry.py). Picking `claude_skills` is a real
choice, not an alias for the rubric: `resolve_scorer` returns **no scorer** for
it, so `jobcut score` stands aside and points you at your skill instead of
quietly rubric-scoring rows you expected Claude to judge.
"""

from dataclasses import dataclass

from .base import JobScore, Scorer
from .registry import backend_status, known_backends

__all__ = ["JobScore", "Scorer", "get_scorer", "resolve_scorer", "ResolveInfo",
           "backend_status", "known_backends"]


def get_scorer(backend: str = "rule_based", **kwargs) -> Scorer:
    """Factory: return a Scorer instance for the named backend."""
    if backend == "rule_based":
        from .rule_based import RuleBasedScorer
        return RuleBasedScorer(**kwargs)
    if backend == "claude_skills":
        from .claude_skills import ClaudeSkillsScorer
        return ClaudeSkillsScorer(**kwargs)
    raise ValueError(f"Unknown scoring backend: {backend!r} "
                     "(expected 'rule_based' or 'claude_skills')")


@dataclass
class ResolveInfo:
    """Outcome of resolving the configured backend to an effective scorer."""

    requested: str
    effective: str
    live: bool          # False -> no scorer; scores arrive via `jobcut ingest-scores`
    fell_back: bool     # True only when `requested` was not a known backend
    reason: str


def resolve_scorer(cfg: dict, **kwargs) -> tuple[Scorer | None, ResolveInfo]:
    """Build the scorer for ``cfg["scoring"]["backend"]``.

    Returns ``(None, info)`` when the configured backend is not live (i.e.
    `claude_skills`) — the caller must not score. An *unknown* backend still
    degrades to `rule_based` (the floor) so a typo can't break the pipeline.
    ``kwargs`` are the rule_based kwargs (taxonomy, weights, …).
    """
    requested = (cfg.get("scoring") or {}).get("backend", "rule_based")
    entry = {b["id"]: b for b in backend_status()}.get(requested)

    if entry is None:
        info = ResolveInfo(requested, "rule_based", True, True, f"unknown backend {requested!r}")
        return get_scorer("rule_based", **kwargs), info

    if not entry["live"]:
        return None, ResolveInfo(requested, requested, False, False, entry["note"])

    return get_scorer(requested, **kwargs), ResolveInfo(requested, requested, True, False, "")
