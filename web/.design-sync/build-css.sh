#!/usr/bin/env bash
# design-sync CSS build: compile the app's Tailwind v4 stylesheet to a static
# CSS the converter can ship (cfg.cssEntry), then define --font-inter (next/font
# sets it at runtime; undefined in a standalone render). Reproducible: version
# tracks the installed tailwindcss. Run by cfg.buildCmd before the converter.
set -euo pipefail
cd "$(dirname "$0")/.."   # -> web/
ver=$(node -p "require('./node_modules/tailwindcss/package.json').version")
npx --yes "@tailwindcss/cli@${ver}" -i app/globals.css -o .design-sync/compiled.css
# --font-inter (set by next/font at runtime) + its metric-adjusted local fallback
# face, so a standalone render matches the app and no family is left dangling.
cat >> .design-sync/compiled.css <<'CSS'

:root{--font-inter:"Inter","Inter Fallback"}
@font-face{font-family:"Inter Fallback";src:local("Arial");ascent-override:90.44%;descent-override:22.52%;line-gap-override:0.0%;size-adjust:107.12%}
CSS
echo "design-sync: compiled.css written (tailwindcss ${ver}) + --font-inter + fallback face"
