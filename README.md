# 📊 Sapienoids Analytics Portal

Upload a CSV or Excel file → get an **industry-aware analytics dashboard and a
professional analyst report in two clicks**. No setup, no formulas, no BI tool
learning curve.

> ⚡ Live app: deploy your own in minutes on Streamlit Community Cloud
> (see [Deployment](#-deployment)).

---

## What it does

1. **Resilient ingestion** — survives real-world exports: title rows above the
   header, `₹1,23,456.00` currency strings, `(500)` bracket negatives,
   DD-MM-YYYY dates, grand-total rows, multi-sheet workbooks, pivoted
   months-as-columns reports. Every fix is listed in a visible data receipt.
2. **Industry preset detection** — 15 built-in presets (Retail & E-commerce,
   B2B Sales/CRM, Finance, HR, Marketing, Logistics, Manufacturing,
   Healthcare, Education, Real Estate, Hospitality, SaaS, Lending/NBFC,
   Energy, Nonprofit). Columns are auto-mapped to business meaning
   ("Bill Amt" → revenue) with a one-screen override, and confirmed mappings
   are **remembered** so next month's file is zero-click.
3. **Expert analysis engine** — data trust score, business KPIs with
   period-over-period movement (partial trailing periods excluded), trend
   tests with seasonal adjustment and p-values, anomaly detection with
   segment attribution, concentration risk, waterfall bridge decomposition
   ("which segment moved the number"), correlation-based driver scan, and
   seasonality-aware forecasting (Holt-Winters / ARIMA / linear,
   auto-selected).
4. **One-click Analyst Report** — a 20-section illustrated PDF/Markdown
   review: executive summary, scorecard with KPI-movement tornado, trend &
   momentum, period bridge, **volume-vs-rate decomposition with mix-shift
   (Simpson's paradox) check**, current-period pace tracking, year-over-year
   (calendar or Indian fiscal year), seasonality, segment deep-dive with
   small-multiples and Pareto curve, **cohort retention & repeat behaviour**,
   distribution & outliers, findings, driver associations with correlation
   heatmap and lagged leading-indicator scan, forecast outlook **with holdout
   backtest overlay**, recommended actions, session log and a methodology
   appendix that **discloses every skipped analysis with its reason** — up to
   ~13 auto-numbered chart exhibits (14 selectable kinds). Shape it in the
   **Report Studio** (branding, your own notes, section/KPI/exhibit
   selection) and even **edit the report text in-app** before the PDF is
   rebuilt.
5. **Ask your data** — natural-language questions become read-only SQL
   (DuckDB) with strict guardrails; pin any answer or insight into the report.
6. **Optional AI commentary** — Google Gemini writes prose around *computed*
   facts only (aggregates, never raw rows). Works fully without any AI key.

## Quick start (local)

```bash
git clone https://github.com/sapienoidscontact/data-web-app.git
cd data-web-app
pip install -r requirements.txt
streamlit run D1.py          # or: run.bat on Windows
```

Optional AI features: get a free Gemini key at
[aistudio.google.com](https://aistudio.google.com) and either add it in the
app sidebar (🔑 expander) or copy `.env.example` → `.env`.

## 🚀 Deployment

**Streamlit Community Cloud (free):** fork/use this repo →
[share.streamlit.io](https://share.streamlit.io) → New app → main file
`D1.py`, Python 3.11 → Deploy. Add Gemini keys under *Settings → Secrets*
(or in-app at runtime):

```toml
GEMINI_KEY_PRIMARY = "AIza..."
GEMINI_KEY_BACKUP  = "AIza..."   # optional failover
```

## Tests

144 headless checks across five suites, plus a Streamlit AppTest harness:

```bash
python tests/test_e2e.py            # original engine suite
python tests/test_presets.py       # ingestion, detection, KPIs, charts
python tests/test_report.py        # analyst report + Report Studio
python tests/test_improvements.py  # correctness batch (partial periods, …)
python tests/test_edge_cases.py    # degenerate inputs never crash
```

## Project structure

```
D1.py                  Streamlit app (pages, sidebar, upload pipeline)
core/ingest/           resilient file loading + cleaning receipt
core/schema/           column role detection
core/presets/          15 industry presets, field mapper, KPIs, audit,
                       insight cards, mapping memory
core/dashboard/        auto-dashboard page + chart renderer
core/reports/          analyst report builder, exhibits, PDF/Markdown
core/forecast/         linear / ARIMA / Holt-Winters auto-selection
core/ai/               Gemini client with dual-key failover
docs/                  product specs, backlog, terms & privacy
tests/                 headless test suites
```

## 🔒 Privacy & data handling (summary)

- Uploaded files are processed **in memory for your session only** — nothing
  is written to a database or shared between visitors.
- AI features send **only aggregate statistics and column names** to Google
  Gemini — never raw rows. With no key configured, no data leaves the app.
- The mapping memory stores **column names only** (never values) locally.
- Full text: [docs/TERMS_AND_PRIVACY.md](docs/TERMS_AND_PRIVACY.md) — users
  accept it in-app before uploading.

## Disclaimer

Outputs are automated statistical analysis for **informational purposes
only** — not financial, medical, legal or investment advice. Verify figures
against source systems before making decisions.

## License

Copyright © 2026 Sapienoids. Source is visible for transparency and personal
evaluation; **all rights reserved** — contact the author for any other use.
