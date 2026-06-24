"""searches.py — structured ↔ actor-input mapping for saved searches (B2).

A saved search is canonically `searches/<name>.json` holding the
harvestapi/linkedin-job-search actor input. The jargon pain is `geoIds` (numeric
LinkedIn ids). This adds a form-friendly `StructuredSearch` that round-trips with
that actor dict, resolving human location names to geoIds via `geo.resolve` and
falling back to a manual override / `needs_geoid` flag — never inventing ids.

`searches/*.json` stays canonical: pull.py and profile.derive_searches are untouched.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from . import geo

_GEOID_UNSET = "REPLACE_ME"   # the canonical "no geoId yet" marker (matches the templates)
_DEFAULT_EMPLOYMENT = ["full-time"]
_DEFAULT_MAX_ITEMS = 50
_DEFAULT_POSTED = "24h"


class StructuredSearch(BaseModel):
    """Form-friendly saved search. Round-trips with the actor input dict."""

    name: str | None = None
    titles: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)        # human names ("European Economic Area")
    work_types: list[str] = Field(default_factory=list)       # actor enum: remote | hybrid | office
    employment_types: list[str] = Field(default_factory=list)
    max_items: int | None = None
    posted_within: str | None = None                          # e.g. "24h"
    geo_ids: list[str] = Field(default_factory=list)          # advanced: manual geoId override
    needs_geoid: bool = False                                 # set on read/resolve when unresolved


def resolve_geoids(s: StructuredSearch) -> tuple[list[str], bool]:
    """Resolve a search's geoIds: table hits + manual override (deduped).

    Returns (geo_ids, needs_geoid). If nothing resolves and there's no override,
    returns ([REPLACE_ME], True) so the search is flagged, never run with a bogus id.
    """
    resolved = [gid for loc in s.locations if (gid := geo.resolve(loc))]
    geoids = list(dict.fromkeys([*resolved, *s.geo_ids]))     # resolved first, override supplements
    if geoids:
        return geoids, False
    return [_GEOID_UNSET], True


def to_actor_input(s: StructuredSearch) -> dict:
    """Serialize to the actor input dict pull.py consumes (the canonical 7 keys)."""
    geoids, _ = resolve_geoids(s)
    return {
        "jobTitles": list(s.titles),
        "geoIds": geoids,
        "workplaceType": list(s.work_types),
        "employmentType": list(s.employment_types) or list(_DEFAULT_EMPLOYMENT),
        "maxItems": s.max_items or _DEFAULT_MAX_ITEMS,
        "postedLimit": s.posted_within or _DEFAULT_POSTED,
        "sortBy": "relevance",
    }


def from_actor_input(name: str, actor: dict) -> StructuredSearch:
    """Read an existing actor input dict into StructuredSearch (for the friendly form).

    Human location names can't be recovered from geoIds, so existing ids land in
    `geo_ids` (the advanced override) and `locations` stays empty. A missing/unset
    geoId (REPLACE_ME) flags `needs_geoid`.
    """
    geoids = [g for g in (actor.get("geoIds") or []) if g and g != _GEOID_UNSET]
    return StructuredSearch(
        name=name,
        titles=list(actor.get("jobTitles") or []),
        locations=[],
        work_types=list(actor.get("workplaceType") or []),
        employment_types=list(actor.get("employmentType") or []),
        max_items=actor.get("maxItems"),
        posted_within=actor.get("postedLimit"),
        geo_ids=geoids,
        needs_geoid=not geoids,
    )
