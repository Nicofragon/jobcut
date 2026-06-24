"""End-to-end output tests: pull-shaped data → score → surface/market/export.

score.run() and the output stages all use the real today(), so scored_date and
surface's "today" agree without freezing the clock.
"""

import json

import pytest

from jobcut import config, db, score, surface, market, export, paths

TAXONOMY = {
    "skills": {
        "SQL": {"cat": "core", "status": "have", "patterns": [r"\bsql\b"]},
        "Python": {"cat": "core", "status": "have", "patterns": [r"\bpython\b"]},
        "Power BI": {"cat": "viz", "status": "gap", "close_via": "portfolio", "patterns": [r"power ?bi"]},
    },
    "role_segments": {"data-analyst": ["data analyst"], "ds-ai": ["machine learning", r"\bai\b"]},
}


@pytest.fixture()
def populated(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(tmp_path))
    config.reset_cache()
    (tmp_path / "config").mkdir()
    config.taxonomy_file().write_text(json.dumps(TAXONOMY))

    conn = db.connect()
    rows = {}
    for jid, title, loc, wp in [
        ("1", "Senior Data Analyst", "Madrid, Spain", "hybrid"),
        ("2", "Machine Learning Engineer", "European Union", "remote"),
        ("3", "Sales Manager", "Madrid, Spain", "on_site"),
    ]:
        r = {c: "" for c in db.JOB_COLS}
        r.update(job_id=jid, title=title, company_name="Acme", company_size="200",
                 location=loc, workplace_type=wp, applicants="10",
                 linkedin_url=f"https://www.linkedin.com/jobs/view/{jid}",
                 description="SQL, Python and Power BI for analytics.")
        rows[jid] = r
    db.upsert_jobs(conn, rows, "2026-06-16")
    score.run(conn)
    yield conn, tmp_path
    conn.close()
    config.reset_cache()


def test_surface_writes_shortlist(populated):
    conn, _ = populated
    surface.main(conn)
    md = (paths.out_dir() / "shortlist.md").read_text()
    assert "Shortlist" in md
    assert "Data Analyst" in md
    assert "Machine Learning Engineer" in md
    assert "Sales Manager" not in md        # discarded by title
    assert (paths.out_dir() / "shortlist.csv").exists()


def test_market_writes_report(populated):
    conn, _ = populated
    market.main(conn)
    gaps = (paths.out_dir() / "market-gaps.md").read_text()
    assert "Market Gaps" in gaps
    assert "Power BI" in gaps               # a gap skill shows up
    assert (paths.out_dir() / "market-dashboard.html").exists()


def test_market_json_is_stable_shape(populated, capsys):
    from jobcut.cli import main
    assert main(["market", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out) >= {"total", "relevant", "segments", "top_demand", "gaps", "salary_pct"}
    assert out["total"] == 3
    assert isinstance(out["top_demand"], list) and isinstance(out["gaps"], list)


def test_surface_json_is_stable_shape(populated, capsys):
    from jobcut.cli import main
    assert main(["surface", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out) >= {"today", "backlog", "meta"}
    assert isinstance(out["today"], list) and isinstance(out["backlog"], list)
    titles = [r["title"] for r in out["today"]]
    assert any("Data Analyst" in t for t in titles)   # scored today, surfaced


def test_export_writes_csv_json(populated):
    conn, _ = populated
    summary = export.main(conn)
    assert summary["total_jobs"] == 3
    assert summary["funnel"] == 3           # all three are home/region-remote
    assert summary["discarded"] == 1        # the sales role
    dash = json.loads((paths.out_dir() / "dashboard.json").read_text())
    assert dash["total_jobs"] == 3
    assert (paths.out_dir() / "jobs.csv").exists()
