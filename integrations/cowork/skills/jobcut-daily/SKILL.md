---
name: jobcut-daily
description: >-
  Run the project's daily job search via the jobcut CLI: pull each saved search
  from Apify (using your local APIFY_TOKEN), score the results against the profile,
  and present the top matches. Use when the user says "run my daily job search",
  "pull and score new jobs", or "refresh my jobcut shortlist".
---

# jobcut-daily

Drives the `jobcut` CLI to refresh the project's job database and surface today's
best matches. **CLI-only** — never write SQL or edit `jobcut.db` directly; every
write goes through a `jobcut` command. The Apify scrape runs through **`jobcut
pull`** (the local Apify client + your `APIFY_TOKEN`) — **no Apify MCP needed**, the
same path the dashboard's "Find new jobs" uses.

## Preconditions

- `jobcut` is installed and on PATH (`jobcut --help` works).
- `JOBCUT_DATA_DIR` points at the project's data dir, already initialized with
  `jobcut init` (so `profile.md`, `config/`, and `searches/*.json` exist).
- The Apify token is set in `$JOBCUT_DATA_DIR/.env` as `APIFY_TOKEN` — `jobcut
  pull` reads it directly (no MCP server required).
- Use a scratch directory for any temp JSON (e.g. `$JOBCUT_DATA_DIR/tmp/`). Never
  write anything outside `$JOBCUT_DATA_DIR`.

## Steps

1. **Pull (paid Apify scrape).** Fetch every saved search in `searches/*.json` and
   upsert the results into the jobs table — one command does both the fetch and the
   store (dedupe by `job_id`):
   ```
   jobcut pull
   ```
   This fires the `harvestapi/linkedin-job-search` actor for each search (trigger
   mode, **costs money** — ~$0.15/day typical). To re-download the last triggered run
   for **free** (no new scrape), use `jobcut pull --read` instead.

   Confirm with the user before a paid run, and respect the **one-owner rule**: don't
   pull if a cron job (or another runner) already scrapes the same searches — Apify
   would be paid twice.

2. **Score — pick ONE mode:**

   **A) Claude scoring (subscription; highest quality).** Let Claude read each job and
   score it against the profile (or just invoke the `jobcut-score` skill, which does
   exactly this):
   ```
   jobcut unscored --json > tmp/unscored.json
   ```
   `unscored` returns the hireable jobs that still need a score, each with its
   `description`. Read the profile from `$JOBCUT_DATA_DIR/profile.md`, then for every
   job produce a 0–100 `match_score` and a one-line `match_reasons`. Write:
   ```json
   { "scores": [
       { "job_id": "123", "match_score": 87, "match_reasons": "Strong SQL+Python fit, remote-EU", "status": "scored" }
   ] }
   ```
   to `tmp/scores.json`, then load it:
   ```
   jobcut ingest-scores tmp/scores.json
   ```
   (`status` is optional and defaults to `scored`; use `discarded` for clear non-fits.
   `ingest-scores` tags the rows `backend=claude_skills` → they show "Scored by Claude".)

   **B) No Claude (deterministic).** Use the configured backend (rule_based / local /
   llm_api per `config.scoring.backend`):
   ```
   jobcut score
   ```

3. **Surface.** Get the ranked shortlist as data and present it:
   ```
   jobcut surface --json
   ```
   Take the `today` list (already filtered to hireable, scored, deduped) and show the
   top few as: `**Title — Company** (score) — why it matches — <link>`. Mention the
   `meta` counts (db_count, funnel_count) briefly.

## Notes

- Read-only commands (`unscored --json`, `surface --json`) never write. The only
  writers are `pull`, `ingest-scores`, and `score` — all via the CLI.
- `jobcut pull` uses the local Apify client + your `APIFY_TOKEN` (no MCP). It does
  both the fetch and the DB upsert, so there is no separate import step.
- Everything is keyed off `JOBCUT_DATA_DIR`. This skill is generic: it does not
  hard-code any profile, location, or external path.
