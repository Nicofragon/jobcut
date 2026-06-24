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
