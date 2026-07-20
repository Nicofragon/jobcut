"""claude_score.py — score new jobs by invoking a local, headless Claude Code.

The OS scheduler runs ``jobcut daily``, which pulls + surfaces but (with the
``claude_skills`` backend) leaves the new jobs **unscored on purpose** — Claude
is the scoring engine, not the pipeline (see ``score.run`` / ``score.py``). This
module closes that loop for an *unattended* run: it shells out to the local
``claude`` CLI in print mode, pointed at the data dir, and asks it to run the
``jobcut-score`` skill over the jobs that still need a score.

Runs **locally**, where jobcut + the database + the user's Claude auth already
live — so there is no cloud sandbox and no environment to rebuild.

Scoped by design: the headless agent is only granted the tools scoring needs
(the ``jobcut`` CLI, file read/write, the Skill loader) — never a blanket
permission bypass. See :data:`ALLOWED_TOOLS`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from . import paths

# Tools the unattended scorer may use — nothing else. Bash is scoped to the
# jobcut CLI (plus mkdir for the scratch dir); Read/Write cover profile.md and
# the temp scores file the skill writes; Skill lets it load jobcut-score.
# Deliberately NOT a permission bypass — an unattended daily job should never
# have free rein over the machine.
ALLOWED_TOOLS = ["Bash(jobcut:*)", "Bash(mkdir:*)", "Read", "Write", "Skill"]

_PROMPT = (
    "Score the jobcut jobs that don't have a score yet. Use the jobcut-score "
    "skill. The data dir is set via JOBCUT_DATA_DIR ({data}); run every read and "
    "write through the jobcut CLI only — never touch the database directly. If "
    "there are no unscored jobs, say so and stop."
)


def claude_bin() -> str | None:
    """Absolute path to the ``claude`` CLI, or ``None`` if it isn't on PATH."""
    return shutil.which("claude")


def build_command(data_dir: Path, claude: str, prompt: str | None = None) -> list[str]:
    """The argv for a scoped, headless scoring run (pure — no side effects).

    ``--allowedTools`` is variadic, so it comes last: nothing after it can be
    mistaken for a tool name.
    """
    return [
        claude,
        "-p", prompt or _PROMPT.format(data=data_dir),
        "--permission-mode", "default",
        "--add-dir", str(data_dir),
        "--allowedTools", *ALLOWED_TOOLS,
    ]


def run(data_dir: Path | str | None = None, timeout: int = 1800) -> int:
    """Run the headless scorer over the unscored jobs.

    Returns the ``claude`` exit code, ``127`` if the CLI isn't installed, or
    ``124`` on timeout. Never raises — a scheduled ``daily`` shouldn't crash just
    because scoring couldn't run; the pull + surface already succeeded.
    """
    data = Path(data_dir) if data_dir else paths.data_dir()
    claude = claude_bin()
    if not claude:
        print("daily · claude scoring skipped — `claude` CLI not found on PATH")
        return 127
    (data / "tmp").mkdir(parents=True, exist_ok=True)  # scratch dir the skill uses
    cmd = build_command(data, claude)
    env = {**os.environ, "JOBCUT_DATA_DIR": str(data)}
    print("daily · scoring new jobs with Claude…")
    try:
        r = subprocess.run(cmd, cwd=str(data), env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"daily · claude scoring timed out after {timeout}s")
        return 124
    except OSError as exc:  # e.g. claude vanished between which() and exec
        print(f"daily · claude scoring couldn't start: {exc}")
        return 126
    print(f"daily · claude scoring finished (exit {r.returncode})")
    return r.returncode
