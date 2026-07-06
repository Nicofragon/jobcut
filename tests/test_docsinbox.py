"""Tests for the documents drop-folder importer (B-22): frontmatter parsing, offer/round
resolution, idempotent re-import, the watcher, and the `import-docs` CLI."""

import json

import pytest

from jobcut import db, docsinbox
from jobcut.cli import main


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def _seed_job(conn, job_id="100", company="Acme", title="Staff Data Analyst"):
    row = {c: "" for c in db.JOB_COLS}
    row.update(job_id=job_id, source_searches="city", title=title, company_name=company,
               location="Madrid, Spain", job_state="LISTED",
               first_seen="2026-01-01", last_seen="2026-01-01")
    db.upsert_jobs(conn, {job_id: row}, "2026-01-01")
    return job_id


def _doc(folder, name, frontmatter, body="# Hello\n\nbody text"):
    fm = "\n".join(f"  {k}: {v}" for k, v in frontmatter.items())
    (folder / name).write_text(f"---\njobcut:\n{fm}\n---\n{body}", encoding="utf-8")
    return folder / name


# --- frontmatter ------------------------------------------------------------

def test_parse_frontmatter_extracts_jobcut_block_and_strips_it():
    meta, body = docsinbox.parse_frontmatter(
        '---\njobcut:\n  job_id: "100"\n  round: R3\n  doc_type: study\n---\n# Title\n\nhi'
    )
    assert meta == {"job_id": "100", "round": "R3", "doc_type": "study"}
    assert body == "# Title\n\nhi"


def test_parse_frontmatter_none_without_jobcut_block():
    # Frontmatter exists but isn't ours → body is left untouched.
    meta, body = docsinbox.parse_frontmatter("---\ntitle: notes\n---\n# Body")
    assert meta is None
    assert body == "---\ntitle: notes\n---\n# Body"


def test_parse_frontmatter_tolerates_bom_and_crlf():
    meta, body = docsinbox.parse_frontmatter('﻿---\r\njobcut:\r\n  job_id: "7"\r\n---\r\nbody')
    assert meta == {"job_id": "7"}
    assert body == "body"


def test_no_frontmatter_is_ignored():
    meta, body = docsinbox.parse_frontmatter("# Just a doc\n\nno meta")
    assert meta is None


# --- offer resolution -------------------------------------------------------

def test_import_by_explicit_job_id(conn, tmp_path):
    jid = _seed_job(conn)
    _doc(tmp_path, "pitch.md", {"job_id": f'"{jid}"', "title": "Pitch", "doc_type": "prep"})
    s = docsinbox.import_dir(tmp_path, conn)
    assert s["written"] == 1 and s["skipped"] == 0
    docs = db.get_documents(conn, jid)
    assert docs[0]["title"] == "Pitch" and docs[0]["doc_type"] == "prep"


def test_resolve_offer_by_company_and_role(conn, tmp_path):
    jid = _seed_job(conn, "555", company="Acme", title="Staff Data Analyst")
    _seed_job(conn, "556", company="Other", title="Staff Data Analyst")
    _doc(tmp_path, "ctx.md", {"company": "Acme", "role": "Data Analyst", "title": "Context"})
    s = docsinbox.import_dir(tmp_path, conn)
    assert s["written"] == 1
    assert db.get_documents(conn, jid)[0]["title"] == "Context"


def test_ambiguous_company_is_skipped_not_mislinked(conn, tmp_path):
    _seed_job(conn, "1", company="Initech", title="Analyst")
    _seed_job(conn, "2", company="Initech", title="Engineer")
    _doc(tmp_path, "x.md", {"company": "Initech"})
    s = docsinbox.import_dir(tmp_path, conn)
    assert s["written"] == 0 and s["skipped"] == 1
    assert "2 offers matched" in s["errors"][0]


def test_unknown_company_is_skipped(conn, tmp_path):
    _seed_job(conn, "1", company="Acme")
    _doc(tmp_path, "x.md", {"company": "Nope"})
    s = docsinbox.import_dir(tmp_path, conn)
    assert s["written"] == 0 and s["skipped"] == 1


# --- round / event resolution ----------------------------------------------

def test_round_resolves_to_unique_interview_event(conn, tmp_path):
    jid = _seed_job(conn)
    ev = db.add_event(conn, jid, "interview", meta=json.dumps({"stage": "Technical", "index": 2}))
    _doc(tmp_path, "r2.md", {"job_id": f'"{jid}"', "round": "R2", "title": "R2 study"})
    docsinbox.import_dir(tmp_path, conn)
    doc = db.get_documents(conn, jid)[0]
    assert doc["event_id"] == ev["event_id"]


def test_ambiguous_round_falls_back_to_offer_level(conn, tmp_path):
    jid = _seed_job(conn)
    db.add_event(conn, jid, "interview", meta=json.dumps({"stage": "HM", "index": 3}))
    db.add_event(conn, jid, "interview", meta=json.dumps({"stage": "HM2", "index": 3}))
    _doc(tmp_path, "r3.md", {"job_id": f'"{jid}"', "round": "R3", "title": "R3"})
    s = docsinbox.import_dir(tmp_path, conn)
    assert s["written"] == 1 and s["offer_level"] == 1
    assert db.get_documents(conn, jid)[0]["event_id"] is None


def test_explicit_event_id_wrong_offer_falls_back_offer_level(conn, tmp_path):
    jid = _seed_job(conn, "100")
    other = _seed_job(conn, "200")
    ev = db.add_event(conn, other, "interview", meta=json.dumps({"index": 1}))
    _doc(tmp_path, "d.md", {"job_id": f'"{jid}"', "event_id": str(ev["event_id"]), "title": "D"})
    s = docsinbox.import_dir(tmp_path, conn)
    assert s["written"] == 1 and s["offer_level"] == 1
    assert db.get_documents(conn, jid)[0]["event_id"] is None


# --- title / client_key / idempotency --------------------------------------

def test_title_defaults_to_h1_then_filename(conn, tmp_path):
    jid = _seed_job(conn)
    (tmp_path / "my_doc.md").write_text(
        f'---\njobcut:\n  job_id: "{jid}"\n---\n# Heading wins\n\nx', encoding="utf-8")
    docsinbox.import_dir(tmp_path, conn)
    assert db.get_documents(conn, jid)[0]["title"] == "Heading wins"


def test_reimport_updates_in_place_no_duplicate(conn, tmp_path):
    jid = _seed_job(conn)
    p = _doc(tmp_path, "pitch.md", {"job_id": f'"{jid}"', "title": "Pitch"}, body="v1")
    docsinbox.import_dir(tmp_path, conn)
    first = db.get_documents(conn, jid)
    assert len(first) == 1 and first[0]["body"] == "v1"

    p.write_text(f'---\njobcut:\n  job_id: "{jid}"\n  title: Pitch\n---\nv2 edited', encoding="utf-8")
    docsinbox.import_dir(tmp_path, conn)
    second = db.get_documents(conn, jid)
    assert len(second) == 1  # same client_key → updated, not duplicated
    assert second[0]["body"] == "v2 edited"
    assert second[0]["doc_id"] == first[0]["doc_id"]


def test_explicit_client_key_is_honored(conn, tmp_path):
    jid = _seed_job(conn)
    _doc(tmp_path, "a.md", {"job_id": f'"{jid}"', "client_key": "my-key", "title": "A"})
    docsinbox.import_dir(tmp_path, conn)
    assert db.get_documents(conn, jid)[0]["client_key"] == "my-key"


# --- watcher ----------------------------------------------------------------

def test_watch_imports_a_changed_file_then_stops(tmp_path, monkeypatch):
    # The watcher opens its own connection (it runs on a thread), so it resolves the DB
    # from JOBCUT_DATA_DIR — seed + verify against that same jobcut.db.
    import threading
    import time
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(tmp_path))
    c = db.connect(tmp_path / "jobcut.db")
    jid = _seed_job(c)
    c.close()

    docsinbox.ensure_dir(tmp_path)
    stop = threading.Event()
    seen = []
    t = threading.Thread(
        target=docsinbox.watch,
        kwargs={"root": tmp_path, "interval": 0.05, "on_import": seen.append, "stop": stop},
        daemon=True,
    )
    t.start()
    time.sleep(0.25)  # let the watcher seed its mtime cache before the file appears
    _doc(tmp_path, "new.md", {"job_id": f'"{jid}"', "title": "Fresh"})

    for _ in range(60):
        if any(s["written"] for s in seen):
            break
        time.sleep(0.05)
    stop.set()
    t.join(timeout=2)

    assert any(s["written"] for s in seen)
    c2 = db.connect(tmp_path / "jobcut.db")
    assert db.get_documents(c2, jid)[0]["title"] == "Fresh"
    c2.close()


# --- CLI --------------------------------------------------------------------

def test_cli_import_docs_dry_run_writes_nothing(tmp_path, capsys, monkeypatch):
    # The CLI resolves its DB from JOBCUT_DATA_DIR → seed the job in that same jobcut.db.
    monkeypatch.setenv("JOBCUT_DATA_DIR", str(tmp_path))
    c = db.connect(tmp_path / "jobcut.db")
    jid = _seed_job(c)
    c.close()
    _doc(tmp_path, "p.md", {"job_id": f'"{jid}"', "title": "P"})

    rc = main(["import-docs", "--dir", str(tmp_path), "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "dry-run" in out and "1 document(s) would be written" in out

    c2 = db.connect(tmp_path / "jobcut.db")
    assert db.get_documents(c2, jid) == []  # dry-run persisted nothing
    c2.close()


def test_readme_is_written_and_ignored(conn, tmp_path):
    docsinbox.ensure_dir(tmp_path)
    assert (tmp_path / "README.md").exists()
    s = docsinbox.import_dir(tmp_path, conn)
    assert s["files"] == 0  # README has no jobcut block → not counted
