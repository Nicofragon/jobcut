"""Backend registry + capability probes.

jobcut ships exactly two ways to score, and they differ in *where* the scoring
happens rather than in quality tiers:

  - `rule_based` — **live**: scores inside `jobcut score`, pure Python, no key.
  - `claude_skills` — **ingest-first**: your Claude Code / Cowork skill scores
    outside jobcut and the results are loaded with `jobcut ingest-scores`.

Both are always *selectable*; the distinction that matters is `live`. A non-live
backend is a real choice — it tells `jobcut score` to stand aside rather than
silently scoring with the rubric behind your back.

`available` is a cheap, never-raising probe used only to pick the *recommended*
card: it detects whether you're running inside Claude Code / Cowork right now.
It never gates selection — you can choose `claude_skills` from a plain terminal
and drive it from Claude later.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class BackendMeta:
    id: str
    label: str
    description: str
    live: bool          # scores inside `jobcut score` (False = ingest-first)
    note: str           # extra hint for the choice card ("" when there's nothing to add)


# --- availability probes (cheap, never raise) -------------------------------

def _rule_based_available() -> bool:
    return True


def _claude_skills_available() -> bool:
    """True when running inside Claude Code / Cowork (detected via env)."""
    if os.environ.get("CLAUDECODE"):
        return True
    return any(k.startswith("CLAUDE_CODE") for k in os.environ)


_BACKENDS: list[tuple[BackendMeta, object]] = [
    (BackendMeta("rule_based", "Free (rule-based)",
                 "Pure-Python rubric that runs on your machine. No key, no cost, works offline.",
                 True, ""), _rule_based_available),
    (BackendMeta("claude_skills", "Claude skills",
                 "Your Claude Code / Cowork skill reads each job and scores it. "
                 "Best quality, no extra cost on a Claude subscription.",
                 False, "Scoring happens in Claude, not in `jobcut score` — run your scoring "
                         "skill and it loads the results for you."), _claude_skills_available),
]

# choice-card display order: Free → Claude
_CARD_ORDER = {"rule_based": 0, "claude_skills": 1}


def backend_status() -> list[dict]:
    """Status of every scoring backend, choice-card-ready.

    Each entry: {id, label, description, live, available, note, order, recommended}.
    Exactly one backend is `recommended`: Claude skills when we can tell you're
    inside Claude Code / Cowork, otherwise the free rubric.
    """
    out = []
    for meta, probe in _BACKENDS:
        out.append({
            "id": meta.id,
            "label": meta.label,
            "description": meta.description,
            "live": meta.live,
            "available": bool(probe()),
            "note": meta.note,
            "order": _CARD_ORDER.get(meta.id, 99),
            "recommended": False,
        })
    in_claude = next((b["available"] for b in out if b["id"] == "claude_skills"), False)
    rec = "claude_skills" if in_claude else "rule_based"
    for b in out:
        b["recommended"] = b["id"] == rec
    return out


def known_backends() -> list[str]:
    """Every selectable backend id, in card order."""
    return [m.id for m, _ in sorted(_BACKENDS, key=lambda p: _CARD_ORDER.get(p[0].id, 99))]
