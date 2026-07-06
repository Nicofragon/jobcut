---
name: jobcut-update
description: >-
  Update the jobcut app to the latest version from git and rebuild the console.
  Use when the user says "update jobcut", "update the app", "I pulled new code
  but I still see the old design", or "get the latest jobcut". Pulls the repo,
  reinstalls if dependencies changed, and restarts `jobcut serve` (which
  auto-rebuilds the web console). Read-only on the database — it never scrapes,
  scores, or deletes data.
---

# jobcut-update

Brings a cloned jobcut install up to date: pull the latest code, reinstall only if
dependencies changed, and restart the console so the new build (and design) shows.
This is the fix for "I updated but still see the old Application Tracker" — the
console is a static build that must be rebuilt and the browser cache busted.

**Never touches the database contents.** No `pull` (no Apify cost), no scoring, no
deletes. The user's jobs, scores, and applications are untouched.

## Preconditions

- The install is a **git clone** of the jobcut repo (there's a `.git/`).
- The venv lives at `.venv/` in the repo (the standard `setup.sh` layout), and
  `jobcut` resolves to `.venv/bin/jobcut`.
- Run from the **repo root**.

## Steps

1. **Check the working tree is clean** before pulling — never clobber local edits:
   ```
   git status --porcelain
   ```
   If it prints anything, stop and tell the user they have uncommitted changes; let
   them decide (commit / stash) before updating. Do **not** `git reset --hard` or
   force anything.

2. **Pull the latest code:**
   ```
   git pull --ff-only origin main
   ```
   If the pull reports "Already up to date.", tell the user they're current — the
   "old design" is then a stale browser cache, so skip to step 5 (hard refresh).

3. **Reinstall only if dependencies changed.** Check whether the pull touched
   `pyproject.toml`:
   ```
   git diff --name-only HEAD@{1} HEAD | grep -q pyproject.toml && echo CHANGED
   ```
   If it prints `CHANGED`, reinstall the package into the venv:
   ```
   .venv/bin/pip install -e '.[api,cv,llm]'
   ```
   Otherwise skip this — an editable install picks up `.py` changes with no reinstall.

4. **Restart the console.** Stop any running `jobcut serve`, then start it again:
   ```
   jobcut serve --open
   ```
   `serve` auto-rebuilds the web console when the source is newer than the build
   (after a pull it will be), so this produces a fresh build and serves it with
   `no-cache` HTML — every later update then shows on a normal reload.

5. **Bust the browser cache once.** The very first load after an update may still show
   the cached old page. Tell the user to **hard-refresh** `localhost:8000`
   (Cmd/Ctrl+Shift+R) or open it in a private window once. After that, the server's
   `no-cache` HTML keeps it current automatically.

## Notes

- **Safe by construction:** read-only on the DB, fast-forward-only pull, no
  force-push, no data deletion. If anything is ambiguous (dirty tree, merge needed),
  stop and ask rather than guess.
- Pair with **jobcut-daily** (fetch + score) and **jobcut-review** (what to apply to)
  — this skill only keeps the install itself current.
