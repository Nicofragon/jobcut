---
name: jobcut-docs
description: >-
  Save a long preparation document — interview prep, a pitch, STAR stories,
  study notes, a post-interview debrief — into a jobcut application, where it
  shows under "Prep documents" on the job-detail page. Use when the user says
  things like "save this prep doc into the Acme application", "add my STAR
  stories to the Acme application", "store this pitch / company-context note in jobcut", or
  "save the R2 interview debrief". Resolves the application from the
  company/title, then writes via `jobcut ingest-documents` (no manual JSON
  fiddling beyond the small payload, no SQL). This is for *documents* (reusable
  reading material) — a short thing that just happened is a note → `jobcut-track`.
---

# jobcut-docs

Lets Claude **save a preparation document** into your jobcut tracker from a normal
conversation — the document-side write-path, alongside `jobcut-track` (timeline) and
`jobcut-score` (scoring). The user has (or asks you to write) a long markdown doc —
interview prep, a pitch, STAR stories, a study sheet, a post-round debrief — and wants
it living *with the application* instead of loose in a vault. It lands in the
`application_documents` table and shows under **"Prep documents"** on that job's detail
page, grouped offer-level or by interview round.

There are **two ways in**, and which one you use depends on whether the `jobcut` CLI is
reachable in your environment:

- **CLI reachable (Claude Code on the user's Mac, a terminal session):** write through
  `jobcut ingest-documents` — the steps below. The CLI is the single schema authority;
  never write SQL or edit `jobcut.db` directly.
- **CLI NOT reachable (e.g. Claude Cowork's sandbox — no `jobcut` on PATH, no DB mounted):**
  do **not** dead-end with "run this in your terminal". Instead **drop a markdown file with
  a `jobcut:` frontmatter block into the `documents/` folder of the jobcut install** — the
  running console auto-imports it (see "The documents/ drop-folder" below). If you can't
  reach that folder either, that's expected: hand the file to the user to save into
  `<jobcut-install>/documents/`, and it appears automatically.

Either way, document bodies are markdown — rendered and sanitised by the console, so plain
GitHub-flavoured markdown (headings, tables, code, task lists) is exactly right; don't add
raw HTML.

**A document is not a note.** A prep document is *reusable reading material* you'd open
and read before an interview (STAR stories, a pitch, a study sheet, a debrief writeup) —
it belongs here, via `ingest-documents`, and shows under "Prep documents". A **note** is
a short thing that *happened* ("recruiter called", "rejected after R2") — that goes to
`jobcut-track` (`kind:"note"`) and shows under "Notes & activity". Rule of thumb: if it's
a page you'd re-read, it's a document; if it's a timeline entry, it's a note. (And neither
is `scores.match_reasons` — that's the score's "why", owned only by `jobcut-score`.)

## Preconditions

- `jobcut` is installed and on PATH (`jobcut --help` works).
- Run from the **jobcut project folder** (so the CLI resolves the project's `jobcut.db`),
  or have `JOBCUT_DATA_DIR` exported. Confirm with `jobcut surface --json` (look at
  `meta.db_count`).
- Use a scratch path for the temp file, e.g. `tmp/documents.json` under the data dir.
  Never write outside it.

## Steps

1. **Read context to resolve the application.** The user names a company/role, not a
   `job_id`:
   ```
   jobcut surface --json
   ```
   - Match on company/title (case-insensitive, partial is fine) to get the `job_id`.
   - **If you can't find it, or more than one matches, ASK** which one — never guess or
     invent a `job_id`.

2. **Pick the document's `doc_type`.** One of:
   - `prep` (default) — interview prep, pitch, STAR stories, company-context notes.
   - `study` — study sheets / cheatsheets / topic notes (SQL, experimentation, etc.).
   - `debrief` — a write-up *after* a round (how it went, questions asked, follow-ups).
   - `other` — anything that doesn't fit.

3. **Choose a stable `client_key` for idempotency.** This is what makes re-saving an
   edited doc **update in place** instead of creating a duplicate. Use a stable slug per
   document, e.g. `acme-star-pitch`, `acme-r2-sql-cheatsheet`. Save the same doc again
   with the same `client_key` → it's overwritten, not duplicated. (Omit only for a truly
   one-off you'll never revise.)

4. **(Optional) Anchor to an interview round.** Most docs are **offer-level** (leave
   `event_id` out) — STAR stories, pitch, company context, general study. Only set
   `event_id` to tie a doc to a *specific* round (e.g. an R2 debrief). Event ids aren't in
   `surface --json`; read them from the running console:
   `curl -s localhost:8000/api/applications/<job_id>/events` (use the port `jobcut serve`
   prints), match the round by stage/date, and use its `event_id`. The CLI verifies the
   event belongs to this application and **skips** the doc if it doesn't — it never
   mis-links to another offer's round. If the console isn't running or you're unsure,
   save it **offer-level** and tell the user it isn't round-anchored.

5. **Write the documents file** as JSON (one entry per document):
   ```json
   { "documents": [
       { "job_id": "4396360445", "title": "STAR stories & 2-min pitch",
         "doc_type": "prep", "client_key": "acme-star-pitch",
         "body": "# Pitch\n\n…full markdown…" },
       { "job_id": "4396360445", "title": "R2 — SQL cheatsheet",
         "doc_type": "study", "client_key": "acme-r2-sql", "event_id": 812,
         "body": "## Window functions\n\n| … | … |\n|---|---|\n…" }
   ] }
   ```
   `title` and `body` are required and non-empty; `body` is markdown. `event_id`,
   `doc_type`, `client_key`, `meta` (a small object, JSON-encoded), and `supersedes_id`
   are optional.

6. **Write to the database** (the only write — direct, via the CLI):
   ```
   jobcut ingest-documents tmp/documents.json
   ```
   It validates each entry, coerces `doc_type`, makes re-ingest idempotent by
   `(job_id, client_key)`, verifies any `event_id` belongs to the application, and prints
   how many documents were written / skipped. It is **read-only on data otherwise** — no
   scrape, no score, no delete.

7. **Confirm + report.** The running console reads the DB per request, so the user just
   refreshes the browser and opens the job → **Prep documents** tab. Tell them where it
   landed (offer-level vs which round) in plain language. To open the console, hand off to
   `jobcut-open`.

## The documents/ drop-folder (no-CLI environments)

When you **can't** run `jobcut` (Cowork's sandbox, or any agent without the CLI on PATH),
use the drop-folder instead of dead-ending. jobcut watches `<jobcut-install>/documents/`:
any markdown file with a `jobcut:` frontmatter block is auto-imported into its application
while `jobcut serve` is running (and on the next `serve` / `jobcut import-docs` otherwise).

Write **one `.md` per document**, body below the frontmatter:

````markdown
---
jobcut:
  job_id: "4396360445"          # the offer. Or resolve by company (+ role):
  company: "Acme"
  role: "Staff Data Analyst"
  title: "Opening pitch"        # the document's title (optional; else its H1 / filename)
  round: "R3"                   # optional — anchor to a round. Or: event_id: 123
  doc_type: "prep"              # prep | study | debrief | other   (default: prep)
  client_key: "acme-pitch"      # optional — edit + re-save updates in place (no duplicate)
---
# Opening pitch

…full markdown…
````

- Prefer `job_id` when you know it. Otherwise `company` (+ optional `role`) must match
  **exactly one** offer or the file is skipped (the importer never mis-links).
- `round`/`event_id` is optional → offer-level if omitted or not uniquely resolved.
- Place the file at `<jobcut-install>/documents/` (subfolders are fine, e.g.
  `documents/acme/pitch.md`). **If your environment can't reach that folder, give the
  finished `.md` to the user to drop in** — the auto-import does the rest, no terminal.
- This is the **same write** as `ingest-documents` under the hood (idempotent by
  `client_key`); it's just the path for when the CLI isn't available.

## Notes

- **Idempotent by `client_key`.** Same `(job_id, client_key)` overwrites; that's how you
  *edit* a saved doc — re-save with the same key and the new body. Without a `client_key`,
  every ingest creates a new document, so reserve key-less ingests for genuine one-offs.
- **Bodies are markdown, rendered + sanitised** by the console (GitHub schema). Headings,
  tables, fenced code, and task lists all render; raw HTML is stripped, so don't rely on
  it. A leading YAML `---` frontmatter block is stripped on display.
- **Versioning / removing (advanced) use the console's API**, since they need a `doc_id`
  (not exposed by `surface --json`): `GET /api/applications/<job_id>/documents` lists docs
  with ids. To supersede, set `supersedes_id` on the new doc. To archive (soft-delete) or
  restore, add an `archive` array to the payload:
  `{ "archive": [ { "doc_id": 42, "restore": false } ] }` (`restore: true` un-archives).
  Archived docs are hidden from the console but not deleted.
- **Read-only in the console (v1).** Documents are authored here (or by any agent through
  this CLI) and *read* in the web UI; the console doesn't edit them. The write path is
  always `jobcut ingest-documents`.
- Hard-codes no path, profile, or company. To record an event/status/field use
  `jobcut-track`; to score use `jobcut-score`; to open the console use `jobcut-open`.
