"""config.py — user-tunable settings (routing, title filter, scoring weights).

Resolution: built-in DEFAULTS, deep-merged with <data>/config/config.json if it
exists. This means the pipeline works out of the box with sensible (generic,
example) values, and the user overrides only the keys they care about.

`jobcut init` writes a starter config/config.json. The geography defaults are
an EXAMPLE — every user should edit them.
"""

from __future__ import annotations

import json
from functools import lru_cache

from . import paths

DEFAULTS = {
    # Geography: who is hireable for you. EXAMPLE values — edit to your own.
    "routing": {
        # Fully hireable (on-site, hybrid or remote).
        "home": r"\b(spain|espa[nñ]a|madrid|barcelona|valencia|seville|sevilla|m[aá]laga|bilbao)\b",
        # Hireable only when remote.
        "region": r"(european union|european economic area|\beea\b|\bemea\b|^europe$|^eu$)",
    },
    # Filter: which job titles are worth scoring (everything else is dropped cheaply).
    "filter": {
        "include_titles": (
            r"(data analyst|data scien|analytics|business intelligence|\bbi\b|product analyst|"
            r"business analyst|data engineer|machine learning|\bml\b|\bai\b|artificial intelligence|"
            r"insight|reporting analyst|decision scien|quantitative|growth analyst|marketing analyst|"
            r"crm analyst|data ?& ?ai|data and ai|datos|anal[ií]st|cient[ií]fic|ingenier[oa] de datos|"
            r"inteligencia artificial|aprendizaje autom)"
        ),
    },
    # Scoring: backend selection + rule_based rubric weights.
    "scoring": {
        # "rule_based" (scores here) or "claude_skills" (your Claude skill scores and
        # loads results with `jobcut ingest-scores`). See scoring/registry.py.
        "backend": "rule_based",
        "weights": {
            "title": 30,        # title matches a target role
            "stack": 20,        # stack keywords present
            "location": 15,     # workable location
            "signals": 10,      # profile "nice-to-have" signals present (role-agnostic)
            "employer": 10,     # reasonable employer (some size)
            "reachable": 10,    # few applicants, or a named recruiter
            "dealbreaker": -20, # a hard requirement you don't meet
        },
        # "nice-to-have" boost patterns + dealbreaker patterns, both derived from the
        # profile (empty by default = no field-specific bias). See profile.py.
        "signals": [],
        "dealbreakers": [],
        # Out-of-profile roles (title doesn't match your target roles) capped below this.
        "out_of_profile_cap": 30,
    },
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def config_file():
    return paths.config_dir() / "config.json"


def taxonomy_file():
    return paths.config_dir() / "taxonomy.json"


def load_taxonomy(required: bool = False) -> dict:
    """Load config/taxonomy.json. Returns {} if missing (unless required)."""
    p = taxonomy_file()
    if p.exists():
        return json.loads(p.read_text())
    if required:
        raise SystemExit(f"No taxonomy at {p}. Copy config/taxonomy.example.json to {p.name} and edit it.")
    return {}


@lru_cache(maxsize=8)
def _load_cached(path_str: str) -> dict:
    from pathlib import Path
    p = Path(path_str)
    if p.exists():
        return _deep_merge(DEFAULTS, json.loads(p.read_text()))
    return DEFAULTS


def load() -> dict:
    """Return the merged config (DEFAULTS + config/config.json)."""
    return _load_cached(str(config_file()))


def update(over: dict) -> dict:
    """Deep-merge `over` into the saved overrides (config/config.json) and persist.

    Preserves unrelated sibling keys — e.g. saving scoring.weights keeps a
    previously-set scoring.backend instead of wiping it. Returns the merged config.
    """
    p = config_file()
    existing = json.loads(p.read_text()) if p.exists() else {}
    merged = _deep_merge(existing, over)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(merged, indent=2))
    reset_cache()
    return load()


def reset_cache() -> None:
    """Clear the config cache (tests / after writing a new config)."""
    _load_cached.cache_clear()
