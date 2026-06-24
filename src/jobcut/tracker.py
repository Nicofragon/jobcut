"""tracker.py — load and classify the optional application tracker.

The application tracker is a CSV/xlsx the user edits by hand (v1 design): one row
per role you've applied to, with a free-text Status. This module loads it from
$JOBCUT_TRACKER, normalizes columns, and classifies each free-text status into
a funnel category — so the dashboard can show an applied → interview → offer funnel.

Columns are matched case-insensitively by substring: company, role, tier,
linkedin/url, status, date. Missing columns degrade gracefully.

Classification/funnel logic lives in status.py (one source of truth, shared with
db.py); this module is now just the CSV/xlsx import path and re-exports those
names for backward compatibility.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

# Re-exported so existing callers (tests, the Streamlit dashboard) keep working.
from .status import (  # noqa: F401
    CATEGORIES, CATEGORY_COLOR, LIVE, classify, iso_week, parse_date, summarize,
)


def tracker_path() -> Path | None:
    tp = os.environ.get("JOBCUT_TRACKER")
    if not tp:
        return None
    p = Path(tp).expanduser()
    return p if p.exists() else None


def _col(df: pd.DataFrame, *needles) -> str | None:
    for c in df.columns:
        cl = str(c).lower()
        if any(n in cl for n in needles):
            return c
    return None


def load() -> pd.DataFrame:
    """Load + normalize the tracker into columns: company, role, tier, url, status, date, category.

    Returns an empty DataFrame (with those columns) if no tracker is configured.
    """
    cols = ["company", "role", "tier", "url", "status", "date", "category"]
    p = tracker_path()
    if p is None:
        return pd.DataFrame(columns=cols)

    raw = pd.read_csv(p) if p.suffix.lower() == ".csv" else pd.read_excel(p)
    cmap = {
        "company": _col(raw, "company", "empresa"),
        "role": _col(raw, "role", "rol", "title"),
        "tier": _col(raw, "tier"),
        "url": _col(raw, "linkedin", "url", "link"),
        "status": _col(raw, "status", "estado"),
        "date": _col(raw, "date", "fecha"),
    }
    def stringify(series):
        # NA-safe: NaN/NaT -> "" (this pandas' astype(str) leaves NA as float, not "nan")
        return series.apply(lambda x: "" if pd.isna(x) else str(x))

    out = pd.DataFrame(index=raw.index)
    for k, src in cmap.items():
        out[k] = stringify(raw[src]) if src is not None else ""
    out = out[out.company.str.strip().ne("")].copy()
    out["date"] = out.date.str.slice(0, 10)
    out["tier"] = out.tier.str.extract(r"(\d)", expand=False).fillna("")
    out["category"] = out.status.map(classify)
    return out[cols]
