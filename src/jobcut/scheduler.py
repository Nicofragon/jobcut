"""scheduler.py — install/remove an OS scheduler that runs ``jobcut daily``.

jobcut is a local tool, so the API process runs as the user and can install a
**launchd** agent (macOS) or a **crontab** entry (Linux) and (un)load it — no
manual ``crontab``/``launchctl`` needed. Windows is not installed from the console
yet (the UI shows Task Scheduler instructions instead).

The chosen schedule is persisted to ``<data>/schedule.json`` so the console can show
the current state reliably (rather than parsing the plist/crontab back).

Frequency model:
- ``daily``    → every day at HH:MM
- ``weekdays`` → Mon–Fri at HH:MM
- ``every_n``  → the OS timer fires daily at HH:MM, but ``jobcut daily --every N``
                 no-ops unless N days have passed since the last pull.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from . import paths

LABEL = "com.jobcut.daily"
CRON_BEGIN = "# >>> jobcut daily >>>"
CRON_END = "# <<< jobcut daily <<<"

DEFAULT = {"enabled": False, "frequency": "daily", "interval_days": 2, "hour": 7, "minute": 30,
           "claude_score": False}
_FREQS = ("daily", "weekdays", "every_n")


def _system() -> str:
    return {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}.get(platform.system(), "other")


def supported() -> bool:
    """True if we can install the schedule from the console on this OS."""
    return _system() in ("macos", "linux")


def _jobcut_bin() -> str:
    """Absolute path to the jobcut CLI (it sits next to the python running the server)."""
    cand = Path(sys.executable).parent / "jobcut"
    return str(cand) if cand.exists() else (shutil.which("jobcut") or "jobcut")


def _config_path() -> Path:
    return paths.data_dir() / "schedule.json"


def _clean(cfg_in: dict) -> dict:
    cfg = dict(DEFAULT)
    cfg.update({k: cfg_in[k] for k in DEFAULT if k in cfg_in})
    cfg["enabled"] = bool(cfg["enabled"])
    cfg["frequency"] = cfg["frequency"] if cfg["frequency"] in _FREQS else "daily"
    cfg["hour"] = max(0, min(23, int(cfg["hour"])))
    cfg["minute"] = max(0, min(59, int(cfg["minute"])))
    cfg["interval_days"] = max(2, min(30, int(cfg["interval_days"])))
    cfg["claude_score"] = bool(cfg["claude_score"])
    return cfg


def _daily_args(cfg: dict) -> list[str]:
    args = [_jobcut_bin(), "daily"]
    if cfg["frequency"] == "every_n":
        args += ["--every", str(cfg["interval_days"])]
    if cfg.get("claude_score"):
        args += ["--claude-score"]
    return args


def _daily_command(cfg: dict) -> str:
    return " ".join(_daily_args(cfg))


# --- public API -------------------------------------------------------------

def get() -> dict:
    """Current schedule config + this machine's capability/state."""
    cfg = dict(DEFAULT)
    p = _config_path()
    if p.exists():
        try:
            cfg.update(_clean(json.loads(p.read_text())))
        except Exception:
            pass
    return {
        **{k: cfg[k] for k in DEFAULT},
        "platform": _system(),
        "supported": supported(),
        "installed": _is_installed(),
        "command": _daily_command(cfg),
    }


def set_schedule(cfg_in: dict) -> dict:
    """Install/update (enabled) or remove (disabled) the OS scheduler, and persist."""
    if not supported():
        raise RuntimeError(f"Scheduling from the console isn't supported on {_system()} yet.")
    cfg = _clean(cfg_in)
    if cfg["enabled"]:
        _install(cfg)
    else:
        _uninstall()
    _config_path().write_text(json.dumps({k: cfg[k] for k in DEFAULT}, indent=2))
    return get()


def clear() -> dict:
    """Remove the OS scheduler and the stored config."""
    if supported():
        _uninstall()
    p = _config_path()
    if p.exists():
        p.unlink()
    return get()


# --- dispatch ---------------------------------------------------------------

def _install(cfg: dict) -> None:
    {"macos": _install_macos, "linux": _install_linux}[_system()](cfg)


def _uninstall() -> None:
    {"macos": _uninstall_macos, "linux": _uninstall_linux}.get(_system(), lambda: None)()


def _is_installed() -> bool:
    if _system() == "macos":
        return _plist_path().exists()
    if _system() == "linux":
        return CRON_BEGIN in _read_crontab()
    return False


# --- macOS (launchd) --------------------------------------------------------

def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _cal_dict(hour: int, minute: int, weekday: int | None = None, indent: str = "        ") -> str:
    wd = f"<key>Weekday</key><integer>{weekday}</integer>" if weekday is not None else ""
    return f"{indent}<dict><key>Hour</key><integer>{hour}</integer><key>Minute</key><integer>{minute}</integer>{wd}</dict>"


def build_plist(cfg: dict) -> str:
    cfg = _clean(cfg)
    args = "\n".join(f"        <string>{a}</string>" for a in _daily_args(cfg))
    data = str(paths.data_dir())
    h, m = cfg["hour"], cfg["minute"]
    if cfg["frequency"] == "weekdays":
        cals = "\n".join(_cal_dict(h, m, wd) for wd in range(1, 6))  # 1=Mon … 5=Fri
        interval = f"    <key>StartCalendarInterval</key>\n    <array>\n{cals}\n    </array>"
    else:
        interval = "    <key>StartCalendarInterval</key>\n" + _cal_dict(h, m, indent="    ")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        f"    <key>Label</key><string>{LABEL}</string>\n"
        "    <key>ProgramArguments</key>\n    <array>\n"
        f"{args}\n    </array>\n"
        f"    <key>WorkingDirectory</key><string>{data}</string>\n"
        "    <key>EnvironmentVariables</key>\n"
        f"    <dict><key>JOBCUT_DATA_DIR</key><string>{data}</string></dict>\n"
        f"{interval}\n"
        f"    <key>StandardOutPath</key><string>{data}/jobcut.daily.log</string>\n"
        f"    <key>StandardErrorPath</key><string>{data}/jobcut.daily.log</string>\n"
        "    <key>RunAtLoad</key><false/>\n"
        "</dict>\n</plist>\n"
    )


def _install_macos(cfg: dict) -> None:
    p = _plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["launchctl", "unload", str(p)], capture_output=True)  # ignore if absent
    p.write_text(build_plist(cfg))
    r = subprocess.run(["launchctl", "load", str(p)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"launchctl load failed: {(r.stderr or r.stdout).strip()}")


def _uninstall_macos() -> None:
    p = _plist_path()
    if p.exists():
        subprocess.run(["launchctl", "unload", str(p)], capture_output=True)
        p.unlink()


# --- Linux (cron) -----------------------------------------------------------

def _read_crontab() -> str:
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def _strip_block(text: str) -> str:
    out, skip = [], False
    for ln in text.splitlines():
        if ln.strip() == CRON_BEGIN:
            skip = True
            continue
        if ln.strip() == CRON_END:
            skip = False
            continue
        if not skip:
            out.append(ln)
    return "\n".join(out).strip()


def build_cron_line(cfg: dict) -> str:
    cfg = _clean(cfg)
    dow = "1-5" if cfg["frequency"] == "weekdays" else "*"
    data = paths.data_dir()
    cmd = f"JOBCUT_DATA_DIR={data} {_daily_command(cfg)} >> {data}/jobcut.daily.log 2>&1"
    return f"{cfg['minute']} {cfg['hour']} * * {dow}  {cmd}"


def _install_linux(cfg: dict) -> None:
    base = _strip_block(_read_crontab())
    block = f"{CRON_BEGIN}\n{build_cron_line(cfg)}\n{CRON_END}"
    new = (base + "\n\n" + block + "\n") if base else (block + "\n")
    r = subprocess.run(["crontab", "-"], input=new, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"crontab install failed: {r.stderr.strip()}")


def _uninstall_linux() -> None:
    base = _strip_block(_read_crontab())
    new = (base + "\n") if base else ""
    subprocess.run(["crontab", "-"], input=new, capture_output=True, text=True)
