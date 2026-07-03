# Roadmap: Replacing the Entire Data Analytics Workflow

Goal: a user in **any** industry uploads their file(s), the app recognizes what the data
is, maps it to a known industry preset, and delivers a complete analytics experience —
cleaning, KPIs, dashboard, forecasts, AI insights, and a branded report — **within clicks**,
with zero configuration required and full override available.

This document maps the standard analytics workflow stage-by-stage against what the app
already does, what is missing, and how to build it on top of the existing architecture
(`core/schema`, `core/kpi`, `core/templates`, `core/visualization`, `core/forecast`,
`core/reports`, `core/ai`).

---

## The workflow being replaced

A typical business today does analytics like this:

| Stage | Typical tools today | Pain |
|---|---|---|
| 1. Collect / export | ERP, POS, CRM, HRMS exports → Excel | Manual, repetitive |
| 2. Clean & reshape | Excel formulas, copy-paste, sometimes Python | Error-prone, hours per report |
| 3. Combine sources | VLOOKUP / Power Query | Breaks constantly |
| 4. Define metrics | Tribal knowledge, ad-hoc formulas | Inconsistent definitions |
| 5. Visualize | Excel charts, Power BI, Tableau | Requires a specialist |
| 6. Analyze / explain | Analyst writes commentary | Slow, expensive |
| 7. Forecast | Rarely done, or naive trendlines | Needs a data scientist |
| 8. Report & distribute | PowerPoint / PDF emailed monthly | Manual assembly |

The app replaces stages 2–8. Stage 1 remains "export a file" initially, later replaced by
connectors.

---

## Stage-by-stage gap analysis

### Stage A — Ingestion (currently: single clean CSV/XLSX, first sheet only)

**Have:** `D1.py` sidebar uploader → `pd.read_csv` / `pd.read_excel`.

**Missing / build next:**
1. **Messy-file resilience** — real business exports are not clean tables:
   - Header-row detection (skip title/logo rows; detect the row where column names live).
   - Merged-cell and multi-row header flattening.
   - Delimiter + encoding sniffing for CSV (`csv.Sniffer`, `charset-normalizer`).
   - Footer/total-row detection and removal (Tally, bank statements end with totals).
   - Currency/percent string parsing: `"₹1,23,456.00"`, `"$1,234"`, `"45%"`, `"(500)"` → numeric.
   - Indian and EU number formats (lakh/crore grouping, comma decimals).
   - Date format inference incl. `DD-MM-YYYY` vs `MM-DD-YYYY` disambiguation via column scan.
2. **Multi-sheet Excel** — sheet picker + "analyze all sheets" (each sheet = a table).
3. **More formats** — JSON (records + nested), Parquet, Google Sheets URL, TSV, fixed-width bank exports, PDF table extraction (later).
4. **Multi-file sessions** — upload several files; each becomes a DuckDB table (see Stage C).
5. **Pivoted-report detection** — detect "months as columns" style exports and auto-unpivot
   to long format (very common in finance/retail exports).

**Where it lives:** new module `core/ingest/` (`loader.py`, `header_detect.py`, `coerce.py`,
`unpivot.py`). The sidebar uploader calls `core.ingest.load(file)` instead of raw pandas.

### Stage B — Cleaning & preparation (currently: manual Wrangle page)

**Have:** manual dedupe/dropna style operations in the Wrangle page.

**Missing / build next:**
1. **Auto-clean pipeline** that runs on upload and shows a "what we fixed" receipt:
   trim whitespace, normalize casing of categoricals, coerce types per schema roles,
   standardize dates, flag (not delete) outliers and dupes.
2. **Cleaning recipes per preset** — each industry preset declares expected fixes
   (e.g., retail: strip SKU prefixes; finance: parse bracketed negatives).
3. **Undoable step log** — every transform recorded; exportable as a reusable recipe so the
   next month's file cleans itself in one click. This is the moat: *repeatability*.

**Where it lives:** new module `core/clean/` with a `CleaningStep` log stored in session +
downloadable as JSON recipe; presets reference recipe fragments.

### Stage C — Combining data (currently: none; DuckDB installed but unused)

**Missing / build next:**
1. Register every uploaded table into an in-memory **DuckDB** connection.
2. **Auto-join suggestion**: match key columns across tables by name + value overlap
   (e.g., `customer_id` in orders ↔ customers) and offer one-click join.
3. SQL escape hatch on the Explore page (DuckDB query box) for power users.

**Where it lives:** new module `core/store/duck.py`. This unlocks the single biggest gap
versus real workflows — analytics is almost never one table.

### Stage D — Semantic layer / field mapping (currently: dataset-level domain guess only)

**Have:** `core/schema/detector.py` (column roles) + `core/schema/mapper.py` (whole-dataset
domain via keyword scoring). Good foundation, but it stops at "this is sales data".

**Missing / build next — the heart of the preset system:**
1. **Field-level canonical mapping**: bind each physical column to a canonical field defined
   by the industry preset (`"Amt (₹)"` → `revenue`, `"Qty."` → `quantity`,
   `"Bill Date"` → `order_date`). Uses synonym lists + role from the detector + value-shape
   checks (see `docs/INDUSTRY_PRESETS.md` for the per-industry canonical schemas).
2. **Confidence scoring + one confirmation screen**: after upload the user sees
   "Detected: Retail & E-commerce (92%)" with the proposed column→field mapping and can
   fix any binding from a dropdown. One screen, then everything downstream is automatic.
   This single screen is what makes "end-to-end within clicks" honest.
3. **Mapping memory**: persist confirmed mappings keyed by (filename pattern, column-set hash)
   in `core/schema/registry.py` so next month's export maps with zero clicks.

**Where it lives:** extend `core/schema/mapper.py` → `map_fields(schema, preset)`;
extend `registry.py` for persistence (JSON file or SQLite, not just in-memory).

### Stage E — KPIs (currently: 24 formulas on ONE auto-picked column)

**Have:** `core/kpi/library.py` + `engine.py`. **Critical limitation:** `compute_kpis`
selects a single numeric column; every KPI runs on that one column.

**Missing / build next:**
1. **Multi-field KPIs** — formulas take the canonical field mapping, not one column:
   ratios (margin = profit/revenue), weighted metrics (AOV = revenue/orders as *entities*,
   not mean of a column), rate metrics (conversion = won/total).
2. **Time-aware KPIs** — MoM/YoY/WoW growth, run-rate, moving averages, seasonality index.
   Requires a resolved `date` canonical field; the detector already finds temporal columns.
3. **Grouped KPIs** — top-N by category, contribution %, per-segment KPI tables.
4. **KPI packs per preset** — each industry preset ships its own definitions (see preset doc).
   Load them from the preset instead of filtering `KPI_LIBRARY` by domain string.
5. **Targets & thresholds** — optional per-KPI target so tiles show red/green status; presets
   ship sensible default thresholds (e.g., inventory turns, occupancy %).

**Where it lives:** `core/kpi/library.py` grows a `MappedKPIDefinition` whose formula
signature is `fn(df, fields: Dict[canonical→column]) -> value`; `engine.py` computes the
preset's pack when a preset is active, falling back to today's behavior for `general`.

### Stage F — Dashboards & visualization (currently: 5 rule-based recommendations)

**Have:** `core/visualization/selector.py` — solid rules, renders via Plotly.

**Missing / build next:**
1. **Preset dashboard layouts** — each industry preset declares an ordered dashboard:
   KPI tile row → primary trend chart → breakdown charts → detail table, all bound to
   canonical fields (so they render instantly once mapping is confirmed).
2. **Default filters/slicers** per preset (date range, region, category…), applied to every
   chart on the page simultaneously.
3. **Drill-down** — click a bar → filter the page to that segment.
4. **Saved views** — persist a configured dashboard per dataset so re-upload restores it.

**Where it lives:** preset spec gains a `dashboard` section; new `core/dashboard/renderer.py`
walks the layout and calls the existing `render_recommendation` plumbing.

### Stage G — Insight, statistics, ML, forecasting (currently: strong)

**Have:** Gemini insights with dual-key failover (`core/ai`), stats page, KMeans/regression,
ARIMA/linear forecasting (`core/forecast`). These are already differentiators.

**Build next (small):**
1. Feed the **canonical mapping + preset context** into the Gemini prompt (the preset's
   `ai_prompt_prefix` already exists — extend it with the industry's KPI vocabulary).
2. **Auto-insight cards** on the dashboard: run 3–5 cheap checks automatically (biggest
   mover vs prior period, anomaly this week, top contributor shift) — no button press.
3. Forecast the preset's **primary metric by default** (revenue for retail, headcount for HR)
   rather than making the user pick columns.

### Stage H — Reporting & distribution (currently: generic PDF/Excel download)

**Have:** `core/reports/generator.py` (fpdf2 + openpyxl).

**Missing / build next:**
1. **Industry report templates** — section order, KPI selection, and commentary style come
   from the preset (a monthly retail report ≠ an HR attrition report).
2. **Branding** — logo upload, company name, accent color on the PDF.
3. **Scheduled delivery** — "email this every Monday" (SMTP + APScheduler); requires the
   mapping-memory from Stage D so refreshed files process untouched.
4. **Share links** — read-only dashboard snapshot (export static HTML first; hosted later).

---

## The "within clicks" user journey (target UX)

```
Click 1: Upload file(s)
   → auto-ingest (headers, types, currencies fixed; receipt shown)
   → preset auto-detected with confidence badge
Click 2: Confirm mapping screen ("Retail & E-commerce — 12/14 fields matched")
   → full dashboard renders: KPI tiles, trend, breakdowns, auto-insight cards
Click 3 (optional): Download branded PDF / Excel, run forecast, ask AI anything
Repeat next month: upload → mapping remembered → 1 click total
```

Everything past click 2 is default-on, not user-assembled. Power features (Wrangle, SQL,
ML, custom charts) stay available behind the sidebar for analysts.

---

## Build order (each phase is shippable)

| Phase | Scope | Modules touched | Why first |
|---|---|---|---|
| **1. Preset engine** | Field-level mapping, preset registry (declarative spec), mapped KPI packs, confirmation screen | `core/schema`, `core/kpi`, `core/templates`→`core/presets`, `D1.py` | Everything else hangs off canonical fields |
| **2. Ingestion hardening** | Header detect, coercion, multi-sheet, unpivot, currency/date parsing | new `core/ingest` | Presets are useless if real-world files fail to load |
| **3. Preset dashboards + auto-insights** | Layouts, slicers, insight cards, default forecast target | `core/dashboard`, `core/visualization`, `core/ai` | This is the visible "wow" |
| **4. Auto-clean + recipes + mapping memory** | Clean receipt, reusable recipes, persistent registry | `core/clean`, `core/schema/registry` | Makes month 2 a one-click experience |
| **5. Multi-table (DuckDB)** | Table registry, auto-join, SQL page | `core/store` | Replaces VLOOKUP/Power Query |
| **6. Reports & distribution** | Branded industry PDFs, scheduling, share export | `core/reports` | Completes end-to-end replacement |
| **7. Connectors** | Google Sheets, then DB/API (Shopify, GA4, Tally…) | new `core/connectors` | Removes the last manual step (the export itself) |

### Implementation keystone: make presets declarative

Today a template is a Python class with 4 attributes. To support 15+ industries and let
non-developers add more, define presets as **data** (YAML/JSON in `core/presets/specs/`),
loaded by one generic engine:

```yaml
# core/presets/specs/retail.yaml (abridged — full specs in docs/INDUSTRY_PRESETS.md)
name: retail
label: Retail & E-commerce
detect:
  keywords: [sku, order, price, qty, store, pos, basket]
  required_roles: {temporal: 1, numeric_continuous: 1}
fields:
  order_date:  {role: temporal,  synonyms: [date, order date, bill date, invoice date, txn date]}
  revenue:     {role: numeric,   synonyms: [amount, sales, net amount, total, gross, amt]}
  quantity:    {role: numeric,   synonyms: [qty, units, quantity, pcs, nos]}
  product:     {role: categorical, synonyms: [item, sku, product name, description]}
kpis: [total_revenue, orders, aov, units_sold, revenue_mom, top_product_share, ...]
dashboard:
  tiles: [total_revenue, revenue_mom, aov, units_sold]
  charts:
    - {type: line, x: order_date, y: revenue, title: Revenue trend}
    - {type: bar,  x: product,    y: revenue, top_n: 10, title: Top products}
filters: [order_date, store, category]
report: {sections: [summary, kpis, trend, top_movers, forecast], tone: retail-manager}
ai_prompt: "You are a retail analyst. Focus on sell-through, basket size, ..."
```

The existing `BaseTemplate.match_score`, `_DOMAIN_TOKENS`, and `KPI_LIBRARY` all fold into
this one spec format.

## Companion specifications

- **`docs/INDUSTRY_PRESETS.md`** — per-industry requirements: users & needs, source
  systems and file styles, canonical field schemas with synonyms, KPI packs, detection
  rules, shared KPI primitives.
- **`docs/VISUAL_PRESETS.md`** — the global visual system (formats, grains, color
  polarity, reference lines, annotations, layout grammar) and the per-industry chart
  matrix with exact settings and drill-downs.
- **`docs/EXPERT_ANALYST_ENGINE.md`** — the six-layer analysis stack (audit → describe →
  compare → explain → predict → prescribe/narrate), insight cards, statistical guardrails,
  per-industry expert lenses, the analyst-memo report, and the remaining
  "perfect-platform" capabilities (NL→SQL ask-your-data, what-if, alerts, glossary,
  PII masking), including how they slot into the phases above (new phases 8–10).
