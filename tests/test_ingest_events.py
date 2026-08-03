"""Tests for the B-5 write-path bridge: ingest.ingest_events + the ingest-events CLI."""

import json

import pytest

from jobcut import config, db, ingest
from jobcut.cli import main


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def _seed_job(conn, job_id="100"):
    """Insert one known job so the job_id is present in the jobs table."""
    row = {c: "" for c in db.JOB_COLS}
    row.update(job_id=job_id, source_searches="city", title=f"Job {job_id}",
               company_name="Acme", location="Madrid, Spain", applicants="10",
               job_state="LISTED", first_seen="2026-01-01", last_seen="2026-01-01")
    db.upsert_jobs(conn, {job_id: row}, "2026-01-01")
    return job_id


def _write_events(tmp_path, events, name="events.json"):
    path = tmp_path / name
    path.write_text(json.dumps(events))
    return path


# --- db-level: ingest.ingest_events -----------------------------------------

def test_note_appends_to_timeline_without_touching_notes_field(conn, tmp_path):
    jid = _seed_job(conn)
    # A status-change note lives in applications.notes; a timeline note must NOT clobber it.
    db.set_application_status(conn, jid, "applied", notes="referred by Ana")
    path = _write_events(tmp_path, [{"job_id": jid, "kind": "note", "body": "called recruiter"}])

    summary = ingest.ingest_events(path, conn)
    assert summary["written"] == 1
    assert summary["skipped"] == 0

    events = db.get_events(conn, jid)
    notes = [e for e in events if e["kind"] == "note"]
    assert len(notes) == 1
    assert notes[0]["body"] == "called recruiter"
    # The note is history in the timeline only — the status note is left untouched
    # (no mirror, so callers never need to re-paste the prior summary into a new note).
    assert db.get_application(conn, jid)["notes"] == "referred by Ana"


def test_interview_carries_meta_and_normalized_ts(conn, tmp_path):
    jid = _seed_job(conn)
    path = _write_events(tmp_path, [{
        "job_id": jid, "kind": "interview", "body": "R3 con HM",
        "meta": {"stage": "Hiring Manager", "index": 3}, "date": "2026-06-30",
    }])

    summary = ingest.ingest_events(path, conn)
    assert summary["written"] == 1

    ev = [e for e in db.get_events(conn, jid) if e["kind"] == "interview"][0]
    assert ev["ts"] == "2026-06-30T12:00:00"
    assert json.loads(ev["meta"]) == {"stage": "Hiring Manager", "index": 3}
    assert ev["body"] == "R3 con HM"


def test_interview_round_is_idempotent_on_its_index(conn, tmp_path):
    """Re-logging round 2 corrects that round — it never becomes a second interview.

    An assistant told to "catch me up on this process" re-emits rounds 1..N; appending
    them duplicated every round on the timeline and injected 0-day gaps into the timing.
    """
    jid = _seed_job(conn)
    db.set_application_status(conn, jid, "interview")
    round2 = {"job_id": jid, "kind": "interview", "meta": {"stage": "Technical", "index": 2}}
    ingest.ingest_events(_write_events(tmp_path, [{**round2, "date": "2026-06-15"}]), conn)
    ingest.ingest_events(
        _write_events(tmp_path, [{**round2, "body": "moved a week", "date": "2026-06-22"}],
                      name="again.json"), conn)

    rounds = [e for e in db.get_events(conn, jid) if e["kind"] == "interview"]
    assert len(rounds) == 1
    assert rounds[0]["ts"] == "2026-06-22T12:00:00"  # the correction won
    assert rounds[0]["body"] == "moved a week"


def test_interview_round_moves_the_plan_pointer(conn, tmp_path):
    """A round logged by the assistant advances the process like the console's button —
    otherwise it stays invisible to the interview funnel."""
    jid = _seed_job(conn)
    db.set_application_status(conn, jid, "interview")
    db.set_process(conn, jid, ["Recruiter", "Technical", "HM"], current=0)
    ingest.ingest_events(_write_events(tmp_path, [
        {"job_id": jid, "kind": "interview", "meta": {"stage": "Technical", "index": 2},
         "date": "2026-06-15"}]), conn)

    assert db.get_application(conn, jid)["process_current"] == 2
    assert db.rounds_reached(conn)[jid] == 2


def test_interview_round_without_index_takes_the_next_one(conn, tmp_path):
    jid = _seed_job(conn)
    db.set_application_status(conn, jid, "interview")
    ingest.ingest_events(_write_events(tmp_path, [
        {"job_id": jid, "kind": "interview", "body": "first", "date": "2026-06-01"},
        {"job_id": jid, "kind": "interview", "body": "second", "date": "2026-06-08"}]), conn)

    rounds = [e for e in db.get_events(conn, jid) if e["kind"] == "interview"]
    assert len(rounds) == 2  # no index to collide on → two distinct rounds
    assert db.rounds_reached(conn)[jid] == 2


def test_note_stays_append_only(conn, tmp_path):
    """The round-identity rule is scoped to interviews: notes still append, every time."""
    jid = _seed_job(conn)
    db.set_application_status(conn, jid, "applied")
    for _ in range(2):
        ingest.ingest_events(_write_events(tmp_path, [
            {"job_id": jid, "kind": "note", "body": "same text"}], name="n.json"), conn)
    assert len([e for e in db.get_events(conn, jid) if e["kind"] == "note"]) == 2


def test_status_creates_row_and_status_change_event(conn, tmp_path):
    jid = _seed_job(conn)
    assert db.get_application(conn, jid) is None
    path = _write_events(tmp_path, [{"job_id": jid, "status": "interview"}])

    summary = ingest.ingest_events(path, conn)
    assert summary["written"] == 1

    app = db.get_application(conn, jid)
    assert app is not None
    assert app["status"] == "interview"
    assert app["status_category"] == "Interview"

    changes = [e for e in db.get_events(conn, jid) if e["kind"] == "status_change"]
    assert len(changes) == 1
    assert changes[0]["to_status"] == "interview"


def test_fields_patches_known_keys_ignores_unknown(conn, tmp_path):
    jid = _seed_job(conn)
    db.set_application_status(conn, jid, "applied")
    path = _write_events(tmp_path, [{
        "job_id": jid,
        "fields": {"priority": "high", "next_action": "send portfolio", "bogus": "x"},
    }])

    summary = ingest.ingest_events(path, conn)
    assert summary["written"] == 1
    assert summary["skipped"] == 0

    app = db.get_application(conn, jid)
    assert app["priority"] == "high"
    assert app["next_action"] == "send portfolio"
    assert "bogus" not in app


def test_fields_on_nonexistent_app_reported_no_crash(conn, tmp_path):
    jid = _seed_job(conn)  # job exists, but no application row
    path = _write_events(tmp_path, [{"job_id": jid, "fields": {"priority": "high"}}])

    summary = ingest.ingest_events(path, conn)
    assert summary["written"] == 0
    assert summary["skipped"] == 1
    assert any("no application to patch" in e for e in summary["errors"])


def test_lenient_skips_missing_jobid_bad_kind_and_oopless(conn, tmp_path):
    jid = _seed_job(conn)
    path = _write_events(tmp_path, [
        {"kind": "note", "body": "no job_id"},                 # missing job_id
        {"job_id": jid, "kind": "status_change"},              # raw status_change not allowed
        {"job_id": jid, "kind": "foo"},                        # unknown kind
        {"job_id": jid},                                       # no actionable op
    ])

    summary = ingest.ingest_events(path, conn)
    assert summary["written"] == 0
    assert summary["skipped"] == 4
    assert len(summary["errors"]) == 4
    assert any("missing job_id" in e for e in summary["errors"])


def test_unknown_job_ids_reported_but_write_lands(conn, tmp_path):
    # an application for a job_id NOT in the jobs table (orphan tracker case)
    orphan = "tracker:99"
    path = _write_events(tmp_path, [{"job_id": orphan, "kind": "note", "body": "orphan note"}])

    summary = ingest.ingest_events(path, conn)
    assert summary["written"] == 1
    assert summary["unknown_job_ids"] == [orphan]
    # the write still landed
    assert any(e["body"] == "orphan note" for e in db.get_events(conn, orphan))


def test_norm_date_helper():
    assert ingest._norm_date("2026-06-30") == "2026-06-30T12:00:00"
    assert ingest._norm_date("2026-06-30T09:15:00") == "2026-06-30T09:15:00"
    assert ingest._norm_date("") is None
    assert ingest._norm_date(None) is None


# --- CLI: jobcut ingest-events ----------------------------------------------

@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    data = tmp_path / "fresh"
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(data))
    config.reset_cache()
    yield data
    config.reset_cache()


def test_cli_ingest_events_ok(_isolated, tmp_path, capsys):
    main(["init", "--no-input"])
    path = _write_events(tmp_path, [{"job_id": "tracker:1", "status": "applied"}])
    rc = main(["ingest-events", str(path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ingest-events" in out
    assert "wrote 1 update(s)" in out


def test_cli_repair_rounds_dry_run_then_apply(_isolated, capsys):
    main(["init", "--no-input"])
    conn = db.connect()
    db.set_application_status(conn, "1", "interview")
    for idx, date in [(1, "2026-06-01"), (2, "2026-06-08"), (1, "2026-06-15")]:
        db.add_event(conn, "1", "interview", meta=json.dumps({"index": idx}),
                     now=f"{date}T12:00:00")
    conn.close()

    assert main(["repair-rounds"]) == 0
    assert "would remove 1 duplicate round(s)" in capsys.readouterr().out
    conn = db.connect()
    assert len([e for e in db.get_events(conn, "1") if e["kind"] == "interview"]) == 3
    conn.close()

    assert main(["repair-rounds", "--apply"]) == 0
    assert "removed 1 duplicate round(s)" in capsys.readouterr().out
    conn = db.connect()
    assert len([e for e in db.get_events(conn, "1") if e["kind"] == "interview"]) == 2
    conn.close()

    assert main(["repair-rounds"]) == 0
    assert "nothing to repair" in capsys.readouterr().out


def test_cli_ingest_events_missing_file(_isolated, capsys):
    main(["init", "--no-input"])
    rc = main(["ingest-events", "/no/such/file.json"])
    assert rc == 1
    assert "file not found" in capsys.readouterr().out


def test_cli_ingest_events_invalid_json(_isolated, tmp_path, capsys):
    main(["init", "--no-input"])
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    rc = main(["ingest-events", str(bad)])
    assert rc == 1
    assert "invalid events file" in capsys.readouterr().out
