"""
Auto Dashboard Page — the "within clicks" experience.

Renders from st.session_state:
  data, bundle (AnalysisBundle), currency_symbol, ingest_receipt

Sections: preset banner + override → trust receipt → field mapping editor →
filters → KPI tiles → insight cards → preset charts → ask-your-data (NL → SQL
via Gemini + DuckDB) → AI analyst commentary.

Filters re-slice the data live: KPIs, cards and charts all recompute on the
filtered frame.
"""

from __future__ import annotations

from typing import Dict, List

import pandas as pd
import streamlit as st

import re

from ..presets import (AnalysisBundle, ALL_PRESETS, PRESET_BY_NAME, build_bundle,
                       cards_to_context, compute_pack, forget, generate_cards,
                       pack_to_context, remember)
from ..reports.analyst_report import (SECTION_MENU, ReportOptions,
                                      SessionContext, build_analyst_report,
                                      markdown_to_doc, render_markdown,
                                      render_pdf)
from .renderer import build_dashboard_charts, fmt_value

_SEV_STYLE = {
    "good": ("#123B2A", "#22C55E", "✅"),
    "risk": ("#3B1212", "#EF4444", "🔻"),
    "warn": ("#3B2E12", "#F59E0B", "⚠️"),
    "info": ("#12233B", "#3B82F6", "💡"),
}

_SQL_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|create|alter|attach|copy|install"
    r"|load|export|call|vacuum|grant)\b"
    r"|\bpragma\w*|\bduckdb_\w+|\bread_\w+|\bglob\s*\(|\bgetenv\b",
    re.I)


def sanitize_sql(sql: str) -> str:
    """G3 guardrails: single read-only SELECT/WITH statement or ValueError."""
    sql = sql.replace("```sql", "").replace("```", "").strip().rstrip(";").strip()
    if ";" in sql:
        raise ValueError("multiple SQL statements are not allowed")
    if not sql.lower().lstrip().startswith(("select", "with")):
        raise ValueError("only SELECT queries are allowed")
    if _SQL_FORBIDDEN.search(sql):
        raise ValueError("only read-only queries are allowed")
    return sql


def _df_hash(d: pd.DataFrame):
    try:
        return int(pd.util.hash_pandas_object(d, index=False).sum())
    except Exception:
        return (d.shape, tuple(map(str, d.columns)))


@st.cache_data(show_spinner=False, max_entries=32,
               hash_funcs={pd.DataFrame: _df_hash})
def _cached_analysis(df: pd.DataFrame, preset_name: str, mapping_items: tuple):
    """A6: KPIs + cards for a filtered view, cached across widget reruns."""
    preset = PRESET_BY_NAME[preset_name]
    mapping = dict(mapping_items)
    kpis = compute_pack(df, preset, mapping)
    cards = generate_cards(df, preset, mapping, kpis, None)
    return kpis, cards


def _rebuild(preset_name: str | None, overrides: Dict[str, str] | None = None):
    df = st.session_state.data
    st.session_state.bundle = build_bundle(
        df, preset_name=preset_name, mapping_override=overrides,
        currency_symbol=st.session_state.get("currency_symbol", ""),
        column_symbols=st.session_state.get("ingest_symbols"),
    )
    # D1: an explicit user choice (preset pick or mapping edit) is worth
    # remembering — next upload with these columns maps itself.
    b = st.session_state.bundle
    if b.preset and (preset_name or overrides):
        remember(list(df.columns), b.preset.name, b.mapping)


def _render_banner(bundle: AnalysisBundle):
    c1, c2, c3 = st.columns([3, 1, 1])
    with c1:
        st.markdown(f"### {bundle.preset_label}")
        if bundle.preset:
            source = ("💾 remembered from a previous session"
                      if bundle.remembered else
                      f"auto-detected with **{bundle.confidence}%** confidence")
            st.caption(f"{source} · {len(bundle.mapping)} fields mapped · "
                       f"trust score **{bundle.audit.score}/100 "
                       f"({bundle.audit.grade})**")
            if bundle.remembered and st.button("Forget saved mapping",
                                               key="forget_map"):
                forget(list(st.session_state.data.columns))
                _rebuild(None)
                st.rerun()
    with c2:
        options = ["auto"] + [p.name for p in ALL_PRESETS]
        current = bundle.preset.name if bundle.preset else "auto"
        idx = options.index(current) if current in options else 0
        choice = st.selectbox(
            "Industry preset", options, index=idx,
            format_func=lambda n: "🔍 Auto-detect" if n == "auto"
            else f"{PRESET_BY_NAME[n].icon} {PRESET_BY_NAME[n].label}",
        )
        if choice != current:
            _rebuild(None if choice == "auto" else choice)
            st.rerun()
    with c3:
        st.metric("Data trust", f"{bundle.audit.score}/100")


def _render_audit(bundle: AnalysisBundle):
    receipt: List[str] = st.session_state.get("ingest_receipt") or []
    n_issues = len(bundle.audit.issues)
    label = f"🧾 Data receipt — {len(receipt)} fix(es) on load, {n_issues} issue(s) found"
    with st.expander(label, expanded=False):
        if receipt:
            st.markdown("**Fixed automatically on upload:**")
            for r in receipt:
                st.markdown(f"- {r}")
        if bundle.audit.issues:
            st.markdown("**Worth knowing before trusting the numbers:**")
            for i in bundle.audit.issues:
                icon = {"high": "🔴", "medium": "🟠", "low": "🟡"}[i.severity]
                st.markdown(f"- {icon} {i.message}")
        if not receipt and not bundle.audit.issues:
            st.success("Clean load — no fixes needed, no issues found.")


def _render_mapping_editor(bundle: AnalysisBundle, df: pd.DataFrame):
    if not bundle.preset:
        return
    preset = bundle.preset
    matched = sum(1 for f in preset.fields if f.name in bundle.mapping)
    with st.expander(f"🔗 Field mapping — {matched}/{len(preset.fields)} matched "
                     "(edit if anything looks wrong)"):
        cols = st.columns(3)
        new_map: Dict[str, str] = {}
        options = ["— not mapped —"] + list(df.columns)
        for i, f in enumerate(preset.fields):
            current = bundle.mapping.get(f.name, "— not mapped —")
            idx = options.index(current) if current in options else 0
            label = f"{f.name}{' *' if f.required else ''}"
            sel = cols[i % 3].selectbox(label, options, index=idx,
                                        key=f"map_{preset.name}_{f.name}")
            new_map[f.name] = "" if sel == "— not mapped —" else sel
        if st.button("Apply mapping", type="primary"):
            st.session_state["mapping_edited"] = True
            _rebuild(preset.name, new_map)
            st.rerun()


def _render_filters(bundle: AnalysisBundle, df: pd.DataFrame):
    """Returns (filtered_df, human-readable list of active filters)."""
    desc: list = []
    if not bundle.preset or not bundle.preset.filters:
        return df, desc
    mapped = [(f, bundle.mapping[f]) for f in bundle.preset.filters
              if f in bundle.mapping and bundle.mapping[f] in df.columns]
    if not mapped:
        return df, desc
    out = df
    cols = st.columns(len(mapped))
    for i, (fname, col) in enumerate(mapped):
        with cols[i]:
            s = out[col]
            if pd.api.types.is_datetime64_any_dtype(s):
                lo, hi = s.min(), s.max()
                if pd.isna(lo) or lo == hi:
                    continue
                rng = st.date_input(f"📅 {col}", (lo.date(), hi.date()),
                                    min_value=lo.date(), max_value=hi.date(),
                                    key=f"flt_{fname}")
                if isinstance(rng, tuple) and len(rng) == 2:
                    mask = (s.dt.date >= rng[0]) & (s.dt.date <= rng[1])
                    out = out[mask.fillna(False)]
                    if rng[0] != lo.date() or rng[1] != hi.date():
                        desc.append(f"{col}: {rng[0]} to {rng[1]}")
            else:
                vals = s.dropna().astype(str).value_counts().head(30).index.tolist()
                sel = st.multiselect(f"🎚 {col}", vals, key=f"flt_{fname}")
                if sel:
                    out = out[s.astype(str).isin(sel)]
                    desc.append(f"{col}: {', '.join(sel[:5])}"
                                + ("…" if len(sel) > 5 else ""))
    return out, desc


def _render_tiles(kpis, preset, symbol: str):
    tile_keys = preset.tiles if preset else []
    by_key = {k.key: k for k in kpis}
    shown = [by_key[k] for k in tile_keys if k in by_key]
    # fill the row with other computed KPIs if tiles are missing
    for k in kpis:
        if len(shown) >= 4:
            break
        if k not in shown:
            shown.append(k)
    if not shown:
        st.info("No KPIs computable — map the required fields above.")
        return
    cols = st.columns(len(shown[:4]))
    for i, k in enumerate(shown[:4]):
        delta = f"{k.delta_pct:+.1f}% vs prev" if k.delta_pct is not None else None
        color = {"up_good": "normal", "up_bad": "inverse",
                 "neutral": "off"}[k.polarity]
        cols[i].metric(k.label, fmt_value(k.value, k.fmt, symbol),
                       delta=delta, delta_color=color, help=k.description)
    extra = [k for k in kpis if k not in shown[:4]]
    if extra:
        with st.expander(f"➕ {len(extra)} more KPIs"):
            ecols = st.columns(4)
            for i, k in enumerate(extra):
                delta = f"{k.delta_pct:+.1f}%" if k.delta_pct is not None else None
                color = {"up_good": "normal", "up_bad": "inverse",
                         "neutral": "off"}[k.polarity]
                ecols[i % 4].metric(k.label, fmt_value(k.value, k.fmt, symbol),
                                    delta=delta, delta_color=color,
                                    help=k.description)


def _render_cards(cards):
    if not cards:
        return
    st.markdown("#### 🧠 Auto-insights")
    for i, c in enumerate(cards):
        bg, border, icon = _SEV_STYLE.get(c.severity, _SEV_STYLE["info"])
        col_card, col_pin = st.columns([12, 1])
        col_card.markdown(
            f"<div style='background:{bg};border-left:4px solid {border};"
            f"border-radius:8px;padding:0.7rem 1rem;margin-bottom:0.5rem'>"
            f"<b>{icon} {c.headline}</b><br>"
            f"<span style='opacity:0.85;font-size:0.92em'>{c.so_what}</span></div>",
            unsafe_allow_html=True,
        )
        if col_pin.button("📌", key=f"pin_card_{i}",
                          help="Pin this finding into the analyst report"):
            st.session_state.setdefault("pinned", []).append(
                {"type": "card", "headline": c.headline, "so_what": c.so_what})
            st.toast("Pinned to report")


def _render_charts(preset, df, mapping):
    charts = build_dashboard_charts(preset, df, mapping)
    if not charts:
        st.info("No charts renderable yet — check the field mapping.")
        return
    # primary chart full width, rest in a 2-col grid
    st.plotly_chart(charts[0][1], use_container_width=True)
    rest = charts[1:]
    for row_start in range(0, len(rest), 2):
        cols = st.columns(2)
        for j, (spec, fig) in enumerate(rest[row_start:row_start + 2]):
            cols[j].plotly_chart(fig, use_container_width=True)


def _render_ask(df: pd.DataFrame, bundle: AnalysisBundle):
    with st.expander("💬 Ask your data (AI → SQL)"):
        q = st.text_input("Question", placeholder="e.g. top 5 stores by revenue "
                          "in the last month", key="ask_q")
        if st.button("Ask", key="ask_btn") and q.strip():
            try:
                import duckdb
                from ..ai import get_sentinel
                cols_desc = ", ".join(f'"{c}" ({df[c].dtype})' for c in df.columns)
                prompt = (
                    "You write DuckDB SQL. Table name: data. Columns: "
                    f"{cols_desc}. Question: {q}\n"
                    "Reply with ONLY the SQL query, no explanation, no markdown. "
                    "Limit results to 50 rows."
                )
                sql = sanitize_sql(get_sentinel().generate_insight(prompt))
                con = duckdb.connect()
                con.register("data", df)
                result = con.execute(sql).df().head(200)
                # record for the report's session log + pinning
                answer = ""
                if len(result) and result.shape[1] >= 1:
                    answer = f"{len(result)} row(s); top: " + ", ".join(
                        str(v) for v in result.iloc[0].tolist()[:4])
                st.session_state.setdefault("qa_history", []).append(
                    {"q": q.strip(), "sql": sql, "answer": answer})
                st.session_state["last_qa"] = {
                    "q": q.strip(), "sql": sql, "answer": answer,
                    "headers": [str(c) for c in result.columns],
                    "rows": result.head(10).astype(str).values.tolist(),
                }
            except ValueError as ve:
                st.warning(f"Query rejected: {ve}")
            except Exception as e:
                st.error(f"Could not answer: {e}")
        last = st.session_state.get("last_qa")
        if last:
            st.code(last["sql"], language="sql")
            st.dataframe(pd.DataFrame(last["rows"], columns=last["headers"]),
                         use_container_width=True)
            if st.button("📌 Pin this answer to the report", key="pin_qa"):
                st.session_state.setdefault("pinned", []).append(
                    {"type": "qa", **last})
                st.toast("Answer pinned to report")


def _render_commentary(bundle: AnalysisBundle, kpis, cards):
    with st.expander("📝 AI analyst commentary"):
        if st.button("Generate commentary", key="comm_btn"):
            try:
                from ..ai import get_sentinel
                preset = bundle.preset
                prompt = (
                    (preset.ai_prompt if preset else "You are a data analyst. ")
                    + "\n\nWrite a concise analyst memo (headline, 3-5 findings, "
                    "2-3 recommended actions) based ONLY on these computed facts. "
                    "Do not invent numbers.\n\n"
                    + pack_to_context(kpis) + "\n\n" + cards_to_context(cards)
                )
                commentary = get_sentinel().generate_insight(prompt)
                st.session_state["last_commentary"] = commentary
                st.markdown(commentary)
            except Exception as e:
                st.error(f"AI unavailable: {e}")


def _report_studio(bundle: AnalysisBundle, kpis) -> ReportOptions:
    """Pre-generation controls: shape the report before it is built."""
    with st.expander("🛠 Report Studio — customise before generating"):
        c1, c2, c3 = st.columns(3)
        title = c1.text_input("Report title (optional)", key="rs_title",
                              placeholder=f"{bundle.preset.label} - Analyst Report")
        company = c2.text_input("Prepared for (optional)", key="rs_company",
                                placeholder="Company / client name")
        author = c3.text_input("Prepared by (optional)", key="rs_author",
                               placeholder="Your name")
        headline = st.text_input(
            "Override the headline finding (optional)", key="rs_headline",
            placeholder="Leave blank to use the top auto-detected finding")
        notes = st.text_area(
            "Analyst's notes — your own commentary, included as its own "
            "section", key="rs_notes", height=90,
            placeholder="Context the data can't know: campaigns, market "
                        "events, decisions taken…")
        section_labels = {k: lbl for k, lbl in SECTION_MENU}
        default_secs = [k for k, _ in SECTION_MENU]
        secs = st.multiselect(
            "Sections to include", options=default_secs,
            default=default_secs, key="rs_sections",
            format_func=lambda k: section_labels[k])
        kc1, kc2 = st.columns(2)
        kpi_opts = [k.key for k in kpis]
        kpi_sel = kc1.multiselect(
            "KPIs in the scorecard", options=kpi_opts, default=kpi_opts,
            key="rs_kpis", format_func=lambda k: next(
                (x.label for x in kpis if x.key == k), k))
        seg_opts = [f.name for f in bundle.preset.fields
                    if f.role == "categorical" and f.name in bundle.mapping]
        seg_sel = kc2.multiselect(
            "Segment dimensions to deep-dive", options=seg_opts,
            default=seg_opts[:3], key="rs_segs",
            format_func=lambda f: f"{f} → {bundle.mapping.get(f, '')}")
        oc1, oc2, oc3, oc4 = st.columns(4)
        top_n = oc1.slider("Rows per segment table", 3, 15, 5, key="rs_topn")
        horizon = oc2.slider("Forecast horizon (periods, 0 = skip)", 0, 24, 8,
                             key="rs_horizon")
        exhibits = oc3.toggle("Include chart exhibits", value=True,
                              key="rs_exhibits")
        fiscal = oc4.selectbox("Fiscal year starts", ["January", "April"],
                               key="rs_fiscal")
        pinned = st.session_state.get("pinned", [])
        if pinned:
            pc1, pc2 = st.columns([4, 1])
            pc1.caption(f"📌 {len(pinned)} pinned item(s) will appear in "
                        "'Analyst's Selected Evidence'.")
            if pc2.button("Clear pins", key="rs_clear_pins"):
                st.session_state["pinned"] = []
                st.rerun()
    return ReportOptions(
        title=title.strip(), company=company.strip(),
        prepared_by=author.strip(), headline=headline.strip(),
        analyst_notes=notes or "",
        sections=secs if secs and set(secs) != set(default_secs) else None,
        kpi_keys=kpi_sel if kpi_sel and set(kpi_sel) != set(kpi_opts) else None,
        segment_fields=seg_sel if seg_sel else None,
        top_n=top_n,
        forecast_horizon=None if horizon == 8 else horizon,
        include_exhibits=exhibits,
        fiscal_start_month=4 if fiscal == "April" else 1,
    )


def _render_report(bundle: AnalysisBundle, fdf: pd.DataFrame, kpis, cards,
                   filter_desc: list, total_rows: int):
    st.markdown("#### 📄 One-Click Analyst Report")
    st.caption("A full professional review with chart exhibits. Shape it in "
               "the Report Studio, generate, then fine-tune the text before "
               "downloading. Reflects the current filters.")
    opts = _report_studio(bundle, kpis)
    if st.button("Generate analyst report", type="primary", key="rep_btn"):
        with st.spinner("Analysing like it's month-end…"):
            ctx = SessionContext(
                filename=st.session_state.get("filename") or "",
                total_rows=total_rows,
                filters=filter_desc,
                qa_history=st.session_state.get("qa_history", []),
                mapping_edited=bool(st.session_state.get("mapping_edited")),
                ai_commentary=st.session_state.get("last_commentary"),
                pinned=st.session_state.get("pinned", []),
            )
            doc = build_analyst_report(fdf, bundle, kpis, cards, ctx, opts)
            st.session_state["report_bank"] = doc.exhibit_bank()
            st.session_state["report_md"] = render_markdown(doc,
                                                            embed_images=True)
            st.session_state["report_preview"] = render_markdown(
                doc, embed_images=False)
            st.session_state.pop("rs_edit_text", None)  # reset editor
            try:
                st.session_state["report_pdf"] = render_pdf(doc)
            except Exception as e:
                st.session_state["report_pdf"] = None
                st.warning(f"PDF render issue ({e}) — markdown preview below.")
    if not st.session_state.get("report_md"):
        return

    # ── fine-tune the text, then rebuild the PDF from the edited version ──
    with st.expander("✏️ Edit report text (PDF rebuilds from your edits)"):
        st.caption("Edit anything — headings, bullets, tables, wording. Keep "
                   "the `*[Exhibit N …]*` lines where you want the charts; "
                   "delete one to drop that chart. Then apply.")
        edited = st.text_area(
            "Report text", key="rs_edit_text",
            value=st.session_state.get("report_preview", ""), height=380,
            label_visibility="collapsed")
        if st.button("Apply edits & rebuild report", key="rs_apply_edits"):
            try:
                doc2 = markdown_to_doc(edited,
                                       st.session_state.get("report_bank"))
                st.session_state["report_preview"] = edited
                st.session_state["report_md"] = render_markdown(
                    doc2, embed_images=True)
                st.session_state["report_pdf"] = render_pdf(doc2)
                st.success("Report rebuilt from your edited text.")
            except Exception as e:
                st.error(f"Could not rebuild from edits: {e}")

    c1, c2 = st.columns(2)
    if st.session_state.get("report_pdf"):
        c1.download_button(
            "⬇ Download PDF report", st.session_state["report_pdf"],
            file_name=f"analyst_report_{pd.Timestamp.now():%Y%m%d_%H%M}.pdf",
            mime="application/pdf", use_container_width=True)
    c2.download_button(
        "⬇ Download Markdown", st.session_state["report_md"],
        file_name="analyst_report.md", mime="text/markdown",
        use_container_width=True)
    with st.expander("👀 Preview report", expanded=True):
        st.markdown(st.session_state.get("report_preview")
                    or st.session_state["report_md"])


# ── entry point ───────────────────────────────────────────────────────────────

def render_dashboard():
    df = st.session_state.data
    bundle: AnalysisBundle = st.session_state.get("bundle")
    if df is None:
        st.info("Upload a file in the sidebar to get your instant dashboard.")
        return
    if bundle is None:
        _rebuild(None)
        bundle = st.session_state.bundle

    symbol = st.session_state.get("currency_symbol", "")
    _render_banner(bundle)
    _render_audit(bundle)
    _render_mapping_editor(bundle, df)

    if not bundle.preset:
        st.warning("No industry preset matched confidently. Pick one from the "
                   "selector above, or use the classic pages in the sidebar.")
        if bundle.ranking:
            best = bundle.ranking[:3]
            st.caption("Closest matches: " + " · ".join(
                f"{r.preset.icon} {r.preset.label} ({r.confidence}%)" for r in best))
        return

    st.divider()
    fdf, filter_desc = _render_filters(bundle, df)
    filtered = len(fdf) != len(df)
    if filtered:
        st.caption(f"Filtered: {len(fdf):,} of {len(df):,} rows")
        kpis, cards = _cached_analysis(
            fdf, bundle.preset.name, tuple(sorted(bundle.mapping.items())))
    else:
        kpis, cards = bundle.kpis, bundle.cards

    _render_tiles(kpis, bundle.preset, symbol)
    st.divider()
    left, right = st.columns([2, 1])
    with right:
        _render_cards(cards)
    with left:
        _render_charts(bundle.preset, fdf, bundle.mapping)
    st.divider()
    _render_report(bundle, fdf, kpis, cards, filter_desc, len(df))
    _render_ask(fdf, bundle)
    _render_commentary(bundle, kpis, cards)
