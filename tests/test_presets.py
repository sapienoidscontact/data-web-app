"""
Preset Pipeline Test — headless end-to-end check of the new engine.
Run from project root:  python tests/test_presets.py

Covers:
  1. Resilient ingest (title rows, ₹ currency strings, DD-MM-YYYY dates, total row)
  2. Preset detection + field mapping (retail, HR, CRM, logistics)
  3. Mapped KPI pack (values verified against pandas ground truth)
  4. Data audit (duplicates, categorical inconsistency)
  5. Insight cards
  6. Dashboard chart rendering (plotly figures, no Streamlit needed)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows console emoji safety

import numpy as np
import pandas as pd

from core.ingest import load_bytes
from core.presets import build_bundle, rank_presets, ALL_PRESETS
from core.schema import detect_schema
from core.dashboard.renderer import build_dashboard_charts, fmt_value

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


# ── 1. Ingest ─────────────────────────────────────────────────────────────────

def test_ingest():
    print("\n[1] Resilient ingest")
    csv = (
        "Sapienoids Traders Pvt Ltd\n"
        "Sales Register 01-01-2024 to 31-03-2024\n"
        "Bill Date,Item Name,Qty,Net Amount,Store\n"
        "05-01-2024,Masala Tea,3,\"₹1,250.00\",Koramangala\n"
        "06-01-2024,Green Tea,2,\"₹840.50\",Indiranagar\n"
        "07-02-2024,Masala Tea,5,\"₹2,100.00\",Koramangala\n"
        "08-02-2024,Filter Coffee,1,\"₹(300.00)\",Indiranagar\n"
        "09-03-2024,Green Tea,4,\"₹1,600.00\",Koramangala\n"
        "Grand Total,,15,\"₹5,490.50\",\n"
    ).encode("utf-8")
    res = load_bytes("register.csv", csv)
    df = res.df
    check("title rows skipped", list(df.columns)[0] == "Bill Date", str(df.columns))
    check("total row removed", len(df) == 5, f"rows={len(df)}")
    check("currency parsed to numeric",
          pd.api.types.is_numeric_dtype(df["Net Amount"]), str(df.dtypes))
    check("paren negative parsed", float(df["Net Amount"].min()) == -300.0)
    check("currency symbol detected", res.currency_symbol == "₹")
    check("DD-MM date parsed",
          pd.api.types.is_datetime64_any_dtype(df["Bill Date"]))
    check("dayfirst respected", df["Bill Date"].iloc[0].day == 5)
    check("receipt written", len(res.receipt) >= 3, str(res.receipt))
    return df


# ── synthetic datasets ────────────────────────────────────────────────────────

def make_retail(n=400):
    rng = np.random.default_rng(7)
    dates = pd.to_datetime("2024-01-01") + pd.to_timedelta(
        rng.integers(0, 180, n), unit="D")
    return pd.DataFrame({
        "Order ID": [f"ORD-{i:05d}" for i in range(n)],
        "Order Date": dates,
        "Product Name": rng.choice(
            ["Masala Tea", "Green Tea", "Filter Coffee", "Hot Chocolate",
             "Espresso", "Latte"], n),
        "Category": rng.choice(["Tea", "Coffee", "Other"], n),
        "Store": rng.choice(["Koramangala", "Indiranagar", "HSR"], n),
        "Qty": rng.integers(1, 10, n),
        "Net Amount": np.round(rng.lognormal(6, 0.6, n), 2),
        "Discount": np.round(rng.uniform(0, 200, n), 2),
    })


def make_hr(n=200):
    rng = np.random.default_rng(3)
    join = pd.Series(pd.to_datetime("2019-01-01") + pd.to_timedelta(
        rng.integers(0, 1800, n), unit="D"))
    exit_ = pd.Series(pd.NaT, index=range(n))
    leavers = rng.choice(n, 40, replace=False)
    exit_.iloc[leavers] = join.iloc[leavers] + pd.to_timedelta(
        rng.integers(90, 900, 40), unit="D")
    return pd.DataFrame({
        "Employee Code": [f"EMP{i:04d}" for i in range(n)],
        "Department": rng.choice(["Engineering", "Sales", "Operations",
                                  "Finance", "HR"], n),
        "Designation": rng.choice(["Analyst", "Manager", "Lead", "Director"], n),
        "Gender": rng.choice(["Male", "Female"], n),
        "CTC": np.round(rng.lognormal(13.5, 0.4, n), 0),
        "Date of Joining": join,
        "Exit Date": exit_,
    })


def make_crm(n=150):
    rng = np.random.default_rng(11)
    created = pd.to_datetime("2024-01-01") + pd.to_timedelta(
        rng.integers(0, 150, n), unit="D")
    return pd.DataFrame({
        "Deal Value": np.round(rng.lognormal(10, 0.8, n), 0),
        "Deal Stage": rng.choice(["Prospecting", "Qualified", "Proposal",
                                  "Negotiation", "Closed Won", "Closed Lost"], n),
        "Created Date": created,
        "Close Date": created + pd.to_timedelta(rng.integers(10, 120, n), unit="D"),
        "Owner": rng.choice(["Asha", "Rahul", "Meera", "Vikram"], n),
        "Company": rng.choice([f"Acct {i}" for i in range(30)], n),
        "Lead Source": rng.choice(["Inbound", "Outbound", "Referral"], n),
    })


def make_logistics(n=300):
    rng = np.random.default_rng(5)
    ship = pd.to_datetime("2024-02-01") + pd.to_timedelta(
        rng.integers(0, 120, n), unit="D")
    status = rng.choice(["Delivered", "In Transit", "RTO", "Delivered",
                         "Delivered"], n)
    return pd.DataFrame({
        "AWB Number": [f"AWB{i:07d}" for i in range(n)],
        "Dispatch Date": ship,
        "Delivery Date": ship + pd.to_timedelta(rng.integers(1, 9, n), unit="D"),
        "Delivery Status": status,
        "Courier Partner": rng.choice(["Delhivery", "BlueDart", "DTDC"], n),
        "Freight Amount": np.round(rng.uniform(40, 400, n), 2),
        "Destination": rng.choice(["Mumbai", "Delhi", "Bengaluru", "Pune"], n),
    })


# ── 2–5. Pipeline per industry ────────────────────────────────────────────────

def test_detection_and_kpis():
    print("\n[2] Preset detection + field mapping")
    cases = [
        (make_retail(), "retail", {"order_date", "revenue", "product"}),
        (make_hr(), "hr", {"employee_id", "department"}),
        (make_crm(), "sales_crm", {"deal_value", "stage", "created_date"}),
        (make_logistics(), "logistics", {"ship_date", "status"}),
    ]
    for df, expected, must_map in cases:
        bundle = build_bundle(df)
        got = bundle.preset.name if bundle.preset else "none"
        check(f"{expected} detected", got == expected,
              f"got={got} conf={bundle.confidence}")
        missing = must_map - set(bundle.mapping)
        check(f"{expected} core fields mapped", not missing, f"missing={missing}")

    print("\n[3] Mapped KPI pack (ground-truth check)")
    df = make_retail()
    bundle = build_bundle(df)
    kv = {k.key: k for k in bundle.kpis}
    check("total_revenue == sum", "total_revenue" in kv and
          abs(kv["total_revenue"].value - df["Net Amount"].sum()) < 0.01)
    check("order_count == distinct orders", "order_count" in kv and
          kv["order_count"].value == df["Order ID"].nunique())
    if "aov" in kv:
        expected_aov = df["Net Amount"].sum() / df["Order ID"].nunique()
        check("aov = revenue/orders", abs(kv["aov"].value - expected_aov) < 0.01)
    check("units_sold == sum qty", "units_sold" in kv and
          kv["units_sold"].value == df["Qty"].sum())
    check("growth KPI computed", "revenue_growth" in kv)
    check("deltas present on some KPIs",
          any(k.delta_pct is not None for k in bundle.kpis))

    crm = make_crm()
    cb = build_bundle(crm)
    ckv = {k.key: k for k in cb.kpis}
    won = crm["Deal Stage"].str.lower().eq("closed won").mean() * 100
    check("CRM win_rate matches", "win_rate" in ckv and
          abs(ckv["win_rate"].value - won) < 0.5,
          f"{ckv.get('win_rate') and ckv['win_rate'].value} vs {won}")
    check("CRM sales_cycle in days", "sales_cycle" in ckv and
          0 < ckv["sales_cycle"].value < 200)

    print("\n[4] Data audit")
    dirty = pd.concat([df, df.head(30)], ignore_index=True)  # 30 dupes
    dirty.loc[5, "Store"] = "KORAMANGALA "                    # case/space variant
    b2 = build_bundle(dirty)
    kinds = {i.kind for i in b2.audit.issues}
    check("duplicates flagged", "duplicates" in kinds, str(kinds))
    check("inconsistent categories flagged", "inconsistent" in kinds, str(kinds))
    check("trust score reduced", b2.audit.score < 100)

    print("\n[5] Insight cards")
    check("cards generated", len(bundle.cards) >= 1,
          f"{len(bundle.cards)} cards")
    check("cards ranked by materiality",
          all(bundle.cards[i].materiality >= bundle.cards[i + 1].materiality
              for i in range(len(bundle.cards) - 1)))
    return bundle, df


# ── 6. Charts ─────────────────────────────────────────────────────────────────

def test_charts(bundle, df):
    print("\n[6] Dashboard charts (headless plotly)")
    charts = build_dashboard_charts(bundle.preset, df, bundle.mapping)
    check("≥ 3 charts rendered", len(charts) >= 3, f"{len(charts)} charts")
    for spec, fig in charts:
        check(f"chart '{spec.title}' has traces", len(fig.data) >= 1)

    print("\n[7] Formatting")
    check("Indian compact currency", fmt_value(12_50_000, "currency", "₹")
          == "₹12.50 L", fmt_value(12_50_000, "currency", "₹"))
    check("crore formatting", fmt_value(3.2e7, "currency", "₹")
          == "₹3.20 Cr", fmt_value(3.2e7, "currency", "₹"))
    check("western compact", fmt_value(1_200_000, "currency", "$") == "$1.20M",
          fmt_value(1_200_000, "currency", "$"))
    check("percent", fmt_value(12.345, "percent") == "12.3%")


def test_all_presets_safe():
    """Every preset must survive an arbitrary dataframe without raising."""
    print("\n[8] Robustness: every preset on every dataset (no crashes)")
    dfs = [make_retail(80), make_hr(60), make_crm(60), make_logistics(60)]
    errors = 0
    for df in dfs:
        schema = detect_schema(df)
        for preset in ALL_PRESETS:
            try:
                b = build_bundle(df, schema=schema, preset_name=preset.name)
                build_dashboard_charts(preset, df, b.mapping)
            except Exception as e:
                errors += 1
                print(f"    💥 {preset.name}: {e}")
    check("no preset crashes on any dataset", errors == 0, f"{errors} errors")


if __name__ == "__main__":
    print("=" * 60)
    print("  PRESET PIPELINE TEST")
    print("=" * 60)
    test_ingest()
    bundle, df = test_detection_and_kpis()
    test_charts(bundle, df)
    test_all_presets_safe()
    print("\n" + "=" * 60)
    print(f"  RESULT: {PASS} passed, {FAIL} failed")
    print("=" * 60)
    sys.exit(1 if FAIL else 0)
