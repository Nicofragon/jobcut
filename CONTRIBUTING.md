# Contributing to jobcut

Thanks for your interest. jobcut is a local-first job-search tracker; contributions of
all sizes are welcome.

## Ground rules

**Never commit personal or environment-specific data.** jobcut is meant to work end-to-end
for anyone, out of the box. Do not commit:

- Real or test **data** — job rows, applications, a `jobcut.db`, exported CSV/XLSX, or
  scraped results.
- **Secrets** — `.env`, API tokens (Apify/OpenAI/Anthropic), credentials.
- **Absolute machine paths** (`/Users/...`, `C:\Users\...`) or personal emails.

A tracked pre-commit hook (`.githooks/pre-commit`, installed by `./setup.sh`) blocks the
highest-risk of these — real API tokens, absolute home paths, and private keys — from
being committed. If it fires, fix the staged content; don't bypass it with `--no-verify`.

## Workflow

`main` is kept green by branches + CI. Every change ships through a short-lived branch and
a CI-gated pull request — no direct pushes to `main`.

1. **Branch** off `main`: `feat/<slug>` for a feature, `fix/<slug>` for a bugfix.
2. **Implement** in small, clear commits (TDD where there are tests).
3. **Keep it green locally** (see below), then **push and open a PR**. CI runs automatically.
4. **Merge only when CI is green** — squash-merge, then delete the branch.

## Local setup

```bash
git clone https://github.com/Nicofragon/jobcut.git
cd jobcut
./setup.sh          # creates .venv, installs jobcut[api,cv,llm], builds the console, installs hooks
```

## Verification (run before opening a PR)

Backend:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check src/ tests/
```

Web console (for any change under `web/`):

```bash
cd web && npm run build && npm run lint
```

CI (`.github/workflows/ci.yml`) runs the same checks on Python 3.11 and 3.12, plus the web
lint + build, on every PR.

## Reporting bugs and requesting features

Open a [GitHub issue](https://github.com/Nicofragon/jobcut/issues). For **security**
vulnerabilities, do **not** open a public issue — see [SECURITY.md](SECURITY.md).
