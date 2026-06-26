#!/usr/bin/env bash
#
# One-command setup for jobcut.
#
#   git clone git@github.com:Nicofragon/jobcut.git
#   cd jobcut
#   ./setup.sh
#
# Creates an isolated environment (you never have to think about it), installs
# jobcut and its dependencies, builds the web console if Node is available, and
# scaffolds your data files. Safe to re-run — it never overwrites your edits.
#
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\n\033[1;33m!\033[0m  %s\n' "$*"; }

# 1) Python 3.11+
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.11+ is required but 'python3' was not found. Install it from https://python.org"
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Python 3.11+ is required (found $(python3 -V))."
  exit 1
fi

# 2) Isolated environment (kept invisible — required on modern macOS/PEP 668)
if [ ! -d .venv ]; then
  say "Creating the local environment (.venv)…"
  python3 -m venv .venv
fi

say "Installing jobcut and its dependencies…"
./.venv/bin/python -m pip install --upgrade pip -q
# api = web console · cv = read PDF/DOCX CVs · llm = optional AI scoring/CV auto-fill
./.venv/bin/python -m pip install -e '.[api,cv,llm]' -q

# 3) Web console — build automatically if Node is present (the CLI works without it)
if command -v npm >/dev/null 2>&1; then
  say "Building the web console…"
  ( cd web && npm install && npm run build )
else
  warn "Node/npm not found — installed the CLI only. Install Node 20.9+ to use the web console."
fi

# 4) Prepare the data folder (idempotent; the web wizard can also create these)
say "Preparing your data folder…"
./.venv/bin/jobcut init --no-input >/dev/null

# 5) Make the ./jobcut launcher runnable (lets you skip activating the venv)
chmod +x jobcut 2>/dev/null || true

cat <<'EOF'

==========================================================================
  Setup complete.

  Everything else happens in the app — no files to edit by hand. The console
  opens a guided wizard where you:
    1. paste your Apify token   (console.apify.com -> Settings -> API)
    2. add your profile         (roles, skills, dealbreakers)
    3. set up your searches     (job titles + location)
    4. run your first scrape    ("Find new jobs")

  Start it any time with:   ./jobcut serve --open
==========================================================================

EOF

# 6) If we're in an interactive terminal, open the guided wizard right away.
if [ -t 1 ]; then
  say "Opening the setup wizard in your browser… (Ctrl+C to stop; restart with ./jobcut serve --open)"
  exec ./jobcut serve --open
fi
