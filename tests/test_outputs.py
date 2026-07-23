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
    # role-agnostic engine ships no title default — this data fixture sets its own
    config.config_file().write_text(json.dumps(
        {"filter": {"include_titles": r"data analyst|analyst|machine learning"}}))

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


def test_shortlist_records_carry_dates(populated):
    conn, _ = populated
    # keys always present so the console can render a freshness line per card
    rows = (d := surface.shortlist_data(conn))["today"] + d["backlog"]
    assert rows, "fixture should surface at least one scored job"
    assert all("first_seen" in r and "posted_date" in r for r in rows)

    # real values surface end-to-end (the fixture rows carry blanks; set some)
    conn.execute("UPDATE jobs SET first_seen = ?, posted_date = ? WHERE job_id = ?",
                 ("2026-06-16", "2026-06-10", "1"))
    conn.commit()
    rows2 = (d := surface.shortlist_data(conn))["today"] + d["backlog"]
    row1 = next(r for r in rows2 if r["job_id"] == "1")
    assert row1["first_seen"] == "2026-06-16"
    assert row1["posted_date"] == "2026-06-10"


def test_shortlist_meta_reports_pull_and_scored_dates(populated, tmp_path):
    conn, _ = populated
    meta = surface.shortlist_data(conn)["meta"]
    assert "last_pull" in meta and "last_scored" in meta
    assert meta["last_pull"] is None                            # no pull recorded yet
    assert meta["last_scored"] and meta["last_scored"][:4].isdigit()

    # once a pull is recorded (last_runs.json), last_pull reflects its date
    (tmp_path / "last_runs.json").write_text(json.dumps({"date": "2026-06-16"}))
    assert surface.shortlist_data(conn)["meta"]["last_pull"] == "2026-06-16"


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


def test_market_salary_by_segment(populated):
    """Disclosed pay (structured + description body) is normalized to EUR/year and summarized
    per role segment, and the disclosure KPI counts the union — not just structured fields."""
    conn, _ = populated
    # Three disclosed data-analyst offers: structured range, monthly-in-text, description body.
    jobs = {}
    for jid, stext, desc in [
        ("10", "", "Data Analyst role. Salario: 40.000 - 50.000 € brutos anuales. Apply."),
        ("11", "", "Data Analyst. Retribución: 3.000 €/mes en 12 pagas."),   # → 36k/yr
        ("12", "", "Data Analyst. Sueldo competitivo según valía."),         # not disclosed
    ]:
        r = {c: "" for c in db.JOB_COLS}
        r.update(job_id=jid, title="Data Analyst", company_name="Acme", location="Madrid, Spain",
                 workplace_type="remote", linkedin_url=f"https://www.linkedin.com/jobs/view/{jid}",
                 salary_text=stext, description=desc)
        jobs[jid] = r
    db.upsert_jobs(conn, jobs, "2026-06-16")

    s = market.summary(conn)
    assert "salary_by_segment" in s
    da = s["salary_by_segment"]["data-analyst"]
    assert da["n"] == 2                       # #10 (45k mid) and #11 (36k) disclosed a band; #12 didn't
    assert 36000 <= da["median"] <= 45000
    assert da["p25"] <= da["median"] <= da["p75"]
    assert s["salary_pct"] > 0                 # union disclosure counted


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
