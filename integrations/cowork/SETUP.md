# Setting up the jobcut ↔ Cowork bridge

This guide installs the project's **own** Cowork/Claude skills so an agent can run
your daily job search and market report through the `jobcut` CLI. The skills
write only to **this project's** database (`$JOBCUT_DATA_DIR/jobcut.db`) via the
CLI — never raw SQL, never any Obsidian vault. A new user can follow this
top-to-bottom and have a working bridge.

> **Independent of any personal setup.** If you already run a personal job-search
> workflow in your own vault, this bridge does not touch it. It's a separate,
> project-specific runner pointed at `jobcut.db`.

## 1. What you're installing

Three skills (each a folder under [`skills/`](skills/)):

| Skill | What it does |
|-------|--------------|
| [`jobcut-daily`](skills/jobcut-daily/SKILL.md) | `jobcut pull` each saved search (local Apify client, no MCP) → score → `surface` the top matches |
| [`jobcut-score`](skills/jobcut-score/SKILL.md) | Score (or re-score) jobs already in the DB with Claude, written straight back via `ingest-scores` — no Apify, no manual JSON |
| [`jobcut-market`](skills/jobcut-market/SKILL.md) | Summarize skill demand vs your profile (`market --json`) |

## 2. Prerequisites

- **Claude Cowork or Claude Code** (the skills run as Claude skills).
- **jobcut installed** and on PATH — `jobcut --help` works. (From a clone:
  `pip install -e .`)
- **A data dir** — pick a folder and export `JOBCUT_DATA_DIR` to point at it.
- **An Apify token** (free tier is enough to start) for the
  `harvestapi/linkedin-job-search` actor. **No Apify MCP server is needed** — the
  `jobcut-daily` skill uses your local `APIFY_TOKEN` (from the data dir's `.env`)
  through the `jobcut` CLI, the same path the web console and dashboard use.

## 3. Install the skills

Copy the skill folders into your Claude skills directory (for Claude Code that's
`~/.claude/skills/`; Cowork uses the same per-user skills location):

```bash
# from the repo root
cp -R integrations/cowork/skills/jobcut-daily  ~/.claude/skills/
cp -R integrations/cowork/skills/jobcut-score  ~/.claude/skills/
cp -R integrations/cowork/skills/jobcut-market ~/.claude/skills/
```

Keep each skill's folder intact (the `SKILL.md` must stay inside its folder). Restart
/ reload Claude so it picks up the new skills, then confirm it can see
`jobcut-daily` and `jobcut-market`.

## 4. Configure the data dir

```bash
export JOBCUT_DATA_DIR="$HOME/jobcut-data"   # or wherever you want the DB
jobcut init                                     # scaffolds profile.md, config/, searches/
```

Then, in `$JOBCUT_DATA_DIR`:

- **`.env`** — set `APIFY_TOKEN=apify_api_...`.
- **`profile.md`** — your roles, skills, must-haves, dealbreakers (drives scoring).
- **`config/config.json`** — your geography under `routing` and your scoring backend
  under `scoring.backend` (`rule_based` works with no key; `local`/`llm_api`/Claude
  are optional tiers).
- **`searches/*.json`** — one file per saved search (the input for the Apify actor).
  `jobcut init` drops example files; edit them to your titles/locations.

> Export `JOBCUT_DATA_DIR` in the same environment Claude runs in, so the skills
> and the CLI resolve the **same** data dir and database.

## 5. Choose ONE run owner

The daily pull triggers a paid Apify actor. Pick **one** runner so the same searches
aren't scraped — and paid for — twice:

- **Cowork bridge** — schedule `jobcut-daily` as a Cowork scheduled task (e.g. each
  weekday morning). Best if you want Claude to score and summarize each run.
- **Repo cron** — a cron job that runs the CLI directly
  (`jobcut pull && jobcut score && jobcut surface`). Best if you want a
  hands-off, no-Claude run.

**Never both for the same searches.** (One-owner rule.) Any personal v1 you already
run is separate, but still don't point two runners at the same Apify searches.

## 6. Run it

In Claude (Cowork/Code), just ask:

- **“run jobcut-daily”** → pulls, imports, scores, and shows today's top matches.
- **“score my jobs”** → runs `jobcut-score`: Claude scores the jobs already in the DB
  and writes them back (no Apify, no manual JSON).
- **“run jobcut-market”** → shows skill demand, your gaps, and segment mix.

To verify the data landed, you can also run the CLI directly:

```bash
jobcut surface --json   # the ranked shortlist as JSON
jobcut market  --json   # the market summary as JSON
```

Both are read-only. The only writers are `import-jobs`, `ingest-scores`, and
`score` — all invoked by the skills via the CLI.

---

## Onboarding copy

Short strings for the Fase C onboarding (C3) to offer this step. Plain language, no
jargon, reassuring:

- **Title:** Automate your daily job search with Claude
- **Body:** Let Claude pull new roles each day, score them against your profile, and
  surface the best matches — all saved to your local jobcut database.
- **Reassurance:** 100% local · uses your own Apify token · you choose Claude scoring
  or the free built-in scorer · we never apply on your behalf.
- **One-owner note:** Pick one runner — Claude's scheduled task *or* a cron job — so
  the same search isn't scraped (and paid for) twice.
- **Primary CTA:** Set up the Cowork bridge
- **Secondary CTA:** Skip for now (you can enable it later in Settings)
- **Success:** Your daily job search is set. Ask Claude to “run jobcut-daily”
  anytime, or let the schedule do it.
