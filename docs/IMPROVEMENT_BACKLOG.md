# Improvement Backlog — What a Complete Analyst Still Does That the App Doesn't

A senior analyst's self-review of the current system (preset engine, dashboard,
insight cards, illustrated report, Report Studio). Ordered by tier: **A** are
correctness issues in what exists (fix before adding anything), **B–I** are
capability gaps ranked by how much closer each takes the app to a *complete*
analyst. Effort: S (<½ day), M (1–2 days), L (multi-day).

> **Status (Jul 2026): SHIPPED** — A1 (partial-period exclusion, 80% coverage
> rule, disclosed in the report), A2 (segment-mover noise gate), A3
> (seasonally-adjusted trend tests), A4 (up to 3 anomalies with attribution),
> A5 (per-column currency symbols), A6 (cached filtered analysis), A7 (unicode
> DejaVu PDF font), A8 (fiscal-year YoY, Studio setting), **B1** (waterfall
> bridge section + exhibit), **D1** (persistent mapping memory with
> remembered-badge + forget), **E1** (pin cards & Q&A answers →
> "Analyst's Selected Evidence" report section), **G3** (SQL guardrails:
> single read-only statement, keyword blocklist, row cap), **C1**
> (Holt-Winters seasonal forecasting with model auto-selection).
> Verified by `tests/test_improvements.py` (30 checks). Everything below that
> is not in this list remains open.

---

## Tier A — Honest self-critique: fix what's already built

These are real weaknesses in the shipped code, found by reviewing it the way
an analyst reviews their own workpapers.

### A1. Partial-period bias in every delta  🔴 highest priority · S
`core/presets/kpis.py` compares the **latest period vs the previous one** —
even when the latest period is incomplete. A dataset ending mid-week shows
"Revenue −73%" when nothing fell (visible in the sample report). A human
analyst never compares a half-finished week to a full one.
**Fix:** in `compute_pack` and the `growth` primitive, drop the trailing
period when its span is < ~80% of the grain (or pro-rate it and label
"provisional"). Apply the same rule in `insights._variance_cards` and the
report's recent-periods table. This single fix removes the most misleading
number the app can currently produce.

### A2. Segment movers have no noise gate · S
Section 7 of the report shows "+5% / −22%" per segment computed on raw
period-over-period sums, with no minimum sample or volatility check — exactly
the false-precision the KPI layer avoids. **Fix:** suppress the move label when
the segment has < 8 records in either period, or when |move| < the segment's
own historical delta σ.

### A3. Trend test ignores seasonality · M
`_trend_card` / report §4 run a linear regression on raw period values. A
seasonal series (weekend-heavy retail, monthly billing spikes) can show a
"significant" slope that is pure seasonality. **Fix:** when ≥ 2 full seasonal
cycles exist, deseasonalize first via `statsmodels.tsa.seasonal_decompose`
(already a dependency) and test the trend component; report "seasonally
adjusted" in the methodology.

### A4. One anomaly per dataset · S
`_anomaly_card` reports only the single worst deviation. Real months contain
several events. **Fix:** return up to 3 anomalies above 2.5σ, ranked, each
with its own attribution; the trend exhibit already supports multiple flags.

### A5. One currency symbol per file · S
Ingest keeps the first symbol found; a file with ₹ revenue and $ ad-spend
mislabels one of them. **Fix:** store symbol per column in `IngestResult`,
let KPI `fmt` resolve from its bound column.

### A6. No caching — every widget click recomputes everything · M
`page.py` recomputes KPIs + cards + charts on each filter interaction and the
bundle on every preset flip; fine at 5k rows, painful at 200k. **Fix:**
`st.cache_data` keyed on (data hash, mapping hash, filter state) around
`compute_pack`/`generate_cards`; hash once at upload.

### A7. PDF transliterates ₹ to "Rs" · S
Core Helvetica is latin-1. **Fix:** ship a DejaVuSans TTF in `core/reports/
fonts/`, `pdf.add_font(...)`, drop `_latin()` except as fallback. Report then
prints real ₹, σ, Δ.

### A8. YoY assumes calendar years · S
Indian businesses read Apr–Mar. **Fix:** fiscal-year-start setting (already
specced in VISUAL_PRESETS §C) applied in `_yoy` and quarter labels.

---

## Tier B — The "why" engine (biggest analytical gap)

A complete analyst's core value is *explaining* change. The app currently
shows movers; it doesn't yet do formal attribution.

### B1. KPI bridge / waterfall decomposition · M · 🥇 highest-value feature
"Revenue fell ₹4.1L: Koramangala −₹3.2L, HSR −₹1.4L, Indiranagar +₹0.5L."
Compute `Δmetric = Σ segment contributions` for the top dimension, render as a
waterfall exhibit (matplotlib bar-bridge), and make it the anomaly/variance
card's evidence. Extends `insights.py`; one new chart in `report_charts.py`.

### B2. Volume-vs-rate split · M
Was the revenue drop fewer orders (volume) or smaller baskets (rate)? Each
preset declares its metric tree (revenue = orders × AOV; CPA = spend ÷
conversions; collection = paid ÷ due). Decompose the primary KPI's change
into component contributions using the standard two-factor bridge
(Δvolume × rate₀ + volume₁ × Δrate).

### B3. Mix-shift / Simpson's paradox check · M
Blended rate moved while every segment's own rate moved the other way →
composition effect. Test whenever a ratio KPI changes: recompute holding mix
constant; if the sign flips, emit a `mix_shift` card ("every campaign's CPA
fell; spend shifted to the expensive channel").

### B4. Lagged driver scan · S
`_drivers` correlates same-row values only. Marketing spend acts with a lag.
Cross-correlate period-aggregated driver vs primary metric at lags 0–4,
report the best significant lag ("spend leads conversions by ~1 week").

### B5. Cohort & repeat-behavior analysis · L
When an entity id + date exist (customer/donor/patient): first-seen cohorts ×
periods-since retention grid, repeat rate, inter-purchase interval. Unlocks
the retention exhibits promised in VISUAL_PRESETS for retail/SaaS/nonprofit.
Worth its own module `core/insight/cohorts.py`.

### B6. Targets & pace tracking · M
Analysts judge against *plan*, not just history. Per-KPI target input (Studio
+ dashboard), then: attainment %, pace ("need ₹31k/day for the remaining 12
days; trailing pace ₹26k → projected 8% miss"), red/amber/green tiles, and a
"vs plan" column in the scorecard. Data model: `{kpi_key: target}` persisted
per dataset.

### B7. Editable benchmark library · M
Preset ships editable context values (e-com repeat rate ~25%, restaurant
aggregator commission ~22%, PAR-30 < 5%, attrition 10–15%) in a YAML users
can adjust; scorecard gains a "context" column clearly labeled as assumption.

---

## Tier C — Forecasting maturity

### C1. Seasonality-aware model · M
ARIMA(1,1,1)/linear miss weekly/annual cycles. Add Holt-Winters
(`statsmodels ExponentialSmoothing`, already installed) when ≥ 2 full cycles
detected; pick by backtest MAPE among {linear, ARIMA, Holt-Winters}.

### C2. Honest backtest display · S
Show a rolling-origin backtest overlay (predicted vs actual for the last 4
periods) in the outlook exhibit so the reader can *see* forecast quality, not
just a MAPE number.

### C3. Scenario bands & anomaly-cleaned history · M
Fit on anomaly-winsorized history (one-off spikes shouldn't drive the trend);
present base/optimistic/pessimistic from residual quantiles. Report gets a
scenario table.

### C4. Segment-level mini-forecasts · S
Forecast the top-3 segments, flag whose trajectory drives the total ("HSR is
the declining store; the other two are flat").

---

## Tier D — Memory & repeatability (the month-2 experience)

### D1. Mapping memory · M · 🥈 second-highest value
`core/schema/registry.py` is in-memory only. Persist confirmed
(column-set hash → preset, mapping, options) to
`~/.sapienoids/registry.json`; on upload, an exact hit skips detection and
confirmation entirely. This is what turns click-2 into click-0 next month.

### D2. Period-close diff · M
Upload this month's file alongside last month's → automatic diff: every KPI,
every segment, new/disappeared categories, schema changes. This is the
monthly reporting ritual, automated. DuckDB joins the two frames.

### D3. Cleaning recipes · M
Record Wrangle/fix-it operations as a JSON recipe attached to the mapping
memory; auto-replay on the next matching upload, with the receipt noting
"applied saved recipe (6 steps)".

### D4. Insight novelty memory · S
Cards repeat every session ("Top-10 share = 100%" forever). Store card
fingerprints per dataset in the registry; decay materiality of previously
shown findings so the rail always leads with what's *new*.

### D5. Audit fix-it actions · M
The audit reports duplicates and case-variant categories but can't fix them.
Add one-click chips: "drop 30 duplicates", "merge 3 spellings of Delhi",
"exclude total rows" → applied to the working frame + logged + recipe-recorded.

---

## Tier E — Interaction: play with results

### E1. Pin anything to the report · M · 🥉 third-highest value
"📌 Add to report" on every dashboard chart, insight card, and **ask-your-data
answer**. Pinned items land in a "Analyst's Selected Exhibits" section with
the user's optional one-line comment. Ask-your-data answers become evidence:
question, SQL, result table, and a small auto-chart. This closes the loop
between exploring and reporting.

### E2. Chart the Q&A answers + conversational context · M
NL→SQL currently returns a table only. Auto-chart the result (reuse the
recommendation rules); keep the last 3 Q&A pairs in the prompt so follow-ups
("same but for June") work.

### E3. Event annotations · S
Let the user register events (promo, festival, price change, outage) with
dates. They draw as vertical lines on all time exhibits, feed anomaly
attribution ("spike coincides with 'Holi promo'"), and are listed in the
report's methodology.

### E4. Native drill-down · M
Streamlit ≥ 1.35 supports `st.plotly_chart(..., on_select=...)`: clicking a
bar filters the page (sets the corresponding multiselect). True click-to-drill
without extra dependencies.

### E5. What-if simulator · L
Sliders on the preset's metric tree (price +5%, conversion +0.5pp, churn
−1pp) propagating to the primary KPI, with a tornado chart of sensitivities.
Depends on B2's metric trees.

### E6. Threshold alerts (in-app) · S
Per-KPI watch thresholds; on upload/filter, breached watches surface as a
banner + card. (Email delivery belongs with connectors, later.)

---

## Tier F — Reporting & delivery

### F1. PowerPoint export · M — analysts deliver decks; `python-pptx`, one
slide per section, exhibits as images, notes in speaker notes.
### F2. Audience variants · S — "Board pack" (exec, scorecard, findings,
outlook, actions) vs "Ops review" (everything) as one-click Studio presets of
the section picker.
### F3. Scheduled email delivery · L — SMTP settings + APScheduler; requires
D1/D3 so refreshed files process untouched. Pairs with connectors.
### F4. Report history · S — keep the last N generated reports (bytes +
options) in a local folder with a "reports" browser tab.
### F5. Static HTML dashboard export · S — plotly `to_html` bundle for
sharing a read-only interactive snapshot.

---

## Tier G — Trust, privacy, governance

### G1. PII detection & masking · M — regex + role scan (emails, phones,
names, MRN/UHID patterns); auto-mask before any AI call; hard-enforced in
HR/healthcare/education presets. Currently only prompt discipline protects
this — make it code, not convention.
### G2. Metric lineage ("why this number") · M — every KPI tile/report figure
expands to: formula, bound columns, filters applied, row count, and a sample
of underlying rows (local only). The appendix has definitions; this adds
per-number traceability.
### G3. SQL guardrails on ask-your-data · S — reject non-SELECT statements
and multi-statement strings before execution (currently prefix-checked only);
cap result size; timeout.
### G4. Glossary page · S — auto-generated from the active preset's KPI pack
+ mapping, one page, linked from dashboard and report.

---

## Tier H — Scale & performance

### H1. DuckDB big-file mode · M — > ~300k rows: register in DuckDB, compute
KPIs/aggregations in SQL, sample only for scatter/histogram exhibits.
### H2. Multi-table analysis · L — the star-schema reality (orders +
customers + products). Auto-join suggestion by key-name + value overlap;
joined view feeds the same preset pipeline. The single biggest structural gap
vs real workflows.
### H3. Bundle caching (A6) + lazy exhibit rendering · S — render report
exhibits only at generate time (done) but also debounce filter recompute.

---

## Tier I — Adoption polish

- Sample dataset per preset ("try with demo data" button) — S
- First-run tour of the 2-click flow — S
- Mapping confidence colors in the editor (green/amber/red per field) — S
- Report cover logo upload — S
- Dark-theme exhibit variant (charts currently light-only) — S
- i18n for report strings (Hindi first) — M

---

## Recommended order of attack

| # | Item | Why first | Effort |
|---|---|---|---|
| 1 | A1 partial-period fix | Kills the worst misleading number | S |
| 2 | A2 + A4 + A5 + A7 quick fixes | Credibility batch | S each |
| 3 | B1 waterfall decomposition | The "why" — biggest analyst leap | M |
| 4 | D1 mapping memory | Month-2 becomes zero-click | M |
| 5 | E1 pin-to-report (incl. Q&A) | Closes explore→report loop | M |
| 6 | B2 volume-vs-rate + B6 targets | Plan-aware analysis | M+M |
| 7 | C1 seasonal forecasting + A3 | Honest trends & forecasts | M |
| 8 | D2 period-close diff | Automates the monthly ritual | M |
| 9 | G1 PII masking + G3 SQL guardrails | Governance before sharing features | M |
| 10 | H2 multi-table | Structural completeness | L |

Everything in Tiers A–E builds on modules that already exist (`kpis.py`,
`insights.py`, `report_charts.py`, `registry.py`, `page.py`) — no
architectural changes required until H2.
