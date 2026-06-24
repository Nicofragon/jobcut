"""status.py — application-status classification + funnel math (one source of truth).

Both the CSV importer (tracker.py) and the SQLite writers (db.py) classify a
free-text or canonical status into a funnel category through this module, so the
funnel logic lives in exactly one place.

`STATUSES` is the canonical set the dashboard sends (controlled vocabulary);
`classify()` also maps arbitrary free text (imported CSV trackers) onto the same
funnel `CATEGORIES`.

Ported from tracker.py (the standalone funnel_dashboard.html logic) and extended
with an Offer stage.
"""

from __future__ import annotations

import datetime
import re

import pandas as pd

# Funnel categories (most→least engaged) and which count as "live / in progress".
CATEGORIES = ["Interview", "Screen", "Active", "Reviewing", "Applied", "Offer",
              "No response", "Closed", "Withdrawn", "Rejected", "Saved", "Other"]
# "Saved" is a parking lot for interesting roles you haven't applied to — it lives in
# `applications` (so it drops out of the Today feed) but is NOT part of the funnel.
NON_FUNNEL = {"Saved"}
LIVE = {"Active", "Reviewing", "Screen", "Interview"}
# "Open" = still in play (waiting on them or on you): LIVE + Applied + Offer.
OPEN = LIVE | {"Applied", "Offer"}
# "Stallable" = stages where *no movement* means YOU can act (nudge the recruiter, or
# decide on an offer). Applied is deliberately excluded: an applied-but-silent role isn't
# actionable — it ages to "No response" instead of nagging you in "Needs attention".
STALLABLE = LIVE | {"Offer"}

# Canonical statuses the dashboard writes (each must classify() to a real bucket).
STATUSES = ["saved", "applied", "screen", "interview", "offer", "rejected", "withdrawn", "no_response"]

# Badge color per category (GitHub-dark palette, matches the reference).
CATEGORY_COLOR = {
    "Interview": "#3fb950", "Screen": "#39c5cf", "Active": "#58a6ff",
    "Reviewing": "#bc8cff", "Applied": "#8b949e", "Offer": "#d2a8ff",
    "No response": "#6e7681", "Closed": "#545b64", "Withdrawn": "#d29922",
    "Rejected": "#f85149", "Saved": "#a371f7", "Other": "#8b949e",
}


def classify(status: str) -> str:
    """Map a free-text or canonical status to a funnel category."""
    s = (status or "").lower()
    if re.search(r"saved|guardad", s):
        return "Saved"
    if re.search(r"rejected|rechaz", s):
        return "Rejected"
    if re.search(r"descartad|withdraw", s):
        return "Withdrawn"
    if re.search(r"offer|oferta", s):
        return "Offer"
    if re.search(r"\br1\b|\br2\b|t[eé]cnica|interview|business case|entrevista", s):
        return "Interview"
    if re.search(r"screen|scheduled|agendad", s):
        return "Screen"
    if re.search(r"reviewing|revisión|revision|under review", s):
        return "Reviewing"
    if re.search(r"active|activa", s):
        return "Active"
    if re.search(r"closed|cerrad", s):
        return "Closed"
    if re.search(r"no.?response|stale|sin respuesta", s):
        return "No response"
    if re.search(r"applied|sent|aplicad", s):
        return "Applied"
    return "Other"


def parse_date(d) -> datetime.date | None:
    m = re.search(r"(\d{4})-(\d{2})(?:-(\d{2}))?", str(d or ""))
    if not m:
        return None
    return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 15))


def iso_week(d: datetime.date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def summarize(df: pd.DataFrame) -> dict:
    """KPIs + funnel + per-category counts + weekly applications from a normalized df.

    Expects columns `category` and `date` (and optionally `status`).
    """
    # "Saved" roles live in the applications table but aren't part of the funnel —
    # drop them so they never inflate Applied/total or any conversion rate.
    if len(df) and "category" in df:
        df = df[~df.category.isin(NON_FUNNEL)]
    total = len(df)
    counts = df.category.value_counts().to_dict() if total else {}
    screen = counts.get("Screen", 0)
    interview = counts.get("Interview", 0) + screen
    live = int(df.category.isin(LIVE).sum()) if total else 0
    offers = counts.get("Offer", 0)
    rejected = counts.get("Rejected", 0)
    no_resp = counts.get("No response", 0) + counts.get("Closed", 0)

    by_week: dict[str, int] = {}
    for d in df.date if total else []:
        dt = parse_date(d)
        if dt:
            by_week[iso_week(dt)] = by_week.get(iso_week(dt), 0) + 1

    return {
        "total": total,
        "live": live,
        "interview": interview,
        "offers": offers,
        "rejected": rejected,
        "no_response": no_resp,
        "counts": counts,
        "funnel": [
            ("Applied", total, "#58a6ff"),
            ("In process (live)", live, "#39c5cf"),
            ("Interview", interview, "#3fb950"),
            ("Offer", offers, "#bc8cff"),
        ],
        "by_week": dict(sorted(by_week.items())),
    }
