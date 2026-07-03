# Visual Presets — Required Visuals & Settings per Industry

Every industry preset ships a **fully-configured dashboard**: not just "show a bar chart"
but the exact bindings, aggregation, time grain, number format, color semantics,
reference lines, annotations, and drill-downs an expert analyst would choose. This file
defines (A) the global visual system every chart obeys, and (B) the per-industry visual
matrix.

Implementation home: extend `ChartRecommendation` in `core/visualization/selector.py`
into a `ChartSpec` carrying these settings; a new `core/dashboard/renderer.py` renders
specs; preset YAMLs (see `docs/INDUSTRY_PRESETS.md`) declare them.

---

## A. Global visual system (applies to every preset)

### A1. Number & unit formatting
- **Currency auto-detection**: scan raw values for symbols (₹, $, €, £) and locale
  setting; store on the dataset. Indian locale → compact lakh/crore (`₹4.2L`, `₹1.8Cr`);
  Western → compact SI (`$1.2M`). Full precision in tooltips, compact on axes/tiles.
- **Percent**: 1 decimal (`12.4%`); rates < 1% get 2 decimals.
- **Counts**: thousands separators, no decimals.
- **Units**: preset declares unit suffixes (kWh, kg, sqft, days) applied to axes/tooltips.

### A2. Time grain (auto, user-overridable)
| Data span | Default grain |
|---|---|
| ≤ 31 days | daily |
| ≤ 26 weeks | weekly (week-start Monday; configurable) |
| ≤ 3 years | monthly |
| > 3 years | quarterly |

Fiscal calendar per preset (finance/lending/HR in India default to Apr–Mar; setting is
global and affects YoY, YTD, and quarter labels). Incomplete current period is rendered
hatched/faded and excluded from trend claims.

### A3. Chart-type rules
- **Bar**: zero baseline always; sorted descending unless x is ordinal; default top-N=10
  with an "Others" bucket; horizontal orientation when category labels average > 12 chars.
- **Line**: y-axis not forced to zero; markers only when < 30 points; when series is noisy
  (CV of period-over-period deltas > 40%) overlay a dashed 7-period moving average;
  forecast segments get shaded confidence bands.
- **Pie/Donut**: only when ≤ 6 categories, otherwise auto-switch to bar; donut with the
  total in the center.
- **Heatmap**: sequential palette for magnitude; day×hour heatmaps start Monday, business
  hours highlighted.
- **Box**: only when every group has ≥ 8 points, else strip/bar of means with n= labels.
- **Funnel**: stages in the preset's declared order (never alphabetical).
- **Cohort grid**: rows = cohort start period, cols = periods since start, cell = retention %.
- **Table**: right-align numbers, delta columns with arrow + color, sticky header.

### A4. Color semantics (colorblind-safe)
- **Neutral magnitude** (revenue by product, visits by dept): single accent hue, intensity
  by value. Never rainbow categoricals beyond 8 hues.
- **Good/bad polarity**: green/red reserved exclusively for metrics with declared polarity.
  Every KPI in a preset declares `polarity: up_good | up_bad | neutral`
  (revenue ↑ good; attrition, DPD, no-show, downtime, CPA, churn ↑ bad). Delta arrows and
  variance charts color by polarity, not by sign.
- **Diverging palette** only for variance-vs-target/budget and correlation heatmaps.
- **Status colors** fixed per preset vocabulary (e.g., logistics: delivered=green,
  in-transit=blue, RTO=red; lending buckets: 0=green → 90+=dark red).

### A5. Reference lines & annotations (this is what makes charts "expert")
- **Target line** (dashed) whenever the preset/user provides a target or budget.
- **Prior-period average** (dotted) on primary trend charts.
- **Control band** (±2σ of trailing 8 periods, shaded) on operational metrics
  (defect rate, on-time %, no-show %) — points outside get an anomaly marker.
- **Auto-annotations**: max/min period labeled; detected anomalies flagged with a marker
  that opens the insight card explaining it; user event flags (promo, festival, policy
  change) render as vertical lines on all time charts.

### A6. Tooltips & interaction
- Tooltip = formatted value + share of total + Δ vs prior period (+ target attainment if any).
- **Cross-filtering**: clicking a bar/segment filters the whole page; breadcrumb chips show
  active filters; every chart has an "expand + underlying rows" view and PNG/CSV export.
- **Drill path** declared per chart (e.g., category → product → order rows).

### A7. Layout grammar
```
Row 1  KPI tiles (4–5): value, delta vs prior period (polarity-colored), sparkline, target bar
Row 2  Primary trend chart (full width) with reference lines + annotations
Row 3+ 2-column grid of breakdown charts (preset order)
Last   Detail table (top movers / exceptions) + auto-insight cards rail
```
Mobile/narrow: single column, tiles 2×2, tables horizontally scrollable. Dark/light theme
follows app setting; charts re-theme (no hardcoded `seaborn` template — theme tokens).

---

## B. Per-industry visual matrix

Legend: **Agg·Grain** = aggregation & time grain; **Ref** = reference lines/annotations;
**Drill** = click-through path. KPI tile rows are listed in `docs/INDUSTRY_PRESETS.md`;
this matrix covers the charts below the tiles.

### 1. Retail & E-commerce
Currency locale-detected; week starts Monday; polarity: revenue/units ↑ good, discount_rate ↑ bad.

| Visual | Type | Bindings | Agg·Grain | Settings | Ref / Annotation | Drill |
|---|---|---|---|---|---|---|
| Revenue trend | line | order_date → revenue | sum · auto | compact currency; MA overlay if noisy | prior-period avg; promo/festival event flags; anomaly markers | day → orders |
| Top products | bar (horiz) | product → revenue | sum, top 10 + Others | labels truncated 24 chars, full in tooltip | share-of-total in tooltip | product → daily trend |
| Category mix | donut→bar | category → revenue | sum | donut if ≤6 categories | Δ share vs prior period in tooltip | category → products |
| Day×hour pattern | heatmap | order_date(dow×hour) → revenue | sum | sequential; business hours framed | — | cell → orders |
| Store comparison | bar | store → revenue | sum | secondary marker: AOV per store | chain-average line | store → categories |
| Movers table | table | product: revenue, Δ%, units, margin | vs prior period | polarity-colored Δ | top/bottom 5 highlighted | row → product page |

### 2. B2B Sales & CRM
Polarity: pipeline/won ↑ good, cycle_days/slippage ↑ bad. Stage order from preset, never alphabetical.

| Visual | Type | Bindings | Agg·Grain | Settings | Ref / Annotation | Drill |
|---|---|---|---|---|---|---|
| Pipeline funnel | funnel | stage → deal_value + count | sum | conversion % between stages labeled | benchmark conversion (if set) | stage → deals |
| Won revenue trend | bar+line | close_date → won value + cumulative | sum · monthly | dual axis; fiscal quarters shaded | quota line (dashed) | month → deals |
| Rep leaderboard | bar (horiz) | owner → won value | sum | win-rate % annotated per bar | team average line | rep → their pipeline |
| Size vs velocity | scatter | cycle_days × deal_value, color=stage | won deals | log y if skewed; median crosshairs | quadrant labels ("big & slow"…) | point → deal |
| Aging pipeline | table | open deals: value, stage, days-in-stage | — | days-in-stage heat-colored (>60 red) | — | row → deal |

### 3. Finance & Accounting
Fiscal year Apr–Mar default (setting); bracketed-negative parsing; polarity: inflow ↑ good, burn ↑ bad.

| Visual | Type | Bindings | Agg·Grain | Settings | Ref / Annotation | Drill |
|---|---|---|---|---|---|---|
| Net cashflow | waterfall/bar | txn_date → net amount | sum · monthly | positive green / negative red (true polarity case) | zero line; 3-mo avg burn | month → transactions |
| In vs out | stacked bar | month → inflows, outflows | sum · monthly | outflows negative-down orientation | — | segment → categories |
| Expense Pareto | bar (horiz) | account/category → outflow | sum, top 10 + Others | cumulative % line (Pareto) | 80% marker | category → transactions |
| Budget variance | diverging bar | category → (actual−budget)/budget | — | diverging palette; sorted by variance | ±10% tolerance band | category → transactions |
| Unusual items | table | largest txns + anomalies | — | z-score badge; recurring-payment tag | — | row → source row |

### 4. HR & People
Aggregate-only to AI; polarity: attrition/pay-gap ↑ bad. Salary charts use median (never mean) by default.

| Visual | Type | Bindings | Agg·Grain | Settings | Ref / Annotation | Drill |
|---|---|---|---|---|---|---|
| Headcount over time | area | join/exit dates → active count | monthly | hires above / exits below as bars | — | month → joiners/leavers |
| Attrition by dept | bar | department → attrition % | annualized | n= labels; suppress groups < 5 (privacy) | company-average line; 10% benchmark | dept → exits list (local) |
| Salary by dept | box | department → salary | — | median labeled; log scale if Gini > 0.4 | company median line | dept → role bands |
| Pay-gap view | dumbbell | role → median salary by gender | — | gap % labeled; groups < 5 suppressed | parity line | role → distribution |
| Tenure mix | histogram | tenure_years | 1-yr bins | — | median marker | bin → employees (local) |

### 5. Marketing & Ads
Polarity: ROAS/CTR ↑ good, CPA/CPM ↑ bad. All efficiency metrics shown with spend context (a low-CPA campaign with ₹200 spend is flagged low-confidence).

| Visual | Type | Bindings | Agg·Grain | Settings | Ref / Annotation | Drill |
|---|---|---|---|---|---|---|
| Spend vs conversions | line dual-axis | date → spend, conversions | sum · daily/weekly | axes color-matched to series | campaign-launch event flags | day → campaigns |
| CPA by campaign | bar (horiz) | campaign → CPA | spend-weighted | min-spend filter (default ≥ 5% of total); n conversions labeled | account-avg CPA line; target CPA | campaign → daily |
| Spend vs ROAS | scatter | spend × ROAS, size=conversions, color=channel | per campaign | log x; quadrants labeled ("scale", "fix", "kill", "test") | ROAS=1 breakeven line | point → campaign |
| Channel mix | stacked area | date × channel → spend | sum · weekly | 100%-stacked toggle | — | channel → campaigns |
| Funnel | funnel | impressions → clicks → conversions | sum | stage rates labeled (CTR, CVR) | benchmark rates per channel | stage → campaigns |

### 6. Logistics & Supply Chain
Status colors fixed (delivered=green, transit=blue, RTO/exception=red); polarity: on-time ↑ good, transit-days/RTO ↑ bad.

| Visual | Type | Bindings | Agg·Grain | Settings | Ref / Annotation | Drill |
|---|---|---|---|---|---|---|
| Volume & on-time | bar+line dual | ship_date → shipments + on-time % | count · weekly | on-time as % line on right axis | SLA target line (e.g., 95%); control band | week → shipments |
| Carrier scorecard | grouped bar | carrier → on-time %, cost/shipment | — | dual metric side-by-side; volume as label | SLA line | carrier → lanes |
| Transit by lane | box/bar | origin→destination → transit days | top 15 lanes by volume | promised-days marker per lane | promised vs actual gap colored | lane → shipments |
| Status mix | stacked bar | week × status → count | 100%-stacked | fixed status colors | — | status → shipments |
| Exceptions | table | delayed/RTO shipments | — | days-late heat-colored | — | row → shipment |

### 7. Manufacturing
Control-chart discipline: ops metrics get ±2σ bands by default. Polarity: output/OEE ↑ good, defects/downtime ↑ bad.

| Visual | Type | Bindings | Agg·Grain | Settings | Ref / Annotation | Drill |
|---|---|---|---|---|---|---|
| Output vs plan | bar+line | date → output (bar), plan (line) | sum · daily | attainment % in tooltip | plan line; shortfall shaded | day → machine detail |
| Defect control chart | line | date → defect rate | daily | SPC ±2σ band from trailing 20 pts | out-of-control points flagged | point → defect log |
| Defect Pareto | bar | defect type/product → count | top 10 | cumulative % line | 80% marker | type → occurrences |
| Downtime heatmap | heatmap | machine × shift → downtime min | sum | sequential red | worst cell annotated | cell → stoppage log |
| Machine league | bar (horiz) | machine → OEE proxy | — | availability/quality split in tooltip | plant average; 85% world-class line | machine → daily trend |

### 8. Healthcare
Privacy: no patient identifiers in any AI payload; small groups suppressed. Polarity: visits/revenue ↑ good, no-show/LOS ↑ bad.

| Visual | Type | Bindings | Agg·Grain | Settings | Ref / Annotation | Drill |
|---|---|---|---|---|---|---|
| Visits trend | line | visit_date → visits | count · weekly | new vs follow-up split toggle | capacity line (if slots known) | week → day → visits |
| Dept revenue | bar (horiz) | department → revenue | sum | revenue-per-visit annotated | — | dept → doctors |
| Doctor productivity | scatter | visits × revenue per doctor, color=dept | — | median crosshairs | — | point → doctor weekly |
| Demand heatmap | heatmap | day × hour → visits | count | clinic hours framed | peak cells annotated | cell → visits |
| No-show tracker | line | week → no-show % | rate | control band; day-of-week split | 10% benchmark | week → missed slots |

### 9. Education
Pivoted attendance/marks auto-unpivoted first. Small classes (< 5) suppressed in comparisons. Polarity: attendance/scores/collection ↑ good.

| Visual | Type | Bindings | Agg·Grain | Settings | Ref / Annotation | Drill |
|---|---|---|---|---|---|---|
| Attendance trend | line | date → attendance % | weekly | per-class toggle | 75% requirement line | week → class → students (local) |
| Scores by subject | box | subject → score | per exam | pass-threshold shading | pass line (e.g., 40) | subject → distribution |
| Batch comparison | bar | class/batch → avg score | mean | n= labels; CI whiskers | school average line | batch → subjects |
| Score distribution | histogram | score | 10-pt bins | pass/merit bands shaded | median marker | bin → students (local) |
| Fee collection | stacked bar | class → paid vs due | sum | collection % labeled | 100% line | class → defaulters (local) |

### 10. Real Estate
Polarity: absorption/collection ↑ good, aging/arrears ↑ bad.

| Visual | Type | Bindings | Agg·Grain | Settings | Ref / Annotation | Drill |
|---|---|---|---|---|---|---|
| Inventory status | stacked bar | project → units by status | count | fixed status colors (sold/booked/available) | absorption % labeled | project → units |
| Bookings pace | bar+line | month → bookings + cumulative | count · monthly | launch event flags | sales-target line | month → bookings |
| Price per sqft | box | unit_type → price/area | — | outlier units flagged | market benchmark (if set) | type → units |
| Arrears | bar (horiz) | project → outstanding | sum | aging buckets stacked (0-30/31-60/60+) | — | project → units in arrears |
| Aging inventory | table | unsold units: days on market, price | — | days heat-colored | — | row → unit |

### 11. Hospitality & F&B
Polarity: revenue/occupancy ↑ good, commission/discount ↑ bad. Business-date logic (day ends 3 AM) as a setting.

| Visual | Type | Bindings | Agg·Grain | Settings | Ref / Annotation | Drill |
|---|---|---|---|---|---|---|
| Daily revenue | line | date → revenue | sum · daily | day-of-week colored markers; MA-7 | same-day-last-week comparison; event flags | day → bills |
| Menu engineering | scatter | item: volume × margin (or price) | per item | quadrants: Stars/Plowhorses/Puzzles/Dogs | median crosshairs | point → item trend |
| Channel mix | stacked bar | week × channel → revenue | sum · weekly | commission % per channel in tooltip | — | channel → orders |
| Peak heatmap | heatmap | day × hour → revenue | sum | service periods framed (lunch/dinner) | peak cells annotated | cell → bills |
| Top items | bar (horiz) | item → revenue | top 15 | qty + margin annotated | — | item → daily |

### 12. SaaS & Subscription
Polarity: MRR/NRR ↑ good, churn ↑ bad. Currency = billing currency; annual plans normalized to MRR.

| Visual | Type | Bindings | Agg·Grain | Settings | Ref / Annotation | Drill |
|---|---|---|---|---|---|---|
| MRR trend | line | month → MRR | monthly | ARR toggle | growth-target line | month → movement |
| MRR movement | waterfall | month → new/expansion/contraction/churned | monthly | movement colors fixed | net line overlaid | segment → accounts |
| Cohort retention | cohort grid | start month × months since → retention % | monthly | sequential palette; row n= labels | median cohort highlighted | cell → accounts |
| Plan mix | stacked bar | month × plan → MRR | 100%-stacked | — | — | plan → accounts |
| Churn table | table | churned accounts: MRR, tenure, plan | this period | sorted by MRR lost | — | row → account history |

### 13. Lending & NBFC
Bucket colors fixed green→dark-red; fiscal Apr–Mar; polarity: collections ↑ good, PAR/DPD ↑ bad.

| Visual | Type | Bindings | Agg·Grain | Settings | Ref / Annotation | Drill |
|---|---|---|---|---|---|---|
| Portfolio by bucket | stacked area | month × bucket → outstanding | sum · monthly | fixed bucket palette | PAR-30 % line overlaid | bucket → loans |
| Disbursement trend | bar | month → disbursed + count | sum · monthly | avg ticket in tooltip | target line | month → loans |
| Branch PAR | bar (horiz) | branch → PAR-30 % | — | portfolio size as bar-label | portfolio-avg line; 5% risk line | branch → buckets |
| Collection efficiency | line | month → collected/due % | monthly | per-branch toggle | 95% target; control band | month → branch |
| Vintage curves | line multi | disbursal cohort → PAR by months-on-book | cohort | one line per quarter cohort | latest cohort emphasized | cohort → loans |

### 14. Energy & Utilities
Unit = kWh/MW; interval data auto-downsampled for display (raw kept for stats). Polarity: generation/PR ↑ good, downtime ↑ bad.

| Visual | Type | Bindings | Agg·Grain | Settings | Ref / Annotation | Drill |
|---|---|---|---|---|---|---|
| Actual vs expected | line | day → energy vs expected | sum · daily | shortfall shaded red | PR % in tooltip | day → intervals |
| Load profile | heatmap | hour × day → kWh | mean | daylight window framed (solar) | zero-generation daylight cells flagged | cell → intervals |
| Site league | bar (horiz) | site → PR % | — | capacity as label | fleet-avg; contractual PR line | site → daily |
| MTD vs target | bullet/line | cumulative day → MTD energy | cumulative | pace projection dotted | monthly target line | day → intervals |
| Downtime log | table | zero-gen periods: site, duration, est. loss | — | loss = duration × avg rate | — | row → interval data |

### 15. Nonprofit & NGO
Donor privacy: names local-only. Polarity: raised/retention ↑ good, concentration ↑ risk (amber, not red).

| Visual | Type | Bindings | Agg·Grain | Settings | Ref / Annotation | Drill |
|---|---|---|---|---|---|---|
| Donations trend | line | date → amount | sum · monthly | campaign event flags | same-month-last-year dotted | month → donations |
| Program funding | bar (horiz) | program → raised vs budget | sum | utilization % labeled | budget markers | program → donations |
| Donor pyramid | bar | donation-size band → donors + amount | banded | concentration % annotated | — | band → donors (local) |
| Retention | cohort grid | first-gift year × years since → % giving | annual | — | sector benchmark (~45%) | cell → donors (local) |
| Channel ROI | bar | channel → raised (− cost if known) | sum | cost-to-raise ratio labeled | — | channel → donations |

---

## C. Settings surface (what the user can change per dashboard, saved per dataset)

| Setting | Default source | Options |
|---|---|---|
| Currency & number style | auto-detected / locale | ₹ lakh-crore, $ SI, custom symbol |
| Fiscal year start | preset | Jan / Apr / custom |
| Week start | preset | Mon / Sun |
| Time grain | auto rule A2 | day / week / month / quarter |
| Top-N in bars | 10 | 5–25 + Others on/off |
| Targets & thresholds | preset defaults | per-KPI numeric target |
| Comparison basis | prior period | prior period / same period last year / target |
| Event flags | none | user-entered (promo, holiday auto-suggested from locale calendar) |
| Theme | app | dark / light |
| Privacy mode | on for HR/health/edu | suppress groups < n, mask IDs |

All of section A becomes shared rendering code; each industry table in section B is ~30
lines of YAML in its preset spec. Adding a new industry = writing YAML, no new chart code.
