#!/usr/bin/env python3
"""market.py — Stage 8: skill-demand vs your profile over the whole database.

Reads the jobs table (db.py), filters the relevant market (data/analytics
segments), counts skill demand over title+description, cross-references your
taxonomy status (have/partial/gap) and writes:
  - out/market-gaps.md          (report)
  - out/market-dashboard.html   (interactive chart)
  - market_history.xlsx         (per-skill, per-date snapshot — local data)

No network. No scores (relevance is by segment, not match_score).
"""

import json
import re
import datetime

import pandas as pd

from . import config, db, paths


# applicant-count bands for the competition view (how crowded your market is).
_APPLICANT_BANDS = [(0, 20, "Low"), (20, 100, "Moderate"), (100, 10**9, "Crowded")]
_INT_RE = re.compile(r"\d[\d,\.]*")


def _first_int(x):
    """First integer in a free-text cell ("Over 200 applicants" → 200). None if none."""
    m = _INT_RE.search(str(x))
    return int(m.group(0).replace(",", "").replace(".", "")) if m else None


def _signals(rel, seg_keys) -> dict:
    """Competition (applicants) + freshness (posting velocity) over the relevant market.

    Both dimensions have ~full coverage in the data (unlike disclosed salary, which sits
    near 3% with mixed currencies/periods and is deliberately NOT turned into bands here).
    """
    # --- competition: parsed applicant counts ---
    appl = rel["applicants"].map(_first_int).dropna() if "applicants" in rel else pd.Series(dtype=float)
    comp_bands = [{"label": lbl, "min": lo, "max": (None if hi >= 10**9 else hi),
                   "count": int(((appl >= lo) & (appl < hi)).sum())} for lo, hi, lbl in _APPLICANT_BANDS]
    by_seg_median = {}
    for seg in seg_keys:
        sa = rel.loc[rel.segment == seg, "applicants"].map(_first_int).dropna() if len(rel) else pd.Series(dtype=float)
        by_seg_median[seg] = int(sa.median()) if len(sa) else 0
    competition = {"n": int(len(appl)),
                   "median": int(appl.median()) if len(appl) else 0,
                   "bands": comp_bands, "by_segment": by_seg_median}

    # --- freshness: posting date (fallback first_seen), weekly inflow + median age ---
    posted = pd.to_datetime(rel.get("posted_date"), errors="coerce") if len(rel) else pd.Series(dtype="datetime64[ns]")
    if len(rel):
        posted = posted.fillna(pd.to_datetime(rel.get("first_seen"), errors="coerce"))
    posted = posted.dropna()
    weekly, median_age = [], 0
    if len(posted):
        labels = posted.dt.strftime("%G-W%V")
        counts = labels.value_counts()
        for w in sorted(counts.index)[-10:]:                 # last 10 ISO weeks present
            weekly.append({"week": w, "count": int(counts[w])})
        today = pd.Timestamp(datetime.date.today())
        median_age = int((today - posted).dt.days.median())
    freshness = {"n": int(len(posted)), "median_age_days": median_age, "weekly": weekly}

    return {"competition": competition, "freshness": freshness}


def compute(conn) -> dict | None:
    """Read-only market computation (no file writes). None when there are no jobs."""
    tax = config.load_taxonomy(required=True)
    segments = dict(tax["role_segments"])

    def segment_of(title):
        t = str(title).lower()
        for seg, pats in segments.items():
            if any(re.search(p, t) for p in pats):
                return seg
        return "other"

    df = db.read_jobs(conn)
    if df.empty:
        return None
    df["segment"] = df.title.map(segment_of)
    df["text"] = (df.title.astype(str) + " " + df.description.astype(str)).str.lower()
    rel = df[df.segment != "other"].copy()      # relevant market
    total = len(df)
    R = len(rel)

    seg_keys = list(segments.keys())
    skills = {}
    for name, spec in tax["skills"].items():
        pats = [re.compile(p, re.I) for p in spec["patterns"]]
        def hit(r, pats=pats):
            return any(p.search(r) for p in pats)
        n = int(rel.text.map(hit).sum())
        seg_pct = {}
        for seg in seg_keys:
            sj = rel[rel.segment == seg]
            seg_pct[seg] = round(100 * sj.text.map(hit).sum() / len(sj)) if len(sj) else 0
        skills[name] = {"cat": spec["cat"], "status": spec["status"], "close_via": spec.get("close_via", ""),
                        "n": n, "pct": round(100 * n / R) if R else 0, "by_seg": seg_pct}

    segcounts = {s: int((df.segment == s).sum()) for s in seg_keys + ["other"]}

    def _hasval(x):
        return str(x).strip().lower() not in ("", "nan", "none", "nat")
    sal = df[df.salary_min.map(_hasval) | df.salary_text.map(_hasval)]
    salary = {"n": len(sal), "pct": round(100 * len(sal) / total) if total else 0}

    gaps = sorted([{"skill": k, **v} for k, v in skills.items()
                   if v["status"] in ("gap", "partial") and v["close_via"] != "skip"],
                  key=lambda x: -x["pct"])
    top = sorted(skills.items(), key=lambda kv: -kv[1]["pct"])[:18]

    return {"total": total, "R": R, "seg_keys": seg_keys, "skills": skills,
            "segcounts": segcounts, "salary": salary, "gaps": gaps, "top": top,
            **_signals(rel, seg_keys)}


# status → how much of the demand it "covers" (have = full, partial = half, gap = none).
_COVER_WEIGHT = {"have": 1.0, "partial": 0.5, "gap": 0.0}


def _load_history():
    """The per-day skill-demand history (market_history.xlsx), read-only. None if absent."""
    hp = paths.data_dir() / "market_history.xlsx"
    if not hp.exists():
        return None
    try:
        return pd.read_excel(hp)
    except Exception:
        return None


def _trend(h, skills) -> dict:
    """{skill: percentage-point delta vs the previous snapshot}. Empty with <2 snapshots."""
    if h is None or getattr(h, "empty", True):
        return {}
    today = datetime.date.today().isoformat()
    prev_dates = sorted(d for d in h.date.unique() if d < today)
    if not prev_dates:
        return {}
    prev = h[h.date == prev_dates[-1]].set_index("skill").pct.to_dict()
    return {k: v["pct"] - prev[k] for k, v in skills.items() if k in prev}


def _coverage(skills, seg_keys) -> dict:
    """Profile coverage: of the demand (weighted by % of offers), how much you already have.

    Overall + per-segment. Only skills the market actually asks (pct/by_seg > 0) count, so a
    skill nobody demands neither helps nor hurts. `partial` counts half — some exposure.
    """
    def cov(weights: dict) -> int:
        tot = sum(weights.values())
        if not tot:
            return 0
        got = sum(w * _COVER_WEIGHT.get(skills[k]["status"], 0.0) for k, w in weights.items())
        return round(100 * got / tot)

    overall = cov({k: v["pct"] for k, v in skills.items() if v["pct"] > 0})
    by_segment = {}
    for seg in seg_keys:
        w = {k: v["by_seg"].get(seg, 0) for k, v in skills.items()}
        by_segment[seg] = cov({k: x for k, x in w.items() if x > 0})
    return {"pct": overall, "by_segment": by_segment}


def summary(conn) -> dict | None:
    """The API-facing market view (GET /api/market). None when there are no jobs.

    Read-only (no file writes): reads market_history.xlsx if present for the trend, but
    never writes it — that's `main()`'s job.
    """
    c = compute(conn)
    if c is None:
        return None
    skills = c["skills"]
    trend = _trend(_load_history(), skills)

    def enrich(k, v):
        return {"skill": k, "pct": v["pct"], "status": v["status"], "cat": v["cat"],
                "close_via": v["close_via"], "n": v["n"], "by_seg": v["by_seg"],
                "trend": trend.get(k)}

    return {
        "total": c["total"], "relevant": c["R"], "segments": c["segcounts"],
        "seg_keys": c["seg_keys"], "salary_pct": c["salary"]["pct"],
        "coverage": _coverage(skills, c["seg_keys"]),
        "top_demand": [enrich(k, v) for k, v in c["top"][:10]],
        "gaps": [{"skill": g["skill"], "pct": g["pct"], "status": g["status"],
                  "close_via": g["close_via"], "n": g["n"], "cat": g["cat"]}
                 for g in c["gaps"][:8]],
        "competition": c["competition"], "freshness": c["freshness"],
    }


def main(conn=None):
    own = conn is None
    conn = conn or db.connect()
    data = paths.data_dir()
    today = datetime.date.today().isoformat()

    c = compute(conn)
    if own:
        conn.close()
    if c is None:
        print("No jobs in the database yet. Run `jobcut pull` first.")
        return None
    total, R, seg_keys = c["total"], c["R"], c["seg_keys"]
    skills, segcounts, salary, gaps, top = c["skills"], c["segcounts"], c["salary"], c["gaps"], c["top"]

    # history (idempotent per day)
    hp = data / "market_history.xlsx"
    h = pd.read_excel(hp) if hp.exists() else pd.DataFrame(columns=["date", "relevant", "skill", "n", "pct"])
    h = h[~(h.date == today)]
    rows = [{"date": today, "relevant": R, "skill": k, "n": v["n"], "pct": v["pct"]} for k, v in skills.items()]
    h = pd.concat([h, pd.DataFrame(rows)], ignore_index=True)
    h.to_excel(hp, index=False)

    # trend vs previous snapshot (h now includes today's rows; _trend excludes them)
    trend = _trend(h, skills)

    EMO = {"have": "✅", "partial": "🟡", "gap": "🔴"}
    md = [
        f"---\ntype: note\nstatus: active\nupdated: {today}\n---\n",
        "# 📊 Market Gaps — demand vs your profile\n",
        f"> Updated {today} · source: mother file ({total} offers, {R} in the relevant data/analytics market). "
        f"Sample {'small — signals, not trends' if R < 100 else 'sufficient'}.\n",
        "## Segment mix\n",
        "| segment | offers |", "|---|---|",
    ]
    for s in seg_keys + ["other"]:
        md.append(f"| {s} | {segcounts.get(s, 0)} |")
    md.append("\n## Skill demand vs your profile (relevant market)\n")
    md.append("| skill | % offers | you | close via | trend |")
    md.append("|---|---|---|---|---|")
    for k, v in top:
        tr = trend.get(k)
        ts = f"{'+' if tr and tr > 0 else ''}{tr}pp" if tr not in (None, 0) else "—"
        md.append(f"| {k} | {v['pct']}% | {EMO[v['status']]} | {v['close_via'] or '-'} | {ts} |")
    md.append("\n## Prioritized gaps (what the market asks that you don't have)\n")
    for x in gaps[:8]:
        md.append(f"- **{x['skill']}** — {x['pct']}% of offers · status {EMO[x['status']]} · via **{x['close_via']}**")
    md.append(f"\n> Salary disclosed in {salary['pct']}% of offers (LinkedIn hides it most of the time).")
    md.append("\n*Interactive dashboard → market-dashboard.html · history in market_history.xlsx.*")
    (paths.out_dir() / "market-gaps.md").write_text("\n".join(md))

    # dashboard
    colors = {"have": "#22c55e", "partial": "#eab308", "gap": "#ef4444"}
    labels = [k for k, _ in top]
    chart_data = [v["pct"] for _, v in top]
    cols = [colors[v["status"]] for _, v in top]
    seg_lab = seg_keys + ["other"]
    seg_dat = [segcounts.get(s, 0) for s in seg_lab]
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Market Gaps</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>body{{font-family:-apple-system,sans-serif;max-width:1000px;margin:24px auto;padding:0 16px;background:#0f172a;color:#e2e8f0}}
h1{{font-size:22px}}.meta{{color:#94a3b8;font-size:13px}}.card{{background:#1e293b;border-radius:12px;padding:16px;margin:12px 0}}
.legend span{{margin-right:14px;font-size:12px}}.dot{{display:inline-block;width:10px;height:10px;border-radius:5px;margin-right:4px}}</style></head><body>
<h1>📊 Market Gaps — demand vs your profile</h1>
<p class="meta">{today} · {total} offers · {R} relevant (data/analytics) · source: jobs_database.xlsx</p>
<div class="legend"><span><i class="dot" style="background:#22c55e"></i>Have</span><span><i class="dot" style="background:#eab308"></i>Partial</span><span><i class="dot" style="background:#ef4444"></i>Gap</span></div>
<div class="card"><h3>% of relevant offers asking for each skill</h3><canvas id="sk" height="150"></canvas></div>
<div class="card"><h3>Offers by segment</h3><canvas id="seg" height="150"></canvas></div>
<script>
new Chart(document.getElementById('sk'),{{type:'bar',data:{{labels:{json.dumps(labels)},datasets:[{{data:{json.dumps(chart_data)},backgroundColor:{json.dumps(cols)}}}]}},options:{{indexAxis:'y',plugins:{{legend:{{display:false}}}},scales:{{x:{{max:100,ticks:{{color:'#94a3b8'}}}},y:{{ticks:{{color:'#e2e8f0'}}}}}}}}}});
new Chart(document.getElementById('seg'),{{type:'doughnut',data:{{labels:{json.dumps(seg_lab)},datasets:[{{data:{json.dumps(seg_dat)},backgroundColor:['#3b82f6','#a855f7','#06b6d4','#f97316','#64748b']}}]}},options:{{plugins:{{legend:{{labels:{{color:'#e2e8f0'}}}}}}}}}});
</script></body></html>"""
    (paths.out_dir() / "market-dashboard.html").write_text(html)

    out = {"total": total, "relevant": R, "segments": segcounts,
           "top_demand": [{"skill": k, "pct": v["pct"], "status": v["status"]} for k, v in top[:10]],
           "gaps": [g["skill"] for g in gaps[:8]], "salary_pct": salary["pct"]}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


if __name__ == "__main__":
    main()
