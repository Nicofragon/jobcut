"""searches.py — structured ↔ actor-input mapping for saved searches (B2).

A saved search is canonically `searches/<name>.json` holding the
harvestapi/linkedin-job-search actor input. The jargon pain was `geoIds` (numeric
LinkedIn ids). The actor also accepts free-text `locations` (its primary location
filter), so a plain name like "Madrid" is a runnable search with no geoId. This
`StructuredSearch` round-trips with the actor dict: names go to `locations`, names
we have a verified geoId for (and manual overrides) go to `geoIds`, and the geoId
is purely optional precision — never invented, never a REPLACE_ME.

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
    locations: list[str] = Field(default_factory=list)        # human names ("Madrid"); sent as actor `locations`
    work_types: list[str] = Field(default_factory=list)       # actor enum: remote | hybrid | office
    employment_types: list[str] = Field(default_factory=list)
    max_items: int | None = None
    posted_within: str | None = None                          # e.g. "24h"
    geo_ids: list[str] = Field(default_factory=list)          # advanced: optional manual geoId override
    needs_geoid: bool = False                                 # True only when there's no location at all
    paused: bool = False                                      # kept but not scraped (in-console pause)


def split_locations(s: StructuredSearch) -> tuple[list[str], list[str]]:
    """Split a search's locations into (free-text names, geoIds).

    The actor accepts free-text `locations` (its primary location filter), so a
    city/country name needs NO geoId. Names we happen to have a verified geoId for
    (e.g. a region like the EEA) plus any manual override go to `geoIds` for
    precision; everything else stays as text. We never emit a REPLACE_ME — a plain
    location name is a valid, runnable search on its own.
    """
    as_text, resolved = [], []
    for loc in s.locations:
        gid = geo.resolve(loc)
        (resolved.append(gid) if gid else as_text.append(loc))
    overrides = [g for g in s.geo_ids if g and g != _GEOID_UNSET]
    geoids = list(dict.fromkeys([*resolved, *overrides]))
    return as_text, geoids


def to_actor_input(s: StructuredSearch) -> dict:
    """Serialize to the actor input dict pull.py sends.

    geoIds take precedence: when a search has any geoId we send ONLY geoIds, never
    also `locations`. The actor doesn't document how it combines the two (it could
    intersect them → zero results), and a numeric geoId is exact while a free-text
    name can be misread (LinkedIn reads "UK" as "Ukraine"). Plain location names are
    sent only when there is no geoId at all.
    """
    as_text, geoids = split_locations(s)
    actor: dict = {"jobTitles": list(s.titles)}
    if geoids:
        actor["geoIds"] = geoids
    elif as_text:
        actor["locations"] = as_text
    actor["workplaceType"] = list(s.work_types)
    actor["employmentType"] = list(s.employment_types) or list(_DEFAULT_EMPLOYMENT)
    actor["maxItems"] = s.max_items or _DEFAULT_MAX_ITEMS
    actor["postedLimit"] = s.posted_within or _DEFAULT_POSTED
    actor["sortBy"] = "relevance"
    return actor


def from_actor_input(name: str, actor: dict) -> StructuredSearch:
    """Read an existing actor input dict into StructuredSearch (for the friendly form).

    Free-text `locations` round-trip back into the form's Locations field; any
    `geoIds` land in `geo_ids` (the advanced override). `needs_geoid` now means "no
    location at all" (neither a name nor a geoId) — that's the only unrunnable case.
    Legacy files with a REPLACE_ME geoId read as having no geoId.
    """
    geoids = [g for g in (actor.get("geoIds") or []) if g and g != _GEOID_UNSET]
    locations = list(actor.get("locations") or [])
    return StructuredSearch(
        name=name,
        titles=list(actor.get("jobTitles") or []),
        locations=locations,
        work_types=list(actor.get("workplaceType") or []),
        employment_types=list(actor.get("employmentType") or []),
        max_items=actor.get("maxItems"),
        posted_within=actor.get("postedLimit"),
        geo_ids=geoids,
        needs_geoid=not (locations or geoids),
        paused=bool(actor.get("_paused")),
    )
