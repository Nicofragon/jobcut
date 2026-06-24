"""geo.py — resolve a human location name to a LinkedIn geoId (B2).

The harvestapi/linkedin-job-search actor wants numeric LinkedIn geoIds; users
shouldn't have to find/paste them. This resolves a friendly name (e.g. "European
Economic Area") to a geoId via a small **bundled, extensible** table
(`data/geoids.json`), seeded only with VERIFIED values — an invented geoId
returns empty results silently, so we never guess. Unresolved names fall back to
a manual override or are flagged `needs_geoid` upstream (see searches.py).

Distinct from `route.geo()`, which classifies a location as home/region/foreign
for hireability — this just maps a name to an actor geoId.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", str(name).strip().lower())


@lru_cache(maxsize=1)
def _table() -> dict[str, str]:
    """The bundled {normalized_name: geo_id} map (empty if the data file is missing)."""
    try:
        raw = (resources.files("jobcut") / "data" / "geoids.json").read_text()
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return {}
    data = json.loads(raw)
    return {_norm(k): str(v) for k, v in (data.get("geoids") or {}).items()}


def resolve(location_name: str) -> str | None:
    """Return the geoId for a location name, or None if it isn't in the bundled table."""
    return _table().get(_norm(location_name))
