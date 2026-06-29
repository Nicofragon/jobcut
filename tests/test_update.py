"""B-20: update-from-repo core (git pull + rebuild) and the API wiring.

Uses a throwaway git repo with a LOCAL "remote" (a file path) so `git pull --ff-only`
works with no network. `_rebuild_web` is skipped via rebuild=False — npm isn't needed
to exercise the git logic.
"""
import subprocess

import pytest
from fastapi.testclient import TestClient

from jobcut import update
from jobcut.api import create_app


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True)


def _commit(repo, name, body="x"):
    (repo / name).write_text(body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", f"add {name}")


@pytest.fixture()
def clone(tmp_path):
    """An `origin` repo (one commit) and a `work` clone tracking it."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    _git(origin, "config", "user.email", "t@t.t")
    _git(origin, "config", "user.name", "t")
    _commit(origin, "README.md", "v1")

    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    _git(work, "config", "user.email", "t@t.t")
    _git(work, "config", "user.name", "t")
    return origin, work


def test_preflight_non_git(tmp_path):
    pf = update.preflight(tmp_path)
    assert pf["is_git"] is False and pf["clean"] is True


def test_run_update_non_git_is_noop(tmp_path):
    res = update.run_update(tmp_path, rebuild=False)
    assert res["ok"] is False and res["blocked"] is False
    assert "isn't a git checkout" in res["message"]


def test_clean_tree_already_up_to_date(clone):
    _origin, work = clone
    res = update.run_update(work, rebuild=False)
    assert res["ok"] is True and res["updated"] is False
    assert "up to date" in res["message"].lower()


def test_pull_advances_to_remote_head(clone):
    origin, work = clone
    before = update.preflight(work)["sha"]
    _commit(origin, "NEW.md", "v2")  # remote moves ahead
    res = update.run_update(work, rebuild=False)
    assert res["ok"] is True and res["updated"] is True
    assert res["from_sha"] == before and res["to_sha"] != before
    assert (work / "NEW.md").exists()


def test_conflicting_tracked_change_blocks_non_destructively(clone):
    # Local edit to a file that ALSO changed upstream → git refuses the ff and aborts.
    # We surface it as blocked, and nothing is overwritten (git is the guard).
    origin, work = clone
    (origin / "README.md").write_text("upstream v2")
    _git(origin, "add", "-A")
    _git(origin, "commit", "-m", "touch README upstream")
    (work / "README.md").write_text("local edit, keep me")  # conflicts with the incoming change
    res = update.run_update(work, rebuild=False)
    assert res["ok"] is False and res["blocked"] is True
    assert "README.md" in res["dirty_files"]
    assert (work / "README.md").read_text() == "local edit, keep me"  # untouched


def test_untracked_files_never_block(clone):
    # DB backups, local scratch dirs, etc. are untracked — a ff pull doesn't touch them,
    # so they must neither flag the tree dirty nor block the update.
    origin, work = clone
    (work / "jobcut.db.bak-20260625-183746").write_text("backup")
    (work / ".superpowers").mkdir()
    (work / ".superpowers" / "x").write_text("scratch")
    assert update.preflight(work)["clean"] is True            # untracked → still clean
    _commit(origin, "NEW.md", "v2")                            # remote moves ahead
    res = update.run_update(work, rebuild=False)
    assert res["ok"] is True and res["updated"] is True        # pulled past the junk
    assert (work / "jobcut.db.bak-20260625-183746").exists()  # untracked file preserved


def test_local_tracked_edit_preserved_when_not_upstream(clone):
    # A tracked file edited locally, NOT changed upstream → ff pull succeeds and keeps the edit.
    origin, work = clone
    (work / "README.md").write_text("my local notes")
    _commit(origin, "NEW.md", "v2")  # upstream changes a DIFFERENT file
    res = update.run_update(work, rebuild=False)
    assert res["ok"] is True and res["updated"] is True
    assert (work / "README.md").read_text() == "my local notes"  # edit preserved
    assert (work / "NEW.md").exists()


def test_update_router_wiring(monkeypatch):
    # Don't run real git in the API test — assert the endpoints return the module's result.
    monkeypatch.setattr(update, "preflight", lambda root=None: {"is_git": True, "sha": "abc1234", "clean": True})
    monkeypatch.setattr(update, "run_update", lambda root=None, rebuild=True: {"ok": True, "message": "done", "updated": False})
    client = TestClient(create_app(serve_web=False))
    assert client.get("/api/update").json()["sha"] == "abc1234"
    assert client.post("/api/update").json() == {"ok": True, "message": "done", "updated": False}
