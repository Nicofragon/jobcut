---
name: jobcut-add
description: >-
  Add a job to jobcut from a URL you paste — Claude fetches the posting, pulls out
  the company, title and location, and saves it (optionally as an application you're
  tracking). Use when the user pastes a job link or says things like "add this job
  (paste a URL)", "agregá esta oferta (con su URL)", "guardá esta búsqueda de
  Lever/Greenhouse", "apliqué a este rol (URL)", or wants a non-LinkedIn / expired
  posting to show up in the tracker instead of a bare id. Writes via `jobcut add-job`
  (no manual JSON, no SQL).
---

# jobcut-add

Lets the user drop a **job URL** into chat and have Claude turn it into a real jobcut
row — so an application to a role outside the LinkedIn scraper (the company site,
Lever, Greenhouse, Ashby, an expired posting…) shows up with its **company and title**
instead of a bare id. Claude does the fetching and extraction; jobcut just ingests the
structured result through its CLI.

**Why this exists.** jobcut only knows a job if the scraper saw it. Applications to
everything else have no job row to cross-reference, so the tracker shows `tracker:60`
or a raw number. This skill fills that gap from a URL.

**CLI-only.** Never write SQL or edit `jobcut.db`. The write goes through
`jobcut add-job`; context reads go through `jobcut surface --json` / `jobcut stats --json`.

## Preconditions

- `jobcut` is installed and on PATH (`jobcut --help` works).
- Run from the **jobcut project folder**, or have `JOBCUT_DATA_DIR` exported. Confirm with
  `jobcut surface --json` (look at `meta.db_count`).

## Steps

1. **Fetch the URL the user pasted** and read the posting. Extract:
   - **company** (the employer — for a Lever/Greenhouse/Ashby link that's the company on
     the page, not the ATS vendor),
   - **title**,
   - **location** (if shown),
   - **description** (optional, a short paste is fine).
   If the page can't be fetched (login wall, expired, JS-only) or a field is genuinely
   unclear, **ask the user** for the company/title — never invent them.

2. **Add the job** (the only write — direct, via the CLI). One job per URL:
   ```
   jobcut add-job --url "<url>" --company "<company>" --title "<title>" \
     --location "<location>" --apply applied
   ```
   - `add-job` derives a **stable job_id** from the URL (LinkedIn → its numeric id; any
     other ATS → a readable `host-slug`), sets `source=manual`, and upserts the job. It's
     idempotent — re-adding the same URL won't duplicate it.
   - `--apply` also links an **application** (default status `applied`). Drop it (or use
     `--apply saved`) if the user only wants to save the role, not mark it applied.
   - **Repairing an existing orphan** (the tracker already shows a bare id for this role):
     pass `--job-id "<that id>"` so the new job binds to the application already there —
     e.g. `jobcut add-job --job-id 4414046061 --company "Acme" --title "Data Analyst"`.
   - Manual jobs have no score, so they never appear in the shortlist or market report —
     they only live in the tracker.

3. **Confirm + report.** Re-read `jobcut stats --json` (or `surface --json`) and tell the
   user what was added (company · title · status). The running console reads the DB per
   request, so they just refresh the browser — no restart.

## Notes

- One write only: `jobcut add-job`. No raw SQL. Reads: `jobcut surface --json`,
  `jobcut stats --json`.
- `add-job` is idempotent by URL/job_id — safe to re-run; it upserts.
- After adding, to record status changes or interview rounds conversationally, hand off to
  **jobcut-track**. To score roles use **jobcut-score**; this skill never scores or scrapes.
- Hard-codes no company, path, or profile — everything resolves from the data dir
  (working directory or `JOBCUT_DATA_DIR`).
