"""db.py — the SQLite layer (canonical data store).

SQLite is the contract between the pipeline and any frontend. The xlsx/CSV files
are exports (see export.py), not the engine.

Two tables:
  - jobs:   the mother accumulator, one row per job_id. first_seen is fixed;
            last_seen / applicants / job_state refresh on re-sighting; never deleted.
  - scores: scoring sidecar, one row per job_id (match_score, reasons, status, date).

Readers return pandas DataFrames so the downstream pandas logic (filter, surface,
market) stays simple.
"""

from __future__ import annotations

import datetime
import json
import re
import sqlite3

import pandas as pd

from . import paths, status

# v9: fresh DBs no longer create `score_runs` (the compare/calibration sidecar went away
# with the local+llm_api backends). Deliberately NOT dropped on existing DBs: it holds
# real calibration rows and jobcut never deletes user data. It is simply inert — nothing
# reads or writes it, and a fresh install never grows one.
SCHEMA_VERSION = 10


def _now_iso() -> str:
    """UTC-aware 'now' for stamping event/application timestamps (B-19).

    Stored as `…+00:00` so the value is self-describing: the web localizes it to the
    user's zone instead of mis-reading a naive string as local time (the 2h-off bug).
    """
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _parse_ts(ts: str | None) -> datetime.datetime | None:
    """Parse a stored ISO timestamp as an aware UTC datetime, or None if unparseable.

    Legacy rows were stamped naive but in a UTC environment, so a naive value means UTC.
    Normalizing both naive (old) and offset-tagged (new) to UTC lets the aging math
    subtract them against each other without the offset-naive/aware TypeError.
    """
    if not ts:
        return None
    try:
        dt = datetime.datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


# jobs columns — mirror pull.flatten() output. job_id is the primary key.
JOB_COLS = [
    "job_id", "source_searches", "first_seen", "last_seen",
    "title", "linkedin_url", "posted_date", "expire_at", "job_state",
    "workplace_type", "work_remote_allowed", "employment_type", "experience_level",
    "location", "applicants", "job_functions", "industries",
    "company_name", "company_size", "company_industry", "company_website", "company_linkedin",
    "ats", "apply_url", "easy_apply_url",
    "recruiter_name", "recruiter_position", "recruiter_url",
    "description", "salary_text", "salary_min", "salary_max",
]

# fields refreshed when a known offer reappears (everything else stays stable)
VOLATILE = ["last_seen", "applicants", "job_state"]

# `backend` (v4): which scorer produced this row (rule_based|claude_skills). "" for rows
# written before v4. Free text, no CHECK: historical rows may carry ids that jobcut no
# longer offers (`local`, `llm_api` — removed in v9) and must keep rendering.
# `skills_matched`/`skills_missing` (v10): JSON-in-TEXT — a Claude/Cowork per-offer skill
# judgment (list of {skill, note}) written by `ingest-scores`. "" for rows without one
# (rule_based, or claude rows scored before v10); the API falls back to the taxonomy-regex
# match in that case. Free-form: skills need not be in the taxonomy (semantic, from profile.md).
SCORE_COLS = ["job_id", "canonical_id", "match_score", "match_reasons", "status", "scored_date",
              "backend", "skills_matched", "skills_missing"]

# applications: user-owned application status. Separate from `scores` (derived) so a
# re-score never clobbers it. PK job_id, no FK (manual/imported rows may have no job).
# v5 adds structured "what do I do now" columns (all nullable, additive).
APPLICATION_COLS = ["job_id", "status", "status_category", "applied_at", "updated_at", "notes", "source",
                    "priority", "next_action", "next_action_date", "contact", "cv_version"]

# application_events (v5): append-only timeline — status history, timestamped notes,
# interview rounds — in one structure. Written ONLY by the applications path (never by
# scoring), so the re-score invariant holds. `meta` is JSON-in-TEXT so per-event detail
# can grow without another schema bump. See docs/adr-002.
APPLICATION_EVENT_COLS = ["event_id", "job_id", "ts", "kind", "from_status", "to_status", "body", "meta"]

# application_documents (v8): prep/debrief/study markdown a user's AI assistant produces
# around each stage of a process, attached to an application and optionally anchored to a
# specific timeline event (`event_id` → application_events.event_id; NULL = offer-level).
# Its OWN table (like scores/salary_estimates), never overloads application_events: docs are
# long, versioned (`supersedes_id`), idempotently re-ingested (`client_key`) and soft-deletable
# (`archived_at`) — the lean activity timeline stays an activity log; docs hang off it. Written
# only via the ingest bridge (`ingest-documents`), read-only in the console. See PRD-prep-docs.
APPLICATION_DOCUMENT_COLS = ["doc_id", "job_id", "event_id", "doc_type", "title", "body",
                            "created_at", "updated_at", "supersedes_id", "client_key",
                            "archived_at", "meta"]

# salary_estimates (v7): a Claude/Cowork-produced salary band for offers where the
# employer did NOT disclose one. Its OWN table (like `scores`) — derived + re-derivable,
# so it never lives in the immutable `jobs` accumulator and never touches the disclosed
# `salary_*` columns. Keeping it out of `jobs` also means market.salary_pct (disclosure)
# stays correct with zero changes. `source` is who produced it (e.g. cowork_web); `basis`
# is the human-readable rationale/source ("Levels.fyi/Glassdoor, Madrid mid BI ~45–55k").
SALARY_ESTIMATE_COLS = ["job_id", "est_min", "est_max", "currency", "period", "basis", "source", "estimated_at"]


def db_path():
    """Canonical SQLite file location."""
    return paths.data_dir() / "jobcut.db"


# DDL (CREATE IF NOT EXISTS + migrations) is idempotent but only needs to run once
# per db file per process. The API opens a fresh connection per request (WAL isn't
# safe to share across threads), so this avoids re-running the schema script on every
# request while keeping connections per-request and thread-safe.
_schema_ready: set[str] = set()


def connect(path=None) -> sqlite3.Connection:
    """Open (creating if needed) the SQLite database and ensure the schema exists."""
    p = path or db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: FastAPI runs sync dependencies and endpoints on
    # different threadpool threads, so a per-request connection opened in the
    # dependency thread is used in the endpoint thread. Connections are never
    # shared across requests, so disabling the same-thread guard is safe here.
    conn = sqlite3.connect(str(p), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")        # per-connection pragmas (cheap, kept)
    conn.execute("PRAGMA foreign_keys=ON")
    key = str(p.resolve())
    if key not in _schema_ready:
        init_schema(conn)                          # idempotent DDL — once per file per process
        _schema_ready.add(key)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create tables and run migrations. Idempotent."""
    cols_sql = ",\n  ".join(f'"{c}" TEXT' for c in JOB_COLS if c != "job_id")
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS jobs (
          "job_id" TEXT PRIMARY KEY,
          {cols_sql}
        );
        CREATE TABLE IF NOT EXISTS scores (
          "job_id" TEXT PRIMARY KEY,
          "canonical_id" TEXT,
          "match_score" INTEGER,
          "match_reasons" TEXT,
          "status" TEXT,
          "scored_date" TEXT,
          "backend" TEXT DEFAULT '',
          "skills_matched" TEXT DEFAULT '',
          "skills_missing" TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS applications (
          "job_id" TEXT PRIMARY KEY,
          "status" TEXT NOT NULL,
          "status_category" TEXT NOT NULL,
          "applied_at" TEXT,
          "updated_at" TEXT,
          "notes" TEXT DEFAULT '',
          "source" TEXT DEFAULT 'manual'
        );
        CREATE TABLE IF NOT EXISTS application_events (
          "event_id" INTEGER PRIMARY KEY AUTOINCREMENT,
          "job_id" TEXT NOT NULL,
          "ts" TEXT NOT NULL,
          "kind" TEXT NOT NULL,
          "from_status" TEXT,
          "to_status" TEXT,
          "body" TEXT DEFAULT '',
          "meta" TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS salary_estimates (
          "job_id" TEXT PRIMARY KEY,
          "est_min" INTEGER,
          "est_max" INTEGER,
          "currency" TEXT,
          "period" TEXT DEFAULT 'year',
          "basis" TEXT,
          "source" TEXT DEFAULT 'cowork_web',
          "estimated_at" TEXT
        );
        CREATE TABLE IF NOT EXISTS application_documents (
          "doc_id" INTEGER PRIMARY KEY AUTOINCREMENT,
          "job_id" TEXT NOT NULL,
          "event_id" INTEGER,
          "doc_type" TEXT DEFAULT 'prep',
          "title" TEXT NOT NULL,
          "body" TEXT NOT NULL,
          "created_at" TEXT,
          "updated_at" TEXT,
          "supersedes_id" INTEGER,
          "client_key" TEXT,
          "archived_at" TEXT,
          "meta" TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS _meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE INDEX IF NOT EXISTS idx_jobs_first_seen ON jobs(first_seen);
        CREATE INDEX IF NOT EXISTS idx_scores_date ON scores(scored_date);
        CREATE INDEX IF NOT EXISTS idx_applications_category ON applications(status_category);
        CREATE INDEX IF NOT EXISTS idx_app_events_job ON application_events(job_id);
        CREATE INDEX IF NOT EXISTS idx_app_docs_job ON application_documents(job_id);
        CREATE INDEX IF NOT EXISTS idx_app_docs_event ON application_documents(event_id);
        CREATE INDEX IF NOT EXISTS idx_app_docs_client ON application_documents(job_id, client_key);
        """
    )
    # v4: add scores.backend for DBs created before v4 (CREATE handles fresh DBs).
    # ALTER because CREATE TABLE IF NOT EXISTS won't add a column to an existing table.
    score_cols = {r[1] for r in conn.execute("PRAGMA table_info(scores)").fetchall()}
    if "backend" not in score_cols:
        conn.execute("ALTER TABLE scores ADD COLUMN \"backend\" TEXT DEFAULT ''")

    # v10: per-offer Claude skill judgment (JSON-in-TEXT), additive + nullable.
    for col in ("skills_matched", "skills_missing"):
        if col not in score_cols:
            conn.execute(f'ALTER TABLE scores ADD COLUMN "{col}" TEXT DEFAULT \'\'')

    # v5: add structured tracking columns for DBs created before v5 (nullable, additive).
    app_cols = {r[1] for r in conn.execute("PRAGMA table_info(applications)").fetchall()}
    for col in ("priority", "next_action", "next_action_date", "contact", "cv_version"):
        if col not in app_cols:
            conn.execute(f'ALTER TABLE applications ADD COLUMN "{col}" TEXT')

    # v6: interview-process tracking columns (additive; see ADR-002 + B-2 spec).
    if "process_stages" not in app_cols:
        conn.execute('ALTER TABLE applications ADD COLUMN "process_stages" TEXT')
    if "process_current" not in app_cols:
        conn.execute('ALTER TABLE applications ADD COLUMN "process_current" INTEGER DEFAULT 0')

    row = conn.execute("SELECT value FROM _meta WHERE key='schema_version'").fetchone()
    if row is None:
        conn.execute("INSERT INTO _meta(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
    elif int(row["value"]) < SCHEMA_VERSION:
        # Migrations are additive (the CREATE TABLE IF NOT EXISTS above already ran);
        # bump the recorded version. Add ALTERs here for future, non-additive changes.
        conn.execute("UPDATE _meta SET value = ? WHERE key = 'schema_version'", (str(SCHEMA_VERSION),))
    conn.commit()


def _merge_sources(*vals) -> str:
    s = set()
    for v in vals:
        if v:
            s.update(str(v).split("|"))
    return "|".join(sorted(x for x in s if x))


def upsert_jobs(conn: sqlite3.Connection, today_agg: dict, today: str) -> tuple[int, int]:
    """Apply today's aggregated rows ({job_id: row}) to the jobs table.

    New job_id -> insert with first_seen=last_seen=today.
    Known job_id -> refresh VOLATILE fields + union source_searches; stable fields
    (title, description, ...) are left untouched, matching the original pipeline.

    Returns (inserted, updated).
    """
    if not today_agg:
        return (0, 0)
    ids = list(today_agg.keys())
    placeholders = ",".join("?" * len(ids))
    existing = {
        r["job_id"]: r
        for r in conn.execute(
            f"SELECT job_id, source_searches FROM jobs WHERE job_id IN ({placeholders})", ids
        ).fetchall()
    }
    inserted = updated = 0
    insert_sql = (
        f'INSERT INTO jobs ({",".join(chr(34)+c+chr(34) for c in JOB_COLS)}) '
        f'VALUES ({",".join("?" * len(JOB_COLS))})'
    )
    for jid, row in today_agg.items():
        if jid in existing:
            merged = _merge_sources(existing[jid]["source_searches"], row.get("source_searches"))
            sets = ["source_searches = ?", "last_seen = ?"]
            params = [merged, row.get("last_seen", today)]
            # only overwrite applicants/job_state when the new value is non-empty
            if str(row.get("applicants", "")).strip():
                sets.append("applicants = ?"); params.append(str(row["applicants"]))
            if str(row.get("job_state", "")).strip():
                sets.append("job_state = ?"); params.append(str(row["job_state"]))
            params.append(jid)
            conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE job_id = ?", params)
            updated += 1
        else:
            r = dict(row)
            r.setdefault("first_seen", today)
            r.setdefault("last_seen", today)
            conn.execute(insert_sql, [str(r.get(c, "") if r.get(c) is not None else "") for c in JOB_COLS])
            inserted += 1
    conn.commit()
    return inserted, updated


def upsert_scores(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Upsert score rows by job_id (last write wins). Returns count written."""
    if not rows:
        return 0
    sql = (
        f'INSERT INTO scores ({",".join(chr(34)+c+chr(34) for c in SCORE_COLS)}) '
        f'VALUES ({",".join("?" * len(SCORE_COLS))}) '
        f'ON CONFLICT(job_id) DO UPDATE SET '
        + ", ".join(f'"{c}" = excluded."{c}"' for c in SCORE_COLS if c != "job_id")
    )
    conn.executemany(sql, [[r.get(c, "") for c in SCORE_COLS] for r in rows])
    conn.commit()
    return len(rows)


def scored_ids(conn: sqlite3.Connection, backend: str | None = None) -> set[str]:
    """job_ids that already have a score (for incremental filtering).

    ``backend`` narrows to rows produced by that scorer (e.g. ``claude_skills``) — used to
    find jobs that still need scoring *by a specific backend*: a rule_based-floored job is
    "scored" for the plain query but NOT scored by ``claude_skills``.
    """
    if backend is None:
        return {r["job_id"] for r in conn.execute("SELECT job_id FROM scores").fetchall()}
    return {r["job_id"] for r in
            conn.execute("SELECT job_id FROM scores WHERE backend = ?", (backend,)).fetchall()}


def upsert_salary_estimates(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Upsert salary-estimate rows by job_id (last write wins). Returns count written.

    Writes ONLY to salary_estimates — never touches jobs (disclosed salary) or scores,
    so re-estimating is as safe as a re-score."""
    if not rows:
        return 0
    sql = (
        f'INSERT INTO salary_estimates ({",".join(chr(34)+c+chr(34) for c in SALARY_ESTIMATE_COLS)}) '
        f'VALUES ({",".join("?" * len(SALARY_ESTIMATE_COLS))}) '
        f'ON CONFLICT(job_id) DO UPDATE SET '
        + ", ".join(f'"{c}" = excluded."{c}"' for c in SALARY_ESTIMATE_COLS if c != "job_id")
    )
    conn.executemany(sql, [[r.get(c) for c in SALARY_ESTIMATE_COLS] for r in rows])
    conn.commit()
    return len(rows)


def get_salary_estimate_row(conn: sqlite3.Connection, job_id: str):
    """One salary-estimate row by primary key (O(1)); None if not estimated."""
    return conn.execute(
        "SELECT * FROM salary_estimates WHERE job_id = ?", (str(job_id),)
    ).fetchone()


def read_jobs(conn: sqlite3.Connection, columns: list[str] | None = None) -> pd.DataFrame:
    """The jobs table as a DataFrame (job_id as str).

    Pass `columns` to read a subset — the heavy `description` (and other long text)
    dominates the read cost, so latency-sensitive callers (the shortlist) skip it.
    """
    sel = "*" if not columns else ", ".join(f'"{c}"' for c in columns)
    df = pd.read_sql_query(f"SELECT {sel} FROM jobs", conn)
    if not df.empty:
        df["job_id"] = df["job_id"].astype(str)
    return df


def read_scores(conn: sqlite3.Connection) -> pd.DataFrame:
    """The scores table as a DataFrame (job_id as str)."""
    df = pd.read_sql_query("SELECT * FROM scores", conn)
    if not df.empty:
        df["job_id"] = df["job_id"].astype(str)
    return df


def count_jobs(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]


def get_job_row(conn: sqlite3.Connection, job_id: str):
    """One job row by primary key (O(1)) — avoids reading the whole table into pandas."""
    return conn.execute("SELECT * FROM jobs WHERE job_id = ?", (str(job_id),)).fetchone()


def get_score_row(conn: sqlite3.Connection, job_id: str):
    """One score row by primary key (O(1))."""
    return conn.execute("SELECT * FROM scores WHERE job_id = ?", (str(job_id),)).fetchone()


# --- applications: user-owned status (the funnel) ---------------------------

def set_application_status(conn: sqlite3.Connection, job_id: str, status_value: str,
                          notes: str | None = None, source: str = "manual",
                          now: str | None = None) -> None:
    """Upsert an application's status (the single write choke-point for the funnel).

    `status_category` is derived via status.classify(). `applied_at` is set once (at
    first apply) and preserved across updates; `updated_at` refreshes every time.
    `notes` is left untouched when None. `now` is injectable for deterministic tests.
    """
    now = now or _now_iso()
    jid = str(job_id)
    category = status.classify(status_value)
    existing = conn.execute(
        "SELECT status, applied_at, notes FROM applications WHERE job_id = ?", (jid,)
    ).fetchone()
    from_status = existing["status"] if existing is not None else None
    if existing is None:
        conn.execute(
            'INSERT INTO applications ("job_id","status","status_category",'
            '"applied_at","updated_at","notes","source") VALUES (?,?,?,?,?,?,?)',
            (jid, status_value, category, now, now, notes or "", source),
        )
    else:
        kept_notes = existing["notes"] if notes is None else notes
        conn.execute(
            'UPDATE applications SET status = ?, status_category = ?, updated_at = ?, '
            'notes = ?, source = ? WHERE job_id = ?',
            (status_value, category, now, kept_notes, source, jid),
        )
    # v5: record the transition on the append-only timeline, in the SAME transaction
    # (status history → time-in-stage / stalled). Skip no-op re-saves of the same status.
    if from_status != status_value:
        conn.execute(
            'INSERT INTO application_events ("job_id","ts","kind","from_status","to_status","body","meta") '
            'VALUES (?,?,?,?,?,?,?)',
            (jid, now, "status_change", from_status, status_value, "", ""),
        )
    conn.commit()


def read_applications(conn: sqlite3.Connection) -> pd.DataFrame:
    """The applications table as a DataFrame (job_id as str)."""
    df = pd.read_sql_query("SELECT * FROM applications", conn)
    if not df.empty:
        df["job_id"] = df["job_id"].astype(str)
    return df


def read_applications_enriched(conn: sqlite3.Connection) -> pd.DataFrame:
    """Applications LEFT JOINed to their job's title/company in one query.

    Lets the API return display-ready rows so the console doesn't have to fetch each
    job separately (the old N+1). LEFT JOIN + COALESCE so manual/pruned rows still
    appear with empty title/company.
    """
    df = pd.read_sql_query(
        "SELECT a.*, COALESCE(j.title, '') AS title, COALESCE(j.company_name, '') AS company_name "
        "FROM applications a LEFT JOIN jobs j ON j.job_id = a.job_id",
        conn,
    )
    if not df.empty:
        df["job_id"] = df["job_id"].astype(str)
    return df


def get_application(conn: sqlite3.Connection, job_id: str) -> dict | None:
    """One application row as a dict, or None if absent."""
    row = conn.execute("SELECT * FROM applications WHERE job_id = ?", (str(job_id),)).fetchone()
    return dict(row) if row is not None else None


# Structured tracking fields (v5) — written by PATCH, never touch status/funnel.
APPLICATION_FIELDS = ("priority", "next_action", "next_action_date", "contact", "cv_version")


def update_application_fields(conn: sqlite3.Connection, job_id: str, fields: dict,
                             now: str | None = None) -> dict | None:
    """Patch structured columns (priority/next_action/…) WITHOUT touching status.

    Returns the updated row, or None if no application exists (caller 404s). Never
    creates a row — the funnel only ever reflects real status writes.
    """
    sets = {k: v for k, v in fields.items() if k in APPLICATION_FIELDS}
    row = conn.execute("SELECT 1 FROM applications WHERE job_id = ?", (str(job_id),)).fetchone()
    if row is None:
        return None
    if sets:
        now = now or _now_iso()
        assignments = ", ".join(f'"{k}" = ?' for k in sets) + ', "updated_at" = ?'
        conn.execute(
            f"UPDATE applications SET {assignments} WHERE job_id = ?",
            [*sets.values(), now, str(job_id)],
        )
        conn.commit()
    return get_application(conn, job_id)


def set_process(conn: sqlite3.Connection, job_id: str, stages: list[str],
                current: int | None = None, now: str | None = None) -> dict | None:
    """Set the interview-stage plan for an application. Returns the updated row,
    or None if the application doesn't exist (caller 404s). Never touches status.

    Blank/whitespace stage names are stripped. An all-blank input is a no-op:
    the existing row is returned unchanged so an accidental empty write can't
    silently wipe a stored plan. `current` is clamped to 0..len(stages) relative
    to the *filtered* list.
    """
    jid = str(job_id)
    if conn.execute("SELECT 1 FROM applications WHERE job_id = ?", (jid,)).fetchone() is None:
        return None
    stages = [str(s).strip() for s in stages if str(s).strip()]
    if not stages:
        return get_application(conn, jid)
    cur = 0 if current is None else max(0, min(int(current), len(stages)))
    now = now or _now_iso()
    conn.execute(
        'UPDATE applications SET process_stages = ?, process_current = ?, updated_at = ? '
        'WHERE job_id = ?',
        (json.dumps(stages, ensure_ascii=False), cur, now, jid),
    )
    conn.commit()
    return get_application(conn, jid)


def advance_process(conn: sqlite3.Connection, job_id: str, note: str = "",
                    date: str | None = None, now: str | None = None) -> dict | None:
    """Mark the current interview stage done: bump process_current (capped) and log
    one kind='interview' event. Returns {application, event, completed} or None if the
    application has no process defined. Never touches status."""
    jid = str(job_id)
    app = get_application(conn, jid)
    if app is None or not app.get("process_stages"):
        return None
    stages = json.loads(app["process_stages"])
    if not stages:
        return None
    cur = int(app.get("process_current") or 0)
    # Normalize a date-only `date` (YYYY-MM-DD) to noon so same-day rounds order
    # stably against other events; a `date` already carrying `T…` is left as-is.
    if date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        date = f"{date}T12:00:00"
    ts = date or now or _now_iso()
    event = None
    if cur < len(stages):
        stage_name = stages[cur]
        cur += 1
        # Stage the increment first WITHOUT committing, then let add_event()'s own
        # conn.commit() (same connection) flush the UPDATE and the event INSERT together
        # as one transaction — a crash can't leave process_current and the timeline out of
        # sync. add_event must stay last; it owns the single commit.
        conn.execute(
            'UPDATE applications SET process_current = ?, updated_at = ? WHERE job_id = ?',
            (cur, ts, jid))
        event = add_event(conn, jid, "interview", body=note,
                          meta=json.dumps({"stage": stage_name, "index": cur},
                                          ensure_ascii=False), now=ts)
    return {"application": get_application(conn, jid), "event": event,
            "completed": cur >= len(stages)}


def delete_application(conn: sqlite3.Connection, job_id: str) -> int:
    """Delete an application and its timeline (logical cascade). Returns rows removed (0 or 1)."""
    jid = str(job_id)
    conn.execute("DELETE FROM application_events WHERE job_id = ?", (jid,))
    cur = conn.execute("DELETE FROM applications WHERE job_id = ?", (jid,))
    conn.commit()
    return cur.rowcount


# --- application_events: append-only timeline (v5) --------------------------

def add_event(conn: sqlite3.Connection, job_id: str, kind: str, body: str = "",
              meta: str = "", from_status: str | None = None,
              to_status: str | None = None, now: str | None = None) -> dict:
    """Append one event to the timeline. Never updates/deletes history. Returns the row.

    Notes (kind='note') do NOT require an application row — this is the solo-note
    write-path that no longer fabricates an 'applied' status.
    """
    ts = now or _now_iso()
    cur = conn.execute(
        'INSERT INTO application_events ("job_id","ts","kind","from_status","to_status","body","meta") '
        'VALUES (?,?,?,?,?,?,?)',
        (str(job_id), ts, kind, from_status, to_status, body or "", meta or ""),
    )
    # Notes live ONLY in the timeline (append-only). We deliberately do NOT mirror a
    # note's body back into applications.notes: that field is the status-change note
    # (set via set_application_status), and clobbering it on every note led callers to
    # re-paste the whole prior summary into each new note "to avoid losing it" — which
    # duplicated the timeline. The timeline is the history; there is nothing to mirror.
    conn.commit()
    row = conn.execute("SELECT * FROM application_events WHERE event_id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def get_events(conn: sqlite3.Connection, job_id: str) -> list[dict]:
    """The timeline for a job, most-recent first."""
    rows = conn.execute(
        "SELECT * FROM application_events WHERE job_id = ? ORDER BY ts DESC, event_id DESC",
        (str(job_id),),
    ).fetchall()
    return [dict(r) for r in rows]


# --- application_documents: prep/debrief/study markdown (v8) -----------------

DOC_TYPES = ("prep", "debrief", "study", "other")


def upsert_document(conn: sqlite3.Connection, *, job_id: str, title: str, body: str,
                    event_id: int | None = None, doc_type: str = "prep",
                    supersedes_id: int | None = None, client_key: str | None = None,
                    meta: str = "", now: str | None = None) -> dict:
    """Insert a document, or update in place when (job_id, client_key) already exists.

    Idempotency (D4): a non-empty `client_key` matching an existing row UPDATES it
    (event_id/doc_type/title/body/supersedes_id/meta + `updated_at`), preserving
    `created_at` and `doc_id`. An omitted/empty `client_key` always INSERTs — an un-keyed
    re-ingest makes a new row by design. `doc_type` is coerced to the DOC_TYPES set.
    Returns the stored row.
    """
    ts = now or _now_iso()
    dt = doc_type if doc_type in DOC_TYPES else "other"
    jid = str(job_id)
    key = str(client_key) if client_key else None
    existing = None
    if key:
        existing = conn.execute(
            "SELECT doc_id FROM application_documents WHERE job_id = ? AND client_key = ?",
            (jid, key),
        ).fetchone()
    if existing is not None:
        conn.execute(
            'UPDATE application_documents SET "event_id" = ?, "doc_type" = ?, "title" = ?, '
            '"body" = ?, "updated_at" = ?, "supersedes_id" = ?, "meta" = ? WHERE doc_id = ?',
            (event_id, dt, title, body, ts, supersedes_id, meta or "", existing["doc_id"]),
        )
        doc_id = existing["doc_id"]
    else:
        cur = conn.execute(
            'INSERT INTO application_documents ("job_id","event_id","doc_type","title","body",'
            '"created_at","updated_at","supersedes_id","client_key","archived_at","meta") '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (jid, event_id, dt, title, body, ts, ts, supersedes_id, key, None, meta or ""),
        )
        doc_id = cur.lastrowid
    conn.commit()
    row = conn.execute("SELECT * FROM application_documents WHERE doc_id = ?", (doc_id,)).fetchone()
    return dict(row)


def get_documents(conn: sqlite3.Connection, job_id: str,
                  include_archived: bool = False) -> list[dict]:
    """Documents for an application: offer-level (NULL event_id) first, then by event, then
    creation order. Excludes archived rows unless `include_archived`."""
    sql = "SELECT * FROM application_documents WHERE job_id = ?"
    if not include_archived:
        sql += " AND archived_at IS NULL"
    sql += " ORDER BY (event_id IS NOT NULL), event_id, created_at, doc_id"
    rows = conn.execute(sql, (str(job_id),)).fetchall()
    return [dict(r) for r in rows]


def get_document(conn: sqlite3.Connection, doc_id: int) -> dict | None:
    """One document by id (including body), or None if absent."""
    row = conn.execute(
        "SELECT * FROM application_documents WHERE doc_id = ?", (int(doc_id),)
    ).fetchone()
    return dict(row) if row is not None else None


def set_document_archived(conn: sqlite3.Connection, doc_id: int, archived: bool = True,
                          now: str | None = None) -> dict | None:
    """Soft-delete (`archived=True` stamps `archived_at`) or restore (`False` clears it).
    Never hard-deletes — append-only ethos. Returns the updated row, or None if absent."""
    did = int(doc_id)
    if conn.execute("SELECT 1 FROM application_documents WHERE doc_id = ?", (did,)).fetchone() is None:
        return None
    ts = (now or _now_iso()) if archived else None
    conn.execute("UPDATE application_documents SET archived_at = ? WHERE doc_id = ?", (ts, did))
    conn.commit()
    return get_document(conn, did)


# An open application idle this many days needs a nudge ("stalled"); past DORMANT_DAYS
# it's effectively dead ("dormant") — surfaced as cleanup, not as "follow up now".
STALLED_DAYS = 14
DORMANT_DAYS = 90
# An 'applied' role with no movement for this long is treated as ghosted → No response.
NO_RESPONSE_DAYS = 30


def age_stale_applications(conn: sqlite3.Connection, now: str | None = None) -> int:
    """Auto-age silent 'Applied' rows to 'no_response' after NO_RESPONSE_DAYS of no movement.

    The company never replied — reflect that and keep the funnel honest, instead of nagging
    in "Needs attention". Goes through set_application_status, so it records a status_change
    on the timeline (source='auto:no_response') and is fully reversible. Returns rows aged.
    """
    aged = 0
    for jid, d in stage_durations(conn, now).items():
        if (d["category"] == "Applied" and d["days_in_stage"] is not None
                and d["days_in_stage"] >= NO_RESPONSE_DAYS):
            set_application_status(conn, jid, "no_response", source="auto:no_response", now=now)
            aged += 1
    return aged


def stage_durations(conn: sqlite3.Connection, now: str | None = None) -> dict:
    """Per application: how long it's sat in its current stage, and its activity state.

    Two clocks:
      - `days_in_stage`/`since` = "entered current stage" = the ts of its latest
        `status_change` event; falls back to `applied_at` (then `updated_at`) for rows
        with no recorded transition (e.g. imported trackers). This clock drives the
        Applied->no_response aging and `by_stage_time` — only a real status change resets
        it (a note/interview does NOT advance the stage).
      - last-activity = the ts of the latest event of ANY tracked kind
        (status_change/interview/note/next_action). This clock drives BOTH the `stalled`
        and `dormant` nudges (B-3), so an actively-interviewing app with a recent interview
        round or note is flagged as neither — even if its status hasn't changed in months.
    For an OPEN application (live / Applied / Offer):
      - `stalled`  = no ACTIVITY for STALLED_DAYS+ days, and not already dormant
      - `dormant`  = no ACTIVITY for DORMANT_DAYS+ days (probably dead — archive)
    Returns {job_id: {category, since, days_in_stage, stalled, dormant}}. `now` is
    injectable for deterministic tests.
    """
    now_dt = _parse_ts(now) if now else datetime.datetime.now(datetime.timezone.utc)
    apps = conn.execute(
        "SELECT job_id, status_category, applied_at, updated_at FROM applications"
    ).fetchall()
    # "Entered current stage" = latest status_change — drives time-in-stage, the
    # Applied->no_response aging, by_stage_time, and the dormant flag. Unchanged.
    change_rows = conn.execute(
        "SELECT job_id, MAX(ts) AS since FROM application_events "
        "WHERE kind = 'status_change' GROUP BY job_id"
    ).fetchall()
    last_change = {str(r["job_id"]): r["since"] for r in change_rows}
    # "Last activity" = latest event of any tracked kind — drives the stalled nudge ONLY,
    # so an actively-interviewing app (recent interview/note) isn't flagged stalled (B-3).
    act_rows = conn.execute(
        "SELECT job_id, MAX(ts) AS ts FROM application_events "
        "WHERE kind IN ('status_change','interview','note','next_action') GROUP BY job_id"
    ).fetchall()
    last_activity = {str(r["job_id"]): r["ts"] for r in act_rows}

    def _days(ts):
        parsed = _parse_ts(ts)
        if parsed is None:
            return None
        return (now_dt - parsed).days

    out: dict[str, dict] = {}
    for a in apps:
        jid = str(a["job_id"])
        since = last_change.get(jid) or a["applied_at"] or a["updated_at"]
        days = _days(since)
        activity_days = _days(last_activity.get(jid) or since)
        category = a["status_category"]
        is_open = category in status.OPEN and days is not None
        # Both nudges key off the ACTIVITY clock (B-3): an app touched recently — a new
        # interview round, a note — is neither stalled nor dead, even if its *status* hasn't
        # changed in months. status_change counts as activity, so activity_days <=
        # days_in_stage always → these are a strict subset of the entered-stage thresholds.
        # dormant = no ACTIVITY for DORMANT_DAYS+ (probably dead — archive).
        dormant = bool(is_open and activity_days is not None and activity_days >= DORMANT_DAYS)
        # stalled = no ACTIVITY for STALLED_DAYS+, and not already dormant (needs a nudge).
        stalled = bool(not dormant and activity_days is not None
                       and category in status.STALLABLE and activity_days >= STALLED_DAYS)
        out[jid] = {"category": category, "since": since, "days_in_stage": days,
                    "stalled": stalled, "dormant": dormant}
    return out


def backfill_initial_status_events(conn: sqlite3.Connection) -> int:
    """One-time, idempotent seed of an initial `status_change` for pre-timeline apps.

    Applications imported before the v5 event timeline have no `status_change` history,
    so their "Notes & activity" starts empty. For each application with NO status_change
    event, insert one (None → current status) dated at `applied_at` (fallback `updated_at`),
    tagged meta='backfill'. Additive only — never edits or deletes. Returns rows seeded;
    re-running is a no-op (apps that now have an event are skipped).
    """
    have = {str(r["job_id"]) for r in conn.execute(
        "SELECT DISTINCT job_id FROM application_events WHERE kind = 'status_change'"
    ).fetchall()}
    apps = conn.execute(
        "SELECT job_id, status, applied_at, updated_at FROM applications"
    ).fetchall()
    n = 0
    for a in apps:
        jid = str(a["job_id"])
        if jid in have:
            continue
        ts = a["applied_at"] or a["updated_at"]
        if not ts:
            continue
        conn.execute(
            'INSERT INTO application_events ("job_id","ts","kind","from_status","to_status","body","meta") '
            'VALUES (?,?,?,?,?,?,?)',
            (jid, ts, "status_change", None, a["status"], "", "backfill"),
        )
        n += 1
    conn.commit()
    return n


def application_funnel(conn: sqlite3.Connection, now: str | None = None) -> dict:
    """Funnel KPIs over the applications table (reuses status.summarize).

    Phase 3: also reports `stalled_count` and `by_stage_time` (mean days-in-stage per
    open category) — additive keys, derived from the status-change timeline.
    """
    df = read_applications(conn)
    adapted = df.rename(columns={"status_category": "category", "applied_at": "date"})
    result = status.summarize(adapted)
    durations = stage_durations(conn, now)
    result["stalled_count"] = sum(1 for d in durations.values() if d["stalled"])
    result["dormant_count"] = sum(1 for d in durations.values() if d["dormant"])
    acc: dict[str, list[int]] = {}
    for d in durations.values():
        if d["category"] in status.OPEN and d["days_in_stage"] is not None:
            acc.setdefault(d["category"], []).append(d["days_in_stage"])
    result["by_stage_time"] = {k: round(sum(v) / len(v), 1) for k, v in acc.items()}
    result["reached"] = application_funnel_cumulative(conn)
    return result


# Funnel-stage rank for the cumulative funnel (B-12). Higher = further along.
_STAGE_RANK = {"Offer": 4, "Interview": 3, "Screen": 2, "Active": 2, "Reviewing": 2, "Applied": 1}


def application_funnel_cumulative(conn: sqlite3.Connection) -> dict:
    """How many applications EVER reached each funnel stage, from the event history —
    so a role rejected/ghosted after an interview still counts toward "reached interview"
    (the current-status funnel drops it into a terminal bucket). Returns
    {applied, screen, interview, offer}. Saved (non-funnel) rows are excluded.

    Per app, the max stage rank it ever touched: its current category, plus every
    `status_change` destination and any `interview` round in the timeline; baseline is
    Applied for any non-Saved row (it did apply).
    """
    max_rank: dict[str, int] = {}
    for a in conn.execute("SELECT job_id, status_category FROM applications").fetchall():
        if a["status_category"] in status.NON_FUNNEL:
            continue
        jid = str(a["job_id"])
        max_rank[jid] = max(1, _STAGE_RANK.get(a["status_category"], 0))
    for e in conn.execute(
        "SELECT job_id, kind, to_status FROM application_events "
        "WHERE kind IN ('status_change','interview')").fetchall():
        jid = str(e["job_id"])
        if jid not in max_rank:  # Saved or no application row
            continue
        rank = 3 if e["kind"] == "interview" else _STAGE_RANK.get(status.classify(e["to_status"] or ""), 0)
        if rank > max_rank[jid]:
            max_rank[jid] = rank
    ranks = list(max_rank.values())
    return {
        "applied": sum(1 for r in ranks if r >= 1),
        "screen": sum(1 for r in ranks if r >= 2),
        "interview": sum(1 for r in ranks if r >= 3),
        "offer": sum(1 for r in ranks if r >= 4),
    }


def interview_funnel(conn: sqlite3.Connection) -> list[dict]:
    """Stage-conversion funnel by interview index. reached[N] = #apps whose
    process_current >= N; conversion[N] = reached[N+1]/reached[N]. Apps with
    process_current = 0 (no process) are excluded."""
    currents = [int(r["process_current"] or 0)
                for r in conn.execute(
                    "SELECT process_current FROM applications "
                    "WHERE process_current IS NOT NULL AND process_current > 0").fetchall()]
    if not currents:
        return []
    top = max(currents)
    reached = [sum(1 for c in currents if c >= n) for n in range(1, top + 1)]
    out = []
    for i, n in enumerate(range(1, top + 1)):
        nxt = reached[i + 1] if i + 1 < len(reached) else None
        conv = (nxt / reached[i]) if (nxt is not None and reached[i]) else None
        out.append({"stage": n, "reached": reached[i], "conversion": conv})
    return out


def _round_dates(conn, job_id):
    """Sorted list of date objects for an app's kind='interview' events (day granularity)."""
    rows = conn.execute(
        "SELECT ts FROM application_events WHERE job_id = ? AND kind = 'interview' ORDER BY ts",
        (str(job_id),)).fetchall()
    out = []
    for r in rows:
        ts = (r["ts"] or "")[:10]
        try:
            out.append(datetime.date.fromisoformat(ts))
        except ValueError:
            continue
    return out


def process_timing(conn: sqlite3.Connection, job_id: str) -> dict | None:
    """Per-application interview timing from kind='interview' event dates. None if < 2 rounds."""
    dates = _round_dates(conn, job_id)
    if len(dates) < 2:
        return None
    gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    duration = (dates[-1] - dates[0]).days
    return {
        "rounds": len(dates),
        "first": dates[0].isoformat(),
        "last": dates[-1].isoformat(),
        "duration_days": duration,
        "gaps_days": gaps,
        "avg_gap_days": duration / (len(dates) - 1),
    }


def process_timing_summary(conn: sqlite3.Connection) -> dict:
    """Aggregate timing across apps with >= 2 interview rounds."""
    job_ids = [r["job_id"] for r in conn.execute(
        "SELECT DISTINCT job_id FROM application_events WHERE kind = 'interview'").fetchall()]
    durations, avg_gaps = [], []
    for jid in job_ids:
        t = process_timing(conn, jid)
        if t is not None:
            durations.append(t["duration_days"])
            avg_gaps.append(t["avg_gap_days"])
    n = len(durations)
    return {
        "processes": n,
        "avg_duration_days": (sum(durations) / n) if n else None,
        "avg_gap_days": (sum(avg_gaps) / n) if n else None,
    }
