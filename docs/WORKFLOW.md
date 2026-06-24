# jobcut — how the workflow works

A complete walkthrough of the pipeline, from pulling listings off Apify to
tracking the roles you apply to. Written for someone seeing the project for the
first time.

---

## 1. The mental model

jobcut is a **local, daily job pipeline**. Once a day it:

1. pulls fresh LinkedIn listings (via the Apify scraper),
2. dedupes them into a local database,
3. routes out the roles you can't take,
4. scores the rest **0–100 against your own profile**,
5. hands you a ranked shortlist + a market-gap report.

It **never applies on your behalf** — finding and ranking is automated; applying
stays human. And because it never deletes a row, the database doubles as your own
**market dataset** (which skills are in demand, where, and how that shifts over time).

### SQLite is the spine

Every stage reads from and writes to **one local SQLite file** (`jobcut.db`).
That is deliberate: the database is the *contract* between the pipeline and any
frontend (the CLI, the Streamlit dashboard, and any future UI all read the same
file). CSV/JSON/Markdown outputs are **exports**, never the source of truth.

```
                          ┌──────────── jobcut.db (SQLite) ────────────┐
                          │   jobs table   ·   scores table              │
                          └──────────────────────────────────────────────┘
   Apify          ▲ write       ▲ write/read     ▲ read          ▲ read
 (LinkedIn)  ─▶  PULL  ─▶ STORE ─▶ ROUTE+FILTER ─▶ SCORE ─▶ SURFACE / MARKET / EXPORT ─▶ out/
                                                                            │
                                                                            ▼
                                          DASHBOARD (Streamlit)  +  application TRACKER (your CSV/xlsx)
```

### Where everything lives — the data dir

All your files live in a **data dir**: the current working directory by default,
or wherever `$JOBCUT_DATA_DIR` points (resolved by
[paths.py](../src/jobcut/paths.py)). Nothing is ever written next to the
installed code.

```
<data-dir>/
├── .env                 # APIFY_TOKEN (git-ignored)
├── profile.md           # your roles, skills, dealbreakers  ← drives scoring
├── config/
│   ├── config.json      # geography, title filter, scoring weights
│   └── taxonomy.json    # skills (regex + have/partial/gap) for the market report
├── searches/*.json      # one file per saved LinkedIn search
├── jobcut.db          # the canonical SQLite store (jobs + scores)
└── out/                 # generated outputs (shortlist, market report, exports)
```

---

## 2. One-time setup — `jobcut init`

[cli.py](../src/jobcut/cli.py) scaffolds the data dir from bundled templates and
prompts for your Apify token. It creates the files above and **never overwrites**
ones you've already edited.

Then you edit four things (once):

| File | What to put there |
|------|-------------------|
| `.env` | Your `APIFY_TOKEN` (from console.apify.com → Settings → API). |
| `profile.md` | Target roles, real skills, dealbreakers. **The highest-leverage file** — bad profile in, bad matches out. |
| `config/config.json` | Your geography under `routing`; optionally tweak the title filter and scoring `weights`. |
| `searches/*.json` | Your saved searches (titles, locations, recency). One file = one search. |

---

## 3. The pipeline, stage by stage

### Stage 1 — PULL (fetch from Apify) · [pull.py](../src/jobcut/pull.py)

```bash
jobcut pull            # PAID — triggers a fresh scrape (~$0.04–0.18 per search)
jobcut pull --read     # FREE — re-downloads the last triggered run (use in dev)
```

- Reads every `searches/*.json` — each file is the input to the Apify actor
  `harvestapi/linkedin-job-search`. The filename becomes the search's label.
- Fires the searches **in parallel**, waits for them, downloads the datasets, and
  **flattens** the nested JSON into clean columns (title, company, location,
  applicants, salary, recruiter, ATS, description, …).
- Remembers the last run in `last_runs.json` so `--read` can re-fetch it for free.

> ⚠️ **This is the only stage that touches the network or costs money.** Everything
> downstream is free, offline, and instant. `--read` is the safe default while
> developing; a bare `pull` is the only thing that spends.

### Stage 2 — STORE (upsert into SQLite) · [db.py](../src/jobcut/db.py)

The flattened rows go into the **`jobs`** table, **one row per `job_id`**:

- **New job** → inserted with `first_seen = last_seen = today`.
- **Seen before** → only the volatile fields refresh (`last_seen`, `applicants`,
  `job_state`); `source_searches` accumulates which searches found it; stable
  fields (title, description) are left untouched.
- **It never deletes** — this is what makes the market dataset accumulate.

### Stage 3 — ROUTE + FILTER (decide what's worth scoring) · [route.py](../src/jobcut/route.py) + [filter.py](../src/jobcut/filter.py)

Two cheap gates run (inside `jobcut score`) *before* any scoring effort is spent:

- **Route (geography).** Is this hireable *for you*? `config.json → routing` defines
  a `home` region (fully hireable: on-site, hybrid or remote) and a wider `region`
  (hireable only when remote). Everything else is "market-intel only" — kept, but
  never scored. The hireable set is the **funnel**.
- **Filter.** A title regex (`config.json → filter.include_titles`) drops obvious
  mismatches before they reach the scorer. It also:
  - **skips anything already scored** (incremental — you only ever score new jobs), and
  - **collapses reposts**: jobs sharing `company | title | location` (a `canonical_id`)
    are reduced to one representative.

### Stage 4 — SCORE (rank against your profile) · [score.py](../src/jobcut/score.py) + [scoring/](../src/jobcut/scoring/)

```bash
jobcut score
```

Scoring is **pluggable** — a `Scorer` interface ([scoring/base.py](../src/jobcut/scoring/base.py))
with three backends selected by `config.json → scoring.backend`:

- **`rule_based`** (default · [rule_based.py](../src/jobcut/scoring/rule_based.py))
  — pure Python, no API key, no cost. A transparent rubric you tune in
  `config.json → scoring.weights`:

  ```text
  +30  title matches a target role        +10  reasonable employer (some size)
  +20  stack keywords present             +10  reachable (<50 applicants or a recruiter)
  +15  workable location                  −20  a hard requirement you don't meet
  +10  AI signals (LLM / GenAI / RAG)     out-of-profile titles capped low
  ```
- **`llm_api`** — optional OpenAI/Anthropic hook (bring your own key). *Phase 2.*
- **`claude_skills`** — optional adapter for Claude users. *Phase 2.*

Each scored job gets a **0–100 score + a one-line reason**. Then the orchestrator:

- has **reposts inherit** their representative's score (no double-spend),
- gives **title-discards** a low fixed score with `status = "discarded"`,
- **upserts everything into the `scores` table** with today's date.

### Stage 5 — SURFACE (your shortlist) · [surface.py](../src/jobcut/surface.py)

```bash
jobcut surface
```

Joins `jobs` + `scores`, keeps the funnel, collapses reposts, and writes:

- **`out/shortlist.md`** — today's top matches (≥60) + a backlog of strong older
  ones (≥75). Each line: score, reason, a working link, and the suggested next step.
- **`out/shortlist.csv`** — the same, machine-readable.

If you've configured an application tracker (§5), surface **excludes roles you've
already applied to**, so they never clutter the shortlist again.

### Stage 6 — MARKET (skill-gap intel) · [market.py](../src/jobcut/market.py)

```bash
jobcut market
```

Analyzes the **whole database** (not just the funnel). For the data/analytics
segment it counts how often each skill (from `taxonomy.json`) is demanded, crosses
it with your have/partial/gap status, and writes:

- **`out/market-gaps.md`** — demand vs your profile, prioritized gaps.
- **`out/market-dashboard.html`** — an interactive chart.
- a per-skill history snapshot, so you can watch demand shift over weeks.

This is *why* never deleting rows matters.

### Stage 7 — EXPORT (neutral formats) · [export.py](../src/jobcut/export.py)

```bash
jobcut export
```

Dumps `out/jobs.csv`, `out/scores.csv`, and `out/dashboard.json` (funnel counts +
score buckets) for the dashboard, a spreadsheet, or GitHub Pages.

---

## 4. Tracking the roles you apply to

jobcut **finds and ranks**; *you* decide and apply. When you apply, you log it in
a hand-edited file (CSV or xlsx) — for example with columns
`Company, Role Title, Tier, LinkedIn URL, Status, Date Applied`. Point jobcut at
it with **`$JOBCUT_TRACKER`**.

That tracker does two things:

1. **Feeds the shortlist's exclusion** — surface drops roles already in it, so you
   never re-triage something you've applied to.
2. **Powers the dashboard's Funnel tab** — [tracker.py](../src/jobcut/tracker.py)
   reads it live and classifies each free-text `Status` into a funnel:
   `Applied → Reviewing → Screen → Interview → Offer` (plus `Rejected`,
   `Withdrawn`, `No response`).

> It's intentionally manual in v1: SQLite is awkward to edit by hand, and
> application status is a human judgment. The tracker stays a file you own.

---

## 5. The dashboard · [dashboard/app.py](../dashboard/app.py)

```bash
jobcut dashboard          # needs: pip install -e '.[dashboard]'
```

A dark, GitHub-style Streamlit app with three tabs:

- **Funnel** — your application funnel from the tracker (KPIs, conversion bars,
  next actions, status + weekly charts, a searchable/filterable table). Reads
  `$JOBCUT_TRACKER` live; if it's unset, the tab explains how to enable it.
- **Discovery** — jobcut's scored shortlist from `jobcut.db` (KPIs, score
  distribution, the ranked table with score badges + a min-score slider).
- **Market gaps** — the `market-gaps.md` report.

---

## 6. A normal day

```bash
jobcut pull --read     # or `pull` for a fresh paid scrape  → updates the jobs table
jobcut score           # route + filter + score the new funnel → scores table
jobcut surface         # → out/shortlist.md  (read this over coffee)
jobcut market          # → out/market-gaps.md
jobcut dashboard       # browse it all interactively
```

In practice you don't type these — you **schedule the daily run** with your OS
(templates in [scheduler/](../scheduler/) for launchd / cron / Task Scheduler), and
the shortlist just appears each morning. You read ~10 good matches, apply to the
ones worth it, and log them in your tracker — which then keeps them off tomorrow's
list and updates your funnel.

---

## 7. Two rules that define the project

1. **Never triggers a paid Apify run without you asking.** `--read` is free; a bare
   `pull` is the only thing that spends, and it's never automatic in dev.
2. **Never applies on your behalf.** It finds and ranks; you decide.

The leverage is in *not* spending attention on the wrong 190 roles — so you have
energy for the right 10.
