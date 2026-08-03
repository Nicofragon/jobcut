# AGENTS.md — driving jobcut from Claude (Cowork / Claude Code)

This file is for an **agent helping a user run their job search** with jobcut — not
for contributing code (that's [`CLAUDE.md`](CLAUDE.md)). If you're a coding agent
working on the repo, read CLAUDE.md instead.

## Start here, every session

When the user opens jobcut and wants to work on their job search, **run the `jobcut`
skill first**. It is the front door: it confirms the jobcut skills are loaded and the
CLI + data dir resolve, tells the user exactly what's missing if not, and routes the
request to the right skill. Do this before taking any jobcut action.

If the `jobcut` skill (or any `jobcut-*` skill) isn't available to you, **say so** and
point the user at `integrations/cowork/install.sh` + `integrations/cowork/SETUP.md` —
do **not** improvise around the missing skill (e.g. by editing the database by hand).
Note that Claude **Cowork** reads a different skills directory than Claude **Code**;
the skills must be installed where *your* tool actually reads them.

## The one rule that's been gotten wrong

**Never edit `jobcut.db` directly. Never write SQL.** Every change goes through the
`jobcut` CLI — it's the single schema authority. And **write into the right place for
what the user is recording**:

| The user tells you… | It's a… | Through | Never put it in |
|---|---|---|---|
| Something that happened / a reminder ("previous rejection", "recruiter called") | **note** | `jobcut-track` (`kind:"note"`) | `scores.match_reasons` |
| An interview round | **interview** event (send `meta.index` — re-sending a round corrects it) | `jobcut-track` | — |
| A pipeline status change | **status** | `jobcut-track` | — |
| Why a job scored what it did | **scoring rationale** | `jobcut-score` only | a note |

`scores.match_reasons` is the *scoring rationale* (why the score is what it is), owned
only by the scorer. A note stashed there won't appear in "Notes & activity" and
corrupts the score's explanation. When the user reports something that happened, it's
a note (or status / field / round) → `jobcut-track`.

The full skill map and the CLI-as-database contract are in
[`integrations/cowork/README.md`](integrations/cowork/README.md).
