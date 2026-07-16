# jobcut — User manual

> How the whole platform works, end to end: the engine (Python pipeline +
> SQLite), the FastAPI bridge, the Next.js console (light **and** dark), the "lite"
> Streamlit dashboard, and every step of the daily flow. Version: 0.1.0 (schema v8).

## Table of contents

1. [What jobcut is](#1-what-jobcut-is)
2. [Architecture on one page](#2-architecture-on-one-page)
3. [Installation](#3-installation)
4. [The "data dir": where everything lives](#4-the-data-dir-where-everything-lives)
5. [Quick start (3 paths)](#5-quick-start-3-paths)
6. [The pipeline, step by step](#6-the-pipeline-step-by-step)
7. [The data model (SQLite)](#7-the-data-model-sqlite)
8. [Profile-derived targeting (role-agnostic)](#8-profile-derived-targeting-role-agnostic)
9. [The scoring (rubric)](#9-the-scoring-rubric)
10. [The web console, section by section](#10-the-web-console-section-by-section)
11. [The core loop (daily use)](#11-the-core-loop-daily-use)
12. [API reference](#12-api-reference)
13. [CLI reference](#13-cli-reference)
14. ["Lite" Streamlit dashboard](#14-lite-streamlit-dashboard)
15. [Cost and security](#15-cost-and-security)
16. [Configuration (reference)](#16-configuration-reference)
17. [Troubleshooting](#17-troubleshooting)
18. [Driving jobcut from Claude (Cowork skills)](#18-driving-jobcut-from-claude-cowork-skills)
19. [Glossary](#19-glossary)

---

## 1. What jobcut is

jobcut is a **100% local platform** for finding a job without scrolling through job
boards. Once a day it:

1. downloads your saved LinkedIn searches (via the Apify scraper),
2. deduplicates them into a local **SQLite** database,
3. discards what you can't take (geography, out-of-profile title),
4. **scores the rest 0–100 against your own profile**, and
5. hands you a **ranked shortlist** that you manage from a dashboard:
   you mark listings as "applied" and watch them move through a **funnel**.

**It never applies for you** (that's a human decision, by design). Because it never
deletes rows, it's also your **market dataset** (which skills are in demand, where, how
it changes over time).

**Principles:** everything local; your data/secrets never leave the machine (except the
Apify call); the paid scraper only fires with explicit confirmation; it works without
any AI API key (the AI layer is optional).

---

## 2. Architecture on one page

**One core, two frontends.** SQLite is the single source of truth; the Python package
is the engine; everything else consumes it.

```
                 ┌───────────────── jobcut (Python package) ─────────────────┐
                 │   pull · db(SQLite) · route/filter · scoring · surface/market │
                 └───────▲───────────────────────────────▲──────────────────────┘
                         │ direct import                  │ direct import
            FastAPI (uvicorn) ◀── HTTP/SSE ── Next.js     Streamlit "lite" (no Node)
                         ▲                       ▲
                         └──── `jobcut serve --open` (API + web + opens browser)
```

- **Python engine (`src/jobcut/`)** — pull, SQLite, routing/filter, scoring, surface/market, CLI.
- **FastAPI bridge (`jobcut.api`)** — a thin backend that **imports** the package and exposes it at `/api`. It does not reimplement logic.
- **Next.js console (`web/`)** — the main UI (onboarding, shortlist, funnel, etc.).
- **Streamlit "lite" (`dashboard/app.py`)** — the no-Node path: read + status change.

Settled decisions (see `docs/ADR-001`): SQLite single truth; FastAPI bridge (not Node
reimplementing the DB); application status in its own table; profile-derived targeting.

---

## 3. Installation

**Requirements:** Python 3.11+ (always). Node 20.9+ **only to build** the console
(not to run it). macOS / Linux / Windows.

```bash
git clone https://github.com/Nicofragon/jobcut.git && cd jobcut
pip install -e .            # engine + CLI
```

Optional extras (install the ones you use):

| Extra | For | Command |
|---|---|---|
| `api` | FastAPI bridge + `jobcut serve` | `pip install -e '.[api]'` |
| `cv` | Import a CV in PDF/DOCX | `pip install -e '.[cv]'` |
| `llm` | AI scoring/CV (OpenAI/Anthropic) | `pip install -e '.[llm]'` |
| `dashboard` | Streamlit "lite" | `pip install -e '.[dashboard]'` |
| `dev` | Tests + lint | `pip install -e '.[dev]'` |

---

## 4. The "data dir": where everything lives

Everything of yours lives in the **data dir** = `$JOBCUT_DATA_DIR` if set, or the
**current directory**. Nothing is written next to the installed package.

```
<data dir>/
├── .env                    # APIFY_TOKEN and (optional) ANTHROPIC_API_KEY / OPENAI_API_KEY
├── profile.md              # your profile — the highest-leverage input
├── jobcut.db             # the SQLite database (the source of truth)
├── config/
│   ├── config.json         # routing, title filter, scoring weights (overrides)
│   └── taxonomy.json       # skills (regex + have/partial/gap status) + role_segments
├── searches/*.json         # one saved search per file (input to the Apify actor)
├── documents/              # prep-docs drop-folder: .md with `jobcut:` frontmatter → auto-import
├── out/                    # exports: shortlist.md/csv, market-gaps.md, dashboard.json…
├── last_runs.json          # pointers to the last Apify run (for `pull --read`)
└── market_history.xlsx     # snapshot of skill demand by date
```

`jobcut init` creates this structure from templates (idempotent: it doesn't overwrite
what you've edited). Everything personal (`.env`, `profile.md`, `*.db`, `config/*.json`,
`searches/*.json`, `out/`) is **git-ignored**.

---

## 5. Quick start (3 paths)

### Path A — Web console (recommended)

```bash
pip install -e '.[api]'
cd web && npm install && npm run build && cd ..   # build the console once (Node 20.9+)
jobcut serve --open                              # http://127.0.0.1:8000
```

`jobcut serve` starts uvicorn and serves the console's static build and the API **in the
same process and origin**. The first time, the console takes you to **onboarding**.

### Path B — Console development (hot reload, 2 processes)

```bash
uvicorn jobcut.api.app:app --port 8000     # terminal 1: the API
cd web && npm run dev                          # terminal 2: Next dev on :3000
```

In dev the console detects port :3000 and hits `http://localhost:8000/api` (CORS already
allows it).

### Path C — No Node (Streamlit "lite")

```bash
pip install -e '.[dashboard]'
jobcut dashboard
```

### Try it without Apify (demo data, free)

```bash
export JOBCUT_DATA_DIR=$(pwd)/demo-data
jobcut init --no-input
python scripts/seed_demo.py     # seeds synthetic listings
jobcut score                  # scores them
jobcut serve --open
```

---

## 6. The pipeline, step by step

The daily flow. Each stage is a module and (nearly all of them) a CLI command. They all
operate on SQLite; none deletes data.

```
pull → store → route → filter → score → surface → market
```

| # | Stage | Module | What it does |
|---|---|---|---|
| 1 | **Pull** | `pull.py` | Reads `searches/*.json`, fires each search on the Apify actor (or re-downloads the last run with `--read`), and flattens the nested payload into clean columns. |
| 2 | **Store** | `db.py` | Upserts 1 row per `job_id` into the `jobs` table. `first_seen` is fixed; `last_seen`/`applicants`/`job_state` are refreshed when the listing is seen again; stable fields are not overwritten. Never deletes (historical accumulator). |
| 3 | **Route** | `route.py` | Geographic gate (config-driven): is it hireable *for you*? `home` (full) vs `region` (remote only) vs `foreign` (market-intel only). |
| 4 | **Filter** | `filter.py` | Applies the title filter (`include_titles`), excludes what's already scored (incremental), and **collapses reposts** by a `canonical_id` (company\|title\|location). |
| 5 | **Score** | `scoring/` | Scores each representative 0–100 against the profile + a one-line reason. Reposts inherit the canonical's score; out-of-profile titles get a fixed low score. |
| 6 | **Surface** | `surface.py` | Joins jobs+scores, applies the funnel, collapses reposts, **excludes already-applied** (the `applications` table), and writes `out/shortlist.md` + `.csv`. |
| 7 | **Market** | `market.py` | Skill demand vs your profile across the whole DB → `out/market-gaps.md` + `out/market-dashboard.html` + history. |

CLI equivalent:

```bash
jobcut pull --read    # free (re-downloads the last run) — or `jobcut pull` (paid)
jobcut score
jobcut surface
jobcut market
jobcut export         # dumps jobs/scores to CSV/JSON in out/
```

From the console, "Run scraper" does the pull (with cost confirmation) and "Re-score"
does the score — both with live progress (SSE).

---

## 7. The data model (SQLite)

Tables (`schema_version = 8`):

**`jobs`** — the mother accumulator, 1 row per `job_id` (PK). ~32 columns that mirror the
flattened payload: `title, company_name, location, workplace_type, applicants,
description, salary_*, recruiter_*, apply_url, linkedin_url, first_seen, last_seen,
source_searches`, etc. `VOLATILE = {last_seen, applicants, job_state}` are refreshed; the
rest is stable. **Never deleted.**

**`scores`** — **derived** sidecar (recomputable), 1 row per `job_id`:
`canonical_id, match_score, match_reasons, status` (`scored` | `discarded`),
`scored_date`.

**`applications`** — **truth written by you** (the funnel), kept separate from `scores` so
that a re-score never overwrites it. PK `job_id` (no FK → supports manual entries):
`status, status_category, applied_at` (set once), `updated_at` (refreshed),
`notes, source` (`manual` | `import` | …). Plus structured tracking columns:
`priority, next_action, next_action_date, contact, cv_version`, and for the
interview process `process_stages` (JSON with the named stages) +
`process_current` (integer: which stage you're on). Every status write goes through a
single point (`db.set_application_status`).

**`application_events`** — **append-only** timeline (1 row per event) of each
application: `kind ∈ status_change | note | interview | next_action`, with `body`, `meta`
and a date. It's the source of the history ("notes & activity") and of the cumulative
funnel ("did it ever reach an interview?"). `jobcut backfill-events` seeds the
initial `status_change` for apps imported before the timeline existed.

**`salary_estimates`** (schema v7) — salary bands **estimated** by Cowork/LLM when
the listing doesn't include them, 1 row per `job_id`: `min, max, currency, period, confidence,
rationale, source`. They're loaded with `jobcut ingest-salary` (the `jobcut-salary` skill) and are
only shown when there's no structured band and none declared in the description. Precedence in
the detail view: structured > declared in the text (`salary_listing`) > estimated.

**`application_documents`** (schema v8) — **prep documents** in markdown attached to an
application (study notes, interview debriefs), 1 row per document:
`job_id, client_key` (idempotency), `title, body, kind, event_id` (optional: anchors the doc
to a timeline event, e.g. a round), `archived_at` (soft-delete). They're written by the
`jobcut ingest-documents` bridge or by dropping the `.md` into `documents/` (auto-import on `serve`);
in the console they're **read-only** ("Prep documents" view in the detail).

**`_meta`** — `schema_version`. Migrations are additive and version-gated (idempotent).

> Why separate `scores` and `applications`: `scores` is rebuilt by recomputing; your
> application status is human input that **must never be lost** in a re-score.

---

## 8. Profile-derived targeting (role-agnostic)

**Nothing is hardwired to a role.** Your searches and your rubric are **derived from
`profile.md`** — it works just as well for a nurse as for a data analyst.

`profile.md` has stable headings that the system parses (`profile.py`), and your skills are
split by **how you stand on each** — the same have / partial / gap language Discovery and the
scorer use:

- `## Target roles` → target titles
- `## Seniority` → one line (kept as a human note)
- `## Core skills` → skills you can do today → status **`have`**
- `## Nice-to-have / learning` → some exposure → status **`partial`**
- `## Skill gaps` → skills your target roles want that you don't have yet → status **`gap`**
- `## Location & work mode` → `Based in:` and `Remote:`
- `## Dealbreakers` → requirements you do NOT meet

Older profiles (written before the `## Skill gaps` heading existed) still parse cleanly — a
missing section just yields no gaps.

### The skills "kit" — one base for scoring **and** Discovery

From the profile, `profile.py` **derives** the artifacts below. The important one is
`config/taxonomy.json` — your skills **kit**: each skill carries a **status**
(`have`/`partial`/`gap`), a **category** (core / viz / dataeng / …), a **regex** (name +
aliases), and a `close_via` for the gaps. This one kit is the single base for both the
**+20 "stack"** scoring component **and** the whole **Discovery** page.

| Derived | Where it comes from | What uses it |
|---|---|---|
| `searches/*.json` | target roles + remote mode (geoId = placeholder to fill in) | the pull |
| `filter.include_titles` | target roles (without seniority) | the filter |
| `routing.home` / `routing.region` | tokens from `Based in:` (region = country) | the route |
| `taxonomy.skills` | **every skill** with its status/category/aliases (the kit) | scoring (stack) **+** Discovery |
| `scoring.signals` | `partial` skills | scoring (bonus) |
| `scoring.dealbreakers` | Dealbreakers section (best-effort, review it) | scoring (penalty) |

Derivation is a **merge, not a clobber**: re-deriving preserves manual taxonomy edits
(extra patterns, `close_via`, and skills you added by hand); only `--force` regenerates from
scratch. It runs automatically when you save the profile, and non-destructively — so an
existing hand-tuned taxonomy (or a profile with custom, non-managed headings) survives an
upgrade untouched.

### Three ways to build the profile

1. **`jobcut-profile` Cowork skill (conversational).** Claude interviews you (any language)
   or reads a pasted CV, splits your skills into have/partial/gap, and writes `profile.md` +
   the kit in one step via `jobcut ingest-profile`. Updating one skill ("I learned dbt —
   move it to have") is the same flow with the new status. See
   [§18](#18-driving-jobcut-from-claude-cowork-skills).
2. **The console form.** **Settings → Profile** (and the onboarding wizard) edit the profile
   as a **structured form** (no markdown on view): fields go through
   `GET/PUT /api/profile/structured`; the raw `profile.md` is still at `GET/PUT /api/profile`.
   "Regenerate" writes the derived artifacts and a re-score applies the new rubric. The kit is
   shown back as a **colour-coded "Your skills kit" card** (have = green, partial = amber,
   gap = red) on the Profile page, with a compact summary in Settings. (Derived:
   `GET /api/profile/derived` previews; `POST /api/profile/derive` writes.)
3. **CV upload (optional AI layer).** Upload a CV (`txt/md` always; `pdf/docx` with the `[cv]`
   extra); with an LLM key present, the AI drafts a `profile.md` with the headings — including
   splitting skills across Core / Nice-to-have / Skill gaps by how strongly the CV evidences
   each; without a key it falls back to a *scaffold* with the CV text to organize. **Never
   saved on its own** — you review and confirm.

---

## 9. The scoring (rubric)

**Pluggable** via the `Scorer` interface. There are **two backends**, selectable in
`config.scoring.backend` — `rule_based` (the default: pure Python, no key, no cost,
transparent) and `claude_skills`. Both are free; they differ in *where* the judging happens.

### `rule_based` — components and weights (editable in `config.json`)

```text
+30  title       the title matches a target role (include_titles)
+20  stack       taxonomy skills present (half if only 1)
+15  location    hireable location (home full, region-remote partial)
+10  signals     "nice-to-have" skills from the profile present (default empty → no effect)
+10  employer    named company + plausible size
+10  reachable   <50 applicants or a named recruiter
−20  dealbreaker a hard requirement you don't meet
     out-of-profile cap: if the title does NOT match your target roles → score ≤ 30
```

Everything above (titles, skills, signals, dealbreakers, geography) **comes from your
profile** — there are no hardcoded role lists. Each score carries a one-line reason.

### `claude_skills` — the other backend

The scores are written by a **Claude Code / Cowork skill** (`jobcut-score`) and loaded with
`jobcut ingest-scores` (tagged `backend=claude_skills`). Best judgement, and no extra cost on
a Claude subscription.

It is **ingest-first**, not a live-pipeline scorer: the judging happens in Claude, outside
jobcut. So selecting it makes **`jobcut score` stand aside** — it prints a pointer to your
skill and writes nothing, rather than quietly rubric-scoring rows you expected Claude to
judge. Run your skill, then ingest. Only an *unknown* backend (a typo in `config.json`) falls
back to `rule_based`.

> **Provenance:** every row in `scores` carries the `backend` that produced it. The column is
> free text and unvalidated, so rows written by backends jobcut no longer ships (`local`,
> `llm_api` — removed in v9) keep their history and still render in the console.

---

## 10. The web console, section by section

Tokenized design with a **light and dark theme** (toggle in the nav + segmented control in
Settings → "Appearance"; the theme is stored in `localStorage` and applied before the first
paint, no flash). Navigation: **Today · Applications · Searches · Discovery · Settings**
(+ Onboarding and Detail). The Onboarding / Searches / Profile / Settings screens are
**friendly structured forms** — no markdown or JSON on view.

- **Onboarding** (`/onboarding`) — first-run wizard: (1) credentials (validate
  Apify for free + save), (2) profile (upload CV → draft, or fill out the form),
  (3) generate derived searches/rubric, (4) scoring backend, (5) first pull.
  Idempotent, with "Skip". The Home redirects here on first run (no token and no
  jobs).
- **Today** (`/`) — the "hero loop": the day's ranked shortlist. Filters (minimum
  score, debounced search). Each card: score, reason, link to the listing, and a quick
  status change. "New today" + "Backlog" sections. **Re-score** (free) and **Run
  scraper** (cost modal → SSE progress) buttons.
- **Detail** (`/job?id=…`) — redesigned around the **active process** (B-18). In the
  hero: title, compact **status strip** (clickable mini-funnel + "In process" /
  "Closed" pill + StatusSelect + "Open posting") and **salary band** (chip: structured,
  declared in the text, or estimated). Left column actionable-first: **Interview
  process card** (named stages + "stage 3/4" position, advance stage with an optional date,
  timing "Process: N days · avg gap N days", **"Suggest from posting"** that proposes stages
  by reading the listing) → **Notes & activity** (notes only) → description (collapsed with a fade +
  "Show full description"). On the right: "Why this matches you", tracking details and company
  data. A **"Prep documents"** tab shows the attached preparation documents
  (rendered and sanitized markdown, grouped by stage: Offer-level / R1 / R2 / …).
- **Applications** (`/applications`) — the tracking center: **KPI cards**, weekly
  activity, **Pipeline** (a funnel showing the **cumulative** reach — "ever reached
  X" — with a faint "N active" per stage), **Interview funnel** (conversion per round),
  **Needs attention** (stalled apps; it's **hidden when there's nothing actionable**), and a
  **flat sortable list** (default order "Active first") with an inline status selector +
  a status icon and a **"+ Add application"** form to load a role by hand.
- **Searches** (`/searches`) — CRUD of searches as a friendly form (with pause),
  create/delete, and "Run scraper" (with a cost warning). Remember to set the real `geoId`.
- **Discovery** (`/discovery`) — market gaps: skill demand vs your profile
  (have/partial/gap), prioritized gaps, segment mix.
- **Settings** (`/settings`) — credentials (validate/save), scoring backend, data
  dir + DB status, **export** CSV/JSON, a link to edit the Profile, an
  **"Appearance"** control (light/dark), and an **"Update jobcut"** card: it shows branch · sha ·
  local changes and an "Update from repo" button (`git pull --ff-only` + console rebuild;
  it pauses without overwriting anything if the working tree is dirty).
- **Profile** (`/profile`) — structured profile editor, regenerate searches/rubric
  (non-destructive), and an editor for scoring **weights**.

---

## 11. The core loop (daily use)

1. Open the console (`jobcut serve --open`, or the shortcut).
2. **Today** → review the shortlist; filter by score.
3. Click a listing → **Detail** → look at the score breakdown → apply on LinkedIn/ATS
   (you, by hand).
4. Mark the **status** (e.g. `applied` → then `screen`/`interview`/`offer`/…).
5. **Applications** → track your funnel; update statuses as you progress.
6. Every so often: **Run scraper** (brings in new listings, with cost confirmation) and
   **Re-score**. The status you set **survives** any re-score.

Targeting adjustment: **Settings → Profile** → edit `profile.md` → "Regenerate" → the
next run improves.

---

## 12. API reference

Base: `/api`. JSON in/out. Long/expensive operations (`pull`, `score`) go through the "run"
model with **SSE**; the rest is synchronous.

| Method | Route | What it does |
|---|---|---|
| GET | `/status` | Health: data dir, schema, counts, credential flags. |
| GET / PUT | `/credentials` | Reads (booleans) / writes `.env` (never returns secrets). |
| POST | `/validate-credentials` | Validates Apify **for free** (`user().get()`, doesn't fire the actor). |
| GET | `/shortlist` | Shortlist `{today, backlog, meta}`. Query: `min_score, backlog_min, q, location, recency_days, include_applied`. |
| GET | `/jobs/{id}` | Full listing + score + application status + salary (`salary_listing` declared in the text when there's no structured band; estimate if one exists). |
| GET | `/applications` | All applications (enriched with title/company + `days_in_stage`/`stalled`/`dormant` flags). |
| POST | `/applications/manual` | Creates a listing by hand (`source='manual'`) and links an application (the "+ Add application" form). |
| GET | `/applications/funnel` | KPIs + funnel + per-category + per-week + `reached` (cumulative reach per stage). |
| GET | `/applications/statuses` | Canonical status vocabulary + categories. |
| GET | `/applications/interview-funnel` | Conversion funnel per interview round. |
| GET | `/applications/process-timing` | Aggregate timing of the interview process. |
| GET/PUT/PATCH/DELETE | `/applications/{id}` | Read / set status (upsert) / PATCH structured fields (priority, next_action…) / delete. |
| GET/POST | `/applications/{id}/events` | Timeline (status/notes/rounds) / append an event (`kind` ∈ note\|interview\|next_action). |
| PUT | `/applications/{id}/process` | Defines the named process stages + current position. |
| POST | `/applications/{id}/process/suggest` | Proposes stages by reading the listing (uses an LLM if a key is present). |
| POST | `/applications/{id}/process/advance` | Advances to the next stage (optional date). |
| GET | `/applications/{id}/process/timing` | Per-application timing (days per stage; `null` if <2 rounds). |
| GET | `/applications/{id}/documents` · `/documents/{doc_id}` | The listing's prep documents (read-only; excludes archived; 404 if absent or from another listing). |
| GET | `/scoring/backends` | Lists the scoring backends with availability/usability flags. |
| GET | `/searches` · `/searches/structured` (CRUD) | Searches: by file (`/{name}`) or as a structured form (`/structured`, with `paused`). |
| GET/PUT | `/profile` | Reads / writes `profile.md` (raw). |
| GET/PUT | `/profile/structured` | Reads / writes the profile as fields (friendly form). |
| GET | `/profile/derived` | Previews derived searches/config/taxonomy. |
| POST | `/profile/derive` | Writes the derived files (non-destructive unless `force`). |
| POST | `/profile/from-cv` | Drafts `profile.md` from CV text (AI or scaffold). |
| POST | `/cv/extract` | Extracts text from an uploaded CV (txt/md; pdf/docx with `[cv]`). |
| GET/PUT | `/config` | Effective config (merged) / writes overrides. |
| GET/POST | `/market` | Market-gaps data (GET, read-only) / regenerate artifacts (POST). |
| POST | `/export` | Writes `out/jobs.csv`, `scores.csv`, `dashboard.json`. |
| POST | `/runs` | Starts a run `{kind: "pull"\|"score", mode, confirm}`. |
| GET | `/runs/{id}` | Run status. |
| GET | `/runs/{id}/events` | **SSE** of progress (`stage`, `message`, `done`). |
| GET/PUT/DELETE | `/schedule` | Reads / writes / deletes the system's daily schedule. |
| GET/POST | `/update` | Checkout status (branch · sha · local changes) / updates jobcut (`git pull --ff-only` + rebuild). localhost only; pauses without overwriting if the working tree is dirty. |

**Cost guard (hard rule):** `kind:"pull"` + `mode:"trigger"` (paid Apify)
**requires `confirm:true`**; otherwise → `409 confirmation_required`. `mode:"read"` and `score`
don't require confirmation. Interactive docs: `http://<host>:<port>/docs`.

---

## 13. CLI reference

```bash
jobcut init [--no-input]    # scaffold the data dir (idempotent)
jobcut pull [--read]        # pull from Apify (no flag = PAID; --read = free re-download)
jobcut score                # filter the funnel + score against the profile
jobcut surface [--json]     # writes out/shortlist.md + .csv (or JSON to stdout)
jobcut market [--json]      # writes out/market-gaps.md + dashboard + history
jobcut stats                # funnel KPIs as JSON (read-only)
jobcut unscored [--json]    # lists hireable jobs without a score (for an external scorer)
jobcut daily [--read] [--every N]   # pull + score + surface (what the scheduler runs)
jobcut export               # dumps the DB to CSV/JSON in out/

# Manual entry and agent writes (Claude/Cowork)
jobcut add-job [--url U | --company C --title T] [--location L] [--apply [STATUS]] [--job-id ID]
                            # adds a listing by hand (source=manual; optionally links an application)
jobcut ingest-scores FILE.json [--backend NAME]   # upsert scores (default backend=claude_skills)
jobcut ingest-events FILE.json    # applies write-ops to applications (notes, rounds, status, fields)
jobcut ingest-salary FILE.json    # upsert estimated salary bands (jobcut-salary skill)
jobcut ingest-documents FILE.json # upsert prep documents (markdown) by client_key; soft-delete via archive
jobcut import-docs [--dir D] [--dry-run]   # imports the .md files from the documents/ drop-folder (what serve does on startup)
jobcut import-jobs FILE.json      # upsert scraped job rows (no scrape)

# Timeline / funnel maintenance
jobcut backfill-events      # seeds the initial status_change for apps predating the timeline
jobcut age-applications     # ages silent Applied (≥30d with no reply) → No response

# Serve / open without a terminal
jobcut serve [--host H] [--port P] [--open] [--replace] [--no-build]
                            # API + console in one process. --open opens the browser;
                            # --replace takes the port if it's busy; --no-build skips recompiling
jobcut shortcut [--path P] [--port N]   # drops the jobcut icon on the Desktop (double-click, no terminal)
jobcut update [--no-build]  # git pull --ff-only + console rebuild (pauses without overwriting if there are local changes)
jobcut dashboard            # Streamlit "lite" (extra [dashboard])
```

---

## 14. "Lite" Streamlit dashboard

The **no-Node** path (maintenance mode, no new features). Three tabs:

- **Funnel** — reads the `applications` table; KPIs, funnel, status/week charts, table,
  and a **status toggle** (writes via `set_application_status`).
- **Discovery** — the scored shortlist from the DB (score buckets + table).
- **Market gaps** — the `out/market-gaps.md` report.

Start: `jobcut dashboard`. It's the option for anyone who doesn't want to install Node; the
Next.js console is the main frontend.

---

## 15. Cost and security

- **Apify is paid** (~$0.04–0.18 per run). `jobcut pull --read` re-downloads the last
  run **for free** and is the default in development. In the console, "Run scraper" always asks for
  confirmation (409 guard in the API).
- **Secrets:** `APIFY_TOKEN` and LLM keys live in `<data>/.env` (git-ignored). The API
  never returns their values (only booleans for "is it set").
- **Privacy:** everything is local. The only thing that leaves the machine is the Apify call.
- **Never auto-applies or auto-generates CVs** (by design).

---

## 16. Configuration (reference)

`config/config.json` (overrides; whatever you omit falls back to defaults). Main keys:

```jsonc
{
  "routing": { "home": "<regex>", "region": "<regex>" },   // hireable geography
  "filter":  { "include_titles": "<regex>" },              // titles worth scoring
  "scoring": {
    "backend": "rule_based",                                // rule_based | claude_skills
    "weights": { "title":30,"stack":20,"location":15,"signals":10,
                 "employer":10,"reachable":10,"dealbreaker":-20 },
    "signals": [],            // bonus patterns (derived from nice-to-have)
    "dealbreakers": [],       // penalty patterns (derived from Dealbreakers)
    "out_of_profile_cap": 30
  }
}
```

`config/taxonomy.json`: `skills` (`{cat, status: have|partial|gap, close_via, patterns}`) +
`role_segments` (for the market). **Environment variables:** `JOBCUT_DATA_DIR`,
`APIFY_TOKEN`, `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`, `NEXT_PUBLIC_API_BASE` (override of the
API base in the front end).

---

## 17. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Console says "API offline" | The API isn't running. `uvicorn jobcut.api.app:app --port 8000` or `jobcut serve`. |
| `serve` says "no build found (web/out)" | `serve` auto-builds the console if Node 20.9+ is present; if Node is missing or it fails, build it: `cd web && npm install && npm run build` (or `npm run dev` on :3000). |
| `serve` says "Port … already in use" | Usually an old `serve`. `jobcut serve --replace` takes the port, or `jobcut serve --port 8001`. |
| "Today" empty but there are jobs | The listings were scored on another day → they're in "Backlog". Lower the minimum score, or re-score. |
| `pull --read` fails | There's no previous run (`last_runs.json`). Run `jobcut pull` (paid) once. |
| A generated search returns nothing | The `geoId` was left as `REPLACE_ME`. Edit `searches/*.json` with your real LinkedIn geoId. |
| A nurse/non-data role scores low | Regenerate the targeting from your `profile.md` (Settings → Profile → Regenerate) and re-score. |
| A PDF CV won't read | Install the extra: `pip install -e '.[cv]'` (or paste the text). |
| `jobcut score` writes nothing and mentions a skill | `scoring.backend` is `claude_skills`, which scores in Claude — run your `jobcut-score` skill, or switch to `rule_based` in Settings. |
| CV import doesn't draft a profile | That's the optional AI layer: it needs `[llm]` + a key (`ANTHROPIC_API_KEY`/`OPENAI_API_KEY`). Without it the import still works, just without drafting. |

---

## 18. Driving jobcut from Claude (Cowork skills)

jobcut ships a set of **Claude skills** so an agent can run the whole pipeline — and build
your profile — by chatting, always through the `jobcut` CLI, **never raw SQL**. They work in
**Claude Cowork** (desktop) and **Claude Code** (CLI). Full guide:
[`integrations/cowork/SETUP.md`](../integrations/cowork/SETUP.md).

### 18.1 Install all the skills (once)

Code and Cowork install skills differently:

- **Claude Code** reads a folder — copy them in, then reload Claude:
  ```bash
  bash integrations/cowork/install.sh          # -> ~/.claude/skills
  ```
- **Claude Cowork** imports one skill per file — build a zip per skill and upload each via
  **Customize → Upload skill**:
  ```bash
  bash integrations/cowork/install.sh --zip    # -> ./jobcut-skill-zips
  ```
  **Start with `jobcut.zip`** (the front door); the other eleven are the workers it
  dispatches to. It's a one-time setup (≈12 uploads); no reload needed.

Point Claude at the **same data dir** as the CLI by exporting `JOBCUT_DATA_DIR` in the
environment Claude runs in. Then say **"is jobcut ready?"** — the **`jobcut`** front-door
skill confirms every skill is loaded and the CLI + data dir resolve, says what to fix if not,
and routes you to the right skill. Run it first each session.

> **One run owner (cost rule).** The daily pull is a paid Apify actor. Pick exactly one
> runner — the in-app scheduler (Settings → Automation), the `jobcut-daily` skill, or your
> own cron — so the same searches aren't scraped, and paid for, twice. If the scheduler is
> on, have Claude run `jobcut-daily` with `pull --read` (a free re-download).

### 18.2 The skills

Each reads via `jobcut <cmd> --json` and writes **only** through a `jobcut ingest-*` / CLI
command — the CLI is the single schema authority (never the DB directly).

| Skill | Does | Writes via |
|---|---|---|
| `jobcut` | Front door: readiness check + routing | — (read-only) |
| `jobcut-profile` | **Build/update your profile** by interview or CV → `profile.md` + kit | `ingest-profile` |
| `jobcut-daily` | The daily run: pull → score → surface today's top matches | `pull` / `score` |
| `jobcut-score` | Score/re-score jobs already in the DB, judged by Claude | `ingest-scores` |
| `jobcut-review` | Read-only: what to apply to, pipeline/weekly stats | — (read-only) |
| `jobcut-track` | Update an application — note, interview round, status, fields | `ingest-events` |
| `jobcut-docs` | Save a prep/study/debrief document into an application | `ingest-documents` |
| `jobcut-add` | Add a job from a URL (company site / Lever / Greenhouse) | `add-job` |
| `jobcut-open` | Launch the web console from chat | — |
| `jobcut-market` | Summarize demand vs your kit (Discovery, read-only) | — (read-only) |
| `jobcut-salary` | Estimate a salary band for offers that disclose none | `ingest-salary` |
| `jobcut-update` | Pull latest code, rebuild + restart the console | — |

### 18.3 How Claude builds the profile, and how it drives scoring + Discovery

This is the chain the whole tool rests on — **one profile, one kit, two consumers:**

```text
  jobcut-profile (interview / CV)                    profile.md  (human-readable record)
        │  extract skills → have / partial / gap          │
        ▼                                                  ▼
  jobcut ingest-profile ──────────────▶  config/taxonomy.json  = your skills KIT
                                            (per skill: status + category + regex)
                                                  │                       │
                             drives ◀─────────────┘                       └────▶ drives
                                  ▼                                                 ▼
                    SCORING  (the +20 "stack" component)              DISCOVERY (jobcut-market)
                                                                     demand · coverage · gaps
```

1. **Skills extraction — `jobcut-profile`.** Claude interviews you (any language) or reads a
   pasted CV and splits your skills into **have** (real strengths), **partial** (some
   exposure), and **gap** (target roles want it; you're learning it). One
   `jobcut ingest-profile` writes `profile.md` **and** re-derives the kit, **merging** so any
   hand-tuned taxonomy patterns survive (see [§8](#8-profile-derived-targeting-role-agnostic)).
   Reviewing a CV, it shows you the have/partial/gap split to correct before writing — it
   doesn't guess silently. Updating one skill ("I learned dbt — move it to have") is the same
   call with the new status.
2. **Scoring uses the kit.** Both backends judge against the same profile-derived skills:
   `rule_based` matches the kit's regex for its **+20 "stack"** component; `claude_skills`
   (the `jobcut-score` skill) reads each job, judges it against your profile, and writes the
   verdict back via `ingest-scores`. Same base, different judge — see
   [§9](#9-the-scoring-rubric).
3. **Discovery uses the same kit.** `jobcut-market` (and the Discovery page) counts market
   demand for each kit skill and crosses it with your have/partial/gap status to compute
   **coverage** and a **prioritized gap** list — so what you're missing, and what to learn
   next, comes straight from the profile you built.

Because scoring and Discovery share one kit, **a better profile improves both at once** — and
nothing is hardwired to a role, so the same chain works for a nurse or a data analyst.

---

## 19. Glossary

- **funnel** — the listings hireable for you (they pass the geo gate); the rest are
  market-intel only.
- **canonical_id** — the `company|title|location` key used to collapse reposts.
- **representative / repost** — when collapsing reposts, one representative is scored; the reposts
  inherit its score.
- **status vs status_category** — `status` is the canonical value you set
  (`applied/screen/interview/offer/rejected/withdrawn/no_response`); `status_category` is
  the derived funnel category (Applied, Screen, Interview, Offer, …).
- **data dir** — the folder with all your data/config (`$JOBCUT_DATA_DIR` or the current dir).
- **lite** — the Streamlit dashboard (read + toggle), the no-Node path.

---

*Related documents: [docs index](README.md) · [WORKFLOW](WORKFLOW.md).*
