"""Pluggable scoring backends.

A `Scorer` takes a job (dict of flattened columns) + the user's profile and
returns a `JobScore` (0–100 + a one-line reason). Backends are selected by
config:

  - rule_based   — default, pure Python, no API key (the floor; must always work).
  - llm_api      — optional OpenAI/Anthropic hook (bring your own key).
  - claude_skills — optional adapter for Claude Code / Claude skills users.

PHASE 1 implements the backends. This package currently ships the interface
(`base`) and stubs.
"""

from dataclasses import dataclass

from .base import JobScore, Scorer
from .registry import backend_status

__all__ = ["JobScore", "Scorer", "get_scorer", "resolve_scorer", "ResolveInfo", "backend_status"]


def get_scorer(backend: str = "rule_based", **kwargs) -> Scorer:
    """Factory: return a Scorer instance for the named backend."""
    if backend == "rule_based":
        from .rule_based import RuleBasedScorer
        return RuleBasedScorer(**kwargs)
    if backend == "llm_api":
        from .llm_api import LLMApiScorer
        return LLMApiScorer(**kwargs)
    if backend == "local":
        from .local import LocalScorer
        return LocalScorer(**kwargs)
    if backend == "claude_skills":
        from .claude_skills import ClaudeSkillsScorer
        return ClaudeSkillsScorer(**kwargs)
    raise ValueError(f"Unknown scoring backend: {backend!r} "
                     "(expected 'rule_based', 'llm_api', 'local' or 'claude_skills')")


@dataclass
class ResolveInfo:
    """Outcome of resolving the configured backend to an effective scorer."""

    requested: str
    effective: str
    fell_back: bool
    reason: str


def resolve_scorer(cfg: dict, **kwargs) -> tuple[Scorer, ResolveInfo]:
    """Build the scorer for ``cfg["scoring"]["backend"]``, degrading to rule_based.

    If the requested backend is *usable* (implemented AND available) it is built
    directly. Otherwise we fall back to ``rule_based`` (the floor) and report the
    motive in ResolveInfo. ``kwargs`` are the rule_based kwargs (taxonomy, weights,
    …) used whenever the effective backend is rule_based.
    """
    requested = (cfg.get("scoring") or {}).get("backend", "rule_based")
    status = {b["id"]: b for b in backend_status()}
    entry = status.get(requested)

    if entry and entry["usable"]:
        info = ResolveInfo(requested, requested, False, "")
    else:
        reason = entry["reason"] if entry else f"unknown backend {requested!r}"
        info = ResolveInfo(requested, "rule_based", True, reason)

    if info.effective == "rule_based":
        return get_scorer("rule_based", **kwargs), info
    return get_scorer(info.effective), info
