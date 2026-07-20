"""Tests for claude_score — the local headless-Claude scoring step (no real claude run)."""

from pathlib import Path

from jobcut import claude_score


def test_build_command_is_scoped_and_headless():
    cmd = claude_score.build_command(Path("/data/dir"), "/usr/bin/claude")
    assert cmd[0] == "/usr/bin/claude"
    assert "-p" in cmd                                    # print / headless mode
    assert "--add-dir" in cmd and "/data/dir" in cmd
    # Scoped, not a blanket bypass — this runs unattended.
    assert "--dangerously-skip-permissions" not in cmd
    assert "--allow-dangerously-skip-permissions" not in cmd
    assert "bypassPermissions" not in cmd
    assert "--allowedTools" in cmd
    # allowedTools is variadic and must come last (nothing mistaken for a tool).
    assert cmd[-len(claude_score.ALLOWED_TOOLS) :] == claude_score.ALLOWED_TOOLS


def test_allowed_tools_grant_only_scoring_surface():
    tools = claude_score.ALLOWED_TOOLS
    assert any(t.startswith("Bash(jobcut:") for t in tools)  # the CLI is the write path
    assert "Skill" in tools                                   # loads jobcut-score
    # No unscoped Bash — an unattended job shouldn't run arbitrary shell.
    assert "Bash" not in tools


def test_prompt_carries_the_data_dir():
    cmd = claude_score.build_command(Path("/some/data"), "claude")
    prompt = cmd[cmd.index("-p") + 1]
    assert "/some/data" in prompt
    assert "jobcut-score" in prompt


def test_run_skips_cleanly_when_claude_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(claude_score, "claude_bin", lambda: None)
    rc = claude_score.run(data_dir=tmp_path)
    assert rc == 127
    assert "claude" in capsys.readouterr().out.lower()


def test_run_invokes_subprocess_with_env_and_cwd(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_score, "claude_bin", lambda: "/bin/claude")
    seen = {}

    class _Result:
        returncode = 0

    def _fake_run(cmd, cwd, env, timeout):
        seen["cmd"], seen["cwd"], seen["env"], seen["timeout"] = cmd, cwd, env, timeout
        return _Result()

    monkeypatch.setattr(claude_score.subprocess, "run", _fake_run)
    rc = claude_score.run(data_dir=tmp_path, timeout=42)
    assert rc == 0
    assert seen["cwd"] == str(tmp_path)
    assert seen["env"]["JOBCUT_DATA_DIR"] == str(tmp_path)
    assert seen["timeout"] == 42
    assert (tmp_path / "tmp").is_dir()                    # scratch dir pre-created
