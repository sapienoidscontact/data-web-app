"""
Analyst Report Test — one-click professional report, headless.
Run from project root:  python tests/test_report.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core.presets import build_bundle
from core.reports.analyst_report import (ReportOptions, SessionContext,
                                         build_analyst_report,
                                         markdown_to_doc, render_markdown,
                                         render_pdf)
from tests.test_presets import make_retail, make_crm

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


def main():
    print("=" * 60)
    print("  ANALYST REPORT TEST")
    print("=" * 60)

    df = make_retail(500)
    bundle = build_bundle(df, currency_symbol="₹")
    ctx = SessionContext(
        filename="retail_sales.xlsx",
        total_rows=650,
        filters=["Store: Koramangala", "Order Date: 2024-01-01 to 2024-06-30"],
        qa_history=[{"q": "top 5 products by revenue",
                     "sql": "SELECT ...", "answer": "5 rows; top: Latte, 35156"}],
        mapping_edited=True,
        ai_commentary="Revenue is concentrated in beverages; expand espresso line.",
    )
    doc = build_analyst_report(df, bundle, bundle.kpis, bundle.cards, ctx)

    titles = [s.title for s in doc.sections]
    print("\n[1] Report structure")
    expected = ["Executive Summary", "Data & Methodology",
                "Performance Scorecard", "Trend & Momentum",
                "Segment Deep-Dive", "Recommended Actions",
                "Analysis Session Log", "Appendix"]
    for e in expected:
        check(f"section '{e}' present", any(e in t for t in titles),
              str(titles))
    check("at least 9 sections", len(doc.sections) >= 9,
          f"{len(doc.sections)}: {titles}")

    print("\n[2] Content checks")
    md = render_markdown(doc)
    check("headline finding in exec summary", "HEADLINE:" in md)
    check("filters disclosed", "Koramangala" in md)
    check("user question logged", "top 5 products by revenue" in md)
    check("mapping table in appendix", "Canonical field" in md)
    check("movement column populated",
          "favourable" in md or "adverse" in md or "+%" in md)
    check("methodology thresholds listed", "p < 0.05" in md)
    check("filtered-row disclosure", "filtered from" in md)
    check("trend significance reported", "p=" in md)
    check("segment share table present", "Share" in md)

    print("\n[3] Outlook / forecast")
    check("forecast section present", any("Outlook" in t for t in titles),
          str(titles))

    print("\n[4] Visual exhibits")
    imgs = [b for s in doc.sections for b in s.blocks if b[0] == "img"]
    check("at least 5 chart exhibits embedded", len(imgs) >= 5,
          f"{len(imgs)} exhibits")
    check("exhibits are PNGs", all(bytes(i[1][:4]) == b"\x89PNG"
                                   for i in imgs))
    check("exhibits auto-numbered",
          any("Exhibit 1 -" in i[2] for i in imgs), str([i[2] for i in imgs]))
    check("trend exhibit present",
          any("trend" in i[2].lower() for i in imgs))
    check("segment exhibit present",
          any(" by " in i[2] for i in imgs))
    check("concentration exhibit present",
          any("Concentration" in i[2] for i in imgs))
    check("distribution section present",
          any("Distribution" in t for t in titles), str(titles))
    check("recent-periods table with absolute values", "Recent" in md)
    check("markdown embeds images as base64",
          "data:image/png;base64," in md)
    preview = render_markdown(doc, embed_images=False)
    check("preview mode uses placeholders",
          "see PDF for the chart" in preview and
          "base64" not in preview)
    check("table of contents in markdown", "**Contents:**" in md)

    print("\n[5] PDF")
    pdf = render_pdf(doc)
    check("PDF bytes produced", isinstance(pdf, (bytes, bytearray))
          and len(pdf) > 3000, f"{len(pdf)} bytes")
    check("valid PDF header", bytes(pdf[:4]) == b"%PDF")
    check("PDF carries embedded images (>60KB)", len(pdf) > 60_000,
          f"{len(pdf)} bytes")

    print("\n[6] Year-over-year (2-year dataset)")
    df2 = make_retail(900)
    import pandas as pd
    import numpy as np
    rng = np.random.default_rng(9)
    df2["Order Date"] = (pd.Timestamp("2023-01-01")
                         + pd.to_timedelta(rng.integers(0, 730, len(df2)),
                                           unit="D"))
    b2 = build_bundle(df2, currency_symbol="₹")
    doc_yoy = build_analyst_report(df2, b2, b2.kpis, b2.cards)
    check("YoY section appears for multi-year data",
          any("Year-over-Year" in s.title for s in doc_yoy.sections),
          str([s.title for s in doc_yoy.sections]))

    print("\n[5] Works without session context / other presets")
    crm = make_crm(200)
    cb = build_bundle(crm)
    doc2 = build_analyst_report(crm, cb, cb.kpis, cb.cards)
    check("CRM report builds bare", len(doc2.sections) >= 7,
          str([s.title for s in doc2.sections]))
    check("no session log when nothing done",
          not any("Session Log" in s.title for s in doc2.sections))
    pdf2 = render_pdf(doc2)
    check("CRM PDF produced", len(pdf2) > 2000)

    print("\n[7] Report Studio options")
    opts = ReportOptions(
        title="Q2 Trading Review", company="Sapienoids Traders",
        prepared_by="Shafe", headline="Custom headline set by the analyst",
        analyst_notes="Holi promo ran in week 11.\nNew store opened in HSR.",
        sections=["exec", "notes", "scorecard", "trend", "recommendations"],
        kpi_keys=["total_revenue", "aov"],
        top_n=4, forecast_horizon=0, include_exhibits=True,
    )
    doc3 = build_analyst_report(df, bundle, bundle.kpis, bundle.cards,
                                None, opts)
    t3 = [s.title for s in doc3.sections]
    check("custom title used", doc3.title == "Q2 Trading Review")
    check("company + author in subtitle",
          "Sapienoids Traders" in doc3.subtitle and "Shafe" in doc3.subtitle)
    md3 = render_markdown(doc3)
    check("headline override applied",
          "Custom headline set by the analyst" in md3)
    check("analyst notes section included",
          any("Analyst's Notes" in t for t in t3) and "Holi promo" in md3)
    check("excluded sections dropped",
          not any("Segment" in t or "Outlook" in t or "Appendix" in t
                  for t in t3), str(t3))
    # subset governs the scorecard table; findings may still cite any KPI
    check("KPI subset respected in scorecard", "| Avg Order Value |" in md3
          and "| Units Sold |" not in md3)
    opts_noimg = ReportOptions(include_exhibits=False)
    doc4 = build_analyst_report(df, bundle, bundle.kpis, bundle.cards,
                                None, opts_noimg)
    imgs4 = [b for s in doc4.sections for b in s.blocks if b[0] == "img"]
    check("exhibits toggle off works", len(imgs4) == 0, f"{len(imgs4)}")

    print("\n[8] Edit-before-download roundtrip")
    bank = doc.exhibit_bank()
    check("exhibit bank populated", len(bank) >= 5, f"{len(bank)}")
    preview_md = render_markdown(doc, embed_images=False)
    edited = preview_md.replace(
        "## 1. Executive Summary",
        "## 1. Executive Summary (edited by analyst)")
    edited += "\n- Manual closing remark added by the analyst\n"
    doc5 = markdown_to_doc(edited, bank)
    check("edited heading survives",
          any("(edited by analyst)" in s.title for s in doc5.sections),
          str([s.title for s in doc5.sections][:3]))
    imgs5 = [b for s in doc5.sections for b in s.blocks if b[0] == "img"]
    check("exhibits re-attached from bank", len(imgs5) == len(bank),
          f"{len(imgs5)} vs {len(bank)}")
    md5 = render_markdown(doc5)
    check("manual remark present", "Manual closing remark" in md5)
    check("tables survive roundtrip", "| Indicator | Value |" in md5)
    pdf5 = render_pdf(doc5)
    check("edited PDF rebuilds with images", len(pdf5) > 60_000,
          f"{len(pdf5)} bytes")
    # deleting an exhibit placeholder drops that chart
    first_ex_line = next(l for l in preview_md.splitlines()
                         if l.startswith("*[Exhibit 1"))
    doc6 = markdown_to_doc(preview_md.replace(first_ex_line, ""), bank)
    imgs6 = [b for s in doc6.sections for b in s.blocks if b[0] == "img"]
    check("deleting a placeholder drops the chart",
          len(imgs6) == len(bank) - 1, f"{len(imgs6)} vs {len(bank) - 1}")

    print("\n" + "=" * 60)
    print(f"  RESULT: {PASS} passed, {FAIL} failed")
    print("=" * 60)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
