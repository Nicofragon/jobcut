"""docsinbox.py — auto-import prep documents from a drop-folder (B-22).

A portable bridge for agents/users that can't call `jobcut ingest-documents`: drop a
markdown file with a ``jobcut:`` frontmatter block into ``<data_dir>/documents/`` and it's
imported into the right application — idempotent by ``client_key`` (edit the file → the
document updates in place). `jobcut serve` imports on startup and then watches the folder
(create/modify → it appears/updates in the console); `jobcut import-docs` runs it once.

Dependency-free by design: a tiny frontmatter parser (no PyYAML) and an mtime poll (no
watchdog), so it ships with the core install and behaves on synced/network folders.

The frontmatter contract (everything but the offer is optional):

    ---
    jobcut:
      job_id: "4396360445"          # the offer. Or resolve by company (+ role):
      company: "Acme"
      role: "Staff Data Analyst"
      title: "Opening pitch"        # the document's display title (else its H1 / filename)
      round: "R3"                   # anchor to an interview round. Or event_id: 123
      doc_type: "prep"              # prep | study | debrief | other   (default: prep)
      client_key: "acme-pitch"      # default: a stable slug of the file's path
    ---
    # body in markdown…

Resolution is deliberately safe: an ambiguous/unknown offer is **skipped + reported**
(never mis-linked); a ``round`` that doesn't resolve to exactly one interview event is
left **offer-level + reported** (set ``event_id`` to anchor). Files without a ``jobcut:``
block are ignored (a plain note someone is keeping in the folder).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import db, ingest, paths

README = """# jobcut — prep documents inbox

Drop a markdown file here (or in a subfolder) with a `jobcut:` frontmatter block and the
running console imports it automatically into the matching application — it shows under
**Prep documents** on that job's page. Edit the file and save: the document updates in
place (no duplicate). This folder lives inside your jobcut install, so it works the same
for everyone — it is not your Obsidian vault or iCloud.

```markdown
---
jobcut:
  job_id: "4396360445"          # the offer. Or match by company (+ role):
  company: "Acme"
  role: "Staff Data Analyst"
  title: "Opening pitch"        # the document's title (optional; else its H1 / filename)
  round: "R3"                   # optional — anchor to an interview round. Or: event_id: 123
  doc_type: "prep"              # prep | study | debrief | other   (default: prep)
  client_key: "acme-pitch"      # optional — default: a stable slug of this file's path
---
# Your document, in markdown…
```

- **Offer:** `job_id` wins; otherwise `company` (+ optional `role`) must match exactly one
  offer, else the file is skipped and reported.
- **Round:** optional. `event_id` wins; otherwise `round` ("R3"/"3"/a stage name) must
  resolve to exactly one interview event, else the document is imported offer-level.
- **client_key:** lets you edit-and-re-import without duplicating. Defaults to a slug of
  the file path; set it explicitly if you rename files.
- A file with no `jobcut:` block (like this README) is ignored.
"""


# --- frontmatter ------------------------------------------------------------

def _clean_scalar(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        v = v[1:-1]
    return v


def _parse_jobcut_block(block: str) -> dict | None:
    """Pull the indented children of a ``jobcut:`` key out of a frontmatter block.
    Returns None when there's no ``jobcut:`` mapping (the file isn't ours)."""
    out: dict | None = None
    for line in block.splitlines():
        if out is None:
            if re.match(r"^jobcut:[ \t]*$", line):
                out = {}
            continue
        if line.strip() == "":
            continue
        m = re.match(r"^\s+([A-Za-z_][\w-]*):[ \t]*(.*)$", line)
        if not m:  # a dedented line ends the jobcut mapping
            break
        out[m.group(1).strip()] = _clean_scalar(m.group(2))
    return out


def parse_frontmatter(text: str) -> tuple[dict | None, str]:
    """Split a leading YAML frontmatter block off the body and return its ``jobcut:``
    mapping. ``(None, original_text)`` when there's no frontmatter or no jobcut block."""
    if text.startswith("﻿"):
        text = text[1:]
    m = re.match(r"---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", text, re.DOTALL)
    if not m:
        return None, text
    meta = _parse_jobcut_block(m.group(1))
    if meta is None:
        return None, text  # frontmatter, but not ours — leave the body untouched
    return meta, text[m.end():]


# --- resolution -------------------------------------------------------------

def _slug(s: str) -> str:
    s = re.sub(r"[^\w]+", "-", s.lower()).strip("-")
    return re.sub(r"-{2,}", "-", s) or "doc"


def _resolve_offer(meta: dict, conn) -> tuple[str | None, str | None]:
    jid = str(meta.get("job_id") or meta.get("offer") or "").strip()
    if jid:
        return jid, None
    company = str(meta.get("company") or "").strip()
    role = str(meta.get("role") or meta.get("position") or "").strip()
    if not company:
        return None, "no job_id and no company to resolve the offer"
    rows = conn.execute("SELECT job_id, title, company_name FROM jobs").fetchall()
    cands = [r for r in rows if company.lower() in str(r["company_name"] or "").lower()]
    if role:
        cands = [r for r in cands if role.lower() in str(r["title"] or "").lower()]
    uniq = sorted({r["job_id"] for r in cands})
    if len(uniq) == 1:
        return uniq[0], None
    label = f"company={company!r}" + (f" role={role!r}" if role else "")
    if not uniq:
        return None, f"no offer matched {label}"
    return None, f"{len(uniq)} offers matched {label} — set job_id to disambiguate"


def _resolve_event(meta: dict, job_id: str, conn) -> tuple[int | None, str | None]:
    """(event_id, note). note is set only when an explicit anchor couldn't be honored,
    so the caller can report a fall-back to offer-level."""
    ev = meta.get("event_id")
    if ev not in (None, ""):
        try:
            ev = int(ev)
        except (TypeError, ValueError):
            return None, f"event_id {ev!r} is not an integer — left offer-level"
        owns = conn.execute(
            "SELECT 1 FROM application_events WHERE event_id = ? AND job_id = ?",
            (ev, str(job_id)),
        ).fetchone()
        return (ev, None) if owns else (None, f"event_id {ev} isn't an event of this offer — left offer-level")

    rnd = str(meta.get("round") or "").strip()
    if not rnd:
        return None, None  # offer-level by design — not a fall-back

    events = []
    for r in conn.execute(
        "SELECT event_id, meta FROM application_events WHERE job_id = ? AND kind = 'interview' "
        "ORDER BY ts, event_id", (str(job_id),)
    ).fetchall():
        try:
            m = json.loads(r["meta"] or "{}")
        except (ValueError, TypeError):
            m = {}
        events.append((r["event_id"], m))

    num = re.search(r"\d+", rnd)
    matches = [eid for eid, m in events if num and m.get("index") == int(num.group())]
    if not matches:  # fall back to a stage-name match
        matches = [eid for eid, m in events if rnd.lower() in str(m.get("stage", "")).lower()]
    if len(matches) == 1:
        return matches[0], None
    if not matches:
        return None, f"round {rnd!r} matched no interview event — left offer-level"
    return None, f"round {rnd!r} matched {len(matches)} interview events — left offer-level; set event_id to anchor"


def _doc_title(meta: dict, body: str, path: Path) -> str:
    t = str(meta.get("title") or "").strip()
    if t:
        return t
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
        if s:
            break  # first real line isn't an H1 — don't scan the whole doc
    return path.stem.replace("_", " ").replace("-", " ").strip() or path.stem


def _relname(f: Path, root: Path) -> str:
    try:
        return str(f.relative_to(root))
    except ValueError:
        return f.name


def _entry_for(path: Path, root: Path, conn) -> tuple[dict | None, dict]:
    text = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    if meta is None:
        return None, {"status": "ignored", "detail": "no jobcut: frontmatter"}
    job_id, err = _resolve_offer(meta, conn)
    if err:
        return None, {"status": "skipped", "detail": err}
    event_id, note = _resolve_event(meta, job_id, conn)
    client_key = str(meta.get("client_key") or "").strip() or _slug(str(Path(_relname(path, root)).with_suffix("")))
    entry = {
        "job_id": job_id,
        "title": _doc_title(meta, body, path),
        "body": body,
        "doc_type": str(meta.get("doc_type") or "prep").strip() or "prep",
        "client_key": client_key,
    }
    if event_id is not None:
        entry["event_id"] = event_id
    status = "offer-level" if note else "ok"
    return entry, {"status": status, "detail": note or "", "job_id": job_id,
                   "event_id": event_id, "client_key": client_key}


# --- scan / import ----------------------------------------------------------

def ensure_dir(root: str | Path | None = None) -> Path:
    root = Path(root) if root else paths.documents_dir()
    root.mkdir(parents=True, exist_ok=True)
    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(README, encoding="utf-8")
    return root


def _md_files(root: Path):
    for f in sorted(root.rglob("*.md")):
        if f.name.lower() != "readme.md":
            yield f


def scan(root: str | Path | None, conn, only=None) -> tuple[list[dict], list[dict]]:
    root = Path(root) if root else paths.documents_dir()
    documents, reports = [], []
    if not root.exists():
        return documents, reports
    onlyset = {Path(p).resolve() for p in only} if only is not None else None
    for f in _md_files(root):
        if onlyset is not None and f.resolve() not in onlyset:
            continue
        try:
            entry, report = _entry_for(f, root, conn)
        except Exception as exc:  # a single bad file never sinks the batch
            reports.append({"file": _relname(f, root), "status": "error", "detail": str(exc)})
            continue
        report["file"] = _relname(f, root)
        reports.append(report)
        if entry is not None:
            documents.append(entry)
    return documents, reports


def import_dir(root: str | Path | None = None, conn=None, only=None) -> dict:
    own = conn is None
    conn = conn or db.connect()
    try:
        documents, reports = scan(root, conn, only=only)
        summary = (ingest.ingest_documents_data({"documents": documents}, conn)
                   if documents else {"written": 0, "errors": [], "unknown_job_ids": []})
        skipped = [r for r in reports if r["status"] in ("skipped", "error")]
        return {
            "files": sum(1 for r in reports if r["status"] != "ignored"),
            "written": summary["written"],
            "offer_level": sum(1 for r in reports if r["status"] == "offer-level"),
            "skipped": len(skipped),
            "unknown_job_ids": summary.get("unknown_job_ids", []),
            "errors": list(summary.get("errors", [])) + [f"{r['file']}: {r['detail']}" for r in skipped],
            "reports": reports,
        }
    finally:
        if own:
            conn.close()


# --- watcher (used by `jobcut serve`) ---------------------------------------

def _snapshot(root: Path) -> dict:
    snap = {}
    for f in _md_files(root):
        try:
            snap[f.resolve()] = f.stat().st_mtime
        except OSError:
            pass
    return snap


def watch(root: str | Path | None = None, interval: float = 3.0, on_import=None, stop=None) -> None:
    """Poll the folder forever (daemon thread), importing only files whose mtime changed.
    Seeds its cache from the current contents so startup files aren't re-imported here —
    `serve` does the one startup pass. Never raises: a transient error just retries next
    tick. Pass a `threading.Event` as `stop` to end the loop (used by tests)."""
    root = ensure_dir(root)
    cache = _snapshot(root)
    while stop is None or not stop.is_set():
        time.sleep(interval)
        try:
            snap = _snapshot(root)
            changed = [p for p, m in snap.items() if cache.get(p) != m]
            cache.clear()
            cache.update(snap)
            if changed:
                summary = import_dir(root, only=changed)
                if on_import:
                    on_import(summary)
        except Exception:
            pass  # the watcher must never take down the console
