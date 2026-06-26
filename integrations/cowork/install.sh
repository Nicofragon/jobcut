#!/usr/bin/env bash
# Install the jobcut Cowork / Claude Code skills.
#
# Two modes:
#
#   COPY (Claude Code) — copies every skill folder under skills/ into your Claude
#   skills directory, then verifies each one landed (folder + its SKILL.md):
#       bash integrations/cowork/install.sh                # -> ~/.claude/skills
#       bash integrations/cowork/install.sh /path/to/dir   # -> that directory
#       JOBCUT_SKILLS_DIR=/path/to/dir bash integrations/cowork/install.sh
#
#   ZIP (Cowork desktop) — builds one <skill>.zip per skill so you can upload them
#   through the Cowork UI (Personalizar → Subir habilidad), which takes one skill
#   per file:
#       bash integrations/cowork/install.sh --zip                 # -> ./jobcut-skill-zips
#       bash integrations/cowork/install.sh --zip /path/to/outdir
#
# IMPORTANT — which directory / mode?
#   Claude Code reads ~/.claude/skills/ → use COPY mode (the default).
#   Claude Cowork (desktop) does NOT read a skills folder; it imports skills through
#   its UI. Its uploader takes one skill at a time, so use ZIP mode and upload each
#   <skill>.zip via Personalizar → Subir habilidad (start with jobcut.zip). After
#   importing, the skills show up under Personalizar — no reload needed.
set -euo pipefail

# Resolve the skills source relative to this script, so it works from any CWD.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/skills"

if [ ! -d "$SRC" ]; then
  echo "error: skills source not found at $SRC" >&2
  exit 1
fi

# ---- ZIP mode (for Cowork upload) -----------------------------------------
if [ "${1:-}" = "--zip" ]; then
  OUT="${2:-$PWD/jobcut-skill-zips}"
  mkdir -p "$OUT"
  OUT="$(cd "$OUT" && pwd)"   # absolutise (we cd into each skill below)
  echo "Building one zip per jobcut skill"
  echo "  from: $SRC"
  echo "  to:   $OUT"
  echo
  built=0
  for skill in "$SRC"/*/; do
    name="$(basename "$skill")"
    rm -f "$OUT/$name.zip"
    # Root the zip at the skill's contents (SKILL.md + any support files at the
    # top level), excluding dotfiles like .DS_Store. Cowork requires a SKILL.md.
    ( cd "$skill" && zip -qr "$OUT/$name.zip" . -x '.*' )
    echo "  ✓ $name.zip"
    built=$((built + 1))
  done
  echo
  echo "Built $built zip(s) in $OUT."
  echo "Upload each one in Cowork → Personalizar → Subir habilidad (start with"
  echo "jobcut.zip — it's the front door). Cowork takes one skill per file."
  exit 0
fi

# ---- COPY mode (for Claude Code) ------------------------------------------
# Target: positional arg > $JOBCUT_SKILLS_DIR > ~/.claude/skills.
DEST="${1:-${JOBCUT_SKILLS_DIR:-$HOME/.claude/skills}}"

mkdir -p "$DEST"
echo "Installing jobcut skills"
echo "  from: $SRC"
echo "  to:   $DEST"
echo

installed=0
failed=0
for skill in "$SRC"/*/; do
  name="$(basename "$skill")"
  # Copy the whole folder (SKILL.md must stay inside it).
  rm -rf "$DEST/$name"
  cp -R "$skill" "$DEST/$name"
  if [ -f "$DEST/$name/SKILL.md" ]; then
    echo "  ✓ $name"
    installed=$((installed + 1))
  else
    echo "  ✗ $name  (SKILL.md missing after copy)" >&2
    failed=$((failed + 1))
  fi
done

echo
echo "Installed $installed skill(s) into $DEST."
if [ "$failed" -ne 0 ]; then
  echo "$failed skill(s) failed to copy correctly." >&2
  exit 1
fi
echo "Now RELOAD Claude (Code or Cowork) so it picks up the new skills,"
echo "then ask Claude to run the 'jobcut' skill to confirm it's ready."
