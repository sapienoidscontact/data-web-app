"""
One-Click Professional Analyst Report.

Assembles everything a senior analyst would put in a periodic business review
(see SECTION_MENU for the full, user-selectable section list):

  executive summary · analyst's notes · data & methodology · scorecard ·
  trend & momentum (seasonally adjusted, partial periods excluded) ·
  period bridge (waterfall decomposition) · year-over-year (calendar/fiscal) ·
  seasonality · segment deep-dive · distribution & outliers · findings ·
  pinned evidence · driver associations · outlook (seasonal-aware forecast) ·
  recommended actions · session log · appendix

The report reflects the *current working view*: filters, mapping edits,
pinned items and Report Studio options (branding, headline override, analyst
notes, section/KPI/segment selection, fiscal calendar, forecast horizon) all
flow into the numbers and are disclosed in the document.

Outputs: structured ReportDoc → markdown (in-app preview / download) and PDF
(fpdf2, unicode DejaVu font, numbered exhibits, TOC, page numbers).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from loguru import logger
from scipy import stats

from ..presets.audit import AuditReport
from ..presets.insights import InsightCard, _period_series, deseasonalize
from ..presets.kpis import (KPIValue, auto_grain, is_partial_period,
                            last_two_full_periods)
from ..presets.model import PresetSpec
from . import report_charts as rc


# ── document model ────────────────────────────────────────────────────────────
# Blocks: ("p", text) | ("bullets", [..]) | ("kv", [(k, v)..])
#         | ("table", headers, rows) | ("quote", text)
#         | ("img", png_bytes, caption)   — visual exhibit, auto-numbered

@dataclass
class Section:
    title: str
    blocks: List[tuple] = field(default_factory=list)
    _doc: Optional["ReportDoc"] = None

    def p(self, text):        self.blocks.append(("p", text))
    def bullets(self, items): self.blocks.append(("bullets", list(items)))
    def kv(self, pairs):      self.blocks.append(("kv", list(pairs)))
    def table(self, headers, rows): self.blocks.append(("table", headers, rows))
    def quote(self, text):    self.blocks.append(("quote", text))

    def img(self, png: Optional[bytes], caption: str,
            kind: Optional[str] = None):
        """Attach a visual exhibit; skipped silently if rendering failed or
        the exhibit kind was deselected in the Report Studio."""
        if not png or (self._doc and self._doc.no_exhibits):
            return
        if (self._doc and self._doc.allowed_charts is not None
                and kind and kind not in self._doc.allowed_charts):
            return
        n = self._doc.next_exhibit() if self._doc else 0
        self.blocks.append(("img", png, f"Exhibit {n} - {caption}"))


@dataclass
class ReportDoc:
    title: str
    subtitle: str
    sections: List[Section] = field(default_factory=list)
    no_exhibits: bool = False
    allowed_charts: Optional[set] = None      # None = all exhibit kinds
    skips: List[tuple] = field(default_factory=list)  # (analysis, reason)
    _exhibits: int = 0

    def skip(self, analysis: str, reason: str):
        """Record why an analysis was omitted — disclosed in the appendix so
        the reader knows nothing was silently missed."""
        self.skips.append((analysis, reason))

    def exhibit_bank(self) -> Dict[int, tuple]:
        """{exhibit number: (png, caption)} — used to re-attach charts after
        the user edits the report text."""
        bank = {}
        for s in self.sections:
            for b in s.blocks:
                if b[0] == "img":
                    try:
                        n = int(b[2].split(" ")[1])
                    except (IndexError, ValueError):
                        continue
                    bank[n] = (b[1], b[2])
        return bank

    def add(self, title) -> Section:
        s = Section(f"{len(self.sections) + 1}. {title}", _doc=self)
        self.sections.append(s)
        return s

    def next_exhibit(self) -> int:
        self._exhibits += 1
        return self._exhibits


@dataclass
class SessionContext:
    """Everything the user did this session that shapes the report."""
    filename: str = ""
    total_rows: int = 0                    # before filters
    filters: List[str] = field(default_factory=list)
    qa_history: List[Dict] = field(default_factory=list)   # {q, sql, answer}
    mapping_edited: bool = False
    ai_commentary: Optional[str] = None
    pinned: List[Dict] = field(default_factory=list)        # E1 pinned items


# Section keys the user can toggle in the Report Studio, in build order.
SECTION_MENU = [
    ("exec", "Executive Summary"),
    ("notes", "Analyst's Notes (your text)"),
    ("methodology", "Data & Methodology"),
    ("scorecard", "Performance Scorecard"),
    ("trend", "Trend & Momentum"),
    ("bridge", "Period Bridge (what moved the number)"),
    ("volume_rate", "Volume vs Rate decomposition"),
    ("pace", "Current Period Pace"),
    ("yoy", "Year-over-Year"),
    ("seasonality", "Seasonality"),
    ("segments", "Segment Deep-Dive"),
    ("cohorts", "Cohorts & Repeat Behaviour"),
    ("distribution", "Distribution & Outliers"),
    ("findings", "Findings & Risk Flags"),
    ("evidence", "Analyst's Selected Evidence (pinned items)"),
    ("drivers", "Driver Associations"),
    ("outlook", "Outlook (Forecast)"),
    ("recommendations", "Recommended Actions"),
    ("session", "Analysis Session Log"),
    ("appendix", "Appendix"),
]

# Exhibit kinds selectable in the Report Studio ("graph options").
CHART_MENU = [
    ("trend", "Trend line with anomaly flags"),
    ("kpi_movement", "KPI movement tornado"),
    ("bridge", "Waterfall bridge"),
    ("volume_rate", "Volume-vs-rate waterfall"),
    ("pace", "Period-to-date pace curve"),
    ("yoy", "Year-over-year lines"),
    ("seasonality", "Weekday pattern bars"),
    ("segment_bars", "Segment bars (move-colored)"),
    ("small_multiples", "Segment small-multiples"),
    ("pareto", "Concentration (Pareto) curve"),
    ("cohort", "Cohort retention grid"),
    ("distribution", "Distribution histogram"),
    ("correlation", "Correlation heatmap"),
    ("forecast", "Forecast with backtest overlay"),
]


@dataclass
class ReportOptions:
    """Pre-generation controls set in the Report Studio."""
    title: str = ""                        # custom report title
    company: str = ""                      # "prepared for"
    prepared_by: str = ""
    headline: str = ""                     # overrides the auto headline
    analyst_notes: str = ""                # user's own commentary section
    sections: Optional[List[str]] = None   # keys from SECTION_MENU; None = all
    kpi_keys: Optional[List[str]] = None   # subset of KPI keys; None = all
    segment_fields: Optional[List[str]] = None  # canonical categorical fields
    top_n: int = 5                         # rows per segment table
    forecast_horizon: Optional[int] = None # None = auto, 0 = skip forecast
    include_exhibits: bool = True
    fiscal_start_month: int = 1           # 4 = Indian FY (Apr-Mar)
    chart_kinds: Optional[List[str]] = None  # CHART_MENU keys; None = all

    def want(self, key: str) -> bool:
        return self.sections is None or key in self.sections


_GRAIN_WORD = {"D": "daily", "W": "weekly", "M": "monthly", "Q": "quarterly"}
_DOW = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
        "Sunday"]


def _fmt(v, fmt="number", symbol=""):
    from ..dashboard.renderer import fmt_value
    return fmt_value(v, fmt, symbol)


def _direction(k: KPIValue) -> str:
    if k.delta_pct is None:
        return ""
    if abs(k.delta_pct) < 0.05:
        return "FLAT"
    arrow = "UP" if k.delta_pct > 0 else "DOWN"
    if k.polarity == "neutral":
        verdict = ""
    else:
        good = (k.delta_pct > 0) == (k.polarity == "up_good")
        verdict = " (favourable)" if good else " (adverse)"
    return f"{arrow} {k.delta_pct:+.1f}%{verdict}"


# ── analysis blocks ───────────────────────────────────────────────────────────

def _exec_summary(doc, kpis, cards, preset, symbol, grain_word,
                  headline_override: str = ""):
    from ..presets.specs import INDUSTRY_LENS
    s = doc.add("Executive Summary")
    s.p(f"This is a {preset.label} analysis. It applies the metrics, charts "
        f"and checks a {preset.report_tone.rstrip('s')} specialist would run "
        "for this kind of data.")
    lens = INDUSTRY_LENS.get(preset.name)
    if lens:
        s.p(f"Industry lens - what matters most in {preset.label}:")
        s.bullets(lens)
    if headline_override:
        s.quote(f"HEADLINE: {headline_override}")
    elif cards:
        s.quote(f"HEADLINE: {cards[0].headline}. {cards[0].so_what}")
    by_key = {k.key: k for k in kpis}
    facts = []
    for key in preset.tiles:
        k = by_key.get(key)
        if k is None:
            continue
        d = f" ({k.delta_pct:+.1f}% vs previous {grain_word.rstrip('ly')})" \
            if k.delta_pct is not None else ""
        facts.append(f"{k.label}: {_fmt(k.value, k.fmt, symbol)}{d}")
    if facts:
        s.bullets(facts)
    adverse = [c for c in cards if c.severity == "risk"]
    good = [c for c in cards if c.severity == "good"]
    bottom = []
    if good:
        bottom.append(f"{len(good)} favourable development(s)")
    if adverse:
        bottom.append(f"{len(adverse)} adverse signal(s) needing attention")
    if bottom:
        s.p("Bottom line: " + " and ".join(bottom) +
            " - details in the findings sections and prioritized actions near the end.")


def _methodology(doc, df, bundle, ctx):
    s = doc.add("Data & Methodology")
    dcol = None
    for f in bundle.preset.fields:
        if f.role == "temporal" and f.name in bundle.mapping:
            dcol = bundle.mapping[f.name]
            break
    period = "n/a"
    if dcol is not None:
        d = pd.to_datetime(df[dcol], errors="coerce").dropna()
        if len(d):
            period = f"{d.min():%d %b %Y} to {d.max():%d %b %Y}"
    s.kv([
        ("Source file", ctx.filename or "uploaded dataset"),
        ("Rows analysed", f"{len(df):,}" + (
            f" (filtered from {ctx.total_rows:,})"
            if ctx.total_rows and ctx.total_rows != len(df) else "")),
        ("Period covered", period),
        ("Industry preset", f"{bundle.preset.label} "
                            f"(detected {bundle.confidence}% confidence)"),
        ("Fields mapped", f"{len(bundle.mapping)}/{len(bundle.preset.fields)}"
                          + (" - user-adjusted" if ctx.mapping_edited else
                             " - auto-mapped")),
        ("Data trust score", f"{bundle.audit.score}/100 "
                             f"(grade {bundle.audit.grade})"),
    ])
    if bundle.audit.issues:
        s.p("Data caveats affecting interpretation:")
        s.bullets([f"[{i.severity.upper()}] {i.message}"
                   for i in bundle.audit.issues])
    else:
        s.p("No data-quality issues detected; figures can be used as-is.")


def _scorecard(doc, kpis, symbol, grain_word):
    s = doc.add("Performance Scorecard")
    s.p(f"All indicators computed on the working view; movement is vs the "
        f"previous {grain_word.rstrip('ly')} period.")
    rows = [[k.label, _fmt(k.value, k.fmt, symbol),
             _direction(k) or "-", k.description] for k in kpis]
    s.table(["Indicator", "Value", "Movement", "Definition"], rows)
    s.img(rc.kpi_delta_bar([(k.label, k.delta_pct, k.polarity)
                            for k in kpis], symbol),
          "KPI movement overview - green favourable, red adverse "
          "(by business polarity)", kind="kpi_movement")


def _trend(doc, df, preset, mapping, symbol, cards=None):
    series, grain, label, dcol = _period_series(df, preset, mapping)
    if series is None or len(series) < 4:
        return None
    s = doc.add("Trend & Momentum")
    # disclose when the trailing partial period was excluded (A1)
    if dcol and dcol in df.columns:
        _d = pd.to_datetime(df[dcol], errors="coerce").dropna()
        if len(_d):
            last_p = _d.max().to_period(grain)
            if is_partial_period(last_p, _d.max(), grain):
                s.p(f"Note: the latest period ({last_p}) is incomplete and is "
                    "excluded from every trend, movement and forecast figure "
                    "below to avoid a false decline.")
    # visual exhibit with anomaly flags from the findings engine
    anomaly_periods = []
    for c in (cards or []):
        if c.type == "anomaly" and c.evidence.get("period"):
            try:
                anomaly_periods.append(pd.Period(c.evidence["period"]))
            except Exception:
                pass
    gw0 = _GRAIN_WORD.get(grain, "period")
    s.img(rc.trend_chart(series, f"{label} per {gw0.rstrip('ly')}", symbol,
                         anomalies=anomaly_periods),
          f"{label} trend with rolling average"
          + (" and anomaly flags (red circles)" if anomaly_periods else ""),
          kind="trend")
    vals = series.astype(float)
    total, mean = vals.sum(), vals.mean()
    best, worst = vals.idxmax(), vals.idxmin()
    gw = _GRAIN_WORD.get(grain, "period")
    kv = [
        (f"Periods analysed ({gw})", str(len(vals))),
        ("Average per period", _fmt(mean, "currency" if symbol else "number",
                                    symbol)),
        ("Best period", f"{best} ({_fmt(vals.max(), 'currency' if symbol else 'number', symbol)})"),
        ("Weakest period", f"{worst} ({_fmt(vals.min(), 'currency' if symbol else 'number', symbol)})"),
    ]
    # trend slope + significance (seasonally adjusted when cycles exist, A3)
    adj_vals, was_adj = deseasonalize(vals, grain)
    x = np.arange(len(adj_vals), dtype=float)
    reg = stats.linregress(x, adj_vals.values)
    if mean:
        slope_pct = reg.slope / abs(mean) * 100
        verdict = ("statistically significant"
                   if reg.pvalue < 0.05 else "not statistically significant")
        adj_note = ", seasonally adjusted" if was_adj else ""
        kv.append(("Underlying trend",
                   f"{slope_pct:+.1f}% per {gw.rstrip('ly')} "
                   f"({verdict}, p={reg.pvalue:.3f}{adj_note})"))
    # volatility & momentum
    cv = vals.std() / abs(mean) * 100 if mean else None
    if cv is not None:
        stability = ("stable" if cv < 15 else
                     "moderately volatile" if cv < 40 else "highly volatile")
        kv.append(("Volatility (CV)", f"{cv:.0f}% - {stability}"))
    if len(vals) >= 5:
        momentum = (vals.iloc[-1] - vals.iloc[-5:-1].mean()) \
            / abs(vals.iloc[-5:-1].mean()) * 100 if vals.iloc[-5:-1].mean() else None
        if momentum is not None:
            kv.append(("Momentum (latest vs trailing-4 avg)",
                       f"{momentum:+.1f}%"))
    s.kv(kv)
    # recent-periods table with absolute values, not just percentages
    recent = vals.tail(6)
    rows = []
    prev = None
    for per, v in recent.items():
        chg = f"{(v - prev) / abs(prev) * 100:+.1f}%" if prev else "-"
        rows.append([str(per), _fmt(v, "currency" if symbol else "number",
                                    symbol), chg])
        prev = v
    s.table([f"Recent {gw}", "Value", "Change"], rows)
    s.p(f"Metric: {label}. A professional read: judge the trend line, not "
        f"single periods - the volatility figure above says how much noise "
        f"to expect before calling a change real.")
    return grain


def _seasonality(doc, df, preset, mapping, symbol):
    dcol = None
    for f in preset.fields:
        if f.role == "temporal" and f.name in mapping:
            dcol = mapping[f.name]
            break
    mcol = mapping.get(preset.primary_metric)
    if dcol is None:
        return
    dates = pd.to_datetime(df[dcol], errors="coerce")
    ok = dates.notna()
    if ok.sum() < 28:
        return
    metric = df[mcol][ok] if mcol and pd.api.types.is_numeric_dtype(
        df.get(mcol, pd.Series(dtype=float))) else pd.Series(1, index=df[ok].index)
    by_dow = metric.groupby(dates[ok].dt.dayofweek).sum()
    if len(by_dow) < 5 or by_dow.sum() == 0:
        return
    share = by_dow / by_dow.sum() * 100
    peak, trough = share.idxmax(), share.idxmin()
    spread = share.max() - share.min()
    if spread < 5:
        doc.skip("Seasonality", "weekday spread under 5 percentage points - "
                                "no actionable weekly pattern")
        return
    s = doc.add("Seasonality Pattern")
    s.img(rc.seasonality_chart(share), "Share of value by weekday",
          kind="seasonality")
    s.kv([
        ("Strongest day", f"{_DOW[peak]} ({share.max():.1f}% of value)"),
        ("Weakest day", f"{_DOW[trough]} ({share.min():.1f}%)"),
        ("Weekly spread", f"{spread:.1f} percentage points"),
    ])
    s.p("Use this for staffing, inventory and campaign timing; compare "
        "same-day-vs-same-day when judging weekly performance.")


def _segments(doc, df, preset, mapping, symbol, segment_fields=None,
              top_n: int = 5):
    mcol = mapping.get(preset.primary_metric)
    if mcol is None or not pd.api.types.is_numeric_dtype(df[mcol]):
        return
    metric = df[mcol]
    # period membership for movement
    dcol = next((mapping[f.name] for f in preset.fields
                 if f.role == "temporal" and f.name in mapping), None)
    cur_mask = prev_mask = None
    if dcol:
        dates = pd.to_datetime(df[dcol], errors="coerce")
        okd = dates.notna()
        if okd.sum() > 8:
            grain = auto_grain(dates[okd])
            cur_p, prev_p = last_two_full_periods(dates[okd], grain)
            if cur_p is not None:
                periods = dates.dt.to_period(grain)
                cur_mask, prev_mask = periods == cur_p, periods == prev_p

    dims = [(f.name, mapping[f.name]) for f in preset.fields
            if f.role == "categorical" and f.name in mapping]
    if segment_fields is not None:
        dims = [d for d in dims if d[0] in segment_fields]
    dims = dims[:4]
    if not dims:
        return
    s = doc.add("Segment Deep-Dive")
    s.p(f"Where the {mcol} actually comes from - and which segments moved "
        "it last period.")
    # small multiples: trend per top segment of the leading dimension
    if dcol and dims:
        col0 = dims[0][1]
        dts = pd.to_datetime(df[dcol], errors="coerce")
        okd = dts.notna()
        if okd.sum() >= 12:
            g0 = auto_grain(dts[okd])
            per = dts[okd].dt.to_period(g0)
            top4 = metric[okd].groupby(df[col0][okd].astype(str)).sum()                 .sort_values(ascending=False).head(4).index
            series_map = {}
            for name in top4:
                m = df[col0][okd].astype(str) == name
                series_map[name] = metric[okd][m].groupby(per[m]).sum()                     .sort_index()
            s.img(rc.small_multiples(series_map, symbol),
                  f"Trend per top {col0} (shared scale) - divergence "
                  "spotting", kind="small_multiples")
    for dim_i, (fname, col) in enumerate(dims):
        g = metric.groupby(df[col].astype(str)).sum().sort_values(ascending=False)
        total = g.sum()
        if total == 0 or len(g) < 2:
            continue
        # last-period movement per segment (for table + exhibit coloring)
        moves: dict = {}
        if cur_mask is not None:
            for name in g.head(8).index:
                seg = df[col].astype(str) == name
                # A2 noise gate: need enough records in both periods for the
                # move label to mean anything
                if (seg & prev_mask).sum() < 8 or (seg & cur_mask).sum() < 8:
                    continue
                prev = metric[seg & prev_mask].sum()
                if prev:
                    cur = metric[seg & cur_mask].sum()
                    moves[str(name)] = (cur - prev) / abs(prev) * 100
        s.img(rc.segment_bar(g, symbol, moves),
              f"{mcol} by {col} (green/red = moved >5% last period)",
              kind="segment_bars")
        rows = []
        for name, v in g.head(top_n).items():
            move = f"{moves[str(name)]:+.0f}%" if str(name) in moves else "-"
            rows.append([str(name)[:28], _fmt(v, "currency" if symbol else
                                              "number", symbol),
                         f"{v / total * 100:.1f}%", move])
        s.table([f"Top {col}", "Value", "Share", "Last-period move"], rows)
        # concentration curve for the leading dimension
        if dim_i == 0 and len(g) >= 6:
            s.img(rc.pareto_chart(g, symbol),
                  f"Concentration curve - cumulative share of {mcol} "
                  f"across {col} (dotted line = 80%)", kind="pareto")
        # movers
        if cur_mask is not None and cur_mask.sum() and prev_mask.sum():
            cur_g = metric[cur_mask].groupby(df[col][cur_mask].astype(str)).sum()
            prev_g = metric[prev_mask].groupby(df[col][prev_mask].astype(str)).sum()
            delta = (cur_g - prev_g.reindex(cur_g.index).fillna(0)).dropna()
            if len(delta) >= 2 and delta.abs().max() > 0:
                up, down = delta.idxmax(), delta.idxmin()
                s.bullets([
                    f"Biggest gainer in {col}: '{up}' "
                    f"({_fmt(delta.max(), 'currency' if symbol else 'number', symbol)} added vs prior period)",
                    f"Biggest decliner in {col}: '{down}' "
                    f"({_fmt(delta.min(), 'currency' if symbol else 'number', symbol)})",
                ])


def _bridge(doc, df, preset, mapping, symbol):
    """
    B1 — waterfall decomposition: which segments moved the primary metric
    between the last two full periods, quantified in currency/units.
    """
    mcol = mapping.get(preset.primary_metric)
    if mcol is None or not pd.api.types.is_numeric_dtype(
            df.get(mcol, pd.Series(dtype=float))):
        return
    dcol = next((mapping[f.name] for f in preset.fields
                 if f.role == "temporal" and f.name in mapping), None)
    dim = next(((f.name, mapping[f.name]) for f in preset.fields
                if f.role == "categorical" and f.name in mapping), None)
    if dcol is None or dim is None:
        return
    dates = pd.to_datetime(df[dcol], errors="coerce")
    ok = dates.notna()
    if ok.sum() < 16:
        return
    grain = auto_grain(dates[ok])
    cur_p, prev_p = last_two_full_periods(dates[ok], grain)
    if cur_p is None:
        return
    periods = dates.dt.to_period(grain)
    cur_mask, prev_mask = periods == cur_p, periods == prev_p
    metric = df[mcol]
    col = dim[1]
    cur_g = metric[cur_mask].groupby(df[col][cur_mask].astype(str)).sum()
    prev_g = metric[prev_mask].groupby(df[col][prev_mask].astype(str)).sum()
    all_idx = cur_g.index.union(prev_g.index)
    delta = (cur_g.reindex(all_idx).fillna(0)
             - prev_g.reindex(all_idx).fillna(0))
    prev_total, cur_total = float(prev_g.sum()), float(cur_g.sum())
    total_delta = cur_total - prev_total
    if prev_total == 0 or abs(total_delta) < abs(prev_total) * 0.005:
        return
    # top contributors by absolute impact, remainder bucketed
    ranked = delta.reindex(delta.abs().sort_values(ascending=False).index)
    top = ranked.head(5)
    rest = ranked.iloc[5:].sum()
    contribs = top.copy()
    if abs(rest) > 0:
        contribs["Others"] = rest
    gw = _GRAIN_WORD.get(grain, "period").rstrip("ly")
    s = doc.add("Period Bridge - What Moved the Number")
    s.p(f"{mcol} moved {_fmt(total_delta, 'currency' if symbol else 'number', symbol)} "
        f"({total_delta / abs(prev_total) * 100:+.1f}%) from {prev_p} to "
        f"{cur_p}. The bridge shows which {col} segments drove it:")
    s.img(rc.waterfall_chart(prev_total, contribs, cur_total,
                             labels=(str(prev_p), str(cur_p)), symbol=symbol),
          f"{mcol} bridge by {col}: {prev_p} to {cur_p}", kind="bridge")
    driver = ranked.index[0]
    share = abs(ranked.iloc[0]) / abs(total_delta) if total_delta else 0
    s.bullets([
        f"'{driver}' explains {min(share, 9.99) * 100:.0f}% of the move "
        f"({_fmt(ranked.iloc[0], 'currency' if symbol else 'number', symbol)}).",
        f"Compare each {gw}'s bridge over time to separate structural shifts "
        "from one-off swings.",
    ])


def _volume_rate(doc, df, preset, mapping, symbol):
    """
    B2 — was the move more activity or more value per activity?
    metric = volume × rate; the change decomposes exactly into
    (Δvolume × rate₀) + (volume₁ × Δrate). Includes a mix-shift
    (Simpson's paradox) check across the leading dimension (B3).
    """
    mcol = mapping.get(preset.primary_metric)
    if mcol is None or not pd.api.types.is_numeric_dtype(
            df.get(mcol, pd.Series(dtype=float))):
        doc.skip("Volume vs Rate", "no numeric primary metric mapped")
        return
    dcol = next((mapping[f.name] for f in preset.fields
                 if f.role == "temporal" and f.name in mapping), None)
    if dcol is None:
        doc.skip("Volume vs Rate", "no date field mapped")
        return
    dates = pd.to_datetime(df[dcol], errors="coerce")
    ok = dates.notna()
    grain = auto_grain(dates[ok]) if ok.sum() else "M"
    cur_p, prev_p = last_two_full_periods(dates[ok], grain) if ok.sum() >= 8 \
        else (None, None)
    if cur_p is None:
        doc.skip("Volume vs Rate", "fewer than two complete periods")
        return
    periods = dates.dt.to_period(grain)
    cur_mask, prev_mask = periods == cur_p, periods == prev_p

    # volume = distinct activity units if an id field is mapped, else rows
    id_field = next((f.name for f in preset.fields
                     if f.role == "identifier" and f.name in mapping), None)
    id_col = mapping.get(id_field) if id_field else None

    def vol(mask):
        return (df[id_col][mask].nunique() if id_col
                else int(mask.sum())) or 0

    metric = df[mcol]
    m0, m1 = float(metric[prev_mask].sum()), float(metric[cur_mask].sum())
    v0, v1 = vol(prev_mask), vol(cur_mask)
    if not v0 or not v1 or m0 == 0:
        doc.skip("Volume vs Rate", "a period has no activity to decompose")
        return
    r0, r1 = m0 / v0, m1 / v1
    vol_eff = (v1 - v0) * r0
    rate_eff = (r1 - r0) * v1
    total = m1 - m0
    if abs(total) < abs(m0) * 0.005:
        doc.skip("Volume vs Rate", "the metric was essentially flat "
                                   "between the last two periods")
        return
    vol_label = id_field or "records"
    gw = _GRAIN_WORD.get(grain, "period").rstrip("ly")
    s = doc.add("Volume vs Rate - The Anatomy of the Move")
    s.p(f"{mcol} moved {_fmt(total, 'currency' if symbol else 'number', symbol)} "
        f"({total / abs(m0) * 100:+.1f}%) {prev_p} → {cur_p}. Splitting it "
        f"into activity (how many {vol_label}) versus value-per-activity:")
    contribs = pd.Series({
        f"volume ({vol_label})": vol_eff,
        "rate (value each)": rate_eff,
    })
    s.img(rc.waterfall_chart(m0, contribs, m1,
                             labels=(str(prev_p), str(cur_p)), symbol=symbol),
          f"{mcol} = volume x rate decomposition, {prev_p} to {cur_p}",
          kind="volume_rate")
    s.kv([
        (f"Volume ({vol_label})", f"{v0:,} → {v1:,} "
         f"({(v1 - v0) / v0 * 100:+.1f}%) — contributed "
         f"{_fmt(vol_eff, 'currency' if symbol else 'number', symbol)}"),
        ("Rate (value per unit)",
         f"{_fmt(r0, 'currency' if symbol else 'number', symbol)} → "
         f"{_fmt(r1, 'currency' if symbol else 'number', symbol)} "
         f"({(r1 - r0) / abs(r0) * 100:+.1f}%) — contributed "
         f"{_fmt(rate_eff, 'currency' if symbol else 'number', symbol)}"),
        ("Dominant driver", "volume" if abs(vol_eff) >= abs(rate_eff)
         else "rate"),
    ])
    s.p("A volume problem needs demand/traffic fixes; a rate problem needs "
        "pricing/mix fixes - they are different playbooks.")

    # B3: mix-shift (Simpson's paradox) check on the leading dimension
    dim = next(((f.name, mapping[f.name]) for f in preset.fields
                if f.role == "categorical" and f.name in mapping), None)
    if dim and id_col is None:
        col = dim[1]
        seg = df[col].astype(str)
        v0_i = seg[prev_mask].value_counts()
        m1_i = metric[cur_mask].groupby(seg[cur_mask]).sum()
        v1_i = seg[cur_mask].value_counts()
        common = v0_i.index.intersection(v1_i.index)
        if len(common) >= 3 and v0_i[common].sum():
            r1_i = (m1_i[common] / v1_i[common]).dropna()
            shares0 = v0_i[common] / v0_i[common].sum()
            r1_fixed = float((shares0.reindex(r1_i.index).fillna(0)
                              * r1_i).sum())
            blended_delta, fixed_delta = r1 - r0, r1_fixed - r0
            if (abs(blended_delta) > abs(r0) * 0.02
                    and blended_delta * fixed_delta < 0):
                s.p(f"⚠ Mix-shift alert: at last period's {col} mix, the rate "
                    f"would have moved the OTHER way "
                    f"({fixed_delta / abs(r0) * 100:+.1f}% vs the blended "
                    f"{blended_delta / abs(r0) * 100:+.1f}%). The blended "
                    "figure reflects a composition change, not underlying "
                    "performance - judge segments individually.")


def _pace(doc, df, preset, mapping, symbol):
    """
    Current-period pace: the in-progress period is excluded from trends (to
    avoid false declines) but tracked here, where partial data is the point.
    """
    mcol = mapping.get(preset.primary_metric)
    dcol = next((mapping[f.name] for f in preset.fields
                 if f.role == "temporal" and f.name in mapping), None)
    if dcol is None:
        doc.skip("Current Period Pace", "no date field mapped")
        return
    dates = pd.to_datetime(df[dcol], errors="coerce")
    ok = dates.notna()
    if ok.sum() < 20:
        doc.skip("Current Period Pace", "too few dated records")
        return
    grain = auto_grain(dates[ok])
    if grain not in ("W", "M"):
        doc.skip("Current Period Pace",
                 f"pace tracking applies to weekly/monthly views, not "
                 f"{_GRAIN_WORD.get(grain, grain)}")
        return
    periods = dates[ok].dt.to_period(grain)
    uniq = sorted(periods.unique())
    if len(uniq) < 2:
        doc.skip("Current Period Pace", "needs at least two periods")
        return
    cur_p, prev_p = uniq[-1], uniq[-2]
    metric = (df[mcol][ok] if mcol and pd.api.types.is_numeric_dtype(
        df.get(mcol, pd.Series(dtype=float))) else pd.Series(1.0, index=dates[ok].index))

    def cum_by_day(period):
        mask = periods == period
        day = (dates[ok][mask] - period.to_timestamp()).dt.days + 1
        return metric[mask].groupby(day).sum().sort_index().cumsum()

    cur_cum, prev_cum = cum_by_day(cur_p), cum_by_day(prev_p)
    if not len(cur_cum) or not len(prev_cum):
        doc.skip("Current Period Pace", "no activity in the latest period")
        return
    day_now = int(cur_cum.index[-1])
    period_len = 7 if grain == "W" else cur_p.days_in_month
    prev_at_same = float(prev_cum[prev_cum.index <= day_now].iloc[-1]) \
        if (prev_cum.index <= day_now).any() else None
    cur_now = float(cur_cum.iloc[-1])
    prev_total = float(prev_cum.iloc[-1])
    run_rate = cur_now / day_now * period_len if day_now else None

    gw = _GRAIN_WORD.get(grain, "period").rstrip("ly")
    s = doc.add("Current Period Pace")
    s.p(f"The {gw} in progress ({cur_p}, day {day_now} of {period_len}) is "
        "excluded from all trend statistics above; here is how it is "
        "tracking:")
    s.img(rc.pace_chart(cur_cum, prev_cum, labels=(str(cur_p), str(prev_p)),
                        symbol=symbol),
          f"Cumulative {mcol or 'activity'}: {cur_p} so far vs {prev_p}",
          kind="pace")
    kv = [(f"So far this {gw}",
           _fmt(cur_now, "currency" if symbol else "number", symbol))]
    if prev_at_same:
        kv.append((f"Previous {gw} at the same day",
                   f"{_fmt(prev_at_same, 'currency' if symbol else 'number', symbol)} "
                   f"({(cur_now - prev_at_same) / prev_at_same * 100:+.1f}% pace)"))
    if run_rate and prev_total:
        kv.append((f"Projected {gw} total (run-rate)",
                   f"{_fmt(run_rate, 'currency' if symbol else 'number', symbol)} "
                   f"({(run_rate - prev_total) / prev_total * 100:+.1f}% vs "
                   f"previous {gw})"))
    s.kv(kv)


def _cohorts(doc, df, preset, mapping, symbol):
    """
    B5 — repeat behaviour: when an entity id (customer/donor/patient/student)
    and dates exist, build first-seen cohorts and a retention grid.
    """
    entity_fields = [f.name for f in preset.fields
                     if f.role == "identifier" and f.name in mapping
                     and any(w in f.name for w in
                             ("customer", "donor", "patient", "student",
                              "member", "user"))]
    if not entity_fields:
        doc.skip("Cohorts & Repeat Behaviour",
                 "no customer/donor/patient-style id field mapped")
        return
    ecol = mapping[entity_fields[0]]
    dcol = next((mapping[f.name] for f in preset.fields
                 if f.role == "temporal" and f.name in mapping), None)
    if dcol is None:
        doc.skip("Cohorts & Repeat Behaviour", "no date field mapped")
        return
    dates = pd.to_datetime(df[dcol], errors="coerce")
    ok = dates.notna() & df[ecol].notna()
    if ok.sum() < 60 or df[ecol][ok].nunique() < 30:
        doc.skip("Cohorts & Repeat Behaviour",
                 "needs at least ~30 distinct entities with dates")
        return
    span_days = (dates[ok].max() - dates[ok].min()).days
    grain = "M" if span_days >= 85 else "W"
    frame = pd.DataFrame({"e": df[ecol][ok].astype(str),
                          "p": dates[ok].dt.to_period(grain)})
    first = frame.groupby("e")["p"].min().rename("cohort")
    frame = frame.merge(first, left_on="e", right_index=True)
    frame["k"] = (frame["p"] - frame["cohort"]).apply(lambda d: d.n)
    max_k = min(6, int(frame["k"].max()))
    if max_k < 1:
        doc.skip("Cohorts & Repeat Behaviour",
                 "every entity appears in a single period only")
        return
    cohort_sizes = first.value_counts().sort_index()
    recent = cohort_sizes.index[-8:]
    matrix = {}
    for c in recent:
        base = cohort_sizes[c]
        row = {}
        for k in range(0, max_k + 1):
            active = frame[(frame["cohort"] == c)
                           & (frame["k"] == k)]["e"].nunique()
            future = (c.to_timestamp() + pd.DateOffset(
                months=k if grain == "M" else 0,
                weeks=k if grain == "W" else 0))
            row[k] = active / base * 100 if future <= dates[ok].max() \
                else float("nan")
        matrix[str(c)] = row
    mat = pd.DataFrame(matrix).T
    repeat_rate = (frame.groupby("e")["p"].nunique() >= 2).mean() * 100
    # period ordinals avoid Period-arithmetic overflow on NaT shifts
    frame["_ord"] = frame["p"].map(lambda p: p.ordinal)
    dedup = frame.drop_duplicates(["e", "_ord"]).sort_values(["e", "_ord"])
    gaps = dedup.groupby("e")["_ord"].diff().dropna()
    med_gap = float(gaps.median()) if len(gaps) else None

    gw = _GRAIN_WORD.get(grain, "period")
    s = doc.add("Cohorts & Repeat Behaviour")
    s.img(rc.cohort_heatmap(mat),
          f"Retention by first-activity cohort ({gw} grain): % of each "
          "cohort active N periods later", kind="cohort")
    kv = [("Entities analysed", f"{df[ecol][ok].nunique():,}"),
          ("Repeat rate", f"{repeat_rate:.1f}% appear in 2+ {gw} periods")]
    if med_gap is not None:
        kv.append((f"Median gap between active {gw} periods",
                   f"{med_gap:.1f}"))
    s.kv(kv)
    s.p("Read down a column: falling retention in newer cohorts means "
        "recently acquired entities are weaker - an early-warning signal "
        "revenue totals hide.")


def _yoy(doc, df, preset, mapping, symbol, fiscal_start: int = 1):
    """Same-month-last-year comparison — only when data spans > 13 months."""
    dcol = next((mapping[f.name] for f in preset.fields
                 if f.role == "temporal" and f.name in mapping), None)
    mcol = mapping.get(preset.primary_metric)
    if dcol is None:
        return
    dates = pd.to_datetime(df[dcol], errors="coerce")
    ok = dates.notna()
    if ok.sum() < 30 or (dates[ok].max() - dates[ok].min()).days < 400:
        doc.skip("Year-over-Year", "data spans less than ~13 months")
        return
    metric = df[mcol][ok] if mcol and pd.api.types.is_numeric_dtype(
        df.get(mcol, pd.Series(dtype=float))) else pd.Series(1.0,
                                                             index=df[ok].index)
    months = dates[ok].dt.month
    years = dates[ok].dt.year
    if fiscal_start > 1:
        # FY named by its ending year: Apr 2023 - Mar 2024 = FY2024
        fy = years + (months >= fiscal_start).astype(int)
        fm = (months - fiscal_start) % 12 + 1
        frame = pd.DataFrame({"y": fy.values, "m": fm.values,
                              "v": metric.values})
        base = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug",
                "Sep", "Oct", "Nov", "Dec"]
        month_labels = base[fiscal_start - 1:] + base[:fiscal_start - 1]
        year_word = "FY"
    else:
        frame = pd.DataFrame({"y": years.values, "m": months.values,
                              "v": metric.values})
        month_labels = None
        year_word = ""
    pivot = frame.pivot_table(index="m", columns="y", values="v", aggfunc="sum")
    if pivot.shape[1] < 2:
        return
    s = doc.add("Year-over-Year Comparison")
    if fiscal_start > 1:
        s.p(f"Fiscal years starting {month_labels[0]} "
            f"(FY named by ending year).")
    s.img(rc.yoy_chart(pivot, symbol, month_labels=month_labels),
          "Monthly value by year - seasonality-adjusted comparison",
          kind="yoy")
    yr_cols = list(pivot.columns)
    totals = pivot.sum()
    rows = []
    for i, yr in enumerate(yr_cols):
        chg = (f"{(totals[yr] - totals[yr_cols[i - 1]]) / abs(totals[yr_cols[i - 1]]) * 100:+.1f}%"
               if i and totals[yr_cols[i - 1]] else "-")
        rows.append([f"{year_word}{yr}", _fmt(totals[yr], "currency" if symbol
                                              else "number", symbol), chg])
    s.table(["Year", "Total", "vs prior year"], rows)
    s.p("Comparing the same month across years removes seasonal distortion - "
        "this is the honest growth view for seasonal businesses.")


def _distribution(doc, df, preset, mapping, symbol):
    """Distribution shape + largest individual records (outlier watch)."""
    mcol = mapping.get(preset.primary_metric)
    if mcol is None or not pd.api.types.is_numeric_dtype(
            df.get(mcol, pd.Series(dtype=float))):
        return
    v = df[mcol].dropna().astype(float)
    if len(v) < 30:
        return
    s = doc.add("Distribution & Outliers")
    s.img(rc.distribution_chart(v, symbol),
          f"Distribution of {mcol} per record", kind="distribution")
    mean, med = v.mean(), v.median()
    skew = v.skew()
    z = np.abs((v - mean) / v.std()) if v.std() else pd.Series(0, index=v.index)
    n_out = int((z > 3).sum())
    shape = ("right-skewed - a few large records pull the average up; "
             "prefer the median" if skew > 1 else
             "left-skewed" if skew < -1 else "roughly symmetric")
    s.kv([
        ("Typical record (median)", _fmt(med, "currency" if symbol else
                                         "number", symbol)),
        ("Average", _fmt(mean, "currency" if symbol else "number", symbol)),
        ("90th percentile", _fmt(v.quantile(0.9), "currency" if symbol else
                                 "number", symbol)),
        ("Shape", f"{shape} (skew {skew:.1f})"),
        ("Outliers (>3 sigma)", f"{n_out} record(s)"),
    ])
    # largest records with context
    if n_out or len(v) >= 50:
        cat_col = next((mapping[f.name] for f in preset.fields
                        if f.role == "categorical" and f.name in mapping), None)
        top = df.loc[v.nlargest(3).index]
        rows = []
        for _, r in top.iterrows():
            ctx_val = str(r[cat_col])[:24] if cat_col else "-"
            rows.append([_fmt(float(r[mcol]), "currency" if symbol else
                              "number", symbol), ctx_val])
        s.table([f"Largest {mcol} records", "Context"], rows)
        s.p("Verify the largest records are genuine - a single mis-keyed "
            "amount can distort every total above.")


def _findings(doc, cards):
    if not cards:
        return
    s = doc.add("Statistical Findings & Risk Flags")
    s.p("Each finding below passed significance/noise gates before being "
        "reported (see appendix for thresholds).")
    sev_word = {"good": "OPPORTUNITY", "risk": "RISK", "warn": "WATCH",
                "info": "NOTE"}
    for c in cards:
        s.bullets([f"[{sev_word.get(c.severity, 'NOTE')}] {c.headline} - "
                   f"{c.so_what}"])


def _pinned_evidence(doc, ctx):
    """E1 — items the analyst pinned while exploring (cards, Q&A answers)."""
    if not ctx.pinned:
        return
    s = doc.add("Analyst's Selected Evidence")
    s.p("Findings and answers pinned by the analyst during this session.")
    for item in ctx.pinned[:12]:
        if item.get("type") == "qa":
            s.quote(f"Q: {item.get('q', '')}")
            if item.get("headers") and item.get("rows"):
                s.table(item["headers"], item["rows"][:8])
            elif item.get("answer"):
                s.p(item["answer"])
        elif item.get("type") == "card":
            s.bullets([f"{item.get('headline', '')} - "
                       f"{item.get('so_what', '')}"])


def _drivers(doc, df, preset, mapping):
    mcol = mapping.get(preset.primary_metric)
    if mcol is None or not pd.api.types.is_numeric_dtype(df.get(mcol,
                                                        pd.Series(dtype=float))):
        return
    results = []
    for fname, col in mapping.items():
        if col == mcol or col not in df.columns:
            continue
        s = df[col]
        if not pd.api.types.is_numeric_dtype(s):
            continue
        pair = pd.concat([df[mcol], s], axis=1).dropna()
        if len(pair) < 30:
            continue
        r, p = stats.pearsonr(pair.iloc[:, 0], pair.iloc[:, 1])
        if abs(r) >= 0.3 and p < 0.01:
            results.append((col, r, p))
    # B4: lagged relationships on period-aggregated series
    lag_findings = []
    dcol = next((mapping[f.name] for f in preset.fields
                 if f.role == "temporal" and f.name in mapping), None)
    if dcol is not None:
        dates = pd.to_datetime(df[dcol], errors="coerce")
        okd = dates.notna()
        if okd.sum() >= 24:
            grain = auto_grain(dates[okd])
            per = dates[okd].dt.to_period(grain)
            target = df[mcol][okd].groupby(per).sum().sort_index()
            gw = _GRAIN_WORD.get(grain, "period").rstrip("ly")
            for fname, col in mapping.items():
                if col == mcol or col not in df.columns \
                        or not pd.api.types.is_numeric_dtype(df[col]):
                    continue
                driver = df[col][okd].groupby(per).sum().sort_index()
                best = None
                for lag in range(1, 5):
                    joined = pd.concat([driver.shift(lag), target], axis=1,
                                       join="inner").dropna()
                    if len(joined) < 8:
                        continue
                    r, p = stats.pearsonr(joined.iloc[:, 0],
                                          joined.iloc[:, 1])
                    if abs(r) >= 0.5 and p < 0.05 \
                            and (best is None or abs(r) > abs(best[1])):
                        best = (lag, r, p)
                if best:
                    lag_findings.append(
                        f"{col} leads {mcol} by ~{best[0]} {gw}(s) "
                        f"(r={best[1]:+.2f}, p={best[2]:.3f}) - watch it as "
                        "an early indicator.")

    num_cols = [c for c in dict.fromkeys(mapping.values())
                if c in df.columns and pd.api.types.is_numeric_dtype(df[c])]
    if not results and not lag_findings and len(num_cols) < 3:
        doc.skip("Driver Associations",
                 "fewer than 3 numeric fields mapped and no significant "
                 "association with the primary metric")
        return
    s = doc.add("Driver Associations")
    s.p(f"Numeric fields that co-move with {mcol}. Association is not "
        "causation - treat these as hypotheses to test with a holdout.")
    if not results and not lag_findings:
        s.p("No numeric field showed a statistically significant "
            f"association with {mcol} (thresholds: |r| >= 0.3, p < 0.01) - "
            "a genuine finding in itself: the drivers of this metric are "
            "not in this file's numeric columns.")
    if results:
        s.table(["Field", "Correlation (r)", "p-value", "Read"],
                [[c, f"{r:+.2f}", f"{p:.4f}",
                  ("strong" if abs(r) >= 0.6 else "moderate") +
                  (" positive" if r > 0 else " negative")]
                 for c, r, p in sorted(results, key=lambda t: -abs(t[1]))])
    if lag_findings:
        s.p("Leading indicators (lagged co-movement):")
        s.bullets(lag_findings)
    if len(num_cols) >= 3:
        corr = df[num_cols].corr(numeric_only=True)
        s.img(rc.corr_heatmap(corr),
              "Correlation matrix of mapped numeric fields "
              "(+1 move together, -1 move opposite)", kind="correlation")


def _outlook(doc, df, preset, mapping, symbol, horizon_override=None):
    series, grain, label, _ = _period_series(df, preset, mapping)
    if series is not None and len(series) < 10 and grain in ("M", "Q"):
        # too few monthly points to model - refit at weekly grain, which a
        # real analyst would do rather than refusing to forecast
        dcol = next((mapping[f.name] for f in preset.fields
                     if f.role == "temporal" and f.name in mapping), None)
        mcol = mapping.get(preset.primary_metric)
        if dcol is not None:
            dts = pd.to_datetime(df[dcol], errors="coerce")
            okw = dts.notna()
            if okw.sum() >= 20:
                per = dts[okw].dt.to_period("W")
                metric = (df[mcol][okw] if mcol and
                          pd.api.types.is_numeric_dtype(
                              df.get(mcol, pd.Series(dtype=float)))
                          else pd.Series(1.0, index=dts[okw].index))
                weekly = metric.groupby(per).sum().sort_index()
                if len(weekly) >= 3 and is_partial_period(
                        weekly.index[-1], dts[okw].max(), "W"):
                    weekly = weekly.iloc[:-1]
                if len(weekly) >= 10:
                    series, grain = weekly, "W"
    if series is None or len(series) < 8:
        doc.skip("Outlook (Forecast)",
                 "needs at least 8 complete periods of history")
        return
    try:
        from ..forecast import run_forecast
        ts = pd.DataFrame({"ds": series.index.to_timestamp()
                           if hasattr(series.index, "to_timestamp")
                           else series.index,
                           "y": series.values.astype(float)})
        horizon = (int(horizon_override) if horizon_override
                   else int(min(8, max(3, len(ts) // 3))))
        res = run_forecast(ts, "ds", "y", horizon=horizon)
        fc = res.forecast

        # C2: honest holdout backtest — refit on truncated history, compare
        # the model's predictions against the periods we already know.
        backtest_df, holdout_mape = None, None
        h_bt = int(min(4, len(ts) // 4))
        if h_bt >= 2:
            try:
                res_bt = run_forecast(ts.iloc[:-h_bt], "ds", "y",
                                      horizon=h_bt)
                pred = res_bt.forecast["forecast"].values[:h_bt]
                actual = ts["y"].values[-h_bt:]
                backtest_df = pd.DataFrame({
                    "date": ts["ds"].values[-h_bt:], "pred": pred})
                nz = actual != 0
                if nz.any():
                    holdout_mape = float(
                        (abs(actual[nz] - pred[nz]) / abs(actual[nz])).mean()
                        * 100)
            except Exception as bt_exc:
                logger.debug(f"Backtest skipped: {bt_exc}")

        gw = _GRAIN_WORD.get(grain, "period")
        s = doc.add("Outlook (Forecast)")
        try:
            hist_df = res.historical.rename(columns=dict(zip(
                res.historical.columns[:2], ["date", "value"])))
            s.img(rc.forecast_chart(hist_df, fc, symbol,
                                    backtest=backtest_df),
                  f"{label} - history, {horizon}-period forecast with "
                  "confidence range"
                  + (" and holdout backtest (orange squares)"
                     if backtest_df is not None else ""), kind="forecast")
        except Exception:
            pass
        nxt = fc.iloc[0]
        s.kv([
            ("Model selected", res.model_name),
            (f"Next {gw.rstrip('ly')} estimate",
             f"{_fmt(nxt['forecast'], 'currency' if symbol else 'number', symbol)} "
             f"(range {_fmt(nxt.get('lower'), 'currency' if symbol else 'number', symbol)}"
             f" - {_fmt(nxt.get('upper'), 'currency' if symbol else 'number', symbol)})"),
            (f"Projected total, next {horizon} {gw} periods",
             _fmt(fc['forecast'].sum(), 'currency' if symbol else 'number', symbol)),
        ] + ([("Holdout backtest error",
               f"{holdout_mape:.1f}% average miss over the last {h_bt} "
               f"known {gw} periods")] if holdout_mape is not None else [])
          + ([("In-sample MAPE", f"{res.metrics['mape']:.1f}%")]
             if res.metrics.get("mape") is not None else []))
        s.p("Forecasts assume history repeats. If sections 4 or 7 flag a "
            "trend break or unresolved anomaly, widen your planning range "
            "accordingly.")
    except Exception as exc:
        logger.debug(f"Report forecast skipped: {exc}")


_ACTION_RULES = {
    "risk":  "Investigate within the week - drill the affected segment in "
             "section 6 and assign an owner.",
    "warn":  "Add to the monitoring list; re-check next period before acting.",
    "good":  "Identify what changed and codify it so the gain repeats.",
}


def _recommendations(doc, cards, preset):
    s = doc.add("Recommended Actions")
    recs = []
    for i, c in enumerate(cards, 1):
        if c.type == "dq_warning":
            recs.append(f"Fix data first: {c.headline}. Unreliable inputs "
                        "invalidate every downstream number.")
        elif c.severity in _ACTION_RULES:
            recs.append(f"{c.headline}: {_ACTION_RULES[c.severity]}")
    if not recs:
        recs.append("Performance is stable - use the time to set targets "
                    "so next period's report can judge pace against plan.")
    recs.append(f"Standing cadence: regenerate this report every period and "
                f"compare scorecards - a {preset.report_tone} works best as "
                "a rhythm, not a one-off.")
    s.bullets(recs[:8])


def _session_log(doc, ctx):
    if not (ctx.filters or ctx.qa_history or ctx.mapping_edited
            or ctx.ai_commentary):
        return
    s = doc.add("Analysis Session Log")
    s.p("Decisions and questions from this session - included so the report "
        "is reproducible and reviewable.")
    if ctx.filters:
        s.p("Active filters (the whole report reflects this view):")
        s.bullets(ctx.filters)
    if ctx.mapping_edited:
        s.bullets(["Field mapping was manually adjusted by the analyst "
                   "(final mapping in appendix)."])
    if ctx.qa_history:
        s.p("Questions asked of the data this session:")
        for qa in ctx.qa_history[-8:]:
            s.bullets([f"Q: {qa.get('q', '')} -> {qa.get('answer', 'see query')}"])
    if ctx.ai_commentary:
        s.p("AI analyst commentary generated during the session:")
        s.quote(ctx.ai_commentary[:1500])


def _appendix(doc, bundle, kpis, df=None):
    s = doc.add("Appendix - Definitions & Method")
    # "misses nothing" disclosure: analyses attempted but not applicable
    if doc.skips:
        s.p("Analyses attempted but not applicable to this dataset "
            "(nothing was silently skipped):")
        s.bullets([f"{name}: {reason}" for name, reason in doc.skips])
    s.p("Field mapping used (canonical field -> source column):")
    s.table(["Canonical field", "Source column"],
            [[k, v] for k, v in bundle.mapping.items()])
    if df is not None:
        unused = [c for c in df.columns if c not in bundle.mapping.values()]
        if unused:
            s.p(f"Columns present but not used in this analysis "
                f"({len(unused)}): " + ", ".join(str(c) for c in unused[:15])
                + ("…" if len(unused) > 15 else "")
                + ". Map them on the dashboard if they carry business meaning.")
    s.p("KPI definitions:")
    s.table(["KPI", "Definition"],
            [[k.label, k.description] for k in kpis])
    s.bullets([
        "Trend significance: least-squares slope, reported only with p < 0.05.",
        "Anomalies: deviation > 2.5 sigma from a rolling local median.",
        "Group comparisons suppressed below n = 8 observations.",
        "Correlations reported only at |r| >= 0.3 and p < 0.01; framed as "
        "association, not causation.",
        "Movement figures compare the latest complete period grain "
        "(auto-selected by data span) to the one before.",
        f"Data trust score {bundle.audit.score}/100 - see section 2 caveats.",
    ])


# ── public: build + render ────────────────────────────────────────────────────

def build_analyst_report(df: pd.DataFrame, bundle, kpis: List[KPIValue],
                         cards: List[InsightCard],
                         ctx: Optional[SessionContext] = None,
                         opts: Optional[ReportOptions] = None) -> ReportDoc:
    ctx = ctx or SessionContext()
    opts = opts or ReportOptions()
    preset: PresetSpec = bundle.preset
    symbol = bundle.currency_symbol
    series, grain, _, _ = _period_series(df, preset, bundle.mapping)
    grain_word = _GRAIN_WORD.get(grain or "M", "monthly")

    if opts.kpi_keys is not None:
        kpis = [k for k in kpis if k.key in opts.kpi_keys]

    subtitle = (f"{ctx.filename or 'Uploaded dataset'} | "
                f"{len(df):,} rows | generated "
                f"{datetime.now():%d %b %Y %H:%M} | "
                f"trust {bundle.audit.score}/100")
    if opts.company:
        subtitle = f"Prepared for {opts.company} | " + subtitle
    if opts.prepared_by:
        subtitle += f" | by {opts.prepared_by}"

    doc = ReportDoc(
        title=opts.title or f"{preset.icon} {preset.label} - Analyst Report",
        subtitle=subtitle,
        no_exhibits=not opts.include_exhibits,
        allowed_charts=set(opts.chart_kinds)
        if opts.chart_kinds is not None else None,
    )
    if opts.want("exec"):
        _exec_summary(doc, kpis, cards, preset, symbol, grain_word,
                      headline_override=opts.headline)
    if opts.analyst_notes.strip() and opts.want("notes"):
        s = doc.add("Analyst's Notes")
        for para in opts.analyst_notes.strip().split("\n"):
            if para.strip():
                s.p(para.strip())
    if opts.want("methodology"):
        _methodology(doc, df, bundle, ctx)
    if opts.want("scorecard"):
        _scorecard(doc, kpis, symbol, grain_word)
    if opts.want("trend"):
        _trend(doc, df, preset, bundle.mapping, symbol, cards)
    if opts.want("bridge"):
        _bridge(doc, df, preset, bundle.mapping, symbol)
    if opts.want("volume_rate"):
        _volume_rate(doc, df, preset, bundle.mapping, symbol)
    if opts.want("pace"):
        _pace(doc, df, preset, bundle.mapping, symbol)
    if opts.want("yoy"):
        _yoy(doc, df, preset, bundle.mapping, symbol,
             fiscal_start=opts.fiscal_start_month)
    if opts.want("seasonality"):
        _seasonality(doc, df, preset, bundle.mapping, symbol)
    if opts.want("segments"):
        _segments(doc, df, preset, bundle.mapping, symbol,
                  segment_fields=opts.segment_fields, top_n=opts.top_n)
    if opts.want("cohorts"):
        _cohorts(doc, df, preset, bundle.mapping, symbol)
    if opts.want("distribution"):
        _distribution(doc, df, preset, bundle.mapping, symbol)
    if opts.want("findings"):
        _findings(doc, cards)
    if opts.want("evidence"):
        _pinned_evidence(doc, ctx)
    if opts.want("drivers"):
        _drivers(doc, df, preset, bundle.mapping)
    if opts.want("outlook") and opts.forecast_horizon != 0:
        _outlook(doc, df, preset, bundle.mapping, symbol,
                 horizon_override=opts.forecast_horizon)
    if opts.want("recommendations"):
        _recommendations(doc, cards, preset)
    if opts.want("session"):
        _session_log(doc, ctx)
    if opts.want("appendix"):
        _appendix(doc, bundle, kpis, df)
    logger.info(f"Analyst report built: {len(doc.sections)} sections, "
                f"{doc._exhibits} exhibits.")
    return doc


# ── edit-before-download: parse edited markdown back into a ReportDoc ─────────

def markdown_to_doc(md: str, exhibit_bank: Optional[Dict[int, tuple]] = None,
                    ) -> ReportDoc:
    """
    Parse the report's own markdown dialect (as produced by render_markdown
    with embed_images=False) back into a ReportDoc so an edited text still
    renders as a full PDF. Exhibit placeholders like
    "*[Exhibit 3 - caption - see PDF for the chart]*" re-attach the stored
    chart from `exhibit_bank`; deleting the placeholder drops the chart.
    """
    import re as _re
    bank = exhibit_bank or {}
    lines = md.splitlines()
    doc = ReportDoc(title="Analyst Report", subtitle="")
    cur: Optional[Section] = None
    table_buf: List[str] = []

    def flush_table():
        nonlocal table_buf
        if cur is not None and len(table_buf) >= 2:
            headers = [c.strip() for c in table_buf[0].strip("|").split("|")]
            rows = [[c.strip() for c in r.strip("|").split("|")]
                    for r in table_buf[2:]]
            cur.table(headers, rows)
        table_buf = []

    for raw in lines:
        line = raw.rstrip()
        if line.startswith("|"):
            table_buf.append(line)
            continue
        flush_table()
        if not line.strip():
            continue
        if line.startswith("# ") and doc.title == "Analyst Report":
            doc.title = line[2:].strip()
        elif line.startswith("## "):
            cur = Section(line[3:].strip(), _doc=doc)
            doc.sections.append(cur)
        elif doc.subtitle == "" and not doc.sections \
                and line.startswith("*") and line.endswith("*") \
                and "Exhibit" not in line:
            doc.subtitle = line.strip("*").strip()
        elif line.startswith("**Contents:**"):
            continue
        elif cur is None:
            continue
        elif line.startswith("> "):
            cur.quote(line[2:].replace("**", "").strip())
        elif _re.match(r"^\*\[?Exhibit (\d+)", line):
            m = _re.match(r"^\*\[?Exhibit (\d+)", line)
            n = int(m.group(1))
            if n in bank:
                cur.blocks.append(("img", bank[n][0], bank[n][1]))
        elif _re.match(r"^- \*\*(.+?):\*\* ", line):
            m = _re.match(r"^- \*\*(.+?):\*\* (.*)$", line)
            if cur.blocks and cur.blocks[-1][0] == "kv":
                cur.blocks[-1][1].append((m.group(1), m.group(2)))
            else:
                cur.kv([(m.group(1), m.group(2))])
        elif line.startswith("- "):
            if cur.blocks and cur.blocks[-1][0] == "bullets":
                cur.blocks[-1][1].append(line[2:].strip())
            else:
                cur.bullets([line[2:].strip()])
        else:
            cur.p(line.replace("**", "").strip())
    flush_table()
    return doc


def render_markdown(doc: ReportDoc, embed_images: bool = True) -> str:
    """Markdown render. embed_images=True inlines exhibits as base64 PNG
    (renders in VS Code/GitHub); False leaves a text placeholder (for the
    in-app preview, where the same charts are already on screen)."""
    import base64
    out = [f"# {doc.title}", f"*{doc.subtitle}*", "", "**Contents:** "
           + " · ".join(s.title for s in doc.sections), ""]
    for sec in doc.sections:
        out.append(f"## {sec.title}")
        for b in sec.blocks:
            if b[0] == "p":
                out += [b[1], ""]
            elif b[0] == "quote":
                out += [f"> **{b[1]}**", ""]
            elif b[0] == "bullets":
                out += [f"- {i}" for i in b[1]] + [""]
            elif b[0] == "kv":
                out += [f"- **{k}:** {v}" for k, v in b[1]] + [""]
            elif b[0] == "img":
                _, png, caption = b
                if embed_images:
                    b64 = base64.b64encode(png).decode()
                    out += [f"![{caption}](data:image/png;base64,{b64})",
                            f"*{caption}*", ""]
                else:
                    out += [f"*[{caption} - see PDF for the chart]*", ""]
            elif b[0] == "table":
                _, headers, rows = b
                out.append("| " + " | ".join(headers) + " |")
                out.append("|" + "---|" * len(headers))
                out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
                out.append("")
    return "\n".join(out)


def _latin(text: str) -> str:
    """fpdf core fonts are latin-1; transliterate what we can."""
    repl = {"₹": "Rs ", "—": "-", "–": "-", "→": "->", "×": "x", "σ": "sigma",
            "Δ": "chg ", "≥": ">=", "≤": "<=", "’": "'", "‘": "'",
            "“": '"', "”": '"', "•": "-", "…": "..."}
    for a, b in repl.items():
        text = str(text).replace(a, b)
    # strip preset icons/emoji
    return text.encode("latin-1", "ignore").decode("latin-1")


def render_pdf(doc: ReportDoc) -> bytes:
    import io as _io

    from fpdf import FPDF

    class _PDF(FPDF):
        def footer(self):
            self.set_y(-12)
            self.set_font("Helvetica", "I", 7.5)
            self.set_text_color(150, 150, 150)
            self.cell(0, 5, f"Page {self.page_no()}/{{nb}}  |  Sapienoids "
                            "Analytics - computed, traceable, reproducible",
                      align="C")

    pdf = _PDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.set_margins(15, 15, 15)

    # A7: real unicode (₹, σ, Δ) via matplotlib's bundled DejaVu TTFs;
    # falls back to Helvetica + transliteration if unavailable.
    font_family, T = "Helvetica", _latin
    try:
        import os as _os

        import matplotlib as _mpl
        ttf_dir = _os.path.join(_mpl.get_data_path(), "fonts", "ttf")
        reg = _os.path.join(ttf_dir, "DejaVuSans.ttf")
        bold = _os.path.join(ttf_dir, "DejaVuSans-Bold.ttf")
        italic = _os.path.join(ttf_dir, "DejaVuSans-Oblique.ttf")
        if all(map(_os.path.exists, (reg, bold, italic))):
            pdf.add_font("DejaVu", "", reg)
            pdf.add_font("DejaVu", "B", bold)
            pdf.add_font("DejaVu", "I", italic)
            font_family = "DejaVu"

            def T(s):
                # DejaVu covers ₹/σ/Δ but not emoji — strip pictographs
                return "".join(
                    ch for ch in str(s).replace("—", "-")
                    if not (0x1F000 <= ord(ch) <= 0x1FAFF
                            or 0x2600 <= ord(ch) <= 0x27BF
                            or ord(ch) in (0xFE0F, 0x200D))
                ).strip()
    except Exception as exc:
        logger.debug(f"Unicode font unavailable, using Helvetica: {exc}")

    real_set_font = pdf.set_font

    def set_font(_family, style="", size=10):
        real_set_font(font_family, style, size)

    pdf.set_font = set_font  # every existing call routes to the loaded family
    S = T  # sanitizer: identity with DejaVu, transliteration with Helvetica

    pdf.add_page()
    epw = pdf.w - 30  # effective page width

    def mc(h, text, align="L"):
        # fpdf 2.8 leaves x at the right edge after multi_cell — reset first
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, h, text, align=align,
                       new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(30, 30, 60)
    mc(9, S(doc.title), align="C")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(110, 110, 110)
    mc(5, S(doc.subtitle), align="C")
    pdf.ln(3)
    pdf.set_draw_color(190, 190, 190)
    pdf.line(15, pdf.get_y(), pdf.w - 15, pdf.get_y())
    pdf.ln(4)

    # table of contents
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(50, 50, 130)
    mc(6, "Contents")
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(90, 90, 90)
    for sec in doc.sections:
        mc(4.6, S(f"  {sec.title}"))
    pdf.ln(3)
    pdf.line(15, pdf.get_y(), pdf.w - 15, pdf.get_y())
    pdf.ln(4)

    for sec in doc.sections:
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(50, 50, 130)
        mc(8, S(sec.title))
        pdf.ln(1)
        for b in sec.blocks:
            if b[0] == "p":
                pdf.set_font("Helvetica", "", 9.5)
                pdf.set_text_color(45, 45, 45)
                mc(5, S(b[1]))
                pdf.ln(1)
            elif b[0] == "quote":
                pdf.set_font("Helvetica", "B", 10)
                pdf.set_text_color(30, 60, 120)
                mc(5.5, S(b[1]))
                pdf.ln(1.5)
            elif b[0] == "bullets":
                pdf.set_font("Helvetica", "", 9.5)
                pdf.set_text_color(45, 45, 45)
                for item in b[1]:
                    mc(5, S(f"  - {item}"))
                pdf.ln(1)
            elif b[0] == "kv":
                for k, v in b[1]:
                    pdf.set_font("Helvetica", "B", 9.5)
                    pdf.set_text_color(45, 45, 45)
                    mc(5, S(f"{k}:  ") + S(str(v)))
                pdf.ln(1)
            elif b[0] == "img":
                _, png, caption = b
                try:
                    from PIL import Image
                    with Image.open(_io.BytesIO(png)) as im:
                        iw, ih = im.size
                    disp_h = epw * ih / iw
                    if pdf.get_y() + disp_h > pdf.h - 22:
                        pdf.add_page()
                    pdf.image(_io.BytesIO(png), x=pdf.l_margin,
                              w=epw)
                    pdf.set_font("Helvetica", "I", 8)
                    pdf.set_text_color(110, 110, 110)
                    mc(4.5, S(caption), align="C")
                    pdf.ln(2)
                except Exception as exc:
                    logger.debug(f"PDF exhibit embed failed: {exc}")
            elif b[0] == "table":
                _, headers, rows = b
                n = len(headers)
                w = [epw / n] * n
                pdf.set_font("Helvetica", "B", 8.5)
                pdf.set_fill_color(235, 236, 245)
                pdf.set_text_color(40, 40, 80)
                for h, wi in zip(headers, w):
                    pdf.cell(wi, 6, S(str(h))[:int(wi / 1.7)], border=1,
                             fill=True)
                pdf.ln()
                pdf.set_font("Helvetica", "", 8.5)
                pdf.set_text_color(45, 45, 45)
                for row in rows:
                    if pdf.get_y() > pdf.h - 25:
                        pdf.add_page()
                    for c, wi in zip(row, w):
                        pdf.cell(wi, 6, S(str(c))[:int(wi / 1.7)], border=1)
                    pdf.ln()
                pdf.ln(2)
        pdf.ln(2)

    out = pdf.output()
    return bytes(out)
