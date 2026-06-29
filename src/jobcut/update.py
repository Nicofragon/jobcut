"""Update jobcut in place: `git pull` + rebuild the console (B-20).

Runs LOCALLY, where `jobcut serve` already runs — the user's install has git, SSH
and Node, so the same machine that serves the console can update it. Both the web
"Update from repo" button (`POST /api/update`, localhost-only) and the `jobcut update`
CLI call `run_update()`, so there's one code path.

Non-destructive by design — and git itself is the guard. A fast-forward pull never
overwrites **untracked** files (DB backups, local notes), and it **aborts** rather than
clobber uncommitted changes to **tracked** files. So we don't pre-block on a dirty tree
(that produced false "paused" on harmless local artifacts); we attempt the pull and only
report a problem when git actually refuses — surfacing exactly which files are in the way.

This mirrors what the `jobcut-update` skill does by hand (pull → reinstall-if-needed →
rebuild), and is read-only on the database — it never scrapes, scores, or deletes data.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import jobcut


def repo_root() -> Path:
    """The install's git checkout root (where `web/`, `.git/`, `pyproject.toml` live).

    The package lives at `<root>/src/jobcut/__init__.py`, so the root is two parents up
    from the package directory.
    """
    return Path(jobcut.__file__).resolve().parents[2]


def _git(root: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    # GIT_TERMINAL_PROMPT=0 makes git fail fast instead of hanging on a credential/host
    # prompt when run from a non-interactive endpoint.
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True, text=True,
        timeout=timeout, env=env,
    )


def _tracked_changes(root: Path) -> list[str]:
    """Modified/staged/deleted **tracked** files (informational).

    Untracked files (`??`) are excluded on purpose: a fast-forward pull never touches
    them, so they are not a reason to warn. Reported only so the UI can show an honest
    "local changes" hint — they do NOT block the update.
    """
    r = _git(root, "status", "--porcelain")
    out: list[str] = []
    for line in r.stdout.splitlines():
        if not line.strip() or line[:2] == "??":   # blank or untracked → ignore
            continue
        path = line[3:].strip()
        if " -> " in path:                          # rename: keep the destination path
            path = path.split(" -> ", 1)[1]
        out.append(path)
    return out


def preflight(root: Path | None = None) -> dict:
    """Inspect the checkout without changing anything: is it git, which branch/sha, clean?"""
    root = root or repo_root()
    if not (root / ".git").exists() or _git(root, "rev-parse", "--git-dir").returncode != 0:
        return {"is_git": False, "root": str(root), "clean": True, "dirty_files": [],
                "branch": None, "sha": None}
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    sha = _git(root, "rev-parse", "--short", "HEAD").stdout.strip()
    tracked = _tracked_changes(root)
    return {"is_git": True, "root": str(root), "branch": branch, "sha": sha,
            "clean": not tracked, "dirty_files": tracked}


def _rebuild_web(root: Path) -> bool:
    """Rebuild the static console so the pulled web source is what gets served.

    The API serves `web/out` statically, so rebuilding in place means the next page
    load gets the new assets — no server restart needed. Best-effort: returns False if
    Node is missing or the build fails (the API keeps serving the prior build)."""
    web = root / "web"
    if not (web / "package.json").exists():
        return False
    npm = shutil.which("npm")
    if not npm:
        return False
    try:
        if not (web / "node_modules").exists():
            subprocess.run([npm, "install"], cwd=str(web), check=True, timeout=600)
        subprocess.run([npm, "run", "build"], cwd=str(web), check=True, timeout=600)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False


def _interpret_pull_failure(p: subprocess.CompletedProcess) -> tuple[str, list[str], bool]:
    """Turn a failed `git pull` into (message, files, blocked).

    `blocked` means the pull was refused to protect local work (git aborted, nothing
    changed) — the user just needs to deal with the listed files. Other failures (no
    upstream, diverged history) aren't "blocked"; they need a terminal.
    """
    text = (p.stderr or p.stdout or "").strip()
    files: list[str] = []
    capturing = False
    for line in text.splitlines():
        if "would be overwritten by merge" in line:   # local-changes OR untracked variant
            capturing = True
            continue
        if capturing:
            if line.startswith(("\t", "    ")) and line.strip():
                files.append(line.strip())
            elif line.strip():
                capturing = False
    if files:
        return ("Update paused so nothing gets overwritten — these files have local "
                "changes. Commit, stash, or discard them, then try again.", files, True)
    low = text.lower()
    if "no tracking information" in low or "no upstream" in low:
        return ("This branch isn't tracking a remote, so there's nothing to pull — "
                "set an upstream from a terminal, then try again.", [], False)
    if "not possible to fast-forward" in low or "diverging" in low or "divergent" in low:
        return ("Local and remote history have diverged, so a fast-forward isn't possible. "
                "Sort it out from a terminal (git status / git pull), then try again.", [], False)
    last = text.splitlines()[-1] if text else "git command failed"
    return (f"Couldn't pull: {last}", [], False)


def run_update(root: Path | None = None, rebuild: bool = True) -> dict:
    """Pull the latest code and rebuild the console. Returns a structured result.

    Steps: preflight → `git pull --ff-only` (git is the non-destructive guard) → rebuild
    if the sha moved. Untracked files never block; tracked conflicts are surfaced by git
    and reported, not overwritten. Never touches the database.
    """
    root = root or repo_root()
    pf = preflight(root)
    if not pf["is_git"]:
        return {"ok": False, "step": "preflight", "blocked": False,
                "message": "This install isn't a git checkout — nothing to update from.",
                **pf}

    from_sha = pf["sha"]
    pull = _git(root, "pull", "--ff-only", timeout=180)
    if pull.returncode != 0:
        message, files, blocked = _interpret_pull_failure(pull)
        return {"ok": False, "step": "pull", "blocked": blocked, "from_sha": from_sha,
                **pf, "message": message, "dirty_files": files}

    to_sha = _git(root, "rev-parse", "--short", "HEAD").stdout.strip()
    updated = to_sha != from_sha
    result = {"ok": True, "step": "done", "blocked": False, "branch": pf["branch"],
              "root": str(root), "from_sha": from_sha, "to_sha": to_sha, "updated": updated}
    if not updated:
        result["rebuilt"] = False
        result["message"] = f"Already up to date ({to_sha})."
        return result

    result["rebuilt"] = _rebuild_web(root) if rebuild else False
    tail = (" Rebuilt the console — hard-refresh your browser to see the new version."
            if result["rebuilt"]
            else " Restart `jobcut serve` to rebuild the console.")
    result["message"] = f"Updated {from_sha} → {to_sha}.{tail}"
    return result
