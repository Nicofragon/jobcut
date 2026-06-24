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
import sqlite3

import pandas as pd

from . import paths, status

SCHEMA_VERSION = 5

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

# `backend` (v4): which scorer produced this row (rule_based|local|llm_api|claude_skills).
# "" for rows written before v4. Additive — does not change scoring behaviour.
SCORE_COLS = ["job_id", "canonical_id", "match_score", "match_reasons", "status", "scored_date", "backend"]

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

# score_runs (v3): calibration sidecar. One row per (job_id, backend) so several
# backends can be compared side-by-side. ADDITIVE — never touches `scores` (the
# single-backend production table) or its behaviour. Written only by compare mode.
SCORE_RUN_COLS = ["job_id", "backend", "match_score", "match_reasons", "scored_at"]


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
          "backend" TEXT DEFAULT ''
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
        CREATE TABLE IF NOT EXISTS score_runs (
          "job_id" TEXT,
          "backend" TEXT,
          "match_score" INTEGER,
          "match_reasons" TEXT,
          "scored_at" TEXT,
          PRIMARY KEY ("job_id", "backend")
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
        CREATE TABLE IF NOT EXISTS _meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE INDEX IF NOT EXISTS idx_jobs_first_seen ON jobs(first_seen);
        CREATE INDEX IF NOT EXISTS idx_scores_date ON scores(scored_date);
        CREATE INDEX IF NOT EXISTS idx_applications_category ON applications(status_category);
        CREATE INDEX IF NOT EXISTS idx_score_runs_backend ON score_runs(backend);
        CREATE INDEX IF NOT EXISTS idx_app_events_job ON application_events(job_id);
        """
    )
    # v4: add scores.backend for DBs created before v4 (CREATE handles fresh DBs).
    # ALTER because CREATE TABLE IF NOT EXISTS won't add a column to an existing table.
    score_cols = {r[1] for r in conn.execute("PRAGMA table_info(scores)").fetchall()}
    if "backend" not in score_cols:
        conn.execute("ALTER TABLE scores ADD COLUMN \"backend\" TEXT DEFAULT ''")

    # v5: add structured tracking columns for DBs created before v5 (nullable, additive).
    app_cols = {r[1] for r in conn.execute("PRAGMA table_info(applications)").fetchall()}
    for col in ("priority", "next_action", "next_action_date", "contact", "cv_version"):
        if col not in app_cols:
            conn.execute(f'ALTER TABLE applications ADD COLUMN "{col}" TEXT')

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


def scored_ids(conn: sqlite3.Connection) -> set[str]:
    """job_ids that already have a score (for incremental filtering)."""
    return {r["job_id"] for r in conn.execute("SELECT job_id FROM scores").fetchall()}


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


# --- score_runs: multi-backend calibration sidecar (v3) ---------------------

def upsert_score_runs(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Upsert calibration rows by (job_id, backend) (last write wins). Returns count.

    Additive: this never reads or writes the `scores` table, so the normal
    single-backend scoring path is untouched.
    """
    if not rows:
        return 0
    sql = (
        f'INSERT INTO score_runs ({",".join(chr(34)+c+chr(34) for c in SCORE_RUN_COLS)}) '
        f'VALUES ({",".join("?" * len(SCORE_RUN_COLS))}) '
        f'ON CONFLICT(job_id, backend) DO UPDATE SET '
        + ", ".join(f'"{c}" = excluded."{c}"' for c in SCORE_RUN_COLS if c not in ("job_id", "backend"))
    )
    conn.executemany(sql, [[r.get(c, "") for c in SCORE_RUN_COLS] for r in rows])
    conn.commit()
    return len(rows)


def read_score_runs(conn: sqlite3.Connection) -> pd.DataFrame:
    """The score_runs table as a DataFrame (job_id as str)."""
    df = pd.read_sql_query("SELECT * FROM score_runs", conn)
    if not df.empty:
        df["job_id"] = df["job_id"].astype(str)
    return df


# --- applications: user-owned status (the funnel) ---------------------------

def set_application_status(conn: sqlite3.Connection, job_id: str, status_value: str,
                          notes: str | None = None, source: str = "manual",
                          now: str | None = None) -> None:
    """Upsert an application's status (the single write choke-point for the funnel).

    `status_category` is derived via status.classify(). `applied_at` is set once (at
    first apply) and preserved across updates; `updated_at` refreshes every time.
    `notes` is left untouched when None. `now` is injectable for deterministic tests.
    """
    now = now or datetime.datetime.now().isoformat(timespec="seconds")
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
        now = now or datetime.datetime.now().isoformat(timespec="seconds")
        assignments = ", ".join(f'"{k}" = ?' for k in sets) + ', "updated_at" = ?'
        conn.execute(
            f"UPDATE applications SET {assignments} WHERE job_id = ?",
            [*sets.values(), now, str(job_id)],
        )
        conn.commit()
    return get_application(conn, job_id)


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
    ts = now or datetime.datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        'INSERT INTO application_events ("job_id","ts","kind","from_status","to_status","body","meta") '
        'VALUES (?,?,?,?,?,?,?)',
        (str(job_id), ts, kind, from_status, to_status, body or "", meta or ""),
    )
    # Keep the applications.notes mirror (last note) in sync when a row exists.
    if kind == "note":
        conn.execute(
            "UPDATE applications SET notes = ?, updated_at = ? WHERE job_id = ?",
            (body or "", ts, str(job_id)),
        )
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

    "Entered current stage" = the ts of its latest `status_change` event; falls back to
    `applied_at` (then `updated_at`) for rows with no recorded transition (e.g. imported
    trackers). For an OPEN application (live / Applied / Offer):
      - `stalled`  = idle STALLED_DAYS..DORMANT_DAYS days (still worth a nudge)
      - `dormant`  = idle >= DORMANT_DAYS days (probably dead — suggest archiving)
    Returns {job_id: {category, since, days_in_stage, stalled, dormant}}. `now` is
    injectable for deterministic tests.
    """
    now_dt = datetime.datetime.fromisoformat(now) if now else datetime.datetime.now()
    apps = conn.execute(
        "SELECT job_id, status_category, applied_at, updated_at FROM applications"
    ).fetchall()
    rows = conn.execute(
        "SELECT job_id, MAX(ts) AS since FROM application_events "
        "WHERE kind = 'status_change' GROUP BY job_id"
    ).fetchall()
    last_change = {str(r["job_id"]): r["since"] for r in rows}
    out: dict[str, dict] = {}
    for a in apps:
        jid = str(a["job_id"])
        since = last_change.get(jid) or a["applied_at"] or a["updated_at"]
        days = None
        if since:
            try:
                days = (now_dt - datetime.datetime.fromisoformat(since)).days
            except ValueError:
                days = None
        category = a["status_category"]
        is_open = category in status.OPEN and days is not None
        # Only "stallable" stages (live / offer) count as needing a nudge — Applied is
        # handled by no-response aging, not by the stalled flag.
        stalled = bool(days is not None and category in status.STALLABLE
                       and STALLED_DAYS <= days < DORMANT_DAYS)
        dormant = bool(is_open and days >= DORMANT_DAYS)
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
    return result
