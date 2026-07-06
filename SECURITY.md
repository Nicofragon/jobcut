# Security policy

## Reporting a vulnerability

Please **do not** report security issues through public GitHub issues.

Instead, use GitHub's private vulnerability reporting:
[**Report a vulnerability**](https://github.com/Nicofragon/jobcut/security/advisories/new).
We'll acknowledge your report and work with you on a fix and disclosure timeline.

## Scope and threat model

jobcut is **local-first**: it runs on your own machine and stores everything in a local
SQLite database (`jobcut.db`) under your data directory. The web console binds to
`127.0.0.1` and is not exposed to the network.

Handled sensitive material:

- **`APIFY_TOKEN`** (and optional `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`) — read from a
  git-ignored `.env`, never committed. The update/serve endpoints that could touch the host
  are bound to localhost only.
- **Your profile and application data** — stored locally, never uploaded. The only outbound
  network call is to the configured Apify actor when you run a scrape (and to the LLM
  provider if you opt into AI scoring).

Things especially worth reporting:

- Any way a token, `.env`, or local data could be exfiltrated or logged.
- Any endpoint reachable beyond localhost, or a path that lets a web request run arbitrary
  host commands.
- Any code path that writes secrets or absolute personal paths into the repo or into logs.

## Supported versions

jobcut is pre-1.0 and ships from `main`. Fixes land on `main`; please test against the
latest commit before reporting.
