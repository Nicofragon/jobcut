---
name: jobcut
description: >-
  Front door for USING the jobcut app to run a user's job search from chat — NOT
  for developing or testing the jobcut codebase. Use this whenever the user wants
  to work with jobcut or asks about their jobs/applications/pipeline, and ALWAYS
  when they say "is jobcut ready?", "is jobcut set up?", "let's work on my job
  search", "open jobcut", "what can you do with my jobs?", or "jobcut isn't working
  / you can't find the skill". It confirms the jobcut skills are loaded and the
  jobcut CLI + data dir resolve, then routes the request to the right jobcut-* skill.
  "Ready" here means the skills + CLI + data are set up — it does NOT mean "are the
  tests/build/CI green", so do not run pytest, ruff, npm build, or a sandbox to
  answer it. Read-only and orchestration only — it verifies and dispatches; the
  specialised jobcut-* skills do the actual work.
---

# jobcut (front door)

The first thing to do when a user wants to work on their job search with jobcut.
It does three things, in order: **(1) check you're ready, (2) if not, tell the user
exactly what's missing and how to fix it — never improvise around a missing skill,
(3) route the request to the right jobcut-* skill.** It never writes the database
itself; it dispatches.

## This is not a code-health check — read first

jobcut is a tool the user **runs** to manage their job search; here you are helping
them **use** it, not develop it. So when the user asks "is jobcut ready?" (or "set
up", "working"), they mean *"are the jobcut skills + CLI + my data set up so you can
run my job search"* — **not** "is the code healthy". Do **not** run the test suite,
`ruff`, `npm run build`, the web build, or boot a sandbox to answer it — that's
contributing to the code, a different job (see `AGENTS.md` / `CLAUDE.md`). Answer with
the three quick checks in step 1 below. Only touch tests/builds if the user explicitly
asks you to change or debug the jobcut source itself.

## 1. Readiness check (run once at the start of a jobcut session)

Confirm all three. This is path-agnostic — don't grep for a skills folder, just
check what you can actually see and run:

1. **The jobcut skills are loaded.** Look at the skills available to you in this
   session and confirm these are present:
   `jobcut-profile`, `jobcut-daily`, `jobcut-score`, `jobcut-review`, `jobcut-track`,
   `jobcut-add`, `jobcut-open`, `jobcut-market`, `jobcut-update`, `jobcut-salary`,
   `jobcut-docs` (plus this one, `jobcut`).
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

Report which specific thing failed and which is fine — "10/11 skills loaded,
`jobcut-score` missing; CLI + DB OK" — so the fix is targeted.

## 3. Route the request to the right skill

| The user wants to… | Hand off to |
|---|---|
| Set up / update their profile or skills (interview or from a CV) | `jobcut-profile` |
| Pull new jobs and score them (the daily run) | `jobcut-daily` |
| Score / re-score jobs already in the DB with Claude | `jobcut-score` |
| Know what to apply to, see the pipeline/weekly stats (read-only) | `jobcut-review` |
| Record something on an application — note, interview round, status, a field | `jobcut-track` |
| Save a prep/study/debrief **document** into an application (shows under "Prep documents") | `jobcut-docs` |
| Add a job from a URL (company site / Lever / Greenhouse / expired post) | `jobcut-add` |
| Open / launch the web console | `jobcut-open` |
| See market demand vs their skill gaps | `jobcut-market` |
| Estimate a salary band for offers that don't disclose one | `jobcut-salary` |
| Update the app to the latest code / "still see the old design" | `jobcut-update` |

If the request is ambiguous, ask one clarifying question rather than guessing a skill.

## The golden rule: never edit `jobcut.db`; one field, one writer

Every write goes through the `jobcut` CLI — never raw SQL, never open the DB file.
The CLI is the single schema authority. And **the field you write into depends on
what the user is recording** — this is the distinction that's been gotten wrong:

| The user wants to record… | Goes into | Through | Shows up as |
|---|---|---|---|
| Something that happened / a reminder ("previous rejection", "recruiter called") | a **note** timeline event | `jobcut-track` → `ingest-events` (`kind:"note"`) | "Notes & activity" |
| A long doc to re-read (interview prep, pitch, STAR stories, study sheet, debrief) | an **application document** | `jobcut-docs` → `ingest-documents` | "Prep documents" |
| An interview round | an **interview** event | `jobcut-track` (`kind:"interview"`, `meta.stage`/`index`, `date`) | timeline + interview funnel + timing |
| Pipeline status (applied / interview / offer / rejected …) | `applications.status` | `jobcut-track` (`status`) | the funnel + status badge |
| A field (priority, next action, contact, cv_version) | `applications.*` | `jobcut-track` (`fields`) | tracker fields |
| **Why a job scored what it did** | **`scores.match_reasons`** | **`jobcut-score` → `ingest-scores` only** | the score's "why" line |

**A note is not a match reason.** `scores.match_reasons` is the *scoring rationale*
("BI Analyst +25; Madrid hybrid +15; …") and is owned **only** by the scorer. Never
stash a note, a reminder, or a status there — it won't appear in "Notes & activity"
and it corrupts the score's explanation. Anything the user *tells you happened* is a
note (or status/field/round) and goes through `jobcut-track`.

## Notes

- This skill is **read-only + orchestration**. It runs `jobcut --help` /
  `jobcut surface --json` to check readiness and then dispatches; the specialised
  skills do the writes through their own CLI commands.
- Hard-codes no path, profile, or company. The readiness check verifies by what's
  actually loaded and what the CLI reports — so it works for any user, any data dir.
- **Bilingual (works in Spanish *and* English), any field.** Talk to the user in their
  language. The profile and the job postings may be in different languages — the skills
  judge and match across languages, translating as needed (`jobcut-profile` gives skills
  cross-language aliases; `jobcut-score` matches offers semantically regardless of language).
  Nothing assumes a role or a language.
- Once readiness passes, you don't need to re-run it every turn — just at the start of
  a session, or whenever a jobcut action behaves unexpectedly (e.g. a skill seems
  missing or a write didn't show up).
