"""
Improvement-batch tests — Tier A fixes, bridge, memory, pins, guardrails, HW.
Run from project root:  python tests/test_improvements.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# isolate the mapping registry from the real user home
os.environ["SAPIENOIDS_HOME"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_tmp_home")

import numpy as np
import pandas as pd

from core.presets import build_bundle, forget, recall, remember
from core.presets.kpis import is_partial_period, last_two_full_periods
from core.reports.analyst_report import (ReportOptions, SessionContext,
                                         build_analyst_report,
                                         render_markdown, render_pdf)
from tests.test_presets import make_retail

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


def make_partial_retail():
    """Full Jan–May + only 3 days of June: June must NOT be the delta basis."""
    rng = np.random.default_rng(2)
    full_days = pd.date_range("2024-01-01", "2024-05-31", freq="D")
    partial_days = pd.date_range("2024-06-01", "2024-06-03", freq="D")
    days = full_days.append(partial_days)
    n = len(days) * 4
    dates = np.random.default_rng(3).choice(days, n)
    return pd.DataFrame({
        "Order ID": [f"O{i}" for i in range(n)],
        "Order Date": pd.to_datetime(dates),
        "Product Name": rng.choice(["A", "B", "C"], n),
        "Store": rng.choice(["S1", "S2"], n),
        "Net Amount": rng.uniform(100, 500, n).round(2),
        "Qty": rng.integers(1, 5, n),
    })


def main():
    print("=" * 60)
    print("  IMPROVEMENT BATCH TEST")
    print("=" * 60)

    print("\n[1] A1 — partial trailing period excluded")
    df = make_partial_retail()
    dates = df["Order Date"]
    cur, prev = last_two_full_periods(dates, "M")
    check("June (3 days) skipped as delta basis",
          str(cur) == "2024-05" and str(prev) == "2024-04",
          f"cur={cur} prev={prev}")
    check("is_partial_period flags June",
          is_partial_period(pd.Period("2024-06", "M"),
                            dates.max(), "M"))
    b = build_bundle(df)
    kv = {k.key: k for k in b.kpis}
    g = kv.get("revenue_growth")
    check("growth is sane (not a -90% partial artifact)",
          g is None or g.value is None or g.value > -50,
          f"growth={g.value if g else None}")
    deltas = [k.delta_pct for k in b.kpis if k.delta_pct is not None]
    check("no delta below -60% from partial June",
          all(d > -60 for d in deltas), str(deltas))

    print("\n[2] A4 — multiple anomalies possible")
    df2 = make_retail(600)
    # inject two separate spikes
    d1 = df2["Order Date"].min() + pd.Timedelta(days=30)
    d2 = df2["Order Date"].min() + pd.Timedelta(days=90)
    extra = df2.head(40).copy()
    extra["Order Date"] = [d1] * 20 + [d2] * 20
    extra["Net Amount"] = 60000
    df2b = pd.concat([df2, extra], ignore_index=True)
    b2 = build_bundle(df2b)
    n_anom = sum(1 for c in b2.cards if c.type == "anomaly")
    check("≥ 2 anomaly cards on double-spike data", n_anom >= 2,
          f"{n_anom} anomaly cards: "
          f"{[c.headline for c in b2.cards if c.type == 'anomaly']}")

    print("\n[3] G3 — SQL guardrails")
    from core.dashboard.page import sanitize_sql
    ok = sanitize_sql("```sql\nSELECT * FROM data LIMIT 5;\n```")
    check("clean SELECT passes", ok.startswith("SELECT"))
    check("column named created_at does not trip the filter",
          bool(sanitize_sql("SELECT created_at FROM data")))
    check("CTE queries pass",
          bool(sanitize_sql("WITH t AS (SELECT 1) SELECT * FROM t")))
    for bad in ["DROP TABLE data", "SELECT 1; DROP TABLE data",
                "INSERT INTO data VALUES (1)", "COPY data TO 'x.csv'",
                "update data set x=1",
                "SELECT * FROM pragma_database_list",
                "SELECT * FROM read_csv('c:/secrets.txt')",
                "select getenv(1)"]:
        try:
            sanitize_sql(bad)
            check(f"rejected: {bad[:30]}", False)
        except ValueError:
            check(f"rejected: {bad[:30]}", True)

    print("\n[4] D1 — mapping memory")
    cols = list(df2.columns)
    forget(cols)
    check("no recall before remember", recall(cols) is None)
    remember(cols, "retail", {"revenue": "Net Amount",
                              "order_date": "Order Date"})
    hit = recall(cols)
    check("recall returns saved mapping", hit is not None
          and hit["preset"] == "retail"
          and hit["mapping"]["revenue"] == "Net Amount")
    b3 = build_bundle(df2)
    check("bundle uses remembered mapping (confidence 100)",
          b3.remembered and b3.confidence == 100
          and b3.mapping.get("revenue") == "Net Amount")
    forget(cols)
    b4 = build_bundle(df2)
    check("forget restores auto-detection", not b4.remembered)

    print("\n[5] B1 — bridge section + waterfall exhibit")
    b5 = build_bundle(make_retail(700), currency_symbol="₹")
    doc = build_analyst_report(make_retail(700), b5, b5.kpis, b5.cards)
    titles = [s.title for s in doc.sections]
    check("bridge section present", any("Bridge" in t for t in titles),
          str(titles))
    bridge_sec = next((s for s in doc.sections if "Bridge" in s.title), None)
    if bridge_sec:
        has_img = any(blk[0] == "img" for blk in bridge_sec.blocks)
        check("waterfall exhibit embedded", has_img)
        md = render_markdown(doc, embed_images=False)
        check("bridge explains the driver", "explains" in md)

    print("\n[6] E1 — pinned evidence section")
    ctx = SessionContext(pinned=[
        {"type": "qa", "q": "top stores?", "headers": ["Store", "Rev"],
         "rows": [["S1", "100"]], "answer": "1 row"},
        {"type": "card", "headline": "Revenue is rising",
         "so_what": "keep going"},
    ])
    doc2 = build_analyst_report(make_retail(300), b5, b5.kpis, b5.cards, ctx)
    md2 = render_markdown(doc2)
    check("evidence section built",
          any("Selected Evidence" in s.title for s in doc2.sections))
    check("pinned Q&A included", "top stores?" in md2)
    check("pinned card included", "Revenue is rising" in md2)

    print("\n[7] A8 — fiscal year YoY")
    df3 = make_retail(800)
    rng = np.random.default_rng(4)
    df3["Order Date"] = (pd.Timestamp("2022-06-01") + pd.to_timedelta(
        rng.integers(0, 700, len(df3)), unit="D"))
    b6 = build_bundle(df3, currency_symbol="₹")
    doc3 = build_analyst_report(df3, b6, b6.kpis, b6.cards, None,
                                ReportOptions(fiscal_start_month=4))
    md3 = render_markdown(doc3, embed_images=False)
    check("fiscal YoY labels (FY)", "FY20" in md3, md3[:0])
    check("fiscal framing disclosed", "Fiscal years starting Apr" in md3)

    print("\n[8] C1 — Holt-Winters seasonal forecasting")
    from core.forecast import run_forecast
    days = pd.date_range("2024-01-01", periods=120, freq="D")
    seasonal = 1000 + 300 * np.sin(np.arange(120) * 2 * np.pi / 7) \
        + np.random.default_rng(5).normal(0, 40, 120)
    ts = pd.DataFrame({"ds": days, "y": seasonal})
    res = run_forecast(ts, "ds", "y", horizon=14)
    check("seasonal model selected for weekly-cyclic daily data",
          "Holt-Winters" in res.model_name, res.model_name)
    check("forecast has confidence band",
          {"lower", "upper"} <= set(res.forecast.columns))
    check("forecast preserves the weekly cycle",
          res.forecast["forecast"].std() > 100,
          f"std={res.forecast['forecast'].std():.0f}")
    # non-seasonal path still works
    flat = pd.DataFrame({"ds": pd.date_range("2024-01-01", periods=40,
                                             freq="W"),
                         "y": np.linspace(100, 200, 40)})
    res2 = run_forecast(flat, "ds", "y", horizon=6)
    check("weekly-grain series uses non-seasonal model",
          "Holt-Winters" not in res2.model_name, res2.model_name)

    print("\n[9] A7 — unicode ₹ in PDF")
    pdf = render_pdf(doc)
    check("PDF renders with embedded font", len(pdf) > 50_000,
          f"{len(pdf)} bytes")
    check("PDF valid", bytes(pdf[:4]) == b"%PDF")

    print("\n" + "=" * 60)
    print(f"  RESULT: {PASS} passed, {FAIL} failed")
    print("=" * 60)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
