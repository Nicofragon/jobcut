# Using jobcut with Claude (Cowork / Claude Code)

This folder ships **the project's own** Cowork/Claude Code skills that let Claude
drive jobcut for you — keep the database fresh, score jobs, tell you what to apply
to, answer questions about your data, and keep the app itself up to date.

The contract is simple: **Claude drives the `jobcut` CLI; it never touches SQLite
directly.** Every write goes through the CLI, which is the single schema authority.

- **Project-specific, not personal.** These skills act on *this project's* database
  at `$JOBCUT_DATA_DIR/jobcut.db`. They're generic: no hard-coded profile, no
  Obsidian-vault paths, no personal scheduler.
- **CLI-only.** The skills never import jobcut as a library or run raw SQL; they
  invoke `jobcut <command>` and read its `--json` output.

## What you can ask Claude to do

| Say this | Skill | What happens |
|----------|-------|--------------|
| "let's work on my job search" / "is jobcut set up?" / "what can you do with my jobs?" | [`jobcut`](skills/jobcut/SKILL.md) | **Front door.** Confirms the jobcut skills are loaded + the CLI/data dir resolve, says what's missing if not, then routes you to the right skill |
| "run my daily job search" / "pull and score new jobs" | [`jobcut-daily`](skills/jobcut-daily/SKILL.md) | Pull saved searches (local Apify client) → score → shortlist |
| "score my jobs with Claude" / "re-score these" | [`jobcut-score`](skills/jobcut-score/SKILL.md) | Claude scores jobs against your profile and writes them straight to the DB |
| "what should I apply to?" / "top 10" / "how's my pipeline this week?" / "open the console" | [`jobcut-review`](skills/jobcut-review/SKILL.md) | **Read-only.** Top picks to apply, pipeline/weekly stats, or launch the web console |
| "Preply passed to R3, scheduled the 30th" / "add a note to Kiwi" / "mark Acme rejected" / "bump X to high priority" | [`jobcut-track`](skills/jobcut-track/SKILL.md) | **Write.** Update an application — note, interview round, status, or fields — via `ingest-events` |
| "add this job &lt;url&gt;" / "guardá esta oferta de Lever" / "apliqué a este rol &lt;url&gt;" | [`jobcut-add`](skills/jobcut-add/SKILL.md) | **Write.** Claude fetches the URL, extracts company/title/location, and saves the job (optionally as an application) via `add-job` |
| "open jobcut" / "abrí jobcut" / "launch the console" | [`jobcut-open`](skills/jobcut-open/SKILL.md) | Start the web console in the background and hand back the URL — no terminal |
| "what's the market asking for?" / "my skill gaps" | [`jobcut-market`](skills/jobcut-market/SKILL.md) | Summarize skill demand vs your profile |
| "update jobcut" / "I still see the old design" | [`jobcut-update`](skills/jobcut-update/SKILL.md) | Pull latest code, reinstall if deps changed, rebuild + restart the console |

Starting a session, just say "let's work on jobcut" — the **jobcut** front door
checks that every skill is loaded and the CLI/data dir resolve (and tells you what to
fix if not), so Claude never silently improvises around a missing skill. A normal day
from there: **jobcut-daily** (fetch + score) → **jobcut-review** (decide what to apply
to / open the console). **jobcut-update** keeps the install current; **jobcut-market**
and **jobcut-score** are on-demand.

## The CLI is the database contract

Claude never opens `jobcut.db` or writes SQL. It reads and writes only through the
`jobcut` CLI, so the schema stays owned by one place:

- **Readers (read-only, structured JSON):**
  `jobcut surface --json` (the ranked shortlist) ·
  `jobcut stats --json` (applications pipeline: funnel, weekly counts, stalled) ·
  `jobcut market --json` (skill demand vs your profile) ·
  `jobcut unscored --json` (jobs missing a score).
- **Writers (the only commands that mutate the DB):**
  `jobcut pull` (ingest jobs from Apify) ·
  `jobcut import-jobs <file>` (upsert job rows from JSON) ·
  `jobcut add-job` (add one job manually by URL/fields, `source=manual`; optionally link an application) ·
  `jobcut ingest-scores <file>` (upsert Claude scores, tagged `backend=claude_skills`) ·
  `jobcut ingest-events <file>` (apply application write-ops: notes, interview rounds, status, fields) ·
  `jobcut score` (run a built-in/rule-based scorer).
- **Console / lifecycle (no DB writes):**
  `jobcut serve --open` (run the API + web console, auto-rebuilds if stale) ·
  `jobcut shortcut` (write a double-click desktop launcher for the console — no terminal) ·
  `jobcut daily` (pull + score + surface in one — what the scheduler runs).

Anything a skill needs to know about the data, it gets from a `--json` reader;
anything it changes, it does through one of the writers. No other path touches the DB.

## One run owner (don't pay Apify twice)

`jobcut pull` / `jobcut daily` trigger a **paid** Apify scrape. Exactly **one** runner
should own a given set of searches:

1. **In-app scheduler** (recommended) — **Settings → Automation** in the console
   installs a launchd (macOS) / cron (Linux) timer that runs `jobcut daily`. Configure
   the frequency and time from the UI; nothing to edit by hand.
2. **jobcut-daily skill** — run on demand from Claude when you want Claude to score and
   summarize each run.
3. **Hand-written cron** — `jobcut daily` from your own crontab for a no-Claude run.

Pick one per search. If the in-app scheduler already owns your searches, run
`jobcut-daily` with `jobcut pull --read` (a **free** re-download of the last run) so
you don't double-pay. (`jobcut-review`, `jobcut-score`, and `jobcut-update` are
always free — they never scrape.)

## Install / config

Full step-by-step in [`SETUP.md`](SETUP.md). In short: install jobcut, set
`JOBCUT_DATA_DIR`, run `jobcut init`, add the Apify token (or do it in the onboarding
UI), install the skills, and choose your run owner (in-app scheduler by default). Skill
install differs by tool: **Claude Code** copies the folders
(`bash integrations/cowork/install.sh`); **Cowork** imports each skill through its UI
(`bash integrations/cowork/install.sh --zip`, then upload each zip via Personalizar →
Subir habilidad, starting with `jobcut.zip`). See SETUP.md §3.
