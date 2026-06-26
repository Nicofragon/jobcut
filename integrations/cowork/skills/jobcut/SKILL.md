---
name: jobcut
description: >-
  Front door for driving jobcut from chat. Run this FIRST when a user starts
  working with jobcut in a session — it confirms the jobcut skills are loaded and
  the CLI + data dir resolve, then routes the request to the right skill. Use when
  the user says things like "let's work on my job search", "open jobcut", "is
  jobcut set up / ready?", "what can you do with my jobs?", "jobcut isn't working /
  you can't find the skill", or whenever you're about to take a jobcut action and
  haven't checked readiness yet. Read-only and orchestration only — it verifies and
  dispatches; the specialised jobcut-* skills do the actual work.
---

# jobcut (front door)

The first thing to do when a user wants to work on their job search with jobcut.
It does three things, in order: **(1) check you're ready, (2) if not, tell the user
exactly what's missing and how to fix it — never improvise around a missing skill,
(3) route the request to the right jobcut-* skill.** It never writes the database
itself; it dispatches.

## 1. Readiness check (run once at the start of a jobcut session)

Confirm all three. This is path-agnostic — don't grep for a skills folder, just
check what you can actually see and run:

1. **The jobcut skills are loaded.** Look at the skills available to you in this
   session and confirm these are present:
   `jobcut-daily`, `jobcut-score`, `jobcut-review`, `jobcut-track`, `jobcut-add`,
   `jobcut-open`, `jobcut-market`, `jobcut-update` (plus this one, `jobcut`).
2. **The CLI is installed and on PATH:**
   ```
   jobcut --help
   ```
3. **The data dir resolves to a real database:**
   ```
   jobcut surface --json
   ```
   Check `meta.db_count` — a number > 0 means the CLI found your jobs. (0 on a fresh
   install is fine; it just means nothing has been pulled yet.)

If all three pass, say so in one line ("jobcut is ready — N skills loaded, DB has M
jobs") and go to step 3.

## 2. If something is missing — say so, don't work around it

The failure mode this skill exists to prevent: a skill isn't loaded, so Claude
quietly does the task by hand (e.g. editing the DB directly) and the result is wrong
or invisible. **Don't.** Name what's missing and the fix, then stop until it's
resolved:

- **A `jobcut-*` skill isn't in your available skills** → the skills aren't installed
  where this Claude reads them. Tell the user to run the installer from their jobcut
  clone:
  ```
  bash integrations/cowork/install.sh           # copies all skills to ~/.claude/skills
  bash integrations/cowork/install.sh <dir>      # or pass your Cowork skills dir
  ```
  **Important:** Claude **Code** reads `~/.claude/skills/`, but **Cowork** reads its
  own skills directory (often your notes/vault `.claude/skills/`, not the home one).
  Install into the directory the tool you're using actually indexes, then **reload**
  so the new skills are picked up. See `integrations/cowork/SETUP.md`.
- **`jobcut --help` fails** → the CLI isn't installed / not on PATH. From the repo:
  `pip install -e .` (or `./setup.sh`).
- **`jobcut surface --json` errors or `meta.db_count` is missing** → the data dir
  isn't resolving. Run from the jobcut project folder, or
  `export JOBCUT_DATA_DIR=/path/to/your/jobcut-data`.

Report which specific thing failed and which is fine — "8/9 skills loaded,
`jobcut-score` missing; CLI + DB OK" — so the fix is targeted.

## 3. Route the request to the right skill

| The user wants to… | Hand off to |
|---|---|
| Pull new jobs and score them (the daily run) | `jobcut-daily` |
| Score / re-score jobs already in the DB with Claude | `jobcut-score` |
| Know what to apply to, see the pipeline/weekly stats (read-only) | `jobcut-review` |
| Record something on an application — note, interview round, status, a field | `jobcut-track` |
| Add a job from a URL (company site / Lever / Greenhouse / expired post) | `jobcut-add` |
| Open / launch the web console | `jobcut-open` |
| See market demand vs their skill gaps | `jobcut-market` |
| Update the app to the latest code / "still see the old design" | `jobcut-update` |

If the request is ambiguous, ask one clarifying question rather than guessing a skill.

## The golden rule: never edit `jobcut.db`; one field, one writer

Every write goes through the `jobcut` CLI — never raw SQL, never open the DB file.
The CLI is the single schema authority. And **the field you write into depends on
what the user is recording** — this is the distinction that's been gotten wrong:

| The user wants to record… | Goes into | Through | Shows up as |
|---|---|---|---|
| Something that happened / a reminder ("previous rejection", "recruiter called") | a **note** timeline event | `jobcut-track` → `ingest-events` (`kind:"note"`) | "Notes & activity" |
| An interview round | an **interview** event | `jobcut-track` (`kind:"interview"`, `meta.stage`/`index`, `date`) | timeline + process timing |
| Pipeline status (applied / interview / offer / rejected …) | `applications.status` | `jobcut-track` (`status`) | the funnel + status badge |
| A field (priority, next action, contact, cv_version) | `applications.*` | `jobcut-track` (`fields`) | tracker fields |
| **Why a job scored what it did** | **`scores.match_reasons`** | **`jobcut-score` → `ingest-scores` only** | the score's "why" line |

**A note is not a match reason.** `scores.match_reasons` is the *scoring rationale*
("BI Analyst +25; Madrid híbrido +15; …") and is owned **only** by the scorer. Never
stash a note, a reminder, or a status there — it won't appear in "Notes & activity"
and it corrupts the score's explanation. Anything the user *tells you happened* is a
note (or status/field/round) and goes through `jobcut-track`.

## Notes

- This skill is **read-only + orchestration**. It runs `jobcut --help` /
  `jobcut surface --json` to check readiness and then dispatches; the specialised
  skills do the writes through their own CLI commands.
- Hard-codes no path, profile, or company. The readiness check verifies by what's
  actually loaded and what the CLI reports — so it works for any user, any data dir.
- Once readiness passes, you don't need to re-run it every turn — just at the start of
  a session, or whenever a jobcut action behaves unexpectedly (e.g. a skill seems
  missing or a write didn't show up).
