# Expert Analyst Engine — Analysis Like an End-to-End Senior Analyst

Charts and KPIs describe *what* happened. An expert analyst also establishes *whether the
data can be trusted*, *what changed and why*, *what happens next*, and *what to do about
it* — then writes it up so a non-analyst can act. This document specifies how the app
automates that, plus the remaining capabilities needed for a "perfect" analytics platform.

New module home: `core/insight/` (audit, compare, decompose, anomaly, materiality,
narrative) building on existing `core/kpi`, `core/forecast`, `core/ai`, scipy/statsmodels
(already dependencies).

---

## 1. The six-layer analysis stack

Every dataset flows through all six layers automatically; each layer emits **insight
cards** (section 3) and feeds the narrative (section 6).

| Layer | Question | Engine |
|---|---|---|
| 0. Audit | Can this data be trusted? | data-quality scoring |
| 1. Describe | What happened? | KPI packs + preset dashboard (already specced) |
| 2. Compare | Is that good or bad? | vs prior period, same-period-last-year, target, benchmark, peer segment |
| 3. Explain | Why did it happen? | decomposition, driver scan, anomaly attribution |
| 4. Predict | What happens next? | forecasting (exists) + risk flags |
| 5. Prescribe & narrate | What should we do? | rule-based playbooks + AI narrative with guardrails |

---

## 2. Layer specifications

### Layer 0 — Data audit (runs on upload, before anything is shown)

Expert analysts never present numbers they haven't sanity-checked. Compute a **trust
score (0–100)** with a visible receipt:

- **Completeness**: null rates per mapped field; required-field gaps weighted heavier.
- **Continuity**: missing dates in the time series (a "sales dip" that is actually a
  missing week must be caught here, not narrated as a business event).
- **Duplication**: exact-row and key-based (same order_id twice) duplicates.
- **Consistency**: mixed date formats parsed differently, categorical near-duplicates
  ("Delhi"/"DELHI"/"Delhi "), currency-scale breaks (column suddenly 100× — paise vs
  rupees), negative values where the preset says impossible (negative quantity).
- **Freshness & coverage**: data ends N days ago; partial current period flagged.
- **Grain check**: verify the assumed grain (one row per order-line vs per order) by
  testing key uniqueness — wrong grain silently doubles every KPI.

Findings become fix-it chips ("Merge 3 city spellings", "Drop 12 duplicate orders") —
one click applies, and the receipt is embedded in every report so numbers are defensible.
**Any insight computed on a field with trust issues carries a caveat badge.**

### Layer 2 — Comparison engine

Every KPI is always computed against four bases (where available):
1. **Prior period** (MoM/WoW) — momentum.
2. **Same period last year** — seasonality-adjusted truth (critical for retail/hospitality/energy).
3. **Target/budget** — if provided or set in-app.
4. **Benchmark** — preset ships editable industry defaults (e.g., e-com repeat rate ~25%,
   restaurant aggregator commission ~22%, PAR-30 < 5%, attrition ~10–15%). Shown as
   "context", clearly labeled as editable assumptions, never as facts.

Deltas are judged by the KPI's declared polarity (see `docs/VISUAL_PRESETS.md` §A4), and
**significance-gated**: a change is only *called* a change if it clears both a materiality
floor and a noise test (§5).

### Layer 3 — Explanation engine (the analyst's core skill)

**a) Contribution decomposition.** When a primary metric moves, decompose the move across
every mapped categorical dimension (product, store, channel, rep, branch…):
`Δmetric = Σ segment contributions`, ranked. Then split each top contributor into
**volume vs rate** (e.g., revenue drop = fewer orders (volume) vs smaller baskets (rate);
CPA rise = CTR fall vs CVR fall vs CPC rise — preset declares its metric tree). Output:
"Revenue fell ₹4.1L (−8%). Store: Koramangala −₹3.2L explains 78% of the decline, driven
by order count (−31%), not basket size (−2%)."

**b) Mix-shift detection.** Overall rate metrics can move with no segment changing
(Simpson's paradox) — always test whether a rate change is real or composition:
"Blended CPA rose 12% — every campaign's CPA actually *fell*; spend shifted toward the
expensive-but-profitable channel."

**c) Driver scan.** Correlate the primary metric against other numeric fields and lagged
versions of itself (spend→conversions with 0–7 day lags; discount→volume). Report only
significant, non-trivial relationships with effect size, phrased as association not
causation ("weeks with >15% discount rate saw 2.1× units — test causality with a holdout").

**d) Anomaly attribution.** For every flagged spike/drop (residual > 2.5σ from the
trend+seasonality fit — statsmodels decompose, already a dependency): find which segment
explains most of the residual, check the calendar (festival, weekend, month-end), check
the audit log (missing data that day?). Card: "Mar 18 spike +₹2.3L: 91% from 'Wedding
collection' in 2 stores; 2 days before Holi weekend."

### Layer 4 — Prediction with judgement

Forecasting exists (`core/forecast`). Add analyst judgement around it:
- Forecast the **preset's primary metric by default**, with scenario bounds.
- **Risk flags**: forecast assumes history repeats — flag when the last 4 periods deviate
  from the fitted pattern ("trend break — forecast confidence low").
- **Pace tracking**: month-to-date vs required run-rate to hit target ("need ₹31k/day for
  remaining 12 days; trailing 7-day pace is ₹26k → projected 8% miss").
- **Leading-indicator alerts** per preset (pipeline coverage < 3× next-quarter target;
  PAR-1-30 rising predicts PAR-30 in 60 days; falling repeat-rate predicts revenue).

### Layer 5 — Prescription playbooks

Two-tier recommendations, always with the evidence chart attached:
1. **Deterministic rules** shipped per preset (auditable, no AI): e.g., retail — high-margin
   low-volume items with rising trend → promote; marketing — campaigns with CPA > 2×
   account median and ≥ 20 conversions → pause candidates; lending — branches with PAR
   rising 3 consecutive months → review list.
2. **AI-composed** (Gemini, existing client): synthesize the insight cards into
   prioritized actions. Guardrails: AI receives only aggregates + cards (never raw rows —
   the existing `summary_string()` discipline), must cite which card supports each
   recommendation, regulated presets (health/lending/HR) get restricted phrasing.

---

## 3. Insight cards — the unit of analysis

Every layer emits typed cards; the dashboard shows the top-ranked rail, the report embeds them.

```yaml
card:
  type: trend|anomaly|concentration|mix_shift|driver|variance|dq_warning|forecast_risk|milestone
  headline: "Koramangala store drove 78% of this month's revenue decline"
  so_what: "Order count fell 31% while basket size held — a traffic problem, not pricing"
  evidence: {chart_spec: ..., stats: {delta: -0.31, p: 0.003, n: 412}}
  confidence: high|medium|low        # from significance + data-trust score
  materiality: 8.2                   # ranking score, see below
  action_hint: "Check store staffing/hours & local competition; compare footfall if available"
  caveats: ["12% of March rows had unparseable dates — excluded"]
```

**Materiality ranking** (what a senior analyst puts first):
`materiality = |impact in primary-metric units| × significance × recency × novelty`
— novelty decays for insights already surfaced in prior sessions (stored in the registry),
so the rail always leads with *new* information. Cap: max 7 cards on the dashboard,
everything else in an "all findings" drawer.

---

## 4. Per-industry expert lenses

What a domain expert checks *first* — encoded as the preset's card priorities:

| Preset | Expert checks (auto-run, in order) |
|---|---|
| Retail | same-store sales vs new; weekend/weekday split; top-SKU dependence; discount elasticity; repeat-rate trend |
| Sales/CRM | pipeline coverage ratio; stage-conversion drops; slipped deals; rep concentration; created-vs-closed balance |
| Finance | burn vs runway; expense category creep (3-mo slope); recurring vs one-off split; budget variance drivers |
| HR | regretted-attrition hotspots (dept×tenure); compa-ratio outliers; manager-level attrition clusters; hiring-vs-exit balance |
| Marketing | fatigue (CTR decay per campaign age); frequency saturation; mix-shift on blended CPA; incrementality caveats |
| Logistics | first-attempt success; lane-level SLA erosion; carrier cost-vs-speed frontier; RTO concentration by pincode |
| Manufacturing | OEE loss tree (availability vs performance vs quality); SPC violations; changeover patterns; supplier-linked defects |
| Healthcare | payer-mix drift; no-show clustering (day/doctor); capacity vs demand by hour; follow-up leakage |
| Education | attendance→score correlation; at-risk cohort size; fee-default aging; batch variance vs teacher |
| Real estate | absorption pace vs launch plan; price realization vs list; aging stock discount pressure; collection slippage |
| Hospitality | menu-engineering quadrants; aggregator dependence trend; RevPASH/table-turn; food-cost creep |
| SaaS | NRR decomposition; churn by tenure band; expansion concentration; logo-vs-revenue churn divergence |
| Lending | vintage deterioration; roll rates (bucket migration); collection-efficiency vs disbursal-growth tension; branch outliers |
| Energy | PR degradation slope; downtime-loss quantification; peak-demand charges; weather-normalized comparison (later) |
| Nonprofit | donor-concentration risk; retention by acquisition channel; program cost-efficiency; grant burn vs timeline |

---

## 5. Statistical rigor guardrails (never ship a wrong "insight")

- **Noise gate**: time-series claims require the change to exceed the series' own
  volatility (±2σ of trailing deltas); group differences require t-test/Mann-Whitney
  (numeric) or chi-square (rates) at p < 0.05 — scipy already in the stack.
- **Small-n suppression**: no comparative claims on groups with n < 8 (n < 5 in privacy
  presets); tiles show "insufficient data" rather than a misleading number.
- **Multiple-comparison discipline**: driver scans test many hypotheses — apply
  Benjamini-Hochberg correction before surfacing correlations.
- **Causal humility**: templated phrasing — "associated with", "test with a holdout" —
  hard-coded in card copy, not left to the LLM.
- **Partial-period protection**: never compare an incomplete period to a complete one
  without pro-rating and labeling.
- **Every number traceable**: cards carry the computation (fields, filter, formula) so
  "expand" shows exactly how the figure was produced.

---

## 6. The narrative — an analyst memo, not a data dump

One-click "Analyst Report" (extends `core/reports/generator.py`), structured the way a
senior analyst writes:

1. **Headline** (one sentence: the single most material finding).
2. **The numbers** — KPI table with all four comparison bases.
3. **What's driving it** — top 3–5 cards with evidence charts.
4. **Watch-outs** — risks, anomalies, data-quality caveats.
5. **Outlook** — forecast + pace vs target.
6. **Recommended actions** — prioritized, each citing its evidence card.
7. **Appendix** — methodology, audit receipt, definitions used.

Tone/length per preset (`report.tone`): board-pack (finance/SaaS), ops stand-up
(logistics/manufacturing), investor update (SaaS), trading report (hospitality). The LLM
writes *prose around computed facts* — it never computes; every figure in the memo comes
from the card payloads.

---

## 7. Remaining capabilities for a "perfect" platform

Beyond presets, visuals, and the analyst engine — ranked by leverage:

**Analysis & interaction**
1. **Ask-your-data (NL → SQL)**: Gemini translates questions to DuckDB SQL using the
   schema + canonical mapping only (no rows); result renders as chart + answer sentence
   with the SQL shown. This is the "expert analyst on demand" interface.
2. **What-if simulator**: sliders on driver metrics (price +5%, spend mix, attrition −2pp)
   propagating through the preset's metric tree to the primary KPI.
3. **Goal tracking**: set targets once; every dashboard, forecast, and report tracks pace
   against them; milestone cards celebrate/warn.
4. **Period-close comparisons**: upload this month's file next to last month's → automatic
   diff of every KPI and segment (the monthly-reporting ritual, automated).

**Trust & governance**
5. **Metric glossary**: auto-generated definitions page (formula, fields, filters) per
   dashboard — kills "which revenue is this?" debates; embedded in report appendix.
6. **PII detection & masking**: regex+role scan (emails, phones, names) → auto-mask before
   any AI call; privacy presets enforce it (extends current aggregates-only discipline).
7. **Audit trail**: every transform, mapping decision, and report generation logged
   (loguru already present) and replayable — the reproducibility a real analyst is held to.

**Operations**
8. **Alerts**: KPI threshold/anomaly watchers; on breach → email/WhatsApp digest with the
   relevant card (requires scheduled re-processing of a connected source, so pairs with
   connectors in roadmap Phase 7).
9. **Scheduled analyst memo**: the section-6 report auto-emailed weekly/monthly.
10. **Snapshot & versioning**: datasets and dashboards versioned; "as of" states restorable.

**Scale & polish**
11. **Big-file mode**: > ~500k rows → DuckDB-backed aggregation with sampled previews
    (pandas-only paths will choke first).
12. **Calendar intelligence**: locale holiday/festival calendars (Diwali, Eid, Black
    Friday) auto-annotate charts and inform anomaly attribution; fiscal-year engine.
13. **Onboarding sample datasets**: one demo file per preset so users experience the full
    click-path before uploading their own.
14. **Collaboration**: comments pinned to charts/cards; share read-only snapshot links.
15. **White-label/embed** (later): agencies run it for their clients with their branding.

---

## 8. Build-order integration

These land inside the existing phase plan (`docs/WORKFLOW_REPLACEMENT_ROADMAP.md`):

| Phase (existing) | Add from this doc |
|---|---|
| 1 Preset engine | KPI polarity + metric trees (needed by decomposition later) |
| 2 Ingestion | Layer-0 audit & trust score (same code touches every cell anyway) |
| 3 Preset dashboards | Insight cards rail: trend/variance/concentration cards + materiality ranking |
| 4 Auto-clean & memory | fix-it chips, novelty memory for cards, metric glossary |
| 5 DuckDB | Ask-your-data NL→SQL, big-file mode, period-close diff |
| 6 Reports | Analyst memo structure, tones, audit receipt in appendix |
| 7 Connectors | Alerts, scheduled memos, snapshots |
| new 8 | Explanation engine full: decomposition, mix-shift, driver scan, anomaly attribution |
| new 9 | What-if simulator, goal tracking, calendar intelligence |
| new 10 | Collaboration, white-label |

The single highest-leverage item after the preset engine is **Layer 3 (explanation)** —
KPIs and charts exist in every BI tool; *automated "why" with statistical guardrails* is
what makes this feel like hiring an analyst rather than buying a dashboard.
