"""funnel_series must match per-row is_funnel (the vectorized shortlist hot path)."""

import pytest

from jobcut import config
from jobcut.route import funnel_series, is_funnel


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(tmp_path))
    config.reset_cache()
    yield
    config.reset_cache()


def test_funnel_series_matches_is_funnel():
    locs = ["Madrid, Spain", "Tokyo, Japan", "European Union", "Madrid, Spain", "", "European Union"]
    wps = ["hybrid", "on_site", "remote", "on_site", "remote", "on_site"]
    assert funnel_series(locs, wps) == [is_funnel(loc, wp) for loc, wp in zip(locs, wps)]


def test_funnel_series_empty():
    assert funnel_series([], []) == []
