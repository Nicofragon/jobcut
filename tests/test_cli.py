"""CLI tests: the init wizard scaffolds a data dir from bundled templates."""

import json

import pytest

from jobcut import config
from jobcut.cli import main


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    # point at a NOT-yet-existing subdir so init must create the data dir itself
    data = tmp_path / "fresh"
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(data))
    config.reset_cache()
    yield data
    config.reset_cache()


def test_init_creates_files(_isolated):
    data = _isolated
    assert not data.exists()
    rc = main(["init", "--no-input"])
    assert rc == 0
    for rel in [".env", "profile.md", "config/config.json", "config/taxonomy.json",
                "searches/example-city.json", "searches/example-remote.json"]:
        assert (data / rel).exists(), rel
    # the written config is valid and loads through the merge layer
    config.reset_cache()
    cfg = config.load()
    assert cfg["scoring"]["backend"] == "rule_based"
    assert "home" in cfg["routing"]


def test_init_is_idempotent(_isolated):
    main(["init", "--no-input"])
    (_isolated / "profile.md").write_text("MY EDITS")
    main(["init", "--no-input"])               # second run must not clobber
    assert (_isolated / "profile.md").read_text() == "MY EDITS"


def test_init_env_has_token_placeholder(_isolated):
    main(["init", "--no-input"])
    assert "APIFY_TOKEN=" in (_isolated / ".env").read_text()


def test_bundled_config_matches_defaults():
    """The shipped config.example.json must stay in sync with config.DEFAULTS."""
    from importlib import resources
    tpl = resources.files("jobcut") / "templates" / "config.example.json"
    shipped = json.loads(tpl.read_text())
    assert shipped["scoring"]["weights"] == config.DEFAULTS["scoring"]["weights"]
    assert shipped["routing"]["home"] == config.DEFAULTS["routing"]["home"]
    # role-agnostic: neither the default nor the shipped template bakes in a title filter
    # (it's derived from the user's profile) — guard against a field-specific default creeping back
    assert config.DEFAULTS["filter"]["include_titles"] == ""
    assert shipped["filter"]["include_titles"] == ""


def test_bundled_taxonomy_ships_empty_no_field_bias():
    """The shipped kit is role-neutral: no skills/segments baked in (derived from the
    profile). Guards against re-introducing a data-analyst (or any single-field) default."""
    from importlib import resources
    tax = json.loads((resources.files("jobcut") / "templates" / "taxonomy.example.json").read_text())
    assert tax["skills"] == {} and tax["role_segments"] == {}


def test_port_in_use_detects_listener():
    import socket

    from jobcut.cli import _port_in_use

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    port = srv.getsockname()[1]
    try:
        assert _port_in_use("127.0.0.1", port) is True
    finally:
        srv.close()
    # a closed listener's port reads as free again
    assert _port_in_use("127.0.0.1", port) is False


def test_serve_refuses_busy_port_without_replace(_isolated, capsys, monkeypatch):
    """On an occupied port, `serve` (no --replace) must fail fast with an actionable
    message and never reach uvicorn — not print a fake 'serving…' banner."""
    import socket

    import jobcut.cli as cli

    called = {"run": False}
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: called.__setitem__("run", True))

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    port = srv.getsockname()[1]
    try:
        rc = cli.main(["serve", "--port", str(port)])
    finally:
        srv.close()
    assert rc == 1
    assert called["run"] is False  # never tried to bind/serve
    out = capsys.readouterr().out
    assert f"Port {port} is already in use" in out
    assert "--replace" in out


def test_launcher_reuses_current_server(_isolated, capsys, monkeypatch):
    """`serve --launcher` on an occupied port that's healthy AND up-to-date: just open
    the browser and exit 0 — it must never build or reach uvicorn (that's the fast reuse
    path a desktop-icon click takes when a good server is already running)."""
    import socket
    import webbrowser

    import jobcut.cli as cli

    calls = {"run": False, "opened": None}
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: calls.__setitem__("run", True))
    monkeypatch.setattr(cli, "_server_is_current", lambda h, p: True)
    monkeypatch.setattr(webbrowser, "open", lambda u: calls.__setitem__("opened", u))

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    port = srv.getsockname()[1]
    try:
        rc = cli.main(["serve", "--launcher", "--open", "--port", str(port)])
    finally:
        srv.close()
    assert rc == 0
    assert calls["run"] is False
    assert calls["opened"] == f"http://127.0.0.1:{port}"
    assert "already running" in capsys.readouterr().out


def test_launcher_replaces_stale_server(_isolated, monkeypatch):
    """`serve --launcher` on an occupied port that's out of date or hung: free the port
    and start fresh (reach uvicorn) — this is what makes the icon load new code after an
    update instead of reconnecting to the old server."""
    import socket

    import jobcut.cli as cli

    main(["init", "--no-input"])  # so db.connect()/age has a real data dir
    calls = {"run": False, "freed": False}
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: calls.__setitem__("run", True))
    monkeypatch.setattr(cli, "_server_is_current", lambda h, p: False)
    monkeypatch.setattr(cli, "_free_port", lambda h, p: calls.__setitem__("freed", True) or True)
    monkeypatch.setattr(cli, "_maybe_build_web", lambda no_build: None)
    monkeypatch.setattr(cli, "_start_docs_inbox", lambda: None)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    port = srv.getsockname()[1]
    try:
        rc = cli.main(["serve", "--launcher", "--port", str(port)])
    finally:
        srv.close()
    assert rc == 0
    assert calls["freed"] is True   # took over the stale server
    assert calls["run"] is True     # and started fresh


def test_stats_json_is_clean_read_only_payload(_isolated, capsys):
    """`jobcut stats --json` prints a JSON pipeline payload (read path for Claude).

    On an empty data dir the funnel is all zeros; the colors must be stripped so the
    `funnel` entries are plain {stage, count} objects.
    """
    main(["init", "--no-input"])
    capsys.readouterr()  # drain init's stdout so we parse only the stats payload
    rc = main(["stats", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["total"] == 0
    assert {"by_week", "funnel", "counts"} <= out.keys()
    assert out["funnel"][0] == {"stage": "Applied", "count": 0}
    # no UI hex colors leak into the agent-facing payload
    assert "#" not in json.dumps(out)
