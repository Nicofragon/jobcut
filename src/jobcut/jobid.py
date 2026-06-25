"""jobid.py — derive a stable, deterministic job_id from a posting URL or fields.

Used by manual job entry (CLI `add-job`, API `POST /applications/manual`, and the
Cowork skill) so a manually-added offer gets the SAME id a scraper would derive —
which lets a later LinkedIn scrape dedupe onto it, and lets an orphan application
(its app row already carries the numeric id) cross-join automatically.

Stdlib only (no dependencies). Three rules:
  - LinkedIn URL → the numeric posting id (`/jobs/view/<id>`, `currentJobId=<id>`,
    or the first run of 6+ digits).
  - Other ATS URL → ``"<host-company>-<url-slug>"`` (e.g. jobs.kiwi.com/jobs/
    senior-ba-inventory/ → ``"kiwi-senior-ba-inventory"``). Noise host labels
    (jobs/www/careers/…) are skipped when picking the company label.
  - No usable URL → ``"manual-<company>-<title>"`` slug fallback.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

_HOST_NOISE = {"jobs", "www", "careers", "career", "boards", "board", "apply",
               "job", "hire", "talent", "work", "join", "recruiting"}


def _slug_id_from_ats_url(s: str) -> str | None:
    p = urlparse(s if "://" in s else "https://" + s)
    if not p.netloc or not p.path:
        return None
    labels = [x for x in p.netloc.lower().split(".") if x not in ("com", "io", "co", "net", "org")]
    company = next((x for x in labels if x not in _HOST_NOISE), labels[0] if labels else "")
    segs = [x for x in p.path.strip("/").split("/") if x]
    slug = next((x for x in reversed(segs) if x and x != company), segs[-1] if segs else "")
    out = re.sub(r"[^a-z0-9-]+", "-", f"{company}-{slug}".lower()).strip("-")
    return out or None


def job_id_from_url(url: str) -> str | None:
    """LinkedIn → numeric id; other ATS → 'host-company-slug'; None if no host+path."""
    s = str(url or "")
    m = re.search(r"/jobs/view/(\d+)", s) or re.search(r"currentJobId=(\d+)", s)
    if m:
        return m.group(1)
    m = re.search(r"(\d{6,})", s)
    if m:
        return m.group(1)
    return _slug_id_from_ats_url(s)


def job_id_from_fields(company: str, title: str) -> str:
    """Fallback when there's no URL: 'manual-<company>-<title>' slug."""
    slug = re.sub(r"[^a-z0-9-]+", "-", f"manual-{company}-{title}".lower()).strip("-")
    return slug or "manual"
