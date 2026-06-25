"""process.py — extract an interview-process stage list from a job description.

On-demand only (the /process/suggest endpoint). Reuses the configured LLM client;
falls back to a default template when no LLM is available or the description has no
process described. Never persists — returns a suggestion for the user to confirm.
"""

from __future__ import annotations

import json

from . import llm

DEFAULT_TEMPLATE = ["Recruiter screen", "Technical", "Hiring Manager", "Final"]

_SYSTEM = "You extract interview process stages from job postings. Reply with ONLY a JSON array."
_PROMPT = (
    "From the job description below, list the interview process stages as a JSON array of "
    "short stage names in order (e.g. [\"Recruiter screen\",\"Technical\",\"Hiring Manager\"]). "
    "If the description does not describe an interview process, reply with []. "
    "Description:\n\n{desc}"
)


def extract_process(description: str) -> tuple[list[str], str]:
    """Return (stages, source). source ∈ {'llm','template'}. Falls back to
    DEFAULT_TEMPLATE when there's no description, no LLM, no process is described,
    or the LLM call errors — never crashes, always degrades to the template."""
    if not (description or "").strip():
        return list(DEFAULT_TEMPLATE), "template"
    if not llm.available():
        return list(DEFAULT_TEMPLATE), "template"
    try:
        raw = llm.complete(_PROMPT.format(desc=description[:6000]), system=_SYSTEM)
    except Exception:
        return list(DEFAULT_TEMPLATE), "template"
    stages = _parse(raw)
    if stages:
        return stages, "llm"
    return list(DEFAULT_TEMPLATE), "template"


def _parse(raw: str | None) -> list[str]:
    if not raw:
        return []
    s = raw.strip()
    start = s.find("[")
    end = s.find("]", start)
    if start == -1 or end == -1:
        return []
    try:
        data = json.loads(s[start:end + 1])
    except ValueError:
        return []
    if not isinstance(data, list) or any(not isinstance(x, (str, int)) for x in data):
        return []
    return [str(x).strip() for x in data if str(x).strip()]
