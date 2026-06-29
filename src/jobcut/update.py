"""Update jobcut in place: `git pull` + rebuild the console (B-20).

Runs LOCALLY, where `jobcut serve` already runs — the user's install has git, SSH
and Node, so the same machine that serves the console can update it. Both the web
"Update from repo" button (`POST /api/update`, localhost-only) and the `jobcut update`
CLI call `run_update()`, so there's one code path.

Non-destructive by design: a dirty working tree **pauses** the pull with a clear
report instead of discarding the user's work. Filesystem/editor noise that is not a
real change (`.fuse_hidden*` from the iCloud/FUSE mount, `.DS_Store`, editor backups)
is ignored so it can't block a legitimate update.

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


def _is_noise(path: str) -> bool:
    """True for working-tree entries that are not a real change (so they don't block)."""
    name = path.rsplit("/", 1)[-1]
    return (
        name.startswith(".fuse_hidden")   # iCloud/FUSE mount leaves these behind
        or name == ".DS_Store"
        or name.endswith("~")             # editor backups
    )


def _dirty_files(root: Path) -> list[str]:
    """Tracked/untracked changes that should block an update, FS noise filtered out."""
    r = _git(root, "status", "--porcelain")
    out: list[str] = []
    for line in r.stdout.splitlines():
        # porcelain v1: 'XY <path>' (status code is the first two chars). Renames read
        # as 'old -> new'; the new path is what matters for the noise check.
        path = line[3:].strip() if len(line) > 3 else line.strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path and not _is_noise(path):
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
    dirty = _dirty_files(root)
    return {"is_git": True, "root": str(root), "branch": branch, "sha": sha,
            "clean": not dirty, "dirty_files": dirty}


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


def _git_error(p: subprocess.CompletedProcess) -> str:
    """A short, user-facing line from a failed git command (stderr, last line)."""
    text = (p.stderr or p.stdout or "").strip()
    return text.splitlines()[-1] if text else "git command failed"


def run_update(root: Path | None = None, rebuild: bool = True) -> dict:
    """Pull the latest code and rebuild the console. Returns a structured result.

    Steps: preflight → (block if dirty) → `git pull --ff-only` → rebuild if the sha
    moved. Never overwrites local changes; never touches the database.
    """
    root = root or repo_root()
    pf = preflight(root)
    if not pf["is_git"]:
        return {"ok": False, "step": "preflight", "blocked": False,
                "message": "This install isn't a git checkout — nothing to update from.",
                **pf}
    if not pf["clean"]:
        return {"ok": False, "step": "dirty", "blocked": True,
                "message": "You have local changes — the update is paused so nothing gets "
                           "overwritten. Commit, stash, or discard them, then try again.",
                **pf}

    from_sha = pf["sha"]
    pull = _git(root, "pull", "--ff-only", timeout=180)
    if pull.returncode != 0:
        return {"ok": False, "step": "pull", "blocked": False, "from_sha": from_sha,
                "message": f"Couldn't pull: {_git_error(pull)}", **pf}

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
