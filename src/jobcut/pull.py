#!/usr/bin/env python3
"""pull.py — Stage 1 of the pipeline (pull + flatten + dedupe into SQLite).

What it does, in one daily pass:
  1. Reads saved searches in <data>/searches/*.json (one file = one search of the
     harvestapi/linkedin-job-search actor; the filename = source_search).
  2. Fires the searches IN PARALLEL on Apify (trigger mode, PAID) and waits for
     them; or, in --read mode, re-downloads the already-triggered runs (FREE).
  3. Downloads each dataset and FLATTENS the nested fields into clean columns.
  4. Upserts into the SQLite database (db.py) with one row per job_id:
       - source_searches = union of the searches that have seen the offer
       - first_seen fixed; last_seen / applicants / job_state refresh on re-sighting
       - never deletes (historical accumulator for funnel + market intel)
  5. Prints a compact summary (the only thing an LLM needs to read).

Usage:
    jobcut pull            # trigger mode (fires the runs, PAID)
    jobcut pull --read     # re-downloads the last triggered runs (FREE)

Requires: APIFY_TOKEN in .env (or the environment).
"""

import os
import sys
import json
import datetime

import pandas as pd  # noqa: F401  (kept available for ad-hoc inspection / parity)

from . import db, paths

try:
    from dotenv import load_dotenv
    load_dotenv(paths.data_dir() / ".env")   # the token lives in the data dir
    load_dotenv()                            # also honor a .env in the current dir
except ImportError:
    pass

# --- Config -----------------------------------------------------------------
ACTOR_ID     = "harvestapi/linkedin-job-search"
RUNS_SIDECAR = paths.data_dir() / "last_runs.json"   # maps source -> run/dataset of the last trigger
WAIT_SECS    = 600                                   # max wait per run

# Top-level fields requested from the dataset (trims payload).
PULL_FIELDS = ["id", "title", "linkedinUrl", "postedDate", "expireAt", "jobState",
               "workplaceType", "workRemoteAllowed", "employmentType", "experienceLevel",
               "location", "applicants", "jobFunctions", "industries", "company",
               "applicantTrackingSystem", "applyMethod", "easyApplyUrl", "hiringTeam",
               "descriptionText", "salary"]


# --- Extraction helpers -----------------------------------------------------
def gp(d, *path, default=""):
    """Tolerant nested get: gp(item,'company','name'), gp(item,'hiringTeam',0,'name')."""
    cur = d
    for p in path:
        if isinstance(cur, dict):
            cur = cur.get(p)
        elif isinstance(cur, list):
            try:
                cur = cur[p]
            except (IndexError, TypeError):
                return default
        else:
            return default
        if cur is None:
            return default
    return cur if cur is not None else default


def join_list(v, n=3):
    """List of strings or of dicts {name/title} -> 'a, b, c' (max n)."""
    if not isinstance(v, list):
        return str(v) if v else ""
    out = []
    for x in v[:n]:
        if isinstance(x, dict):
            out.append(str(x.get("name") or x.get("title") or x.get("text") or "").strip())
        elif x:
            out.append(str(x).strip())
    return ", ".join([o for o in out if o])


def flatten(item, source):
    """Actor item (nested) -> flat dict per db.JOB_COLS (+ internal _source field)."""
    return {
        "job_id": str(gp(item, "id")).strip(),
        "_source": source,
        "title": str(gp(item, "title")).strip(),
        "linkedin_url": gp(item, "linkedinUrl"),
        "posted_date": str(gp(item, "postedDate"))[:10],
        "expire_at": str(gp(item, "expireAt"))[:10],
        "job_state": gp(item, "jobState"),
        "workplace_type": gp(item, "workplaceType"),
        "work_remote_allowed": gp(item, "workRemoteAllowed"),
        "employment_type": gp(item, "employmentType"),
        "experience_level": gp(item, "experienceLevel"),
        "location": gp(item, "location", "linkedinText") or gp(item, "location", "parsed", "text"),
        "applicants": gp(item, "applicants"),
        "job_functions": join_list(gp(item, "jobFunctions", default=[])),
        "industries": join_list(gp(item, "industries", default=[])),
        "company_name": gp(item, "company", "name"),
        "company_size": gp(item, "company", "employeeCount"),
        "company_industry": join_list(gp(item, "company", "industries", default=[]), n=2),
        "company_website": gp(item, "company", "website"),
        "company_linkedin": gp(item, "company", "linkedinUrl"),
        "ats": gp(item, "applicantTrackingSystem"),
        "apply_url": gp(item, "applyMethod", "companyApplyUrl"),
        "easy_apply_url": gp(item, "easyApplyUrl") or gp(item, "applyMethod", "easyApplyUrl"),
        "recruiter_name": gp(item, "hiringTeam", 0, "name"),
        "recruiter_position": gp(item, "hiringTeam", 0, "position"),
        "recruiter_url": gp(item, "hiringTeam", 0, "linkedinUrl"),
        "description": str(gp(item, "descriptionText"))[:30000],
        "salary_text": gp(item, "salary", "text"),
        "salary_min": gp(item, "salary", "min"),
        "salary_max": gp(item, "salary", "max"),
    }


# --- Daily aggregation (1 row per id, union of sources) ----------------------
def _merge_sources(*vals):
    s = set()
    for v in vals:
        if v:
            s.update(str(v).split("|"))
    return "|".join(sorted(x for x in s if x))


def aggregate_today(flat_rows, today):
    """flat_rows: list of flatten() dicts. Returns {job_id: row} with merged sources."""
    agg = {}
    for r in flat_rows:
        jid = r["job_id"]
        if not jid:
            continue
        src = r.pop("_source", "")
        if jid in agg:
            agg[jid]["source_searches"] = _merge_sources(agg[jid]["source_searches"], src)
            for k in ("applicants", "job_state"):
                if not agg[jid].get(k) and r.get(k):
                    agg[jid][k] = r[k]
        else:
            row = dict(r)
            row["source_searches"] = src
            row["first_seen"] = today
            row["last_seen"] = today
            agg[jid] = row
    return agg


# --- Apify: trigger + download ----------------------------------------------
def load_searches():
    files = sorted(paths.searches_dir().glob("*.json"))
    if not files:
        sys.exit(f"No searches found in {paths.searches_dir()}")
    return [(f.stem, json.loads(f.read_text())) for f in files]


_PLACEHOLDER_TOKEN = "apify_api_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"


def _resolve_token() -> str | None:
    """Read the Apify token fresh at call time.

    The data-dir ``.env`` is authoritative (the web console writes the token there),
    then the process environment as a fallback. We read the file directly rather than
    trusting ``os.environ`` because ``load_dotenv`` runs once at import — a token saved
    via the UI after the server started would otherwise be missed (stale placeholder).
    """
    env_path = paths.data_dir() / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            s = line.strip()
            if s.startswith("APIFY_TOKEN=") and "=" in s:
                v = s.split("=", 1)[1].strip()
                if v and v != _PLACEHOLDER_TOKEN:
                    return v
    env = os.environ.get("APIFY_TOKEN")
    return env if env and env != _PLACEHOLDER_TOKEN else None


def client():
    token = _resolve_token()
    if not token:
        sys.exit("APIFY_TOKEN is not set. Add it in the console (Settings → Connect) or in .env, then try again.")
    from apify_client import ApifyClient
    return ApifyClient(token)


def trigger_all(cli, searches):
    """Start all searches in parallel. Returns [(name, run_id, dataset_id)].

    A bad input in one search (e.g. an invalid workplaceType) must not sink the whole
    pull — we isolate per-search start failures and continue with the rest.
    """
    started = []
    for name, inp in searches:
        try:
            run = cli.actor(ACTOR_ID).start(run_input=inp)
        except Exception as e:
            print(f"  x skip {name}: {e}")
            continue
        started.append((name, run.id, run.default_dataset_id))
        print(f"  > start {name}: run {run.id}")
    if not started:
        sys.exit("No searches could be started — check your searches/*.json inputs "
                 "(e.g. workplaceType must be one of remote/hybrid/office).")
    RUNS_SIDECAR.write_text(json.dumps(
        {"date": datetime.date.today().isoformat(),
         "runs": [{"name": n, "run_id": r, "dataset_id": d} for n, r, d in started]}, indent=2))
    return started


def wait_and_collect(cli, started):
    """Wait for each run; 1 retry on failure; isolate failures. Returns valid [(name, dataset_id)]."""
    ok = []
    for name, run_id, dataset_id in started:
        run = cli.run(run_id).wait_for_finish(wait_duration=datetime.timedelta(seconds=WAIT_SECS))
        status = run.status if run else "UNKNOWN"
        if status == "SUCCEEDED":
            ok.append((name, dataset_id))
        else:
            print(f"  ! {name}: run {run_id} finished {status} — retrying once")
            try:
                inp = dict(next(i for n, i in load_searches() if n == name))
                r2 = cli.actor(ACTOR_ID).start(run_input=inp)
                r2 = cli.run(r2.id).wait_for_finish(wait_duration=datetime.timedelta(seconds=WAIT_SECS))
                if r2 and r2.status == "SUCCEEDED":
                    ok.append((name, r2.default_dataset_id))
                else:
                    print(f"  x {name}: retry {r2.status if r2 else 'UNKNOWN'} — skipping this search")
            except Exception as e:
                print(f"  x {name}: error on retry ({e}) — skipping")
    return ok


def download(cli, name_dataset):
    """Download datasets -> list of flatten() with _source. No raw rows hit stdout."""
    rows = []
    for name, dataset_id in name_dataset:
        items = list(cli.dataset(dataset_id).iterate_items(clean=True, fields=PULL_FIELDS))
        print(f"  v {name}: {len(items)} items")
        for it in items:
            rows.append(flatten(it, name))
    return rows


# --- Main -------------------------------------------------------------------
def main(argv=None, progress=None):
    emit = progress or (lambda e: None)
    argv = sys.argv[1:] if argv is None else argv
    read_mode = "--read" in argv
    today = datetime.date.today().isoformat()
    searches = load_searches()
    mode_label = "READ (free)" if read_mode else "TRIGGER (paid)"
    print(f"pull · {today} · {mode_label} · "
          f"{len(searches)} searches: {', '.join(n for n, _ in searches)}")
    emit({"stage": "start", "message": f"{mode_label} · {len(searches)} searches",
          "counts": {"searches": len(searches)}})

    cli = client()

    if read_mode:
        if not RUNS_SIDECAR.exists():
            sys.exit("No last_runs.json: nothing to re-download. Run without --read to trigger.")
        side = json.loads(RUNS_SIDECAR.read_text())
        name_dataset = [(r["name"], r["dataset_id"]) for r in side["runs"]]
        print(f"  re-downloading runs from {side['date']}")
        emit({"stage": "download", "message": f"re-downloading runs from {side['date']}"})
    else:
        emit({"stage": "trigger", "message": "triggering paid Apify runs"})
        started = trigger_all(cli, searches)
        name_dataset = wait_and_collect(cli, started)

    if not name_dataset:
        sys.exit("No dataset available (all searches failed). Not writing.")

    flat_rows = download(cli, name_dataset)
    print(f"Total downloaded: {len(flat_rows)} rows across {len(name_dataset)} search(es)")
    emit({"stage": "download", "message": f"downloaded {len(flat_rows)} rows",
          "counts": {"rows": len(flat_rows)}})
    if not flat_rows:
        print("No rows; not writing.")
        emit({"stage": "done", "message": "no rows; nothing written", "counts": {"new": 0, "updated": 0}})
        return

    today_agg = aggregate_today(flat_rows, today)
    conn = db.connect()
    inserted, updated = db.upsert_jobs(conn, today_agg, today)
    total = db.count_jobs(conn)
    conn.close()

    # Compact summary
    by_src = {}
    for r in today_agg.values():
        for s in str(r["source_searches"]).split("|"):
            by_src[s] = by_src.get(s, 0) + 1
    print("\nSummary:")
    print(f"  unique offers today: {len(today_agg)}  ({', '.join(f'{k}={v}' for k,v in sorted(by_src.items()))})")
    print(f"  new: {inserted} | updated: {updated}")
    print(f"  total in {db.db_path().name}: {total} rows")
    emit({"stage": "done", "message": f"new {inserted}, updated {updated}, total {total}",
          "counts": {"unique_today": len(today_agg), "new": inserted, "updated": updated, "total": total}})


if __name__ == "__main__":
    main()
