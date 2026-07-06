"""`jobcut shortcut` generates an OS-appropriate double-click launcher."""

import os

import pytest

from jobcut import config
from jobcut.cli import cmd_shortcut, main


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(data))
    config.reset_cache()
    yield data
    config.reset_cache()


def test_macos_app(tmp_path, monkeypatch, _isolated):
    monkeypatch.setattr("jobcut.cli.sys.platform", "darwin")
    out = tmp_path / "out"
    out.mkdir()
    rc = main(["shortcut", "--path", str(out), "--port", "8000"])
    assert rc == 0
    app = out / "jobcut.app"
    assert app.is_dir()
    exe = app / "Contents" / "MacOS" / "jobcut"
    assert exe.exists()
    assert os.access(exe, os.X_OK)
    body = exe.read_text()
    assert str(_isolated.resolve()) in body
    assert "--port 8000" in body
    # delegates reuse-or-replace to `serve --launcher` (no fragile curl guard of its own)
    assert "serve --open --launcher" in body
    # the bundle carries its Info.plist and the shipped brand icon
    assert (app / "Contents" / "Info.plist").exists()
    assert (app / "Contents" / "Resources" / "jobcut.icns").exists()
    # re-running overwrites without error (idempotent)
    assert main(["shortcut", "--path", str(out), "--port", "8000"]) == 0
    assert app.is_dir()


def test_linux_desktop(tmp_path, monkeypatch, _isolated):
    monkeypatch.setattr("jobcut.cli.sys.platform", "linux")
    out = tmp_path / "out"
    out.mkdir()
    assert main(["shortcut", "--path", str(out)]) == 0
    launcher = out / "jobcut.desktop"
    assert launcher.exists()
    body = launcher.read_text()
    assert "[Desktop Entry]" in body
    assert "serve --open --launcher" in body
    # a real icon and no terminal window (the point of this change)
    assert "jobcut.png" in body
    assert "Terminal=false" in body


def test_windows_bat(tmp_path, monkeypatch, _isolated):
    monkeypatch.setattr("jobcut.cli.sys.platform", "win32")
    out = tmp_path / "out"
    out.mkdir()
    assert main(["shortcut", "--path", str(out)]) == 0
    assert (out / "jobcut.bat").exists()


def test_explicit_file_path_is_honored(tmp_path, monkeypatch, _isolated):
    monkeypatch.setattr("jobcut.cli.sys.platform", "darwin")
    target = tmp_path / "nested" / "my-launcher.app"
    assert main(["shortcut", "--path", str(target), "--port", "9001"]) == 0
    assert target.is_dir()
    assert "--port 9001" in (target / "Contents" / "MacOS" / "jobcut").read_text()


def test_missing_venv_jobcut_errors(tmp_path, monkeypatch, capsys, _isolated):
    # point sys.executable at a tmp dir with no `jobcut` next to it
    fake_python = tmp_path / "bin" / "python"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text("")
    monkeypatch.setattr("jobcut.cli.sys.executable", str(fake_python))
    monkeypatch.setattr("jobcut.cli.sys.platform", "darwin")

    class _NS:
        path = str(tmp_path / "out")
        port = 8000

    rc = cmd_shortcut(_NS())
    assert rc == 1
    assert "Couldn't find the jobcut command" in capsys.readouterr().out
