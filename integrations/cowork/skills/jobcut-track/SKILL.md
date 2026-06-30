---
name: jobcut-track
description: >-
  Update your jobcut applications by talking to Claude — add a note, log an
  interview round, change status, or set fields like priority/next action, all
  written straight into the local jobcut database. Use when the user says things
  like "Preply passed to R3, scheduled for the 30th", "Preply pasó a R3 agendada
  el 30/06", "add a note to the Kiwi application", "mark Acme as rejected",
  "bump Globant to high priority", or "log the technical interview for X".
  Resolves the application from the company/title, then writes via
  `jobcut ingest-events` (no manual JSON, no SQL).
---

# jobcut-track

Lets Claude **write** to your jobcut application tracker from a normal conversation
— the funnel-side counterpart to `jobcut-score`. The user describes what happened
("Preply moved to round 3, scheduled for June 30") and Claude records it: a note, an
interview round, a status change, or a structured field — all through the `jobcut`
CLI. This is the only write-path skill; the others (`jobcut-score`, `jobcut-review`)
score or read.

**CLI-only.** Never write SQL or edit `jobcut.db` directly. The CLI is the single
schema authority: context comes from `jobcut surface --json` / `jobcut stats --json`,
and the write goes through `jobcut ingest-events`. This keeps the DB valid and is
just as direct.

**A note is not a match reason.** Everything the user *tells you happened* — a
rejection, a recruiter call, a reminder — is a **note** (or a status / field / round)
and belongs here, via `ingest-events`. It is **never** written into
`scores.match_reasons`: that field is the *scoring rationale* (why the job scored what
it did) and is owned only by `jobcut-score`. A note put there won't show in "Notes &
activity" and corrupts the score's "why" line. When in doubt: did the user tell you
something that happened? → note here. Are you explaining a score? → that's
`jobcut-score`, not this skill.

**A note is not a document, either.** A short thing that happened ("recruiter called",
"rejected after R2") is a **note** and belongs here. A long doc you'd *re-read* —
interview prep, a pitch, STAR stories, a study sheet, a post-round debrief — is an
**application document**: that goes to `jobcut-docs` (`ingest-documents`) and shows under
"Prep documents", not "Notes & activity". Don't cram a whole prep doc into a note body.

## Preconditions

- `jobcut` is installed and on PATH (`jobcut --help` works).
- Run from the **jobcut project folder** (so the CLI resolves the project's
  `jobcut.db`), or have `JOBCUT_DATA_DIR` exported. Confirm with
  `jobcut surface --json` (look at `meta.db_count`).
- Use a scratch path for the temp events file, e.g. `tmp/events.json` under the data
  dir. Never write outside it.

## Steps

1. **Read context to resolve the application.** The user names a company/role, not a
   `job_id`. Pull the current shortlist and pipeline and find the matching application:
   ```
   jobcut surface --json
   jobcut stats --json
   ```
   - Match on company/title (case-insensitive, partial is fine) to get the `job_id`.
   - **If you can't find it, or more than one matches, ASK** which one — never guess a
     `job_id`, and never invent one.

2. **Translate what the user said into one or more event items.** Each item is **one
   operation**, keyed by `job_id`:

   - **Add a note** → `{"job_id": "...", "kind": "note", "body": "Recruiter call went well"}`
     The `body` is **only the new note** — the one thing the user just told you. The
     timeline is append-only and already keeps every prior note, so **never** read the
     existing notes/summary and paste them into the new `body` to "preserve history":
     that duplicates the whole block on the timeline. One note in, one note on the
     timeline. (Notes do not overwrite any summary field; there is nothing to preserve.)
   - **Log an interview round** → `{"job_id": "...", "kind": "interview",
     "body": "Technical with Diego", "meta": {"stage": "Technical", "index": 2},
     "date": "2026-06-15"}` (use `date` for when the round actually happened; `YYYY-MM-DD`).
   - **Change status** → `{"job_id": "...", "status": "interview"}` (or `offer`,
     `rejected`, `withdrawn`, `screen`, `applied`, …). This is the funnel choke-point —
     use the `status` field, not a `status_change` kind.
   - **Set structured fields** → `{"job_id": "...", "fields": {"priority": "high",
     "next_action": "send portfolio", "next_action_date": "2026-07-01",
     "contact": "Diego Yus", "cv_version": "v3"}}`

   To do several things to one application (e.g. log a round **and** bump priority),
   emit **several items** — one op each.

3. **Write the events file** as JSON:
   ```json
   { "events": [
       { "job_id": "4396360445", "status": "interview" },
       { "job_id": "4396360445", "kind": "interview", "body": "HM scheduled",
         "meta": { "stage": "Hiring Manager", "index": 3 }, "date": "2026-06-30" }
   ] }
   ```

4. **Write to the database** (the only write — direct, via the CLI):
   ```
   jobcut ingest-events tmp/events.json
   ```
   It applies each item by precedence (`status` → status change; `fields` → field patch;
   `kind` → timeline event), skips and reports anything invalid, and prints how many
   updates landed. A `job_id` not in the `jobs` table still gets written (that's a valid
   orphan/manual application) — it's just reported.

5. **Confirm + report.** Re-read `jobcut surface --json` (or `stats --json`) and tell the
   user what changed in plain language. The running console reads the DB per request, so
   they just refresh the browser — no restart needed.

## Notes

- Read-only commands: `jobcut surface --json`, `jobcut stats --json`. The only writer is
  `jobcut ingest-events`. No raw SQL, ever.
- **Events are append-only** — re-running adds another note/round. Don't re-ingest the
  same events "just in case". `status` and `fields` are idempotent (they overwrite), so
  those are safe to repeat.
- **A note's `body` is just the new note, never the accumulated history.** The timeline
  shows each note as its own entry; the console "Notes & activity" panel reads that same
  timeline. So writing only the new text is exactly what the user sees — concatenating the
  prior summary into each note just repeats the whole block. To *correct* an earlier note,
  add a new short note saying what changed; the old one stays as the record.
- Use the `date` field for an interview round that happened in the past (e.g. importing
  from memory) so the timeline and process-timing reflect the real dates; omit it to
  stamp "now".
- This skill records what the user tells you. It does **not** advance the process stepper
  (`process_current`) — that's done from the web UI. It also never scrapes (no cost) and
  hard-codes no profile, path, or company.
- To *score* jobs use `jobcut-score`; to decide what to apply to or open the console use
  `jobcut-review`. This skill is for updating the **funnel** as your search moves.
