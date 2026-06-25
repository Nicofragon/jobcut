"""Pure-logic tests for the scheduler (no real launchd/cron side effects)."""

import os

import pytest

from jobcut import scheduler


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(tmp_path))
    yield tmp_path


def test_clean_bounds_and_defaults():
    c = scheduler._clean({"hour": 99, "minute": -3, "interval_days": 1, "frequency": "bogus", "enabled": 1})
    assert c["hour"] == 23 and c["minute"] == 0          # clamped
    assert c["interval_days"] == 2                        # min 2
    assert c["frequency"] == "daily"                      # invalid → daily
    assert c["enabled"] is True


def test_cron_line_daily_and_weekdays():
    daily = scheduler.build_cron_line({"frequency": "daily", "hour": 7, "minute": 30})
    assert daily.startswith("30 7 * * *  ")
    assert "jobcut daily" in daily and "JOBCUT_DATA_DIR=" in daily

    wd = scheduler.build_cron_line({"frequency": "weekdays", "hour": 8, "minute": 5})
    assert wd.startswith("5 8 * * 1-5  ")


def test_cron_line_every_n_passes_flag():
    line = scheduler.build_cron_line({"frequency": "every_n", "interval_days": 3, "hour": 9, "minute": 0})
    assert line.startswith("0 9 * * *  ")            # OS timer stays daily
    assert "daily --every 3" in line                 # interval enforced by the command


def test_plist_has_calendar_and_env():
    p = scheduler.build_plist({"frequency": "daily", "hour": 6, "minute": 15})
    assert "<key>Label</key><string>com.jobcut.daily</string>" in p
    assert "<key>Hour</key><integer>6</integer>" in p and "<key>Minute</key><integer>15</integer>" in p
    assert "JOBCUT_DATA_DIR" in p
    assert "<string>daily</string>" in p              # ProgramArguments includes the subcommand


def test_plist_weekdays_emits_five_days():
    p = scheduler.build_plist({"frequency": "weekdays", "hour": 7, "minute": 0})
    assert p.count("<key>Weekday</key>") == 5         # Mon–Fri


def test_get_reports_platform_and_capability():
    s = scheduler.get()
    assert s["platform"] in ("macos", "linux", "windows", "other")
    assert isinstance(s["supported"], bool)
    assert s["enabled"] is False                      # nothing persisted yet
    assert "jobcut" in s["command"] and "daily" in s["command"]


def test_set_schedule_unsupported_os_raises(monkeypatch):
    monkeypatch.setattr(scheduler, "_system", lambda: "windows")
    with pytest.raises(RuntimeError):
        scheduler.set_schedule({"enabled": True})
    assert scheduler.get()["supported"] is False
    assert "JOBCUT_DATA_DIR" in os.environ            # fixture sanity
