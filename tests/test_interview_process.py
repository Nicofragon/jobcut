import datetime
import json

import pytest
from jobcut import db, process


def test_extract_process_parses_llm_json(monkeypatch):
    monkeypatch.setattr(process.llm, "available", lambda: True)
    monkeypatch.setattr(process.llm, "complete",
                        lambda *a, **k: '["Recruiter screen", "Technical", "Hiring Manager"]')
    stages, source = process.extract_process("Our process: recruiter, technical, HM.")
    assert stages == ["Recruiter screen", "Technical", "Hiring Manager"]
    assert source == "llm"


def test_extract_process_template_when_no_llm(monkeypatch):
    monkeypatch.setattr(process.llm, "available", lambda: False)
    stages, source = process.extract_process("anything")
    assert stages == process.DEFAULT_TEMPLATE and source == "template"


def test_extract_process_template_on_empty_llm(monkeypatch):
    monkeypatch.setattr(process.llm, "available", lambda: True)
    monkeypatch.setattr(process.llm, "complete", lambda *a, **k: "[]")
    stages, source = process.extract_process("no process mentioned")
    assert stages == process.DEFAULT_TEMPLATE and source == "template"


def test_extract_process_template_on_llm_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(process.llm, "available", lambda: True)
    monkeypatch.setattr(process.llm, "complete", boom)
    stages, source = process.extract_process("Our process: recruiter, technical.")
    assert stages == process.DEFAULT_TEMPLATE and source == "template"


def test_extract_process_handles_trailing_prose(monkeypatch):
    monkeypatch.setattr(process.llm, "available", lambda: True)
    monkeypatch.setattr(process.llm, "complete",
                        lambda *a, **k: 'Stages: ["Recruiter","Technical"] adjust [these].')
    stages, source = process.extract_process("recruiter then technical")
    assert stages == ["Recruiter", "Technical"]
    assert source == "llm"


def test_extract_process_blank_description_skips_llm(monkeypatch):
    def fail_if_called(*a, **k):
        raise AssertionError("llm.complete must not be called for a blank description")
    monkeypatch.setattr(process.llm, "available", lambda: True)
    monkeypatch.setattr(process.llm, "complete", fail_if_called)
    stages, source = process.extract_process("   ")
    assert stages == process.DEFAULT_TEMPLATE and source == "template"


def test_extract_process_template_on_nested_array(monkeypatch):
    monkeypatch.setattr(process.llm, "available", lambda: True)
    monkeypatch.setattr(process.llm, "complete", lambda *a, **k: '["A", ["B","C"]]')
    stages, source = process.extract_process("garbage nested output")
    assert stages == process.DEFAULT_TEMPLATE and source == "template"


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def test_migration_adds_process_columns_and_bumps_version(tmp_path):
    p = tmp_path / "v6.db"
    c = db.connect(p)
    cols = {r[1] for r in c.execute("PRAGMA table_info(applications)").fetchall()}
    assert {"process_stages", "process_current"} <= cols
    ver = c.execute("SELECT value FROM _meta WHERE key='schema_version'").fetchone()["value"]
    assert ver == "6"
    c.close()
    # idempotent: reopening must not duplicate columns or error
    c2 = db.connect(p)
    names = [r[1] for r in c2.execute("PRAGMA table_info(applications)").fetchall()]
    assert names.count("process_stages") == 1 and names.count("process_current") == 1
    c2.close()


def test_set_process_stores_stages_and_clamps_current(conn):
    db.set_application_status(conn, "1", "interview", now="2026-06-01T00:00:00")
    out = db.set_process(conn, "1", ["Recruiter", "Técnica", "HM"], current=5)
    assert json.loads(out["process_stages"]) == ["Recruiter", "Técnica", "HM"]
    assert out["process_current"] == 3  # clamped to len(stages)


def test_set_process_returns_none_when_no_application(conn):
    assert db.set_process(conn, "nope", ["A", "B"]) is None


def test_set_process_all_blank_input_is_noop(conn):
    db.set_application_status(conn, "1", "interview", now="2026-06-01T00:00:00")
    db.set_process(conn, "1", ["Recruiter", "Técnica", "HM"])
    out = db.set_process(conn, "1", ["", "  "])  # all-blank → must not wipe
    assert json.loads(out["process_stages"]) == ["Recruiter", "Técnica", "HM"]


def test_advance_increments_logs_event_and_caps(conn):
    db.set_application_status(conn, "1", "interview", now="2026-06-01T00:00:00")
    db.set_process(conn, "1", ["Recruiter", "Técnica", "HM"], current=0)
    r1 = db.advance_process(conn, "1", note="call ok", now="2026-06-02T00:00:00")
    assert r1["application"]["process_current"] == 1
    assert r1["completed"] is False
    assert r1["event"]["kind"] == "interview"
    assert json.loads(r1["event"]["meta"]) == {"stage": "Recruiter", "index": 1}
    # status is untouched
    assert r1["application"]["status"] == "interview"
    db.advance_process(conn, "1", now="2026-06-03T00:00:00")
    r3 = db.advance_process(conn, "1", now="2026-06-04T00:00:00")
    assert r3["application"]["process_current"] == 3 and r3["completed"] is True
    # already at the top: no further increment, no event, still completed
    r4 = db.advance_process(conn, "1", now="2026-06-05T00:00:00")
    assert r4["application"]["process_current"] == 3
    assert r4["event"] is None
    assert r4["completed"] is True
    # exactly one interview event per real stage advance — none for the over-cap call
    assert len([e for e in db.get_events(conn, "1") if e["kind"] == "interview"]) == 3


def test_advance_returns_none_without_process(conn):
    db.set_application_status(conn, "2", "applied", now="2026-06-01T00:00:00")
    assert db.advance_process(conn, "2") is None


def test_advance_returns_none_when_no_application(conn):
    # no application row at all → exercises the `app is None` guard
    assert db.advance_process(conn, "missing-job-id") is None


def test_interview_funnel_counts_reached_and_conversion(conn):
    for jid, cur in [("1", 3), ("2", 2), ("3", 2), ("4", 0)]:
        db.set_application_status(conn, jid, "interview", now="2026-06-01T00:00:00")
        db.set_process(conn, jid, ["A", "B", "C"], current=cur)
    funnel = db.interview_funnel(conn)
    # reached: 1st=3 (jids 1,2,3), 2nd=3, 3rd=1; jid 4 (current 0) excluded
    by_stage = {f["stage"]: f for f in funnel}
    assert by_stage[1]["reached"] == 3
    assert by_stage[2]["reached"] == 3
    assert by_stage[3]["reached"] == 1
    assert round(by_stage[2]["conversion"], 2) == 0.33  # 1/3
    assert by_stage[3]["conversion"] is None


def test_process_timing_three_rounds(conn):
    db.set_application_status(conn, "1", "interview", now="2026-06-01T00:00:00")
    db.set_process(conn, "1", ["R1", "R2", "R3"], current=0)
    for d in ("2026-06-01", "2026-06-08", "2026-06-15"):
        db.add_event(conn, "1", "interview", now=d)
    t = db.process_timing(conn, "1")
    assert t["rounds"] == 3
    assert t["first"] == "2026-06-01" and t["last"] == "2026-06-15"
    assert t["duration_days"] == 14
    assert t["gaps_days"] == [7, 7]
    assert t["avg_gap_days"] == 7.0


def test_process_timing_none_with_one_round(conn):
    db.set_application_status(conn, "1", "interview", now="2026-06-01T00:00:00")
    db.add_event(conn, "1", "interview", now="2026-06-01")
    assert db.process_timing(conn, "1") is None


def test_process_timing_mixes_date_only_and_full_iso(conn):
    db.set_application_status(conn, "1", "interview", now="2026-06-01T00:00:00")
    # date-only + full-ISO ts must parse to the same day granularity
    db.add_event(conn, "1", "interview", now="2026-06-01")
    db.add_event(conn, "1", "interview", now="2026-06-08T12:00:00")
    db.add_event(conn, "1", "interview", now="2026-06-15T09:30:45")
    t = db.process_timing(conn, "1")
    assert t["rounds"] == 3
    assert t["duration_days"] == 14
    assert t["gaps_days"] == [7, 7]
    assert t["avg_gap_days"] == 7.0


def test_process_timing_summary_counts_only_multi_round_apps(conn):
    # app "1": 3 rounds → 14 days, avg gap 7
    db.set_application_status(conn, "1", "interview", now="2026-06-01T00:00:00")
    for d in ("2026-06-01", "2026-06-08", "2026-06-15"):
        db.add_event(conn, "1", "interview", now=d)
    # app "2": 2 rounds → 4 days, avg gap 4
    db.set_application_status(conn, "2", "interview", now="2026-06-01T00:00:00")
    for d in ("2026-06-01", "2026-06-05"):
        db.add_event(conn, "2", "interview", now=d)
    # app "3": 1 round → excluded
    db.set_application_status(conn, "3", "interview", now="2026-06-01T00:00:00")
    db.add_event(conn, "3", "interview", now="2026-06-01")
    s = db.process_timing_summary(conn)
    assert s["processes"] == 2
    assert s["avg_duration_days"] == (14 + 4) / 2  # 9.0
    assert s["avg_gap_days"] == (7.0 + 4.0) / 2    # 5.5


def test_process_timing_summary_empty(conn):
    assert db.process_timing_summary(conn) == {
        "processes": 0, "avg_duration_days": None, "avg_gap_days": None}


def test_advance_process_normalizes_date_only(conn):
    db.set_application_status(conn, "1", "interview", now="2026-06-01T00:00:00")
    db.set_process(conn, "1", ["R1", "R2"], current=0)
    r = db.advance_process(conn, "1", date="2026-06-08")
    assert r["event"]["ts"] == "2026-06-08T12:00:00"


def test_advance_process_without_date_uses_today(conn):
    db.set_application_status(conn, "1", "interview", now="2026-06-01T00:00:00")
    db.set_process(conn, "1", ["R1", "R2"], current=0)
    r = db.advance_process(conn, "1")
    today = datetime.date.today().isoformat()
    assert r["event"]["ts"].startswith(today)


def test_recent_interview_event_clears_stalled(conn):
    # entered Interview 40 days ago (status_change), but had a round 2 days ago.
    db.set_application_status(conn, "1", "interview", now="2026-05-01T00:00:00")
    db.add_event(conn, "1", "interview", body="round 2", now="2026-06-08T00:00:00")
    d = db.stage_durations(conn, now="2026-06-10T00:00:00")["1"]
    assert d["stalled"] is False  # recent activity = not stalled


def test_no_activity_still_stalled(conn):
    db.set_application_status(conn, "2", "interview", now="2026-05-01T00:00:00")
    d = db.stage_durations(conn, now="2026-06-10T00:00:00")["2"]
    assert d["stalled"] is True  # 40 days idle, no events


def test_applied_aging_clock_ignores_notes(conn):
    # A note must NOT reset the entered-stage clock that age_stale_applications uses.
    db.set_application_status(conn, "1", "applied", now="2026-05-01T00:00:00")
    db.add_event(conn, "1", "note", body="ping", now="2026-06-05T00:00:00")
    d = db.stage_durations(conn, now="2026-06-05T00:00:00")["1"]
    assert d["days_in_stage"] == 35  # still measured from the status_change, not the note


def test_dormant_not_suppressed_by_recent_note(conn):
    # 100 days in Interview but a recent note: dormant still fires; stalled does not.
    db.set_application_status(conn, "2", "interview", now="2026-03-01T00:00:00")
    db.add_event(conn, "2", "note", body="ping", now="2026-06-01T00:00:00")
    d = db.stage_durations(conn, now="2026-06-09T00:00:00")["2"]
    assert d["dormant"] is True and d["stalled"] is False
