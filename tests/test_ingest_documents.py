"""Tests for the prep-docs bridge: ingest.ingest_documents + the ingest-documents CLI."""

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


def _write(tmp_path, payload, name="documents.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return path


# --- db-level: ingest.ingest_documents --------------------------------------

def test_document_written_offer_level(conn, tmp_path):
    jid = _seed_job(conn)
    path = _write(tmp_path, {"documents": [
        {"job_id": jid, "doc_type": "prep", "title": "Company research",
         "body": "## Mission\n- ..."},
    ]})
    summary = ingest.ingest_documents(path, conn)
    assert summary == {"written": 1, "archived": 0, "skipped": 0, "errors": [],
                       "unknown_job_ids": []}
    docs = db.get_documents(conn, jid)
    assert len(docs) == 1
    assert docs[0]["title"] == "Company research" and docs[0]["event_id"] is None


def test_bare_list_form_is_documents(conn, tmp_path):
    jid = _seed_job(conn)
    path = _write(tmp_path, [{"job_id": jid, "title": "t", "body": "b"}])
    summary = ingest.ingest_documents(path, conn)
    assert summary["written"] == 1
    assert len(db.get_documents(conn, jid)) == 1


def test_event_anchored_document(conn, tmp_path):
    jid = _seed_job(conn)
    db.set_application_status(conn, jid, "interview", now="2026-06-01T10:00:00")
    ev = db.add_event(conn, jid, "interview", body="R3", now="2026-06-10T12:00:00")
    path = _write(tmp_path, {"documents": [
        {"job_id": jid, "event_id": ev["event_id"], "doc_type": "debrief",
         "title": "R3 debrief", "body": "they asked SQL"},
    ]})
    summary = ingest.ingest_documents(path, conn)
    assert summary["written"] == 1
    assert db.get_documents(conn, jid)[0]["event_id"] == ev["event_id"]


def test_event_id_must_belong_to_job(conn, tmp_path):
    jid = _seed_job(conn, "100")
    other = _seed_job(conn, "200")
    db.set_application_status(conn, other, "interview", now="2026-06-01T10:00:00")
    ev = db.add_event(conn, other, "interview", body="R1", now="2026-06-10T12:00:00")
    # The doc claims job 100 but points at job 200's event → never silently mis-link.
    path = _write(tmp_path, {"documents": [
        {"job_id": jid, "event_id": ev["event_id"], "title": "wrong", "body": "x"},
    ]})
    summary = ingest.ingest_documents(path, conn)
    assert summary["written"] == 0 and summary["skipped"] == 1
    assert any("not an event of this application" in e for e in summary["errors"])
    assert db.get_documents(conn, jid) == []


def test_missing_title_or_body_skipped(conn, tmp_path):
    jid = _seed_job(conn)
    path = _write(tmp_path, {"documents": [
        {"job_id": jid, "title": "", "body": "has body"},     # no title
        {"job_id": jid, "title": "has title", "body": "   "}, # blank body
        {"title": "no job", "body": "b"},                      # missing job_id
    ]})
    summary = ingest.ingest_documents(path, conn)
    assert summary["written"] == 0 and summary["skipped"] == 3
    assert len(summary["errors"]) == 3


def test_idempotent_by_client_key(conn, tmp_path):
    jid = _seed_job(conn)
    p1 = _write(tmp_path, {"documents": [
        {"job_id": jid, "title": "Debrief", "body": "v1", "client_key": "r3-debrief"},
    ]}, name="a.json")
    p2 = _write(tmp_path, {"documents": [
        {"job_id": jid, "title": "Debrief", "body": "v2", "client_key": "r3-debrief"},
    ]}, name="b.json")
    ingest.ingest_documents(p1, conn)
    ingest.ingest_documents(p2, conn)
    docs = db.get_documents(conn, jid)
    assert len(docs) == 1 and docs[0]["body"] == "v2"   # updated in place, no duplicate


def test_meta_dict_is_json_encoded(conn, tmp_path):
    jid = _seed_job(conn)
    path = _write(tmp_path, {"documents": [
        {"job_id": jid, "title": "t", "body": "b", "meta": {"source": "cowork"}},
    ]})
    ingest.ingest_documents(path, conn)
    assert json.loads(db.get_documents(conn, jid)[0]["meta"]) == {"source": "cowork"}


def test_archive_op_hides_document(conn, tmp_path):
    jid = _seed_job(conn)
    d = db.upsert_document(conn, job_id=jid, title="oops", body="b")
    path = _write(tmp_path, {"documents": [], "archive": [{"doc_id": d["doc_id"]}]})
    summary = ingest.ingest_documents(path, conn)
    assert summary["archived"] == 1 and summary["written"] == 0
    assert db.get_documents(conn, jid) == []
    # restore
    p2 = _write(tmp_path, {"archive": [{"doc_id": d["doc_id"], "restore": True}]}, name="r.json")
    ingest.ingest_documents(p2, conn)
    assert len(db.get_documents(conn, jid)) == 1


def test_archive_unknown_doc_reported(conn, tmp_path):
    path = _write(tmp_path, {"archive": [{"doc_id": 99999}, {"restore": True}]})
    summary = ingest.ingest_documents(path, conn)
    assert summary["archived"] == 0 and summary["skipped"] == 2
    assert any("no document with doc_id 99999" in e for e in summary["errors"])
    assert any("missing doc_id" in e for e in summary["errors"])


def test_unknown_job_id_reported_but_write_lands(conn, tmp_path):
    orphan = "tracker:99"
    path = _write(tmp_path, {"documents": [
        {"job_id": orphan, "title": "t", "body": "b"},
    ]})
    summary = ingest.ingest_documents(path, conn)
    assert summary["written"] == 1
    assert summary["unknown_job_ids"] == [orphan]
    assert len(db.get_documents(conn, orphan)) == 1


def test_bad_payload_shape_raises(conn, tmp_path):
    path = _write(tmp_path, "just a string")
    with pytest.raises(ValueError):
        ingest.ingest_documents(path, conn)


# --- CLI: jobcut ingest-documents -------------------------------------------

@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    data = tmp_path / "fresh"
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(data))
    config.reset_cache()
    yield data
    config.reset_cache()


def test_cli_ingest_documents_ok(_isolated, tmp_path, capsys):
    main(["init", "--no-input"])
    path = _write(tmp_path, {"documents": [
        {"job_id": "tracker:1", "title": "Prep", "body": "## notes"},
    ]})
    rc = main(["ingest-documents", str(path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ingest-documents" in out and "wrote 1 document(s)" in out


def test_cli_ingest_documents_missing_file(_isolated, capsys):
    main(["init", "--no-input"])
    rc = main(["ingest-documents", "/no/such/file.json"])
    assert rc == 1
    assert "file not found" in capsys.readouterr().out


def test_cli_ingest_documents_invalid_json(_isolated, tmp_path, capsys):
    main(["init", "--no-input"])
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    rc = main(["ingest-documents", str(bad)])
    assert rc == 1
    assert "invalid documents file" in capsys.readouterr().out
