# The One-Click Analyst Report — How the Built-In Expert Analyst Works

Implemented in `core/reports/analyst_report.py`, surfaced on the **⚡ Dashboard**
page as **"📄 One-Click Analyst Report"**. This document describes the expert
analyst the app emulates: his way of working, his complete workflow stage by
stage, how everything the user does feeds his analysis, and exactly what he
delivers at the end.

---

## 1. Who the built-in analyst is

Think of a senior business analyst with 15 years across industries. He is:

- **Skeptical first** — he never presents a number he hasn't audited. Before any
  chart, he checks whether the data can be trusted, and he says so in writing.
- **Comparative** — a number alone means nothing to him. Every figure is judged
  against the previous period, the trend, and the concentration behind it.
- **Statistical** — he refuses to call noise a trend. He tests significance,
  suppresses tiny samples, and labels correlation as association, never cause.
- **Explanatory** — "revenue fell 8%" is not analysis. *Which segment, volume or
  rate, since when, is it one-off or structural* — that's his job.
- **Forward-looking** — every review ends with an outlook and what to do about it.
- **Accountable** — every figure in his report is traceable: what data, what
  filters, what formula, what thresholds. Anyone can reproduce it.

## 2. His complete workflow (all automated, in order)

### Stage 0 — Intake & preparation (`core/ingest`)
What he does with a raw file before anything else:
- Detects and skips letterhead/title rows to find the real table.
- Converts `₹1,23,456.00`, `(500)`, `45%` text into numbers; notes the currency.
- Fixes date columns, resolving DD-MM vs MM-DD ambiguity.
- Removes grand-total rows that would double-count everything.
- Reshapes pivoted "months as columns" reports into analyzable form.
- **Writes a receipt of every fix** so nothing happens silently.

### Stage 1 — Data audit (`core/presets/audit.py`)
Before analysis, he scores trust 0–100 and lists caveats:
duplicates, missing values in key fields, gaps in the timeline (a "sales dip"
that is really missing data), category spellings that split groups
("Delhi"/"DELHI "), impossible negatives, incomplete current period.
**Findings on affected fields carry the caveat into the report.**

### Stage 2 — Business framing (`core/presets/specs.py` + `detect.py`)
He recognizes *what business this is* (15 industry presets, ranked with a
confidence score) and maps every column to its business meaning
("Bill Amt" → revenue). This decides which KPIs matter, which charts to draw,
which risks to check, and what tone the report takes.

### Stage 3 — Measurement (`core/presets/kpis.py`)
He computes the industry's KPI pack — not one-column stats, but real business
metrics: ratios (AOV, CPA, ROAS, win rate, PAR-30, collection efficiency),
durations (sales cycle, transit days, tenure, length of stay), concentration
(top-10 share), growth — **each with movement vs the previous period** at the
right time grain (daily/weekly/monthly, chosen from the data span).

### Stage 4 — Trend & momentum reading
- Fits a trend line and reports the slope **only with its p-value** — below
  significance he writes "not statistically significant" rather than a story.
- Quantifies volatility (CV) so the reader knows how much noise is normal.
- Measures momentum: the latest period against the trailing-4 average.
- Names the best and weakest periods explicitly.

### Stage 5 — Seasonality
He checks whether value concentrates by weekday (peak day, weakest day, spread)
and tells the reader how to use it: staffing, inventory, campaign timing, and
same-day-vs-same-day comparisons.

### Stage 6 — Decomposition (the "why")
For each key dimension (store, product, campaign, branch, doctor…):
- Top-5 contributor table with share of total and last-period movement.
- **Biggest gainer and biggest decliner** by absolute change — the two names a
  manager needs first.

### Stage 7 — Statistical findings (`core/presets/insights.py`)
Typed, gated findings: significant trends, anomalies (>2.5σ from local level,
**with attribution** — "that spike is 91% one store"), adverse/favourable KPI
moves beyond noise, concentration risk, group leaders. Ranked by materiality;
capped so only what matters surfaces.

### Stage 8 — Driver scan
Correlation of every numeric field against the primary metric, reported only at
|r| ≥ 0.3 and p < 0.01, always phrased as *association* with a suggestion to
verify via holdout.

### Stage 9 — Outlook (`core/forecast`)
Model-selected forecast (linear vs ARIMA by data size) of the primary metric:
next-period estimate with confidence range, projected total over the horizon,
backtest error — plus his standard warning: forecasts assume history repeats;
if a trend break was flagged, widen the planning range.

### Stage 10 — Prescription
Rules, not vibes: every risk finding gets an owner-and-deadline style action;
favourable findings get "codify it so it repeats"; data-quality issues get
"fix data first — it invalidates everything downstream." He always closes with
cadence advice: this review works as a rhythm, not a one-off.

### Stage 11 — Documentation
He logs the session and appends definitions and method so the report survives
scrutiny (see §4).

## 3. How the user's own actions shape the report

The report analyzes **the user's current working view**, and discloses it:

| User action on the dashboard | Effect on the report |
|---|---|
| Applies filters (date range, store, category…) | Every number is computed on the filtered view; §2 shows "rows analysed: X (filtered from Y)"; §11 lists each active filter |
| Edits the field mapping | All KPIs/charts rebind instantly; §2 marks mapping "user-adjusted"; the final mapping is printed in the appendix |
| Overrides the industry preset | The entire report re-frames: different KPI pack, sections, tone |
| Asks questions in "Ask your data" | Q&A pairs (question → answer summary) are logged into §11, so the report records the investigation, not just the conclusion |
| Generates AI commentary | The commentary is embedded in §11 as session narrative |

This makes the report an **audit trail of an analysis session**, not just a data
dump: a reviewer sees what was asked, what was excluded, and why.

## 4. The end result — the illustrated 13-section deliverable

One click produces a PDF (+ Markdown) with a table of contents, page numbers,
and **auto-numbered visual exhibits** rendered per chart-design rules
(`core/reports/report_charts.py`): compact ₹ lakh/crore axes, single accent
hue, peak/low annotations, anomaly flags, confidence bands. Typical exhibit
set (~9 charts):

| Exhibit | What it shows |
|---|---|
| Trend | Primary metric per period, rolling average, peak/low labels, red anomaly circles |
| Year-over-year | Monthly lines per year (appears when data spans > 13 months) |
| Seasonality | Weekday share bars, peak highlighted |
| Segment bars (×3 dims) | Top contributors, labels with value + share + last move; bars green/red when moved > ±5% |
| Concentration curve | Pareto bars + cumulative % line with 80% marker |
| Distribution | Histogram with median and P90 markers |
| Forecast | History + dashed forecast with shaded confidence range |

The report structure:

1. **Executive Summary** — the single headline finding as a pull-quote, the four
   headline KPIs with movement, and a bottom line counting favourable vs adverse
   signals with pointers to detail sections.
2. **Data & Methodology** — source file, rows (and filter disclosure), period
   covered, preset + detection confidence, mapping provenance, trust score, and
   every data caveat.
3. **Performance Scorecard** — all KPIs: value, movement marked
   *favourable/adverse by business polarity* (a cost rising is adverse even
   though the number went up), and plain-language definitions.
4. **Trend & Momentum** — trend exhibit with anomaly flags, periods analysed,
   best/weakest period, slope with significance verdict, volatility rating,
   momentum, and a recent-periods table with **absolute values**, not just %.
5. **Year-over-Year Comparison** *(multi-year data)* — YoY exhibit, per-year
   totals with growth, seasonality-honest framing.
6. **Seasonality Pattern** — weekday exhibit, strongest/weakest day and how to
   exploit it.
7. **Segment Deep-Dive** — per dimension: move-colored bar exhibit, top-5 table
   (value, share, move), gainer/decliner call-outs, Pareto concentration curve.
8. **Distribution & Outliers** — histogram exhibit, median vs mean guidance
   (skew-aware), outlier count, largest individual records with context and a
   verify-the-big-ones warning.
9. **Statistical Findings & Risk Flags** — the gated insight cards, labeled
   RISK / WATCH / OPPORTUNITY / NOTE.
10. **Driver Associations** — significant correlations with strength, p-value,
    and the causality disclaimer.
11. **Outlook** — forecast exhibit with confidence band, model name,
    next-period estimate with range, horizon total, backtest error, planning
    caveat.
12. **Recommended Actions** — prioritized, each tied to its finding, max 8.
    **Analysis Session Log** — filters, mapping edits, the user's Q&A history,
    AI commentary (only appears if the session had any).
13. **Appendix** — field mapping table, unused-columns disclosure, KPI
    definitions, and the methodology thresholds (p < 0.05 trends, 2.5σ
    anomalies, n ≥ 8 group floor, |r| ≥ 0.3 & p < 0.01 correlations).

Every industry gets the same discipline with its own vocabulary: a lender's
report reads PAR-30 and collection efficiency; a clinic's reads no-show rate
and revenue per visit; a SaaS company's reads MRR, ARPA and churn.

## 5. Report Studio — shape and edit the report in-app

Before generation (expander above the Generate button):
- **Branding**: custom report title, "prepared for" company, "prepared by" author.
- **Headline override**: replace the auto-detected headline with your own.
- **Analyst's notes**: free-text commentary (context the data can't know —
  promos, market events, decisions) becomes its own section after the summary.
- **Section picker**: include/exclude any of the 15 sections.
- **KPI picker**: choose which KPIs appear in the scorecard (findings still
  cite any KPI — selection curates presentation, never suppresses evidence).
- **Segment dimensions**: pick which categorical fields get the deep-dive,
  and rows per table (3–15).
- **Forecast horizon**: 0 (skip) to 24 periods.
- **Exhibits toggle**: text-only report when charts aren't wanted.

After generation (✏️ *Edit report text*): the full report text is editable in
the app — rewrite wording, delete bullets, add remarks. `*[Exhibit N …]*`
placeholder lines mark where charts sit; move or delete them to move or drop a
chart. "Apply edits & rebuild" parses the edited text back into a structured
document (`markdown_to_doc`), re-attaches the stored chart images by exhibit
number, and regenerates both the PDF and Markdown downloads.

## 6. Verification

`tests/test_report.py` (24 checks): section structure, headline presence,
filter/Q&A disclosure, movement labeling, methodology thresholds, forecast
section, valid PDF bytes, and bare-context builds across presets. Run:
`python tests/test_report.py`.
