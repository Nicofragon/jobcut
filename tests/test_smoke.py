"""Smoke tests: the package imports, the CLI wires up, paths/route/scorer basics.

Deeper coverage lives in test_db / test_scoring / test_outputs / test_cli.
"""



def test_package_imports():
    import jobcut
    assert jobcut.__version__


def test_cli_parser_builds():
    from jobcut.cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["pull", "--read"])
    assert args.command == "pull"
    assert args.read is True


def test_cli_serve_parser():
    from jobcut.cli import build_parser
    args = build_parser().parse_args(["serve", "--open", "--port", "9999"])
    assert args.command == "serve" and args.open is True and args.port == 9999


def test_data_dir_respects_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(tmp_path))
    # re-import fresh so the env var is read at call time
    from jobcut import paths
    assert paths.data_dir() == tmp_path.resolve()
    assert paths.searches_dir() == tmp_path.resolve() / "searches"


def test_route_example_geography():
    from jobcut.route import is_funnel, geo
    assert geo("Madrid, Spain") == "home"
    assert is_funnel("Madrid, Spain", "on_site") is True
    # region + remote is funnel; region + on-site is not
    assert is_funnel("European Union", "remote") is True
    assert is_funnel("European Union", "on_site") is False


def test_scorer_factory_returns_scored_result():
    from jobcut.scoring import get_scorer, JobScore
    scorer = get_scorer("rule_based")
    js = scorer.score({"job_id": "1", "title": "x"}, "profile")
    assert isinstance(js, JobScore)
    assert 0 <= js.match_score <= 100


def test_unknown_backend_raises():
    from jobcut.scoring import get_scorer
    try:
        get_scorer("nope")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for unknown backend")
