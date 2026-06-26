#!/usr/bin/env bash
# Install the jobcut Cowork / Claude Code skills.
#
# Copies every skill folder under integrations/cowork/skills/ into your Claude
# skills directory, then verifies each one landed (folder + its SKILL.md).
#
# Usage:
#   bash integrations/cowork/install.sh                # -> ~/.claude/skills
#   bash integrations/cowork/install.sh /path/to/dir   # -> that directory
#   JOBCUT_SKILLS_DIR=/path/to/dir bash integrations/cowork/install.sh
#
# IMPORTANT — which directory?
#   Claude Code reads ~/.claude/skills/ (the default below).
#   Claude Cowork reads ITS OWN skills directory — often your notes/vault's
#   .claude/skills/, NOT the home one. If you use Cowork, pass that directory so the
#   skills are visible there; installing only into ~/.claude/skills makes them
#   visible to Claude Code but invisible to Cowork. After installing, RELOAD the app.
set -euo pipefail

# Resolve the skills source relative to this script, so it works from any CWD.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/skills"

# Target: positional arg > $JOBCUT_SKILLS_DIR > ~/.claude/skills.
DEST="${1:-${JOBCUT_SKILLS_DIR:-$HOME/.claude/skills}}"

if [ ! -d "$SRC" ]; then
  echo "error: skills source not found at $SRC" >&2
  exit 1
fi

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
