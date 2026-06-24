"""Geo routing: which jobs are hireable for YOU (funnel) vs market-intel only.

Config-driven (see config.py → "routing"). Built-in defaults are a generic
EXAMPLE — set your own home/region regexes in config/config.json.

Two buckets:
  - "funnel"  = jobs you could realistically take. These get scored.
  - "market"  = everything else. Kept for the market dataset, never scored.

The model: a HOME area is fully hireable (on-site, hybrid or remote); a wider
REGION is hireable only when the job is remote.
"""

from __future__ import annotations

import re
from functools import lru_cache

from . import config


@lru_cache(maxsize=2)
def _patterns(home: str, region: str):
    return re.compile(home, re.I), re.compile(region, re.I)


def _compiled():
    r = config.load()["routing"]
    return _patterns(r["home"], r["region"])


def geo(loc):
    """Classify a location string into 'home', 'region' or 'foreign'."""
    home_re, region_re = _compiled()
    t = str(loc).strip().lower()
    if home_re.search(t):
        return "home"
    if region_re.search(t):
        return "region"
    return "foreign"


def is_funnel(location, workplace_type):
    """True if the job is hireable for you (enters the scoring funnel)."""
    g = geo(location)
    wp = str(workplace_type).strip().lower()
    return g == "home" or (g == "region" and wp != "on_site")


def funnel_series(locations, workplace_types) -> list[bool]:
    """Vectorized is_funnel over two equal-length sequences.

    Avoids pandas' per-row ``DataFrame.apply(axis=1)`` (which builds a Series per row
    — ~0.3ms each, the shortlist's real bottleneck) and memoizes by the unique
    (location, workplace_type) pair, of which there are far fewer than rows. The cache
    is per-call, so routing-config changes still take effect on the next request.
    """
    cache: dict[tuple, bool] = {}
    out = []
    for loc, wp in zip(locations, workplace_types):
        key = (loc, wp)
        val = cache.get(key)
        if val is None:
            val = is_funnel(loc, wp)
            cache[key] = val
        out.append(val)
    return out
