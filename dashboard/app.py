"""jobcut dashboard — LITE mode (read + status toggle), the no-Node path.

Maintenance mode per ADR-001: the Next.js console is the primary frontend; this
Streamlit app is the dependency-light fallback (read + change application status),
talking to the SQLite package directly. No new features land here.

Three tabs:
  - Funnel — your application funnel from the `applications` table (KPIs, conversion,
    a status toggle, status + weekly charts, table). Writes via db.set_application_status.
  - Discovery — jobcut's scored shortlist from SQLite (score buckets + table).
  - Market — the market-gaps report.

Run:  jobcut dashboard      (or: streamlit run dashboard/app.py)
Data dir: current directory, or $JOBCUT_DATA_DIR.
"""

import html

import altair as alt
import pandas as pd
import streamlit as st

from jobcut import db, paths, status

# ---------------------------------------------------------------- theme / palette
BG, PANEL, PANEL2, LINE = "#0d1117", "#161b22", "#1c2230", "#2a323d"
TXT, MUT, DIM = "#e6edf3", "#8b949e", "#6e7681"
ACCENT, BLUE, AMBER, RED, PURPLE, CYAN = "#3fb950", "#58a6ff", "#d29922", "#f85149", "#bc8cff", "#39c5cf"

st.set_page_config(page_title="jobcut", page_icon="🎯", layout="wide")

st.markdown(f"""
<style>
  .stApp {{ background:{BG}; }}
  header[data-testid="stHeader"], #MainMenu, footer {{ display:none; }}
  .block-container {{ padding:1.6rem 2rem 5rem; max-width:1280px; }}
  html, body, [class*="css"] {{ font-family:'SF Pro Text',-apple-system,Segoe UI,Roboto,sans-serif; color:{TXT}; }}
  div[data-testid="stVerticalBlockBorderWrapper"] {{
    background:{PANEL}; border:1px solid {LINE}; border-radius:12px; padding:4px 6px;
  }}
  h1.jp {{ font-size:22px; font-weight:700; letter-spacing:-.02em; margin:0; }}
  .jp-sub {{ color:{MUT}; font-size:13px; margin-top:3px; }}
  .jp-src {{ color:{DIM}; font-size:12px; margin-top:6px; }}
  .jp-h2 {{ font-size:13px; font-weight:700; text-transform:uppercase; letter-spacing:.05em; color:{MUT}; margin:2px 0 12px; }}
  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:14px; margin:18px 0 4px; }}
  .kpi {{ background:{PANEL}; border:1px solid {LINE}; border-radius:12px; padding:16px 18px; }}
  .kpi .lbl {{ font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:{MUT}; font-weight:600; }}
  .kpi .val {{ font-size:30px; font-weight:700; letter-spacing:-.02em; margin-top:6px; line-height:1; }}
  .kpi .meta {{ font-size:12px; color:{DIM}; margin-top:5px; }}
  .fn {{ display:flex; flex-direction:column; gap:9px; }}
  .fmeta {{ display:flex; justify-content:space-between; font-size:12px; color:{MUT}; margin-bottom:4px; }}
  .fmeta b {{ color:{TXT}; }}
  .fbar {{ height:42px; border-radius:7px; display:flex; align-items:center; padding:0 14px; font-weight:600; color:{BG}; min-width:60px; }}
  .conv {{ font-size:11px; color:{DIM}; margin-top:2px; }}
  .empty {{ text-align:center; color:{DIM}; padding:24px; }}
  table.jp {{ width:100%; border-collapse:collapse; font-size:13px; }}
  table.jp th {{ text-align:left; padding:9px 10px; color:{MUT}; font-size:11px; text-transform:uppercase; letter-spacing:.04em; border-bottom:1px solid {LINE}; white-space:nowrap; }}
  table.jp td {{ padding:10px; border-bottom:1px solid {LINE}; vertical-align:top; }}
  table.jp tr:hover td {{ background:{PANEL2}; }}
  .badge {{ display:inline-block; padding:3px 9px; border-radius:6px; font-size:11px; font-weight:600; white-space:nowrap; }}
  .tlink {{ color:{BLUE}; text-decoration:none; }} .tlink:hover {{ text-decoration:underline; }}
  .note2 {{ font-size:11px; color:{DIM}; margin-top:3px; max-width:360px; }}
</style>
""", unsafe_allow_html=True)


def card():
    return st.container(border=True)


def alt_dark(chart):
    return (chart
            .configure_view(strokeWidth=0, fill=PANEL)
            .configure_axis(labelColor=MUT, titleColor=MUT, gridColor=LINE, domainColor=LINE, tickColor=LINE)
            .configure_legend(labelColor=TXT, titleColor=MUT))


def badge(text, color):
    return f'<span class="badge" style="background:{color}22;color:{color}">{html.escape(str(text))}</span>'


# ---------------------------------------------------------------- header
st.markdown(
    f'<h1 class="jp">🎯 jobcut <span style="font-size:12px;color:{DIM}">lite</span></h1>'
    f'<div class="jp-sub">Local, scored job pipeline · read + status toggle (no-Node fallback)</div>'
    f'<div class="jp-src">Data dir: <code>{paths.data_dir()}</code> · DB: <code>{db.db_path().name}</code> · '
    f'full UI: <code>jobcut serve</code></div>',
    unsafe_allow_html=True,
)

tab_funnel, tab_disc, tab_market = st.tabs(["Funnel", "Discovery", "Market gaps"])

# ================================================================ FUNNEL (applications table)
with tab_funnel:
    conn = db.connect()
    apps = db.read_applications(conn)
    jobs = db.read_jobs(conn)

    if apps.empty:
        conn.close()
        st.markdown(
            '<div class="empty">No applications yet.<br>'
            'Mark jobs as applied from the console (Today → set status), then they appear here.</div>',
            unsafe_allow_html=True,
        )
    else:
        s = db.application_funnel(conn)
        jcols = (jobs[["job_id", "title", "company_name", "linkedin_url"]]
                 if not jobs.empty else pd.DataFrame(columns=["job_id", "title", "company_name", "linkedin_url"]))
        view = apps.merge(jcols, on="job_id", how="left").sort_values("updated_at", ascending=False)

        def pct(n):
            return f"{n / s['total'] * 100:.1f}%" if s["total"] else "0%"

        kpis = [
            ("Applications", s["total"], "total", TXT),
            ("Live / in process", s["live"], f"{pct(s['live'])} of total", ACCENT),
            ("Interviews", s["interview"], "screen + interview", PURPLE),
            ("Offers", s["offers"], "—", TXT),
            ("Rejections", s["rejected"], pct(s["rejected"]), RED),
            ("No response", s["no_response"], "stale + closed", AMBER),
        ]
        st.markdown(
            '<div class="kpis">' + "".join(
                f'<div class="kpi"><div class="lbl">{lbl}</div>'
                f'<div class="val" style="color:{col}">{val}</div><div class="meta">{meta}</div></div>'
                for lbl, val, meta, col in kpis
            ) + "</div>", unsafe_allow_html=True,
        )

        c1, c2 = st.columns([1.1, 0.9])
        with c1:
            with card():
                st.markdown('<div class="jp-h2">Conversion funnel</div>', unsafe_allow_html=True)
                mx = s["total"] or 1
                bars = []
                for name, val, col in s["funnel"]:
                    w = max(val / mx * 100, 6)
                    bars.append(
                        f'<div><div class="fmeta"><span>{name}</span><b>{val} · {pct(val)}</b></div>'
                        f'<div class="fbar" style="width:{w}%;background:{col}">{val}</div></div>'
                    )
                st.markdown(f'<div class="fn">{"".join(bars)}</div>', unsafe_allow_html=True)
        with c2:
            with card():
                st.markdown('<div class="jp-h2">Update status</div>', unsafe_allow_html=True)

                def _label(jid):
                    row = view[view.job_id == jid].iloc[0]
                    return f"{row.title or jid} — {row.company_name or ''}".strip(" —")

                with st.form("status_toggle"):
                    jid = st.selectbox("Application", view.job_id.tolist(), format_func=_label)
                    new = st.selectbox("New status", status.STATUSES)
                    if st.form_submit_button("Save status"):
                        db.set_application_status(conn, jid, new)
                        conn.close()
                        st.rerun()

        c3, c4 = st.columns(2)
        with c3:
            with card():
                st.markdown('<div class="jp-h2">Pipeline status</div>', unsafe_allow_html=True)
                cc = pd.DataFrame(
                    [(k, v, status.CATEGORY_COLOR.get(k, MUT)) for k, v in s["counts"].items()],
                    columns=["category", "n", "color"],
                ).sort_values("n")
                chart = alt.Chart(cc).mark_bar(cornerRadius=5).encode(
                    x=alt.X("n:Q", title=None),
                    y=alt.Y("category:N", sort="-x", title=None),
                    color=alt.Color("color:N", scale=None, legend=None),
                    tooltip=["category", "n"],
                ).properties(height=220)
                st.altair_chart(alt_dark(chart), use_container_width=True)
        with c4:
            with card():
                st.markdown('<div class="jp-h2">Applications per week</div>', unsafe_allow_html=True)
                wk = pd.DataFrame(list(s["by_week"].items()), columns=["week", "n"])
                if wk.empty:
                    st.markdown('<div class="empty">No dated rows</div>', unsafe_allow_html=True)
                else:
                    chart = alt.Chart(wk).mark_bar(cornerRadius=4, color=BLUE).encode(
                        x=alt.X("week:N", title=None, axis=alt.Axis(labelAngle=-45)),
                        y=alt.Y("n:Q", title=None), tooltip=["week", "n"],
                    ).properties(height=220)
                    st.altair_chart(alt_dark(chart), use_container_width=True)

        with card():
            st.markdown(f'<div class="jp-h2">All applications ({len(view)})</div>', unsafe_allow_html=True)
            trows = []
            for _, d in view.iterrows():
                cat = str(d.status_category)
                note = (f'<div class="note2">{html.escape(str(d.notes)[:80])}</div>'
                        if isinstance(d.notes, str) and d.notes else "")
                url = str(d.linkedin_url or "")
                link = f'<a class="tlink" href="{html.escape(url)}" target="_blank">view ↗</a>' if url.startswith("http") else "—"
                trows.append(
                    f"<tr><td><b>{html.escape(str(d.title or d.job_id))}</b></td>"
                    f"<td>{html.escape(str(d.company_name or ''))}</td>"
                    f"<td>{badge(cat, status.CATEGORY_COLOR.get(cat, MUT))}{note}</td>"
                    f'<td style="white-space:nowrap;color:{MUT}">{html.escape(str(d.updated_at or "")[:10])}</td>'
                    f"<td>{link}</td></tr>"
                )
            st.markdown(
                '<table class="jp"><thead><tr><th>Role</th><th>Company</th>'
                '<th>Status</th><th>Updated</th><th>Link</th></tr></thead><tbody>'
                + "".join(trows) + "</tbody></table>",
                unsafe_allow_html=True,
            )
        conn.close()

# ================================================================ DISCOVERY (DB)
with tab_disc:
    if not db.db_path().exists():
        st.markdown('<div class="empty">No database yet. Run <code>jobcut pull</code> first.</div>', unsafe_allow_html=True)
    else:
        conn = db.connect()
        jobs, scores = db.read_jobs(conn), db.read_scores(conn)
        conn.close()
        if jobs.empty:
            st.markdown('<div class="empty">No jobs yet. Run <code>jobcut pull</code>.</div>', unsafe_allow_html=True)
        else:
            from jobcut.route import is_funnel
            d = jobs.merge(scores, on="job_id", how="left")
            d["funnel"] = d.apply(lambda r: is_funnel(r.location, r.workplace_type), axis=1)
            d["score"] = pd.to_numeric(d.match_score, errors="coerce")

            kp = [
                ("Collected", len(d), "total in DB", TXT),
                ("In funnel", int(d.funnel.sum()), "hireable for you", BLUE),
                ("Scored", int((d.status == "scored").sum()), "passed the filter", CYAN),
                ("Strong (≥80)", int((d.score >= 80).sum()), "top matches", ACCENT),
                ("Discarded", int((d.status == "discarded").sum()), "off-profile", AMBER),
            ]
            st.markdown(
                '<div class="kpis">' + "".join(
                    f'<div class="kpi"><div class="lbl">{lbl}</div>'
                    f'<div class="val" style="color:{col}">{val}</div><div class="meta">{meta}</div></div>'
                    for lbl, val, meta, col in kp
                ) + "</div>", unsafe_allow_html=True,
            )

            scored = d[d.funnel & (d.status == "scored")].copy()
            c1, c2 = st.columns([1, 1])
            with c1:
                with card():
                    st.markdown('<div class="jp-h2">Score distribution</div>', unsafe_allow_html=True)
                    buckets = pd.DataFrame({
                        "bucket": ["80–100", "60–79", "40–59", "0–39"],
                        "n": [
                            int((scored.score >= 80).sum()),
                            int(((scored.score >= 60) & (scored.score < 80)).sum()),
                            int(((scored.score >= 40) & (scored.score < 60)).sum()),
                            int((scored.score < 40).sum()),
                        ],
                        "color": [ACCENT, CYAN, AMBER, DIM],
                    })
                    chart = alt.Chart(buckets).mark_bar(cornerRadius=5).encode(
                        x=alt.X("n:Q", title=None),
                        y=alt.Y("bucket:N", sort=["80–100", "60–79", "40–59", "0–39"], title=None),
                        color=alt.Color("color:N", scale=None, legend=None), tooltip=["bucket", "n"],
                    ).properties(height=200)
                    st.altair_chart(alt_dark(chart), use_container_width=True)
            with c2:
                with card():
                    st.markdown('<div class="jp-h2">Top matches by score</div>', unsafe_allow_html=True)
                    st.markdown(f'<div style="font-size:30px;font-weight:700;color:{ACCENT}">{int((scored.score >= 80).sum())}</div>'
                                f'<div class="meta" style="color:{MUT};font-size:12px">roles at ≥80 · median score '
                                f'{int(scored.score.median()) if len(scored) else 0}</div>', unsafe_allow_html=True)

            with card():
                st.markdown('<div class="jp-h2">Ranked shortlist</div>', unsafe_allow_html=True)
                min_score = st.slider("Minimum score", 0, 100, 60, 5, label_visibility="collapsed")
                v = scored[scored.score >= min_score].sort_values("score", ascending=False)
                if v.empty:
                    st.markdown('<div class="empty">No roles at that score.</div>', unsafe_allow_html=True)
                else:
                    def sbadge(sc):
                        c = ACCENT if sc >= 80 else CYAN if sc >= 60 else AMBER if sc >= 40 else DIM
                        return badge(int(sc), c)
                    trows = []
                    for _, r in v.iterrows():
                        link = f'<a class="tlink" href="{html.escape(str(r.linkedin_url))}" target="_blank">view ↗</a>' if str(r.linkedin_url).startswith("http") else "—"
                        trows.append(
                            f"<tr><td>{sbadge(r.score)}</td><td><b>{html.escape(str(r.title))}</b></td>"
                            f"<td>{html.escape(str(r.company_name))}</td><td>{html.escape(str(r.location))}</td>"
                            f'<td style="color:{MUT}">{html.escape(str(r.match_reasons or ""))[:90]}</td>'
                            f"<td>{link}</td></tr>"
                        )
                    st.markdown(
                        '<table class="jp"><thead><tr><th>Score</th><th>Title</th><th>Company</th>'
                        '<th>Location</th><th>Why</th><th>Link</th></tr></thead><tbody>'
                        + "".join(trows) + "</tbody></table>",
                        unsafe_allow_html=True,
                    )

# ================================================================ MARKET
with tab_market:
    gaps = paths.out_dir() / "market-gaps.md"
    if gaps.exists():
        st.markdown(gaps.read_text())
    else:
        st.markdown('<div class="empty">No market report yet. Run <code>jobcut market</code>.</div>', unsafe_allow_html=True)
