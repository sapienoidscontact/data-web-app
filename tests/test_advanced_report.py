"""
Advanced analyst report tests — volume/rate, pace, cohorts, lag scan,
backtest overlay, exhibit picker, coverage disclosure.
Run from project root:  python tests/test_advanced_report.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
os.environ["SAPIENOIDS_HOME"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_tmp_home")

import numpy as np
import pandas as pd

from core.presets import build_bundle
from core.reports.analyst_report import (CHART_MENU, ReportOptions,
                                         build_analyst_report,
                                         render_markdown, render_pdf)

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


def make_rich_retail(n=3000):
    """Retail with repeat customers over 8 months — exercises every section."""
    rng = np.random.default_rng(42)
    customers = [f"CUST{i:04d}" for i in range(300)]
    dates = pd.Timestamp("2024-01-01") + pd.to_timedelta(
        rng.integers(0, 240, n), unit="D")
    return pd.DataFrame({
        "Order ID": [f"ORD{i:06d}" for i in range(n)],
        "Order Date": dates,
        "Customer ID": rng.choice(customers, n),
        "Product Name": rng.choice(["Latte", "Espresso", "Green Tea",
                                    "Masala Tea", "Cold Brew"], n),
        "Category": rng.choice(["Coffee", "Tea"], n),
        "Store": rng.choice(["Koramangala", "Indiranagar", "HSR"], n),
        "Qty": rng.integers(1, 6, n),
        "Net Amount": np.round(rng.lognormal(5.8, 0.5, n), 2),
        "Discount": np.round(rng.uniform(0, 120, n), 2),
    })


def exhibits(doc):
    return [b for s in doc.sections for b in s.blocks if b[0] == "img"]


def main():
    print("=" * 60)
    print("  ADVANCED ANALYST REPORT TEST")
    print("=" * 60)
    df = make_rich_retail()
    bundle = build_bundle(df, currency_symbol="₹")
    doc = build_analyst_report(df, bundle, bundle.kpis, bundle.cards)
    titles = [s.title for s in doc.sections]
    md = render_markdown(doc, embed_images=False)

    print("\n[1] New sections present")
    for want in ["Volume vs Rate", "Cohorts & Repeat", "Driver"]:
        present = any(want in t for t in titles)
        disclosed = any(want in s[0] for s in doc.skips)
        check(f"'{want}' section present or skip disclosed",
              present or disclosed, str(titles) + str(doc.skips))

    print("\n[2] Volume vs Rate content")
    check("volume and rate contributions quantified",
          "Volume (" in md and "Rate (value per unit)" in md)
    check("dominant driver named", "Dominant driver" in md)
    check("playbook guidance present", "different playbooks" in md)

    print("\n[3] Cohorts content")
    check("repeat rate reported", "Repeat rate" in md)
    check("entities count reported", "Entities analysed" in md)
    caps = [b[2] for b in exhibits(doc)]
    check("cohort retention grid exhibit",
          any("Retention by first-activity cohort" in c for c in caps),
          str(caps))

    print("\n[4] New exhibits rendered")
    for want in ["KPI movement overview", "volume x rate",
                 "Trend per top", "Correlation matrix"]:
        check(f"exhibit '{want}'", any(want in c for c in caps), str(caps))
    check("≥ 10 exhibits total in rich report", len(caps) >= 10,
          f"{len(caps)}")

    print("\n[5] Forecast backtest")
    outlook_ok = any("Outlook" in t for t in titles)
    check("outlook section", outlook_ok)
    if outlook_ok:
        check("holdout backtest disclosed",
              "Holdout backtest error" in md or "backtest" in md.lower())

    print("\n[6] Coverage disclosure (nothing silently skipped)")
    check("skips recorded", len(doc.skips) >= 1,
          str(doc.skips))
    check("appendix discloses skips",
          "not applicable to this dataset" in md)
    # YoY must be among skips for 8-month data
    check("YoY skip reason present",
          any("Year-over-Year" in s[0] for s in doc.skips), str(doc.skips))

    print("\n[7] Exhibit picker (chart_kinds)")
    only_trend = build_analyst_report(
        df, bundle, bundle.kpis, bundle.cards, None,
        ReportOptions(chart_kinds=["trend"]))
    caps2 = [b[2] for b in exhibits(only_trend)]
    check("only trend exhibits kept", len(caps2) >= 1
          and all("trend" in c.lower() for c in caps2), str(caps2))
    check("CHART_MENU has 14 kinds", len(CHART_MENU) == 14,
          str(len(CHART_MENU)))

    print("\n[8] Pace section on in-progress period")
    dfp = df[df["Order Date"] <= "2024-08-10"]  # August partial
    bp = build_bundle(dfp, currency_symbol="₹")
    docp = build_analyst_report(dfp, bp, bp.kpis, bp.cards)
    mdp = render_markdown(docp, embed_images=False)
    has_pace = any("Pace" in s.title for s in docp.sections)
    pace_skipped = any("Pace" in s[0] for s in docp.skips)
    check("pace section built or explicitly skipped with reason",
          has_pace or pace_skipped, str(docp.skips))
    if has_pace:
        check("pace projects run-rate", "run-rate" in mdp)

    print("\n[9] PDF with all new exhibits")
    pdf = render_pdf(doc)
    check("PDF renders", bytes(pdf[:4]) == b"%PDF" and len(pdf) > 100_000,
          f"{len(pdf)} bytes")

    print("\n" + "=" * 60)
    print(f"  RESULT: {PASS} passed, {FAIL} failed")
    print("=" * 60)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
