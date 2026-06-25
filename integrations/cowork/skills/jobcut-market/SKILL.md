---
name: jobcut-market
description: >-
  Summarize the job market against the user's profile from jobcut's accumulated
  database, via the CLI. Reports skill demand, prioritized gaps, segment mix, and
  salary disclosure. Use when the user says "what's the market asking for?",
  "show my skill gaps", or "run the jobcut market report".
---

# jobcut-market

Presents jobcut's market analysis. **CLI-only** — the computation lives in
jobcut; this skill just invokes it and formats the result. Do not recompute or
read the database directly.

## Preconditions

- `jobcut` is installed and `JOBCUT_DATA_DIR` is set (with `config/taxonomy.json`
  present — `jobcut init` provides it).
- The jobs table has data (run `jobcut-daily` first if it's empty).

## Steps

1. Get the market summary as data:
   ```
   jobcut market --json
   ```
   It returns a stable object:
   ```json
   {
     "total": 0, "relevant": 0,
     "segments": { "<segment>": <count> },
     "top_demand": [ { "skill": "SQL", "pct": 72, "status": "have" } ],
     "gaps": [ "Power BI", "dbt" ],
     "salary_pct": 18
   }
   ```
   If it returns `{"total": 0, ..., "empty": true}`, there are no jobs yet — tell the
   user to run **jobcut-daily** first and stop.

2. Present it in plain language:
   - **Market size:** `relevant` of `total` offers are in the user's segments.
   - **Top demand:** the `top_demand` skills with their `pct` and `status`
     (have / partial / gap).
   - **Prioritized gaps:** the `gaps` list — what the market asks that the profile
     lacks.
   - **Segment mix:** the `segments` counts.
   - **Salary transparency:** `salary_pct`% of offers disclose pay.

## Notes

- Read-only. `jobcut market --json` writes nothing; the full text report and
  dashboard are produced by plain `jobcut market` (not needed here).
- Generic: no hard-coded skills or profile — everything comes from the user's
  `config/taxonomy.json` and the accumulated jobs.
- For "what should I apply to" or pipeline stats (not market-wide demand), use
  **jobcut-review** instead.
