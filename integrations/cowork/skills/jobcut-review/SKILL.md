---
name: jobcut-review
description: >-
  Review the jobcut shortlist and answer questions about your job-search data —
  read-only, via the CLI. Use when the user says "what should I apply to today",
  "show my top 10", "how's my pipeline / what did I apply to this week", "what
  jobs do I have", or "open the jobcut console". Reads `surface --json`,
  `stats --json`, and `market --json`; can launch the web console with
  `jobcut serve --open`. Never scrapes (no cost) and never writes.
---

# jobcut-review

The daily **consumer** side of jobcut: once jobs are pulled and scored (by
`jobcut-daily` / `jobcut-score` / the in-app scheduler), this skill helps the user
decide **what to apply to** and answers questions about their data. It is
**read-only** — it runs no Apify scrape (no cost) and never writes to the DB.

**CLI-only.** Never open `jobcut.db` or write SQL. Every answer comes from a
read-only `jobcut … --json` reader.

## Preconditions

- `jobcut` is installed and on PATH (`jobcut --help` works).
- `JOBCUT_DATA_DIR` points at the project's data dir (or run from the project
  folder). Confirm with `jobcut surface --json` → look at `meta.db_count`.
- If the DB is empty, run **jobcut-daily** first, then come back here.

## The three readers

| Question | Reader | What it returns |
|----------|--------|-----------------|
| "What should I apply to?" / "top 10" | `jobcut surface --json` | `today` (ranked, hireable, scored, deduped) + `backlog` + `meta` |
| "How's my pipeline / this week?" | `jobcut stats --json` | applications funnel: `total`, `live`, `interview`, `offers`, `by_week`, `counts`, `stalled_count` |
| "What's the market asking?" | `jobcut market --json` | skill demand, gaps, segment mix, salary disclosure |

## Steps

1. **Pick the reader** that matches the question (table above). For a general
   "what's going on with my search" ask, read `surface --json` **and**
   `stats --json` and combine them.

2. **Top-N to apply** (the most common ask). Run:
   ```
   jobcut surface --json
   ```
   Take the `today` list (already filtered to hireable + scored + deduped, ranked by
   score) and present the top 10 as:

   `**1. Title — Company** (score) · why it matches · <apply link>`

   Lead with the strongest fits, keep each "why" to one honest line, and end with the
   `meta` counts (e.g. "showing top 10 of 34 in the funnel; 164 in the DB"). If the
   user asks to narrow ("only remote", "only ≥80"), filter the same list — don't
   re-scrape.

3. **Pipeline / weekly questions.** Run `jobcut stats --json` and answer from it:
   applications this week = `by_week[<current ISO week>]`; what's live/interviewing =
   `live` / `interview`; anything stuck = `stalled_count`. Don't invent numbers the
   reader doesn't return — if it's not in the payload, say so and offer to open the
   console (step 5).

4. **Market questions.** Defer to the **jobcut-market** skill (or run
   `jobcut market --json` and summarize demand, gaps, and segment mix).

5. **Open the console** when the user wants to click around (apply, change a status,
   see the tracker KPIs and the weekly-activity chart):
   ```
   jobcut serve --open
   ```
   This serves the API + web console as one process and opens the browser. It
   auto-rebuilds the console if it's stale, so the user always sees the current
   design. The tracker now has Saved (park-for-later) status, pipeline KPIs, and an
   8-week activity chart — point the user there for anything interactive.

## Notes

- **Read-only, zero cost.** This skill never calls `jobcut pull` (no Apify spend) and
  never writes. To fetch new jobs, use **jobcut-daily**; to (re)score, use
  **jobcut-score**.
- All three readers print to stdout — read them directly, don't write temp files.
- Generic: everything is keyed off `JOBCUT_DATA_DIR`; no hard-coded profile or paths.
