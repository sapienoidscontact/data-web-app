"""
End-to-End Test — Sapienoids Analytics Portal
Run from project root: python tests/test_e2e.py

Does NOT require a real Gemini API key.
Does NOT require Streamlit to be running.
Does NOT require any external files.

Tests each layer in order:
  1. Schema Detection
  2. Domain Mapping
  3. KPI Engine
  4. Visualization Selector
  5. Template Detection
  6. GeminiSentinel (mocked — no real API call)
  7. Forecast Engine
  8. PDF Report Generation
  9. Excel Report Generation
"""

import os
import sys

# Ensure project root is on path regardless of working directory
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Load env vars (keys not needed for this test)
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import io
import traceback
from unittest.mock import patch

import pandas as pd
import numpy as np

# ── Inline sample dataset (no file dependency) ────────────────────────────────
def _make_sales_df() -> pd.DataFrame:
    np.random.seed(42)
    n = 120
    return pd.DataFrame({
        "order_id":    range(1, n + 1),
        "order_date":  pd.date_range("2023-01-01", periods=n, freq="3D"),
        "customer":    np.random.choice(["Alice", "Bob", "Carol", "Dave", "Eve"], n),
        "product":     np.random.choice(["Widget A", "Widget B", "Gadget X"], n),
        "revenue":     np.random.lognormal(mean=5, sigma=0.8, size=n).round(2),
        "quantity":    np.random.randint(1, 20, size=n),
        "discount":    np.random.choice([0.0, 0.05, 0.10, 0.15], n),
        "region":      np.random.choice(["North", "South", "East", "West"], n),
    })


# ── Test harness ──────────────────────────────────────────────────────────────
PASS  = "\033[92mPASS\033[0m"
FAIL  = "\033[91mFAIL\033[0m"
results = []

def run_test(name: str, fn):
    try:
        fn()
        print(f"  [{PASS}] {name}")
        results.append((name, True, None))
    except Exception as exc:
        tb = traceback.format_exc()
        print(f"  [{FAIL}] {name}")
        print(f"           {exc}")
        results.append((name, False, tb))


# ── Individual layer tests ────────────────────────────────────────────────────

def test_schema_detection():
    from core.schema import detect_schema
    df = _make_sales_df()
    schema = detect_schema(df)
    assert schema.row_count == 120
    assert schema.col_count == 8
    assert "order_id" in schema.identifier_cols or "order_id" in [c for c in schema.columns]
    assert len(schema.numeric_cols) >= 2
    assert len(schema.temporal_cols) >= 1
    summary = schema.summary_string()
    assert "rows" in summary.lower()


def test_domain_mapping():
    from core.schema import detect_schema, map_domain
    df = _make_sales_df()
    schema = detect_schema(df)
    domain, scores = map_domain(schema)
    assert domain == "sales", f"Expected 'sales', got '{domain}'"
    assert scores.get("sales", 0) > 0


def test_kpi_engine():
    from core.schema import detect_schema, map_domain
    from core.kpi import compute_kpis, kpis_to_context_string
    df = _make_sales_df()
    schema = detect_schema(df)
    domain, _ = map_domain(schema)
    kpis = compute_kpis(df, schema, domain)
    assert len(kpis) >= 10, f"Expected ≥10 KPIs, got {len(kpis)}"
    ctx = kpis_to_context_string(kpis, kpis[0].column)
    assert "KPI summary" in ctx


def test_visualization_selector():
    from core.schema import detect_schema
    from core.visualization import recommend_charts, render_recommendation
    df = _make_sales_df()
    schema = detect_schema(df)
    recs = recommend_charts(df, schema, max_recommendations=3)
    assert len(recs) >= 1
    fig = render_recommendation(recs[0], df)
    assert fig is not None


def test_template_detection():
    from core.templates import auto_detect_template
    df = _make_sales_df()
    tmpl = auto_detect_template(list(df.columns))
    assert tmpl is not None
    assert tmpl.name == "sales", f"Expected 'sales' template, got '{tmpl.name}'"
    instance = tmpl()
    assert "sales" in instance.ai_prompt_prefix().lower() or "revenue" in instance.ai_prompt_prefix().lower()


def test_gemini_sentinel_mock():
    """Tests the sentinel without a real API key by mocking generate_content."""
    from core.ai import get_sentinel, GeminiSentinel
    import core.ai.gemini_client as _mod

    # Reset singleton so we get a fresh one with mock keys
    _mod._sentinel = None
    with patch.dict(os.environ, {
        "GEMINI_KEY_PRIMARY": "fake_primary_key",
        "GEMINI_KEY_BACKUP":  "fake_backup_key",
    }):
        _mod._sentinel = None  # force re-init with patched env

        class _FakeResponse:
            text = "Mocked AI insight: revenue is growing steadily."

        with patch("google.generativeai.GenerativeModel") as MockModel:
            MockModel.return_value.generate_content.return_value = _FakeResponse()
            sentinel = GeminiSentinel()
            result = sentinel.generate_insight("Test prompt")
            assert "revenue" in result.lower() or "mocked" in result.lower()

        status = GeminiSentinel()
        st = status.get_status()
        assert "keys" in st
        assert "active_key" in st
        assert "both_down" in st

    _mod._sentinel = None  # reset after test


def test_forecast_engine():
    from core.forecast import run_forecast
    df = _make_sales_df()
    result = run_forecast(df, date_col="order_date", value_col="revenue", horizon=10)
    assert result.model_name in ("Linear Trend", "ARIMA(1, 1, 1)", "ARIMA(1, 1, 0)")
    assert len(result.forecast) == 10
    assert "forecast" in result.forecast.columns
    assert "lower" in result.forecast.columns
    assert "upper" in result.forecast.columns
    assert result.figure is not None


def test_pdf_report():
    from core.schema import detect_schema, map_domain
    from core.kpi import compute_kpis
    from core.reports import generate_pdf_report
    df = _make_sales_df()
    schema = detect_schema(df)
    domain, _ = map_domain(schema)
    kpis = compute_kpis(df, schema, domain)
    pdf_bytes = generate_pdf_report(
        df=df, schema=schema, kpi_results=kpis,
        domain=domain, filename="test_sales.csv",
        ai_summary="This is a test AI summary."
    )
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000
    assert pdf_bytes[:4] == b"%PDF"


def test_excel_report():
    from core.schema import detect_schema, map_domain
    from core.kpi import compute_kpis
    from core.reports import generate_excel_report
    df = _make_sales_df()
    schema = detect_schema(df)
    domain, _ = map_domain(schema)
    kpis = compute_kpis(df, schema, domain)
    xl_bytes = generate_excel_report(
        df=df, schema=schema, kpi_results=kpis,
        domain=domain, filename="test_sales.csv"
    )
    assert isinstance(xl_bytes, bytes)
    assert len(xl_bytes) > 1000
    # Verify it's a valid xlsx (PK zip magic bytes)
    assert xl_bytes[:2] == b"PK"


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\nSapienoids Analytics Portal — End-to-End Test Suite")
    print("=" * 55)
    df = _make_sales_df()
    print(f"Sample dataset: {df.shape[0]} rows × {df.shape[1]} columns\n")

    run_test("1. Schema Detection",          test_schema_detection)
    run_test("2. Domain Mapping",            test_domain_mapping)
    run_test("3. KPI Engine (24 formulas)",  test_kpi_engine)
    run_test("4. Visualization Selector",    test_visualization_selector)
    run_test("5. Template Detection",        test_template_detection)
    run_test("6. GeminiSentinel (mocked)",   test_gemini_sentinel_mock)
    run_test("7. Forecast Engine",           test_forecast_engine)
    run_test("8. PDF Report Generation",     test_pdf_report)
    run_test("9. Excel Report Generation",   test_excel_report)

    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    print(f"\n{'='*55}")
    print(f"Results: {passed}/{len(results)} passed", end="")
    if failed:
        print(f"  |  {failed} FAILED")
        for name, ok, tb in results:
            if not ok:
                print(f"\n--- {name} traceback ---\n{tb}")
    else:
        print("  OK  All systems operational")
    print()
    sys.exit(0 if failed == 0 else 1)
