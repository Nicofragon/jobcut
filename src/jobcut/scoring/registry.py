"""Backend registry + capability probes (A1).

Each known scoring backend has static metadata (label/description, whether it's
*implemented* yet) and a cheap *availability* probe. A backend is **usable**
only when it is both implemented AND available; otherwise the selector degrades
to `rule_based` (the floor). The probes never raise and never spend money:
`local` does a short-timeout urllib GET; `claude_skills` sniffs the environment.

A1 ships only the scaffold. The `local` scorer (Ollama) is A2 and the
`claude_skills` logic is A3, so both are `implemented=False` here.
"""

from __future__ import annotations

import os
import urllib.request
from dataclasses import dataclass

from .. import llm

OLLAMA_DEFAULT_URL = "http://localhost:11434"


@dataclass
class BackendMeta:
    id: str
    label: str
    description: str
    implemented: bool


def _ollama_url() -> str:
    return os.environ.get("JOBCUT_OLLAMA_URL") or OLLAMA_DEFAULT_URL


# --- availability probes (cheap, never raise) -------------------------------

def _rule_based_available() -> bool:
    return True


def _llm_api_available() -> bool:
    return llm.available()


def _local_available() -> bool:
    """True if an Ollama-compatible server answers at JOBCUT_OLLAMA_URL."""
    try:
        with urllib.request.urlopen(_ollama_url(), timeout=0.5) as resp:
            return getattr(resp, "status", 200) < 500
    except Exception:
        return False


def _claude_skills_available() -> bool:
    """True when running inside Claude Code / Cowork (detected via env)."""
    if os.environ.get("CLAUDECODE"):
        return True
    return any(k.startswith("CLAUDE_CODE") for k in os.environ)


_BACKENDS: list[tuple[BackendMeta, object]] = [
    (BackendMeta("rule_based", "Free (rule-based)",
                 "Pure-Python rubric. No key, no cost. Always available — the floor.",
                 True), _rule_based_available),
    (BackendMeta("llm_api", "API (your key)",
                 "Calls an LLM with your own API key (Anthropic/OpenAI). Higher quality, per-job cost.",
                 True), _llm_api_available),
    (BackendMeta("local", "Local (Ollama)",
                 "Scores on a local Ollama/LM Studio server. Free, private, no key.",
                 True), _local_available),
    (BackendMeta("claude_skills", "Claude skills",
                 "Scores from your Claude Code / Cowork skill, loaded via `jobcut ingest-scores`. "
                 "Not a live-pipeline scorer.",
                 False), _claude_skills_available),
]


def _reason(meta: BackendMeta, available: bool, usable: bool) -> str:
    """Human-readable motive when a backend is not usable ('' when it is)."""
    if usable:
        return ""
    if not meta.implemented:
        return "not a live-pipeline scorer; load scores via `jobcut ingest-scores`"
    if meta.id == "llm_api":
        return "no LLM key configured (set ANTHROPIC_API_KEY or OPENAI_API_KEY)"
    if meta.id == "local":
        return f"Ollama not reachable at {_ollama_url()}"
    return "unavailable"


# choice-card display order (B3): Free → Local → API → Claude
_CARD_ORDER = {"rule_based": 0, "local": 1, "llm_api": 2, "claude_skills": 3}
# which usable backend to suggest, best-first (free+private > paid > floor; claude_skills isn't live)
_RECOMMEND_PREF = ["local", "llm_api", "rule_based"]


def backend_status() -> list[dict]:
    """Status of every known backend, choice-card-ready (B3).

    Each entry: {id, label, description, available, usable, reason, order, recommended}.
    `order` is the friendly card order; exactly one usable backend is `recommended`.
    """
    out = []
    for meta, probe in _BACKENDS:
        available = bool(probe())
        usable = meta.implemented and available
        out.append({
            "id": meta.id,
            "label": meta.label,
            "description": meta.description,
            "available": available,
            "usable": usable,
            "reason": _reason(meta, available, usable),
            "order": _CARD_ORDER.get(meta.id, 99),
            "recommended": False,
        })
    usable_ids = {b["id"] for b in out if b["usable"]}
    rec = next((i for i in _RECOMMEND_PREF if i in usable_ids), "rule_based")
    for b in out:
        b["recommended"] = b["id"] == rec
    return out
