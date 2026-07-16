---
name: jobcut-profile
description: >-
  Build or update the user's jobcut profile by interviewing them (or reading a
  pasted CV), then write it straight into the local jobcut install — profile.md
  plus the skills "kit" that powers scoring and Discovery. Use when the user says
  "set up my profile", "armá mi perfil", "update my skills", "I learned X / move X
  to have", or "extract my profile from my CV". Writes via `jobcut ingest-profile`.
---

# jobcut-profile

Turns a short conversation (or a CV) into the user's jobcut **profile** — the single
input everything else keys off. It writes `profile.md` **and** re-derives the skills
**kit** (`config/taxonomy.json` + `config.json`), which is what `jobcut score` scores
against and what the **Discovery** page reports on (demand, coverage, gaps, heatmap).

**CLI-only, one writer.** Never edit `profile.md`, `jobcut.db`, or the config files
directly. The only write is `jobcut ingest-profile <file.json>`. It writes the profile,
merges the kit (your manual taxonomy edits survive), and regenerates searches.

**Any language.** Interview in whatever language the user speaks; skill/role names can be
in any language. jobcut matches them literally, so keep them as the user actually says them.

## Preconditions

- `jobcut` is installed and on PATH (`jobcut --help` works), or `JOBCUT_DATA_DIR` is set.
- Use a scratch path under the data dir for the payload, e.g. `tmp/profile.json`.

## Steps

1. **Gather the inputs.** Either interview the user or read a CV they paste:
   - **Target roles** — the job titles they want (e.g. "Senior Data Analyst").
   - **Seniority** — one line ("~8 years, senior IC").
   - **Location & remote** — where they're based; remote appetite (yes / hybrid only /
     on-site only).
   - **Skills, split by how they stand on each** — this is the important part:
     - `have` — real strengths they can do today.
     - `partial` — some exposure, wouldn't claim as core.
     - `gap` — skills their target roles want that they don't have yet / are learning.
   - **Dealbreakers** — hard constraints they do NOT meet (a required language, clearance…).
   - Optionally tag each skill with a **category** (core / viz / dataeng / warehouse /
     method / ml) and **aliases** (other names/tools that mean the same skill).
   - If reading a CV, draft the split yourself, then **show the user the have/partial/gap
     lists and let them correct** before writing — don't guess silently.

2. **Build the payload** as JSON (skills can be bare names — they default to have/core):
   ```json
   {
     "target_roles": ["Senior Data Analyst", "Product Analyst"],
     "seniority": "~8 years, senior IC",
     "locations": ["Madrid, Spain"],
     "work_types": ["remote", "hybrid"],
     "dealbreakers": ["security clearance"],
     "skills": [
       { "name": "SQL",     "status": "have",    "category": "core",    "aliases": ["postgres"] },
       { "name": "Python",  "status": "have",    "category": "core",    "aliases": ["pandas"] },
       { "name": "Tableau", "status": "partial", "category": "viz" },
       { "name": "dbt",     "status": "gap",     "category": "dataeng" },
       { "name": "Airflow", "status": "gap",     "category": "dataeng" }
     ]
   }
   ```

3. **Write it** (the only write — profile + kit in one step):
   ```
   jobcut ingest-profile tmp/profile.json
   ```
   It prints how many skills landed (have / partial / gap) and re-derives the kit,
   **merging** so any hand-tuned taxonomy patterns/close_via survive. `profile.md`'s custom
   sections (e.g. "Notes for the scorer") are preserved; the managed sections are regenerated.

4. **Confirm + next steps.** Tell the user the profile is set and the kit updated, then point
   them onward:
   - See the kit visually + tweak: the **Profile** page (or `jobcut serve --open`).
   - Re-score against the new profile: hand off to **jobcut-score**.
   - Check demand vs the profile: **Discovery** / **jobcut-market**.

## Notes

- **Updating one skill** ("I learned dbt — move it to have") is the same flow: re-run with
  the corrected `status`. The merge keeps everything else.
- **This does not scrape or score** (no Apify cost, no DB job/score writes). It only writes
  the profile + kit. To then fetch and score jobs, use **jobcut-daily** / **jobcut-score**.
- The kit (`have`/`partial`/`gap` + category) is deliberately the base for BOTH scoring and
  Discovery, so a good profile here improves both at once.
- Everything is keyed off the data dir (working dir or `JOBCUT_DATA_DIR`). No hard-coded
  profile, path, or language.
