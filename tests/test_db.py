"""Tests for the SQLite layer: upsert/dedupe, source union, volatile refresh."""

import sqlite3

import pytest

from jobcut import db, surface


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def _job(job_id, source, **over):
    row = {c: "" for c in db.JOB_COLS}
    row.update(job_id=job_id, source_searches=source, title=f"Job {job_id}",
               company_name="Acme", location="Madrid, Spain", applicants="10",
               job_state="LISTED", first_seen="2026-01-01", last_seen="2026-01-01")
    row.update(over)
    return row


def test_insert_new_jobs(conn):
    agg = {"1": _job("1", "city"), "2": _job("2", "remote")}
    inserted, updated = db.upsert_jobs(conn, agg, "2026-01-01")
    assert (inserted, updated) == (2, 0)
    assert db.count_jobs(conn) == 2


def test_reupsert_unions_sources_and_refreshes_volatile(conn):
    db.upsert_jobs(conn, {"1": _job("1", "city", applicants="10")}, "2026-01-01")
    # same job seen again from another search, more applicants, later day
    again = _job("1", "remote", applicants="42", first_seen="2026-01-02", last_seen="2026-01-02",
                 title="SHOULD NOT OVERWRITE")
    inserted, updated = db.upsert_jobs(conn, {"1": again}, "2026-01-02")
    assert (inserted, updated) == (0, 1)

    df = db.read_jobs(conn)
    row = df[df.job_id == "1"].iloc[0]
    assert set(row.source_searches.split("|")) == {"city", "remote"}  # unioned
    assert row.first_seen == "2026-01-01"   # stable
    assert row.last_seen == "2026-01-02"    # refreshed
    assert str(row.applicants) == "42"      # volatile refreshed
    assert row.title == "Job 1"             # stable field NOT overwritten


def test_empty_applicants_does_not_clobber(conn):
    db.upsert_jobs(conn, {"1": _job("1", "city", applicants="10")}, "2026-01-01")
    db.upsert_jobs(conn, {"1": _job("1", "city", applicants="")}, "2026-01-02")
    row = db.read_jobs(conn).iloc[0]
    assert str(row.applicants) == "10"      # kept, not clobbered by empty


def test_scores_upsert_and_incremental(conn):
    rows = [
        {"job_id": "1", "canonical_id": "c1", "match_score": 80, "match_reasons": "good", "status": "scored", "scored_date": "2026-01-01"},
        {"job_id": "2", "canonical_id": "c2", "match_score": 20, "match_reasons": "title", "status": "discarded", "scored_date": "2026-01-01"},
    ]
    assert db.upsert_scores(conn, rows) == 2
    assert db.scored_ids(conn) == {"1", "2"}
    # re-score job 1 (last write wins)
    db.upsert_scores(conn, [{"job_id": "1", "canonical_id": "c1", "match_score": 95, "match_reasons": "better", "status": "scored", "scored_date": "2026-01-02"}])
    sc = db.read_scores(conn)
    assert int(sc[sc.job_id == "1"].iloc[0].match_score) == 95
    assert len(sc) == 2


# --- applications table + migration -----------------------------------------

def _schema_version(conn) -> str:
    return conn.execute("SELECT value FROM _meta WHERE key='schema_version'").fetchone()[0]


def _has_table(conn, name) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def test_fresh_db_is_current(conn):
    assert _schema_version(conn) == str(db.SCHEMA_VERSION)
    assert _has_table(conn, "applications")
    assert _has_table(conn, "score_runs")


def test_migration_v1_to_current(tmp_path):
    # Build a raw "v1" DB: jobs + _meta(=1), with data, NO applications/score_runs table.
    p = tmp_path / "v1.db"
    raw = sqlite3.connect(str(p))
    raw.executescript(
        'CREATE TABLE jobs ("job_id" TEXT PRIMARY KEY, "title" TEXT, "first_seen" TEXT);'
        "CREATE TABLE _meta (key TEXT PRIMARY KEY, value TEXT);"
        "INSERT INTO jobs(job_id, title, first_seen) VALUES ('1', 'Old Job', '2026-01-01');"
        "INSERT INTO _meta(key, value) VALUES ('schema_version', '1');"
    )
    raw.commit()
    raw.close()

    conn = db.connect(p)
    try:
        assert _schema_version(conn) == str(db.SCHEMA_VERSION)
        assert _has_table(conn, "applications")
        assert _has_table(conn, "score_runs")
        # existing data preserved (additive migrations only)
        assert conn.execute("SELECT title FROM jobs WHERE job_id='1'").fetchone()[0] == "Old Job"
    finally:
        conn.close()


def test_read_jobs_columns_subset(conn):
    db.upsert_jobs(conn, {"1": _job("1", "c", description="long text here")}, "2026-01-01")
    df = db.read_jobs(conn, columns=["job_id", "title"])
    assert list(df.columns) == ["job_id", "title"]   # subset only — no heavy `description`
    assert df.iloc[0].job_id == "1"


def test_scores_backend_column_roundtrip(conn):
    db.upsert_scores(conn, [{"job_id": "1", "canonical_id": "", "match_score": 80,
                             "match_reasons": "x", "status": "scored", "scored_date": "2026-01-01",
                             "backend": "local"}])
    row = db.read_scores(conn).iloc[0]
    assert row.backend == "local"


def test_migration_adds_backend_to_existing_scores(tmp_path):
    # A pre-v4 DB: scores table WITHOUT the backend column.
    p = tmp_path / "v3.db"
    raw = sqlite3.connect(str(p))
    raw.executescript(
        'CREATE TABLE scores ("job_id" TEXT PRIMARY KEY, "canonical_id" TEXT, "match_score" INTEGER, '
        '"match_reasons" TEXT, "status" TEXT, "scored_date" TEXT);'
        "CREATE TABLE _meta (key TEXT PRIMARY KEY, value TEXT);"
        "INSERT INTO scores(job_id, match_score) VALUES ('1', 70);"
        "INSERT INTO _meta(key, value) VALUES ('schema_version', '3');"
    )
    raw.commit()
    raw.close()

    conn = db.connect(p)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(scores)").fetchall()}
        assert "backend" in cols                       # ALTER added it
        assert _schema_version(conn) == str(db.SCHEMA_VERSION)
        assert int(conn.execute("SELECT match_score FROM scores WHERE job_id='1'").fetchone()[0]) == 70
    finally:
        conn.close()


def test_set_and_read_application(conn):
    db.set_application_status(conn, "1", "applied", now="2026-06-16T10:00:00")
    df = db.read_applications(conn)
    assert len(df) == 1
    row = df.iloc[0]
    assert row.job_id == "1"
    assert row.status_category == "Applied"
    assert row.applied_at == "2026-06-16T10:00:00"
    assert row.updated_at == "2026-06-16T10:00:00"
    assert row.source == "manual"


def test_status_update_preserves_applied_at(conn):
    db.set_application_status(conn, "1", "applied", now="2026-06-16T10:00:00")
    db.set_application_status(conn, "1", "interview", now="2026-06-20T09:30:00")
    a = db.get_application(conn, "1")
    assert a["applied_at"] == "2026-06-16T10:00:00"   # fixed at first apply
    assert a["updated_at"] == "2026-06-20T09:30:00"   # refreshed
    assert a["status"] == "interview"
    assert a["status_category"] == "Interview"


def test_application_survives_rescore(conn):
    db.set_application_status(conn, "1", "interview", now="2026-06-16T10:00:00")
    # a re-score writes the scores table; applications must be untouched
    db.upsert_scores(conn, [{"job_id": "1", "canonical_id": "c1", "match_score": 90,
                             "match_reasons": "x", "status": "scored", "scored_date": "2026-06-17"}])
    a = db.get_application(conn, "1")
    assert a["status"] == "interview"
    assert a["applied_at"] == "2026-06-16T10:00:00"


def test_notes_preserved_when_omitted(conn):
    db.set_application_status(conn, "1", "applied", notes="referred by Ana", now="2026-06-16T10:00:00")
    db.set_application_status(conn, "1", "screen", now="2026-06-18T10:00:00")  # notes=None
    a = db.get_application(conn, "1")
    assert a["notes"] == "referred by Ana"


def test_application_without_job_in_jobs(conn):
    # No FK: an application can exist for a job that isn't in the jobs table.
    db.set_application_status(conn, "manual:abc", "applied", source="import", now="2026-06-16T10:00:00")
    a = db.get_application(conn, "manual:abc")
    assert a is not None and a["source"] == "import"


# --- v5: application_events timeline + structured columns -------------------

def test_v5_schema_has_events_table_and_columns(conn):
    assert _has_table(conn, "application_events")
    app_cols = {r[1] for r in conn.execute("PRAGMA table_info(applications)").fetchall()}
    for c in ("priority", "next_action", "next_action_date", "contact", "cv_version"):
        assert c in app_cols


def test_status_change_writes_timeline_event(conn):
    db.set_application_status(conn, "1", "applied", now="2026-06-16T10:00:00")
    db.set_application_status(conn, "1", "interview", now="2026-06-20T09:30:00")
    events = db.get_events(conn, "1")  # reverse-chron, latest first
    assert [(e["kind"], e["from_status"], e["to_status"]) for e in events] == [
        ("status_change", "applied", "interview"),
        ("status_change", None, "applied"),
    ]
    db.set_application_status(conn, "1", "interview", now="2026-06-21T10:00:00")  # no-op re-save
    assert len(db.get_events(conn, "1")) == 2  # no duplicate event


def test_rescore_does_not_touch_applications_or_events(conn):
    # The invariant: re-scoring writes only `scores`; user-owned tables are untouched.
    db.set_application_status(conn, "1", "interview", now="2026-06-16T10:00:00")
    before = db.get_events(conn, "1")
    db.upsert_scores(conn, [{"job_id": "1", "canonical_id": "c1", "match_score": 90,
                             "match_reasons": "x", "status": "scored", "scored_date": "2026-06-17"}])
    assert db.get_events(conn, "1") == before
    assert db.get_application(conn, "1")["status"] == "interview"


def test_note_event_needs_no_application(conn):
    # Solo-note write-path: a note for a never-applied job creates no funnel row.
    db.add_event(conn, "1", "note", body="recruiter pinged me", now="2026-06-16T10:00:00")
    assert db.get_application(conn, "1") is None  # no fabricated 'applied'
    events = db.get_events(conn, "1")
    assert len(events) == 1 and events[0]["kind"] == "note"
    assert events[0]["body"] == "recruiter pinged me"


def test_delete_application_cascades_events(conn):
    db.set_application_status(conn, "1", "applied", now="2026-06-16T10:00:00")
    db.add_event(conn, "1", "note", body="n", now="2026-06-16T11:00:00")
    assert len(db.get_events(conn, "1")) == 2
    db.delete_application(conn, "1")
    assert db.get_events(conn, "1") == []


def _scored(jid, score, date):
    return {"job_id": jid, "canonical_id": f"c{jid}", "match_score": score,
            "match_reasons": "x", "status": "scored", "scored_date": date}


def test_shortlist_slider_governs_backlog_and_latest_batch(conn):
    # 3 jobs, two scored in an older batch, one in the latest batch.
    agg = {j: _job(j, "s", linkedin_url=f"https://www.linkedin.com/jobs/view/{j}")
           for j in ("1", "2", "3")}
    db.upsert_jobs(conn, agg, "2026-06-20")
    db.upsert_scores(conn, [_scored("1", 85, "2026-06-20"), _scored("2", 65, "2026-06-20")])
    db.upsert_scores(conn, [_scored("3", 90, "2026-06-23")])  # latest batch

    # Floor 60: latest batch = job3 only; backlog = both older jobs (slider governs it).
    d = surface.shortlist_data(conn, min_score=60, today="2026-06-24")
    assert {r["job_id"] for r in d["today"]} == {"3"}        # latest batch, not literal today
    assert {r["job_id"] for r in d["backlog"]} == {"1", "2"}

    # Raise the floor to 80: the 65-scored job drops from the backlog (the bug fix).
    d2 = surface.shortlist_data(conn, min_score=80, today="2026-06-24")
    assert {r["job_id"] for r in d2["today"]} == {"3"}
    assert {r["job_id"] for r in d2["backlog"]} == {"1"}     # only the 85 survives


def test_shortlist_feed_limit_exceeds_cli_top_n(conn):
    # 12 earlier-batch jobs, all above the floor → the web feed shows all 12
    # (the old TOP_N=10 cap would have hidden 2). One fresh job marks the latest batch.
    agg = {str(j): _job(str(j), "s", linkedin_url=f"https://www.linkedin.com/jobs/view/{j}")
           for j in range(1, 14)}
    db.upsert_jobs(conn, agg, "2026-06-20")
    db.upsert_scores(conn, [_scored(str(j), 80, "2026-06-20") for j in range(1, 13)])
    db.upsert_scores(conn, [_scored("13", 90, "2026-06-23")])  # latest batch
    d = surface.shortlist_data(conn, min_score=70, today="2026-06-24")
    assert len(d["backlog"]) == 12   # > TOP_N (10) — the slider/feed isn't artificially capped
    assert {r["job_id"] for r in d["today"]} == {"13"}


def test_stage_durations_stalled_dormant(conn):
    # Moved to interview 20 days ago and never since → stallable + stalled (14..90d).
    db.set_application_status(conn, "1", "applied", now="2026-06-01T10:00:00")
    db.set_application_status(conn, "1", "interview", now="2026-06-04T10:00:00")
    # Applied only 3 days ago → open but fresh.
    db.set_application_status(conn, "2", "applied", now="2026-06-21T10:00:00")
    # Rejected long ago → terminal, neither stalled nor dormant.
    db.set_application_status(conn, "3", "rejected", now="2026-05-01T10:00:00")
    # Applied 100 days ago, untouched → dormant (>= 90d), not stalled.
    db.set_application_status(conn, "4", "applied", now="2026-03-16T10:00:00")
    # Applied 20 days ago → NOT stalled: Applied isn't stallable (it ages to No response).
    db.set_application_status(conn, "5", "applied", now="2026-06-04T10:00:00")
    d = db.stage_durations(conn, now="2026-06-24T10:00:00")
    assert d["1"]["days_in_stage"] == 20 and d["1"]["stalled"] is True and d["1"]["dormant"] is False
    assert d["2"]["days_in_stage"] == 3 and d["2"]["stalled"] is False and d["2"]["dormant"] is False
    assert d["3"]["stalled"] is False and d["3"]["dormant"] is False  # terminal
    assert d["4"]["stalled"] is False and d["4"]["dormant"] is True   # >= 90d
    assert d["5"]["days_in_stage"] == 20 and d["5"]["stalled"] is False  # Applied never "stalled"


def test_saved_status_is_non_funnel(conn):
    from jobcut import status
    assert "saved" in status.STATUSES and status.classify("saved") == "Saved"
    # A saved role lives in applications but must NOT inflate the funnel.
    db.set_application_status(conn, "1", "saved", now="2026-06-20T10:00:00")
    db.set_application_status(conn, "2", "applied", now="2026-06-20T10:00:00")
    f = db.application_funnel(conn, now="2026-06-24T10:00:00")
    assert f["total"] == 1                      # only the applied one counts
    assert f["counts"].get("Saved") is None     # Saved absent from funnel counts
    assert f["stalled_count"] == 0              # saved never stalls
    # …but the row still exists for the tracker to show.
    assert db.get_application(conn, "1")["status_category"] == "Saved"


def test_age_stale_applications(conn):
    db.set_application_status(conn, "1", "applied", now="2026-05-01T10:00:00")     # 54d → age
    db.set_application_status(conn, "2", "applied", now="2026-06-20T10:00:00")     # 4d → keep
    db.set_application_status(conn, "3", "interview", now="2026-05-01T10:00:00")   # 54d but not Applied → keep
    n = db.age_stale_applications(conn, now="2026-06-24T10:00:00")
    assert n == 1
    assert db.get_application(conn, "1")["status"] == "no_response"
    assert db.get_application(conn, "2")["status"] == "applied"
    assert db.get_application(conn, "3")["status"] == "interview"
    # the transition is recorded on the timeline (reversible audit trail)
    ev = db.get_events(conn, "1")
    assert ev[0]["kind"] == "status_change"
    assert ev[0]["from_status"] == "applied" and ev[0]["to_status"] == "no_response"
    # idempotent: a second pass ages nothing (it's no longer 'Applied')
    assert db.age_stale_applications(conn, now="2026-06-24T10:00:00") == 0


def test_funnel_reports_stalled_dormant_and_stage_time(conn):
    db.set_application_status(conn, "1", "interview", now="2026-06-01T10:00:00")  # 23d stalled
    db.set_application_status(conn, "2", "applied", now="2026-06-22T10:00:00")    # 2d fresh
    db.set_application_status(conn, "3", "applied", now="2026-01-01T10:00:00")    # 174d dormant
    f = db.application_funnel(conn, now="2026-06-24T10:00:00")
    assert f["stalled_count"] == 1
    assert f["dormant_count"] == 1
    assert f["by_stage_time"]["Interview"] == 23.0


def test_backfill_initial_status_events(conn):
    # Simulate a pre-timeline imported row: an application with applied_at but no events.
    conn.execute(
        'INSERT INTO applications ("job_id","status","status_category","applied_at",'
        '"updated_at","notes","source") VALUES (?,?,?,?,?,?,?)',
        ("imp1", "applied", "Applied", "2026-03-01T10:00:00", "2026-03-01T10:00:00", "", "import"),
    )
    conn.commit()
    assert db.get_events(conn, "imp1") == []

    n = db.backfill_initial_status_events(conn)
    assert n == 1
    ev = db.get_events(conn, "imp1")
    assert len(ev) == 1
    assert ev[0]["kind"] == "status_change"
    assert ev[0]["from_status"] is None and ev[0]["to_status"] == "applied"
    assert ev[0]["ts"] == "2026-03-01T10:00:00"  # anchored at applied_at, not now

    # Idempotent: a second run seeds nothing.
    assert db.backfill_initial_status_events(conn) == 0

    # An app that already has a status_change is left untouched.
    db.set_application_status(conn, "x", "interview", now="2026-06-01T10:00:00")
    before = db.get_events(conn, "x")
    db.backfill_initial_status_events(conn)
    assert db.get_events(conn, "x") == before


def test_get_and_delete_application(conn):
    assert db.get_application(conn, "nope") is None
    db.set_application_status(conn, "1", "applied", now="2026-06-16T10:00:00")
    assert db.delete_application(conn, "1") == 1
    assert db.get_application(conn, "1") is None
    assert db.delete_application(conn, "1") == 0
