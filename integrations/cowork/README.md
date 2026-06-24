# jobcut ↔ Claude Cowork bridge (project-specific)

This folder ships **the project's own** Cowork/Claude Code skills that drive the
`jobcut` CLI so an agent can keep the database fresh and surface results —
**without touching SQLite directly** (every write goes through the CLI, which is
the single schema authority).

- **Project-specific, not personal.** These skills write to *this project's*
  database at `$JOBCUT_DATA_DIR/jobcut.db`. They are generic: no hard-coded
  profile, no Obsidian-vault paths, no personal scheduler. (Any personal v1 setup
  a user already runs is separate and untouched.)
- **CLI-only.** The skills never import jobcut as a library or run raw SQL; they
  invoke `jobcut <command>` and read its `--json` output.

## Skills

| Skill | What it does | CLI it drives |
|-------|--------------|---------------|
| [`jobcut-daily`](skills/jobcut-daily/SKILL.md) | Pull saved searches (local Apify client) → score → shortlist | `pull`, `unscored`/`ingest-scores` or `score`, `surface --json` |
| [`jobcut-score`](skills/jobcut-score/SKILL.md) | Score (or re-score) jobs with Claude and write them straight to the DB — no Apify, no manual JSON | `unscored`/`surface --json`, `ingest-scores` |
| [`jobcut-market`](skills/jobcut-market/SKILL.md) | Summarize skill demand vs the profile | `market --json` |

## The CLI is the database contract

Claude never opens `jobcut.db` or writes SQL. It reads and writes only through the
`jobcut` CLI, so the schema stays owned by one place:

- **Readers (read-only, structured JSON):**
  `jobcut unscored --json` (jobs missing a score) ·
  `jobcut surface --json` (the ranked shortlist) ·
  `jobcut market --json` (skill demand vs your profile).
- **Writers (the only commands that mutate the DB):**
  `jobcut pull` (ingest jobs from Apify) ·
  `jobcut import-jobs <file>` (upsert job rows from JSON) ·
  `jobcut ingest-scores <file>` (upsert Claude scores, tagged `backend=claude_skills`) ·
  `jobcut score` (run a built-in/rule-based scorer).

Anything a skill needs to know about the data, it gets from a `--json` reader; anything
it changes, it does through one of the writers. No other path touches the database.

## Install / config

Full step-by-step in [`SETUP.md`](SETUP.md). In short: install jobcut, set
`JOBCUT_DATA_DIR`, run `jobcut init`, add the Apify token, copy the skills into
your Claude skills directory, and pick **one run owner** — this Cowork bridge **or**
the repo's cron, not both for the same searches (so Apify isn't paid twice).
