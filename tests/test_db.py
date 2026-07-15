"""Tests for the SQLite layer: upsert/dedupe, source union, volatile refresh."""

import datetime
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
    assert not _has_table(conn, "score_runs")   # calibration sidecar, removed in v9


def test_migration_v1_to_current(tmp_path):
    # Build a raw "v1" DB: jobs + _meta(=1), with data, NO applications table.
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


def test_funnel_cumulative_counts_history_not_just_now(conn):
    # 1: Applied → Interview → Rejected (ever reached interview, even though now terminal)
    db.set_application_status(conn, "1", "applied", now="2026-05-01T10:00:00")
    db.set_application_status(conn, "1", "interview", now="2026-05-10T10:00:00")
    db.set_application_status(conn, "1", "rejected", now="2026-05-20T10:00:00")
    # 2: Applied → No response (only ever reached Applied)
    db.set_application_status(conn, "2", "applied", now="2026-05-01T10:00:00")
    db.set_application_status(conn, "2", "no_response", now="2026-06-15T10:00:00")
    # 3: an interview ROUND logged without a status_change to interview (still counts)
    db.set_application_status(conn, "3", "applied", now="2026-05-01T10:00:00")
    db.add_event(conn, "3", "interview", body="R1", now="2026-05-15T10:00:00")
    r = db.application_funnel_cumulative(conn)
    assert r["applied"] == 3
    assert r["screen"] == 2          # 1 and 3 reached interview (>= screen); 2 did not
    assert r["interview"] == 2       # 1 (status history) and 3 (interview round)
    assert r["offer"] == 0
    # the live funnel still shows the current snapshot, the new key is additive
    f = db.application_funnel(conn, now="2026-06-24T10:00:00")
    assert f["reached"] == r
    assert f["counts"].get("Interview") is None  # nobody is *currently* in interview


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


# --- B-19: UTC-aware stamping + mixed naive/aware aging ----------------------

def test_default_stamps_are_utc_aware(conn):
    # A real instant (no injected `now`) is stamped UTC-aware (+00:00), so the web
    # can localize it instead of mis-reading a naive string as local time.
    db.set_application_status(conn, "1", "applied")
    ev = conn.execute(
        "SELECT ts FROM application_events WHERE job_id='1' AND kind='status_change'"
    ).fetchone()["ts"]
    parsed = datetime.datetime.fromisoformat(ev)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == datetime.timedelta(0)
    # add_event default and applications.updated_at follow the same rule
    note = db.add_event(conn, "1", "note", body="hi")
    assert datetime.datetime.fromisoformat(note["ts"]).tzinfo is not None
    app = db.get_application(conn, "1")
    assert datetime.datetime.fromisoformat(app["updated_at"]).utcoffset() == datetime.timedelta(0)


def test_date_only_interview_anchor_stays_naive(conn):
    # A round entered as a calendar date is a date, not an instant — it keeps the
    # naive noon anchor (no offset) so the UI can show it date-only without inventing
    # a time, and `[:10]` day-granularity logic is unaffected.
    db.set_application_status(conn, "1", "interview", now="2026-06-01T10:00:00+00:00")
    db.set_process(conn, "1", ["Recruiter", "Technical"])
    r = db.advance_process(conn, "1", date="2026-06-08")
    assert r["event"]["ts"] == "2026-06-08T12:00:00"


def test_stage_durations_handles_mixed_naive_and_aware(conn):
    # Legacy rows are naive; new rows are aware. The aging math must compare them
    # without the offset-naive/aware TypeError, treating naive as UTC.
    db.set_application_status(conn, "1", "interview", now="2026-06-01T10:00:00")          # naive (legacy)
    db.set_application_status(conn, "2", "interview", now="2026-06-04T10:00:00+00:00")    # aware (new)
    d = db.stage_durations(conn, now="2026-06-21T10:00:00+00:00")
    assert d["1"]["days_in_stage"] == 20 and d["1"]["stalled"] is True
    assert d["2"]["days_in_stage"] == 17 and d["2"]["stalled"] is True


# --- v8: application_documents (prep/debrief/study markdown) -----------------

def test_v8_schema_has_documents_table(conn):
    assert _has_table(conn, "application_documents")
    assert _schema_version(conn) == str(db.SCHEMA_VERSION)


def test_document_insert_and_get(conn):
    d = db.upsert_document(conn, job_id="1", title="R3 prep", body="## Format\n- SQL",
                           event_id=None, doc_type="prep", now="2026-06-20T10:00:00")
    assert d["doc_id"] >= 1
    assert d["created_at"] == "2026-06-20T10:00:00" == d["updated_at"]
    assert d["archived_at"] is None and d["client_key"] is None
    got = db.get_document(conn, d["doc_id"])
    assert got["body"] == "## Format\n- SQL" and got["title"] == "R3 prep"
    assert db.get_document(conn, 99999) is None


def test_document_idempotent_update_by_client_key(conn):
    a = db.upsert_document(conn, job_id="1", title="Debrief", body="v1",
                           client_key="acme-r3-debrief", now="2026-06-20T10:00:00")
    b = db.upsert_document(conn, job_id="1", title="Debrief (edited)", body="v2",
                           client_key="acme-r3-debrief", now="2026-06-21T09:00:00")
    assert b["doc_id"] == a["doc_id"]                 # updated in place, no duplicate
    assert b["body"] == "v2" and b["title"] == "Debrief (edited)"
    assert b["created_at"] == "2026-06-20T10:00:00"   # preserved
    assert b["updated_at"] == "2026-06-21T09:00:00"   # bumped
    assert len(db.get_documents(conn, "1")) == 1


def test_document_null_client_key_always_inserts(conn):
    db.upsert_document(conn, job_id="1", title="A", body="a", now="2026-06-20T10:00:00")
    db.upsert_document(conn, job_id="1", title="B", body="b", now="2026-06-20T10:00:01")
    assert len(db.get_documents(conn, "1")) == 2       # NULL key never dedups


def test_document_type_coerced_to_known_set(conn):
    d = db.upsert_document(conn, job_id="1", title="x", body="y", doc_type="wat")
    assert d["doc_type"] == "other"


def test_get_documents_excludes_archived_and_orders_offer_first(conn):
    # offer-level + event-anchored; archived hidden by default.
    db.set_application_status(conn, "1", "interview", now="2026-06-01T10:00:00")
    ev = db.add_event(conn, "1", "interview", body="R3", now="2026-06-10T12:00:00")
    db.upsert_document(conn, job_id="1", title="event doc", body="b",
                       event_id=ev["event_id"], now="2026-06-11T10:00:00")
    offer = db.upsert_document(conn, job_id="1", title="offer doc", body="b",
                               event_id=None, now="2026-06-12T10:00:00")
    archived = db.upsert_document(conn, job_id="1", title="old", body="b", now="2026-06-13T10:00:00")
    db.set_document_archived(conn, archived["doc_id"], now="2026-06-14T10:00:00")

    docs = db.get_documents(conn, "1")
    assert [d["title"] for d in docs] == ["offer doc", "event doc"]   # offer-level first
    assert all(d["archived_at"] is None for d in docs)               # archived hidden
    assert len(db.get_documents(conn, "1", include_archived=True)) == 3
    assert offer["event_id"] is None


def test_document_archive_and_restore(conn):
    d = db.upsert_document(conn, job_id="1", title="oops", body="b", now="2026-06-20T10:00:00")
    arc = db.set_document_archived(conn, d["doc_id"], now="2026-06-21T10:00:00")
    assert arc["archived_at"] == "2026-06-21T10:00:00"
    assert db.get_documents(conn, "1") == []                          # hidden
    res = db.set_document_archived(conn, d["doc_id"], archived=False)
    assert res["archived_at"] is None
    assert len(db.get_documents(conn, "1")) == 1                      # back
    assert db.set_document_archived(conn, 99999) is None              # unknown id


def test_v9_leaves_an_existing_score_runs_table_alone(tmp_path):
    """v9 stopped creating `score_runs`, but must never drop one that already exists:
    it holds real calibration rows and jobcut does not delete user data. Inert, not gone."""
    p = tmp_path / "v8.db"
    raw = sqlite3.connect(str(p))
    raw.executescript(
        'CREATE TABLE jobs ("job_id" TEXT PRIMARY KEY, "title" TEXT, "first_seen" TEXT);'
        "CREATE TABLE _meta (key TEXT PRIMARY KEY, value TEXT);"
        'CREATE TABLE score_runs ("job_id" TEXT, "backend" TEXT, "match_score" INTEGER,'
        ' "match_reasons" TEXT, "scored_at" TEXT, PRIMARY KEY ("job_id", "backend"));'
        "INSERT INTO score_runs VALUES ('1', 'local', 77, 'old calibration', '2026-01-01');"
        "INSERT INTO _meta(key, value) VALUES ('schema_version', '8');"
    )
    raw.commit()
    raw.close()

    conn = db.connect(p)
    try:
        assert _schema_version(conn) == str(db.SCHEMA_VERSION)
        assert _has_table(conn, "score_runs")
        assert conn.execute("SELECT match_score FROM score_runs").fetchone()[0] == 77
    finally:
        conn.close()


def test_documents_migration_v7_to_v8(tmp_path):
    # A pre-v8 DB (v7 schema, no application_documents table) upgrades additively.
    p = tmp_path / "v7.db"
    raw = sqlite3.connect(str(p))
    raw.executescript(
        'CREATE TABLE jobs ("job_id" TEXT PRIMARY KEY, "title" TEXT, "first_seen" TEXT);'
        "CREATE TABLE _meta (key TEXT PRIMARY KEY, value TEXT);"
        "INSERT INTO jobs(job_id, title, first_seen) VALUES ('1', 'Old Job', '2026-01-01');"
        "INSERT INTO _meta(key, value) VALUES ('schema_version', '7');"
    )
    raw.commit()
    raw.close()

    conn = db.connect(p)
    try:
        assert _schema_version(conn) == str(db.SCHEMA_VERSION)
        assert _has_table(conn, "application_documents")
        assert conn.execute("SELECT title FROM jobs WHERE job_id='1'").fetchone()[0] == "Old Job"
        d = db.upsert_document(conn, job_id="1", title="t", body="b")
        assert db.get_document(conn, d["doc_id"])["title"] == "t"
    finally:
        conn.close()
