---
name: jobcut-salary
description: >-
  Estimate a salary band for jobcut offers where the employer didn't disclose one,
  using a web search, and write it back as an ESTIMATE (clearly separate from a real
  disclosed band). Use when the user says things like "estimate salaries", "what would
  these roles pay?", "estimá el sueldo de las ofertas sin banda", "rangos salariales de
  mi shortlist", or "how much does this role pay in this city?". Searches the web for
  role + seniority + location, then writes via `jobcut ingest-salary` (no manual JSON,
  no SQL). Never overwrites a disclosed salary.
---

# jobcut-salary

LinkedIn hides the salary on most offers, which is one of the most useful things to
know before applying. This skill fills that gap: for offers with **no disclosed band**,
Claude looks up a market range (role + seniority + location) and writes it back as an
**estimate** — stored separately and shown in the console with an "est." marker, never
confused with a number the employer actually published.

**CLI-only.** Never write SQL or edit `jobcut.db`. Context comes from
`jobcut surface --json` / `jobcut stats --json`; the write goes through
`jobcut ingest-salary`. The estimate lives in its own place — it **never** touches the
disclosed `salary_*` fields, and jobcut only *shows* an estimate when the employer
disclosed none (so it can never override a real band).

## Preconditions

- `jobcut` is installed and on PATH (`jobcut --help` works).
- Run from the **jobcut project folder**, or have `JOBCUT_DATA_DIR` exported. Confirm with
  `jobcut surface --json` (look at `meta.db_count`).
- Use a scratch path for the temp file, e.g. `tmp/estimates.json` under the data dir.

## Steps

1. **Pick the offers to estimate.** Pull the shortlist and resolve which roles the user
   means (their whole shortlist, or the ones they named):
   ```
   jobcut surface --json
   ```
   Each row has `job_id`, `title`, `company_name`, `location`. If the user named a
   company/role, match on that; otherwise estimate the top shortlisted ones.

2. **Estimate each band with a web search.** For each offer, search the web for the pay
   range for that **role + seniority (from the title) + location/market** — use sources
   like Levels.fyi, Glassdoor, Payscale, or local market reports. Produce, per offer:
   - `est_min`, `est_max`: integers in the local currency (annual unless the market
     quotes otherwise). At least one is required; give a range when you can.
   - `currency`: ISO-ish code (`EUR`, `USD`, `GBP`, …).
   - `period`: `year` (default), `month`, or `hour`.
   - `basis`: one short line naming the source + your reasoning
     (e.g. `"Glassdoor/Levels.fyi — Madrid mid-level BI Analyst, ~45–55k EUR"`).
   - **Be honest about uncertainty** — a wide range with a clear basis beats a fake-precise
     point. If you genuinely can't find anything for a role, skip it (don't invent one).

3. **Write the estimates file** as JSON:
   ```json
   { "estimates": [
       { "job_id": "4396360445", "est_min": 45000, "est_max": 55000,
         "currency": "EUR", "period": "year",
         "basis": "Glassdoor/Levels.fyi — Madrid mid BI Analyst" }
   ] }
   ```

4. **Write to the database** (the only write — direct, via the CLI):
   ```
   jobcut ingest-salary tmp/estimates.json
   ```
   It upserts by `job_id` (re-estimating overwrites the previous estimate), tags each
   row `source=cowork_web`, and reports how many landed / were skipped.

5. **Confirm + report.** Tell the user the bands you estimated (company · title · range ·
   basis), and that they show in the console marked **"est."**. The running console reads
   the DB per request, so they just refresh — no restart.

## Notes

- The only writer is `jobcut ingest-salary`. Reads: `jobcut surface --json`,
  `jobcut stats --json`. No raw SQL, ever.
- **Estimate ≠ disclosed.** This skill produces only estimates. Never present an estimate
  as the employer's figure, and never write into the disclosed `salary_*` fields. jobcut
  shows the estimate only when there's no disclosed band, with an "est." marker.
- Estimates are **idempotent** (upsert by `job_id`) — safe to re-run to refresh a band.
- Disclosure metrics (the market report's "salary disclosed in N%") keep counting only
  **disclosed** salaries — estimates never inflate them.
- To score offers use `jobcut-score`; to decide what to apply to use `jobcut-review`.
  Hard-codes no profile, path, or company.
