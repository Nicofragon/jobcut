---
name: jobcut-score
description: >-
  Score jobcut job listings against the user's profile and write the results
  straight into the local jobcut database — fully automatic, no manual JSON.
  Use when the user says "score my jobs", "re-score with Claude", or
  "update the jobcut scores". Reads jobs needing a
  score via `jobcut unscored`/`surface`, judges each against profile.md, and
  writes them back via `jobcut ingest-scores` (tagged backend=claude_skills).
---

# jobcut-score

Lets Claude be the scoring engine for jobcut, end-to-end and hands-off. Claude
reads the jobs from the database, scores them against the profile, and writes the
scores **directly back** — all through the `jobcut` CLI. The user does nothing
beyond asking.

**CLI-only.** Never write SQL or edit `jobcut.db` directly. The CLI is the single
schema authority: reads for scoring go through `jobcut unscored --json` (it returns
the **full** `description`), the write goes through `jobcut ingest-scores`. This
keeps the DB valid and is just as direct.

**Score against the full `description`, always.** Every score must be based on the
complete job description, never the title, metadata, or a truncated snippet — titles
mislead (a "Data Analyst" posting can be an Analytics-Engineering role; a "Data
Analytics Analyst" can be SAS-required data QA; a whole batch can be a training
*program*, not jobs). If a description is long, read it in batches, but read all of
it. **Never source the text to score from `jobcut surface --json`** — `surface`
deliberately drops `description` (it's the shortlist/report view). Use `unscored`
for scoring; `surface` is only for the final report in step 6.

## Preconditions

- `jobcut` is installed and on PATH (`jobcut --help` works).
- Run from the **jobcut project folder** (so the CLI resolves the project's
  `jobcut.db`), or have `JOBCUT_DATA_DIR` exported to the data dir. Confirm with
  `jobcut surface --json` (look at `meta.db_count`).
- `profile.md` exists in the data dir (it drives the rubric).
- Use a scratch path for the temp scores file, e.g. `tmp/scores.json` under the data
  dir. Never write outside it.

## Steps

1. **Get the jobs to score.** All three paths use `unscored`, so you always get the
   **full `description`** (ingest upserts by `job_id`, so re-ingesting overwrites a
   score):
   - Default (incremental — new/unscored jobs only):
     ```
     jobcut unscored --json > tmp/to_score.json
     ```
     Returns hireable jobs without a score yet, each with its `description`.
   - Re-score everything ("re-score all my jobs"): the whole funnel, including
     already-scored rows:
     ```
     jobcut unscored --include-scored --json > tmp/to_score.json
     ```
   - Re-score specific roles ("re-score these"): exactly those ids, regardless of
     funnel or scored state:
     ```
     jobcut unscored --ids <id1,id2> --json > tmp/to_score.json
     ```
   - Do **not** use `jobcut surface --json` here — it drops `description`; it's only
     for the final report (step 6).
   - If the list is empty, tell the user there's nothing to score and stop.

2. **Read the profile**: read `profile.md` from the data dir. Note target roles,
   seniority, must-haves, dealbreakers.

3. **Score each job** against the profile. For every job produce:
   - `match_score`: integer 0–100.
   - `match_reasons`: one plain-language line on the fit.
   - `status`: `"scored"`, or `"discarded"` for a clear non-fit.

   Be honest and discriminating (this is the whole point of Claude scoring vs the
   rule-based floor): penalize seniority mismatches (junior posting for a senior
   profile, or vice-versa), off-target disciplines, missing core skills, and
   dealbreakers. Reward real alignment on role, stack, seniority, and location.

4. **Write the scores file** as JSON:
   ```json
   { "scores": [
       { "job_id": "123", "match_score": 87, "match_reasons": "Senior data role, SQL+Python core, remote-EU", "status": "scored" }
   ] }
   ```

5. **Write to the database** (the only write — direct, via the CLI):
   ```
   jobcut ingest-scores tmp/scores.json
   ```
   `ingest-scores` upserts by `job_id` and tags each row `backend=claude_skills` by
   default (so they show "Scored by Claude" in the dashboard). It prints how many
   were written / skipped.

6. **Confirm + report**: run `jobcut surface --json` and show the top matches as
   `**Title — Company** (score) — why it matches`. The running dashboard reads the DB
   per request, so the user just refreshes the browser to see the new scores — no
   restart needed.

## Notes

- Read-only commands: `jobcut unscored --json` (with `--include-scored` for a full
  re-score, or `--ids <id1,id2>` for a targeted re-score — both return full
  descriptions) and `jobcut surface --json` (report view, no descriptions). The only
  writer is `jobcut ingest-scores`. No raw SQL, ever.
- **`match_reasons` is the *scoring rationale* — yours alone.** It explains *why a job
  scored what it did* ("BI Analyst +25; Madrid hybrid +15; …") and is written **only**
  by this skill via `ingest-scores`. It is **not** a place to record notes, reminders,
  or anything the user *tells you happened* — that's a **note** and goes through
  `jobcut-track` (`kind:"note"`), where it shows in "Notes & activity". Putting a note
  in `match_reasons` makes it invisible as a note and corrupts the score's "why" line.
- This skill does **not** pull from Apify (no cost). To also fetch new jobs first, use
  the `jobcut-daily` skill, then this one to score. To then pick what to apply to (top
  10) or open the console, hand off to **jobcut-review**.
- Everything is keyed off the data dir resolved from the working directory (or
  `JOBCUT_DATA_DIR`). The skill hard-codes no profile, path, or location.
