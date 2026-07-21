"""API tests — the FastAPI bridge over the package (TestClient, no network)."""

import json

import pytest
from fastapi.testclient import TestClient

from jobcut import config, db, score
from jobcut.api import create_app

TAXONOMY = {
    "skills": {
        "SQL": {"cat": "core", "status": "have", "patterns": [r"\bsql\b"]},
        "Python": {"cat": "core", "status": "have", "patterns": [r"\bpython\b"]},
        "Power BI": {"cat": "viz", "status": "gap", "close_via": "portfolio", "patterns": [r"power ?bi"]},
    },
    "role_segments": {"data-analyst": ["data analyst"], "ds-ai": ["machine learning", r"\bai\b"]},
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("JOBCUT_TRACKER", raising=False)
    config.reset_cache()
    (tmp_path / "config").mkdir()
    config.taxonomy_file().write_text(json.dumps(TAXONOMY))
    # role-agnostic engine ships no title default — this data fixture sets its own
    config.config_file().write_text(json.dumps(
        {"filter": {"include_titles": r"data analyst|analyst|machine learning"}}))
    (tmp_path / "searches").mkdir()

    # the Discovery cache is a module global — clear it so a prior test's data can't leak
    from jobcut.api.routers import market as _mkt
    _mkt._CACHE.clear()

    conn = db.connect()
    rows = {}
    for jid, title, loc, wp in [
        ("1", "Senior Data Analyst", "Madrid, Spain", "hybrid"),
        ("2", "Machine Learning Engineer", "European Union", "remote"),
        ("3", "Sales Manager", "Madrid, Spain", "on_site"),
    ]:
        r = {c: "" for c in db.JOB_COLS}
        r.update(job_id=jid, title=title, company_name="Acme", company_size="200",
                 location=loc, workplace_type=wp, applicants="10", posted_date="2026-06-10",
                 linkedin_url=f"https://www.linkedin.com/jobs/view/{jid}",
                 description="SQL, Python and Power BI for analytics.")
        rows[jid] = r
    db.upsert_jobs(conn, rows, "2026-06-16")
    score.run(conn)
    conn.close()

    yield TestClient(create_app(serve_web=False))
    config.reset_cache()


def test_static_console_mount(tmp_path, monkeypatch):
    from jobcut.api.app import create_app as _create, mount_web

    monkeypatch.setenv("JOBCUT_DATA_DIR", str(tmp_path / "data"))
    config.reset_cache()
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html>jobcut console</html>")
    app = _create(serve_web=False)
    mount_web(app, web)
    c = TestClient(app)
    assert "console" in c.get("/").text          # static console served at /
    assert c.get("/api/status").status_code == 200  # API still works alongside it


# --- health / status --------------------------------------------------------

def test_health_reports_running_sha(client, monkeypatch):
    """`/api/health` echoes the code revision `serve` stamped — the launcher reads this
    to decide reuse-vs-replace. Cheap by design: no DB dependency, unlike /api/status."""
    monkeypatch.setenv("JOBCUT_RUNNING_SHA", "abc1234")
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["running_sha"] == "abc1234"


def test_health_running_sha_none_when_unstamped(client, monkeypatch):
    monkeypatch.delenv("JOBCUT_RUNNING_SHA", raising=False)
    assert client.get("/api/health").json()["running_sha"] is None


def test_status(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    from jobcut import db
    assert body["schema_version"] == db.SCHEMA_VERSION
    assert body["jobs"] == 3
    assert body["applications"] == 0
    assert body["apify_token_set"] is False


# --- shortlist + job detail -------------------------------------------------

def test_shortlist(client):
    body = client.get("/api/shortlist").json()
    titles = [j["title"] for j in body["today"]]
    assert "Senior Data Analyst" in titles
    assert "Machine Learning Engineer" in titles
    assert "Sales Manager" not in titles      # title-discarded / low score
    assert body["meta"]["db_count"] == 3


def test_shortlist_excludes_applied(client):
    client.put("/api/applications/1", json={"status": "applied"})
    titles = [j["title"] for j in client.get("/api/shortlist").json()["today"]]
    assert "Senior Data Analyst" not in titles
    # include_applied brings it back
    titles2 = [j["title"] for j in client.get("/api/shortlist?include_applied=true").json()["today"]]
    assert "Senior Data Analyst" in titles2


def test_job_detail(client):
    body = client.get("/api/jobs/1").json()
    assert body["job"]["title"] == "Senior Data Analyst"
    assert body["score"]["match_score"] >= 60
    assert body["score"]["backend"] == "rule_based"   # score.run tags the effective backend
    assert body["application"] is None
    assert body["salary_estimate"] is None            # none until estimated (B-15)

    # per-offer skills: rule_based leaves the skills cells empty, so the API derives them
    # from taxonomy+text — the description names SQL+Python (have) and Power BI (gap).
    sm = body["skills_match"]
    assert sm["source"] == "taxonomy"
    assert {s["skill"] for s in sm["matched"]} == {"SQL", "Python"}
    assert {s["skill"] for s in sm["missing"]} == {"Power BI"}
    assert next(s for s in sm["missing"] if s["skill"] == "Power BI")["close_via"] == "portfolio"

    assert client.get("/api/jobs/999").status_code == 404


def test_job_detail_prefers_claude_skills(client):
    # A Claude-judged skill list on the score row overrides the taxonomy-regex fallback,
    # and may name skills outside the taxonomy (free-form, from profile.md).
    conn = db.connect()
    db.upsert_scores(conn, [{
        "job_id": "1", "match_score": 82, "match_reasons": "x", "status": "scored",
        "scored_date": "2026-06-16", "backend": "claude_skills",
        "skills_matched": json.dumps([{"skill": "Advanced SQL", "note": "7y"}]),
        "skills_missing": json.dumps([{"skill": "Kubernetes", "note": "asked, not on CV"}]),
    }])
    conn.close()
    sm = client.get("/api/jobs/1").json()["skills_match"]
    assert sm["source"] == "claude"
    assert sm["matched"][0]["skill"] == "Advanced SQL" and sm["matched"][0]["note"] == "7y"
    assert sm["missing"][0]["skill"] == "Kubernetes"   # not in the taxonomy — semantic


def test_job_detail_includes_salary_estimate(client):
    conn = db.connect()
    db.upsert_salary_estimates(conn, [{"job_id": "2", "est_min": 50000, "est_max": 70000,
                                       "currency": "EUR", "period": "year", "basis": "Levels.fyi"}])
    conn.close()
    est = client.get("/api/jobs/2").json()["salary_estimate"]
    assert est is not None
    assert est["est_min"] == 50000 and est["est_max"] == 70000
    assert est["currency"] == "EUR" and est["basis"] == "Levels.fyi"


def test_job_detail_salary_from_description(client):
    # B-17: salary stated only in the description body → surfaced as salary_listing
    conn = db.connect()
    row = {c: "" for c in db.JOB_COLS}
    row.update(job_id="10", title="BI Analyst", company_name="Acme",
               description="Great team. Salary: Up to 60K€ + 20% variable. Apply now.")
    db.upsert_jobs(conn, {"10": row}, "2026-06-16")
    conn.close()
    assert client.get("/api/jobs/10").json()["salary_listing"] == "Salary: Up to 60K€ + 20% variable"


def test_job_detail_structured_salary_wins_over_description(client):
    # a structured band present → don't parse the description (listing stays null)
    conn = db.connect()
    row = {c: "" for c in db.JOB_COLS}
    row.update(job_id="11", title="X", company_name="Acme", salary_text="50k–60k EUR",
               description="Salary: Up to 99K€ buried in the text")
    db.upsert_jobs(conn, {"11": row}, "2026-06-16")
    conn.close()
    assert client.get("/api/jobs/11").json()["salary_listing"] is None


def test_job_detail_application_only(client):
    # A row the user owns (an application) with no jobs row must open (200, job:null),
    # never 404 — so notes + status stay reachable. KR-v2-5.
    client.put("/api/applications/777", json={"status": "interview", "notes": "manual add"})
    r = client.get("/api/jobs/777")
    assert r.status_code == 200
    body = r.json()
    assert body["job"] is None
    assert body["score"] is None
    assert body["application"]["status"] == "interview"
    assert body["application"]["notes"] == "manual add"
    # A truly unknown id (no job, no score, no application) still 404s.
    assert client.get("/api/jobs/888").status_code == 404


def test_applications_list_is_enriched(client):
    # the list endpoint joins title/company server-side so the console needs no N+1
    client.put("/api/applications/1", json={"status": "applied"})
    rows = client.get("/api/applications").json()
    assert len(rows) == 1
    assert rows[0]["job_id"] == "1"
    assert rows[0]["title"] == "Senior Data Analyst"   # joined from jobs
    assert "company_name" in rows[0]


# --- applications -----------------------------------------------------------

def test_applications_crud_and_funnel(client):
    assert client.get("/api/applications").json() == []

    r = client.put("/api/applications/1", json={"status": "interview", "notes": "ref by Ana"})
    assert r.status_code == 200
    assert r.json()["status_category"] == "Interview"

    one = client.get("/api/applications/1").json()
    assert one["notes"] == "ref by Ana" and one["status"] == "interview"

    # status update preserves applied_at, refreshes status
    applied_at = one["applied_at"]
    client.put("/api/applications/1", json={"status": "offer"})
    upd = client.get("/api/applications/1").json()
    assert upd["applied_at"] == applied_at and upd["status_category"] == "Offer"

    funnel = client.get("/api/applications/funnel").json()
    assert funnel["total"] == 1 and funnel["offers"] == 1

    assert client.delete("/api/applications/1").status_code == 200
    assert client.get("/api/applications/1").status_code == 404
    assert client.delete("/api/applications/1").status_code == 404


def test_applications_list_serializes_null_structured_fields(client):
    # Post-v5 the structured columns default to NULL; the list endpoint must return
    # them as JSON null (not NaN) and never 500.
    for jid in ("1", "2", "3"):
        client.put(f"/api/applications/{jid}", json={"status": "applied"})
    r = client.get("/api/applications")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 3
    assert all(row["priority"] is None and row["next_action"] is None for row in rows)


def test_application_events_timeline(client):
    # A status change lands on the timeline; a note appends without fabricating status.
    client.put("/api/applications/1", json={"status": "applied"})
    r = client.post("/api/applications/1/events", json={"kind": "note", "body": "called recruiter"})
    assert r.status_code == 200
    ev = client.get("/api/applications/1/events").json()
    assert ev[0]["kind"] == "note" and ev[0]["body"] == "called recruiter"  # most recent first
    assert "status_change" in [e["kind"] for e in ev]
    # A note on a never-tracked job creates no application row (no funnel inflation).
    client.post("/api/applications/2/events", json={"kind": "note", "body": "maybe later"})
    assert client.get("/api/applications/2").status_code == 404
    assert client.get("/api/applications/2/events").json()[0]["body"] == "maybe later"
    # Unknown kinds are rejected.
    assert client.post("/api/applications/1/events", json={"kind": "bogus"}).status_code == 422


def test_application_documents_read(client):
    # Documents are written via the ingest bridge (db layer); the API is read-only.
    conn = db.connect()
    db.set_application_status(conn, "1", "interview", now="2026-06-16T10:00:00")
    ev = db.add_event(conn, "1", "interview", body="R3", now="2026-06-20T12:00:00")
    db.upsert_document(conn, job_id="1", title="Company research", body="## Mission",
                       event_id=None, now="2026-06-17T10:00:00")
    anchored = db.upsert_document(conn, job_id="1", title="R3 debrief", body="they asked SQL",
                                  event_id=ev["event_id"], now="2026-06-21T10:00:00")
    archived = db.upsert_document(conn, job_id="1", title="old", body="x", now="2026-06-18T10:00:00")
    db.set_document_archived(conn, archived["doc_id"], now="2026-06-19T10:00:00")
    conn.close()

    docs = client.get("/api/applications/1/documents").json()
    titles = [d["title"] for d in docs]
    assert titles == ["Company research", "R3 debrief"]   # offer-level first; archived hidden
    assert docs[1]["event_id"] == ev["event_id"]

    one = client.get(f"/api/applications/1/documents/{anchored['doc_id']}")
    assert one.status_code == 200 and one.json()["body"] == "they asked SQL"

    # 404: unknown id, and an id that belongs to another offer.
    assert client.get("/api/applications/1/documents/99999").status_code == 404
    assert client.get(f"/api/applications/2/documents/{anchored['doc_id']}").status_code == 404


def test_application_documents_empty(client):
    assert client.get("/api/applications/3/documents").json() == []


def test_application_patch_fields(client):
    client.put("/api/applications/1", json={"status": "interview"})
    r = client.patch("/api/applications/1", json={"priority": "high", "next_action": "send case",
                                                  "next_action_date": "2026-07-01", "contact": "Ana"})
    assert r.status_code == 200
    a = r.json()
    assert a["priority"] == "high" and a["next_action"] == "send case"
    assert a["next_action_date"] == "2026-07-01" and a["contact"] == "Ana"
    assert a["status"] == "interview"  # PATCH never touches status
    # partial update leaves other fields intact
    client.patch("/api/applications/1", json={"contact": "Ana Ruiz"})
    a2 = client.get("/api/applications/1").json()
    assert a2["contact"] == "Ana Ruiz" and a2["next_action"] == "send case"
    # PATCH on a non-existent application 404s (never fabricates a row)
    assert client.patch("/api/applications/999", json={"priority": "low"}).status_code == 404


def test_applications_list_includes_stage_info(client):
    # Each row carries time-in-stage + stalled flag (Phase 3 enrichment).
    client.put("/api/applications/1", json={"status": "interview"})
    rows = client.get("/api/applications").json()
    row = next(r for r in rows if str(r["job_id"]) == "1")
    assert "days_in_stage" in row and "stalled" in row and "dormant" in row
    assert isinstance(row["stalled"], bool) and isinstance(row["dormant"], bool)


def test_funnel_exposes_stalled_keys(client):
    client.put("/api/applications/1", json={"status": "applied"})
    f = client.get("/api/applications/funnel").json()
    assert "stalled_count" in f and "dormant_count" in f and "by_stage_time" in f


def test_application_statuses(client):
    body = client.get("/api/applications/statuses").json()
    assert "interview" in body["statuses"] and "Offer" in body["categories"]


# --- searches ---------------------------------------------------------------

def test_searches_crud(client):
    assert client.get("/api/searches").json() == []
    r = client.post("/api/searches", json={"name": "remote-de", "input": {"title": "data engineer"}})
    assert r.status_code == 200
    assert client.post("/api/searches", json={"name": "remote-de", "input": {}}).status_code == 409
    assert client.get("/api/searches/remote-de").json()["input"]["title"] == "data engineer"
    client.put("/api/searches/remote-de", json={"input": {"title": "ml engineer"}})
    assert client.get("/api/searches/remote-de").json()["input"]["title"] == "ml engineer"
    assert client.delete("/api/searches/remote-de").status_code == 200
    assert client.get("/api/searches/remote-de").status_code == 404


def test_search_name_validation(client):
    assert client.get("/api/searches/..%2f..%2fetc").status_code in (400, 404)
    assert client.post("/api/searches", json={"name": "bad name!", "input": {}}).status_code == 400


# --- profile / config -------------------------------------------------------

def test_profile_get_put(client):
    assert client.get("/api/profile").json()["content"] == ""
    client.put("/api/profile", json={"content": "# Me\nData analyst"})
    assert "Data analyst" in client.get("/api/profile").json()["content"]


def test_config_get_put(client):
    cfg = client.get("/api/config").json()
    assert cfg["scoring"]["backend"] == "rule_based"
    client.put("/api/config", json={"config": {"scoring": {"out_of_profile_cap": 25}}})
    assert client.get("/api/config").json()["scoring"]["out_of_profile_cap"] == 25


def test_config_put_preserves_other_keys(client):
    # Saving one nested key must not wipe sibling overrides (weights vs backend).
    client.put("/api/config", json={"config": {"scoring": {"backend": "local"}}})
    client.put("/api/config", json={"config": {"scoring": {"out_of_profile_cap": 25}}})
    cfg = client.get("/api/config").json()
    assert cfg["scoring"]["backend"] == "local"  # not clobbered by the second save
    assert cfg["scoring"]["out_of_profile_cap"] == 25


def test_cv_extract_and_from_cv(client):
    r = client.post("/api/cv/extract", files={"file": ("cv.txt", b"Senior Nurse, ACLS", "text/plain")})
    assert r.status_code == 200
    assert r.json()["text"] == "Senior Nurse, ACLS"

    draft = client.post("/api/profile/from-cv", json={"text": "Senior Nurse, ACLS"}).json()
    assert draft["source"] == "scaffold"            # no LLM configured
    assert "## Target roles" in draft["profile_md"]


def test_cv_extract_unsupported(client):
    r = client.post("/api/cv/extract", files={"file": ("cv.rtf", b"x", "application/rtf")})
    assert r.status_code == 422


def test_profile_derive(client):
    client.put("/api/profile", json={"content": (
        "## Target roles\n- Marketing Manager\n\n## Core skills\n- SEO\n- Content strategy\n\n"
        "## Location & work mode\n- Based in: Berlin, Germany\n- Remote: yes\n"
    )})
    derived = client.get("/api/profile/derived").json()
    assert "Marketing Manager" in derived["searches"][next(iter(derived["searches"]))]["jobTitles"]
    assert "remote" in derived["searches"]                 # Remote: yes -> remote search
    assert "SEO" in derived["taxonomy"]["skills"]

    report = client.post("/api/profile/derive", json={"force": True}).json()
    assert report["written"]
    # the written config now drives include_titles (role-agnostic)
    import re
    inc = client.get("/api/config").json()["filter"]["include_titles"]
    assert re.search(inc, "Marketing Manager", re.I)


# --- credentials ------------------------------------------------------------

def test_credentials_put_and_validate(client):
    assert client.get("/api/credentials").json()["apify_token_set"] is False
    client.put("/api/credentials", json={"apify_token": "apify_api_realish"})
    assert client.get("/api/credentials").json()["apify_token_set"] is True
    # empty/missing token validates as invalid without any network call
    v = client.post("/api/validate-credentials", json={}).json()
    assert v["apify"]["valid"] is False


# --- profile → kit ----------------------------------------------------------

def test_put_profile_structured_autoderives_kit(client):
    # Saving the profile re-derives the kit (merge): profile owns status, existing skills survive.
    r = client.put("/api/profile/structured", json={
        "target_roles": ["Data Analyst"], "skills": ["SQL"], "must_haves": ["Tableau"],
        "gaps": ["dbt"], "locations": ["Madrid"], "work_types": ["remote"], "dealbreakers": [],
    })
    assert r.status_code == 200
    assert "dbt" in r.json()["gaps"]

    config.reset_cache()
    tax = config.load_taxonomy()
    assert tax["skills"]["dbt"]["status"] == "gap"            # gap skill flowed into the kit
    assert tax["skills"]["dbt"]["close_via"]                  # gap carries a close_via
    assert tax["skills"]["Tableau"]["status"] == "partial"    # nice-to-have → partial
    assert tax["skills"]["SQL"]["status"] == "have"
    assert "Power BI" in tax["skills"]                        # existing kit skill preserved (merge)

    # the kit endpoint reflects the same live taxonomy, flattened + counted by status.
    kit = client.get("/api/profile/kit").json()
    by_name = {s["name"]: s for s in kit["skills"]}
    assert by_name["dbt"]["status"] == "gap" and by_name["dbt"]["category"]
    assert kit["counts"]["gap"] >= 1 and kit["counts"]["have"] >= 1


# --- market -----------------------------------------------------------------

def test_market(client):
    body = client.get("/api/market").json()
    assert body["total"] == 3
    assert body["relevant"] >= 1
    assert "salary_pct" in body

    # coverage: SQL + Python are `have`, Power BI is a `gap`. All three are demanded
    # (each offer's description mentions them), so coverage sits between 0 and 100.
    assert 0 < body["coverage"]["pct"] < 100
    assert set(body["coverage"]["by_segment"]) == {"data-analyst", "ds-ai"}

    # enriched skills carry the taxonomy detail the flat payload used to drop.
    sql = next(s for s in body["top_demand"] if s["skill"] == "SQL")
    assert sql["status"] == "have" and sql["cat"] == "core"
    assert "by_seg" in sql and "trend" in sql and sql["n"] >= 1

    # gaps are objects now (skill + how to close it), not bare strings.
    gap = next(g for g in body["gaps"] if g["skill"] == "Power BI")
    assert gap["status"] == "gap" and gap["close_via"] == "portfolio"

    # score distribution: the two in-profile analyst roles are scored; bands sum to total.
    dist = body["score_distribution"]
    assert dist["total"] == sum(b["count"] for b in dist["bands"])
    assert [b["label"] for b in dist["bands"]] == ["Below bar", "Shortlist", "Top"]
    assert dist["total"] >= 1

    # freshness: both in-market rows carry a date, so there's ≥1 weekly bucket and an age.
    # (Applicant "competition" is intentionally not surfaced — it's a pull-time snapshot.)
    fresh = body["freshness"]
    assert fresh["n"] == 2 and fresh["weekly"] and fresh["median_age_days"] >= 0
    assert "competition" not in body

    # shortlist gaps: the in-market analyst offers (score ≥ 60) all name Power BI (a gap).
    sg = body["shortlist_gaps"]
    assert sg["n"] >= 1
    assert "Power BI" in {g["skill"] for g in sg["gaps"]}

    # POST (Refresh) must return the SAME enriched shape as GET — never the old flat one.
    refreshed = client.post("/api/market").json()
    assert "coverage" in refreshed and "score_distribution" in refreshed
    assert "freshness" in refreshed
    assert isinstance(refreshed["gaps"], list)
    assert all(isinstance(g, dict) for g in refreshed["gaps"])


def test_market_payload_is_cached_and_invalidates(client, tmp_path):
    """The Discovery payload is expensive, so it's cached by a DB/taxonomy signature:
    a repeat GET is served from cache, and any data change transparently recomputes."""
    from jobcut.api.routers import market as mr
    mr._CACHE.clear()

    body1 = client.get("/api/market").json()
    assert body1["total"] == 3
    # cache populated in-process AND on disk (the disk copy is what the daily run warms)
    assert mr._CACHE.get("payload") is not None
    assert mr._cache_path().exists()
    # a repeat GET returns the identical payload (served from cache)
    assert client.get("/api/market").json() == body1

    # add a job → signature changes → the cache must invalidate and recompute
    conn = db.connect()
    r = {c: "" for c in db.JOB_COLS}
    r.update(job_id="9", title="Data Analyst", company_name="Beta", company_size="50",
             location="Madrid, Spain", workplace_type="remote", posted_date="2026-06-11",
             linkedin_url="https://www.linkedin.com/jobs/view/9",
             description="SQL and Python for analytics.")
    db.upsert_jobs(conn, {"9": r}, "2026-06-17")
    score.run(conn)
    conn.close()

    body2 = client.get("/api/market").json()
    assert body2["total"] == 4          # recomputed, not the stale cached 3


def test_market_warm_writes_disk_cache(client):
    """`warm()` (called by the daily pipeline) precomputes + persists the disk cache so the
    first console load after a pull/score is instant instead of multi-second."""
    from jobcut.api.routers import market as mr
    mr._CACHE.clear()
    if mr._cache_path().exists():
        mr._cache_path().unlink()

    payload = mr.warm()
    assert mr._cache_path().exists()
    disk = json.loads(mr._cache_path().read_text())
    assert disk["payload"]["total"] == payload["total"] == 3
    assert disk["sig"] == mr._CACHE["sig"]


def test_export(client):
    body = client.post("/api/export").json()
    assert body["summary"]["total_jobs"] == 3
    assert body["out_dir"]


# --- runs + SSE -------------------------------------------------------------

def test_run_score_streams_to_done(client):
    rid = client.post("/api/runs", json={"kind": "score"}).json()["run_id"]
    with client.stream("GET", f"/api/runs/{rid}/events") as resp:
        body = "".join(resp.iter_text())
    assert "event: done" in body
    assert client.get(f"/api/runs/{rid}").json()["status"] == "done"


def test_run_pull_trigger_requires_confirm(client):
    r = client.post("/api/runs", json={"kind": "pull", "mode": "trigger"})
    assert r.status_code == 409
    # read mode does not need confirmation (guard only blocks the paid path)
    r2 = client.post("/api/runs", json={"kind": "pull", "mode": "trigger", "confirm": True})
    assert r2.status_code == 200
