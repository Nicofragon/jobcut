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
