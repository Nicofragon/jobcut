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

# 1) Python 3.10+
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.10+ is required but 'python3' was not found. Install it from https://python.org"
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "Python 3.10+ is required (found $(python3 -V))."
  exit 1
fi

# 2) Isolated environment (kept invisible — required on modern macOS/PEP 668)
if [ ! -d .venv ]; then
  say "Creating the local environment (.venv)…"
  python3 -m venv .venv
fi

say "Installing jobcut and its dependencies…"
./.venv/bin/python -m pip install --upgrade pip -q
./.venv/bin/python -m pip install -e '.[api]' -q

# 3) Web console — build automatically if Node is present (the CLI works without it)
if command -v npm >/dev/null 2>&1; then
  say "Building the web console…"
  ( cd web && npm install && npm run build )
else
  warn "Node/npm not found — installed the CLI only. Install Node 20.9+ to use the web console."
fi

# 4) Scaffold your data files in this folder (idempotent — keeps your edits)
say "Setting up your data files…"
./.venv/bin/jobcut init --no-input

# 5) Make the ./jobcut launcher runnable (lets you skip activating the venv)
chmod +x jobcut 2>/dev/null || true

cat <<'EOF'

==========================================================================
  Setup complete.

  Next, edit these files (just created in this folder):
    .env            add your APIFY_TOKEN   (console.apify.com -> Settings -> API)
    profile.md      your roles, skills, dealbreakers  (drives the scoring)
    searches/*.json your job titles + LinkedIn geoIds  (copy an example-*.json)

  Then run your first scrape and watch jobs populate:
    ./jobcut pull               first real scrape (~$0.04-0.18 via Apify)
    ./jobcut score && ./jobcut surface
    ./jobcut serve --open       or open the local web console
==========================================================================

EOF
