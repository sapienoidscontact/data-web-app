"""
Dashboard Renderer — turns preset ChartSpecs into Plotly figures, applying the
global visual system (docs/VISUAL_PRESETS.md §A):

  - auto time grain by span; bars zero-based, sorted, top-N + "Others"
  - horizontal bars when labels are long; donut only when ≤ 6 categories
  - compact number formatting incl. Indian lakh/crore when ₹ detected
  - single accent hue for magnitude; categorical palette capped

Pure pandas/plotly — no Streamlit imports, so it is fully testable headless.
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from ..presets.kpis import auto_grain
from ..presets.model import ChartSpec, PresetSpec

ACCENT = "#6366F1"
PALETTE = ["#6366F1", "#22B8A6", "#F59E0B", "#EC4899", "#3B82F6",
           "#84CC16", "#A855F7", "#64748B"]
TEMPLATE = "seaborn"


# ── formatting ────────────────────────────────────────────────────────────────

def fmt_value(v: Optional[float], fmt: str = "number", symbol: str = "") -> str:
    """Compact display formatting; Indian lakh/crore grouping when ₹."""
    if v is None:
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    if fmt == "percent":
        return f"{v:,.1f}%"
    if fmt == "ratio":
        return f"{v:,.2f}×"
    if fmt in ("days", "months", "years"):
        unit = fmt if abs(v) != 1 else fmt[:-1]
        return f"{v:,.1f} {unit}"
    prefix = symbol if fmt == "currency" else ""
    a = abs(v)
    if symbol == "₹" and fmt == "currency":
        if a >= 1e7:
            return f"{prefix}{v / 1e7:,.2f} Cr"
        if a >= 1e5:
            return f"{prefix}{v / 1e5:,.2f} L"
    else:
        if a >= 1e9:
            return f"{prefix}{v / 1e9:,.2f}B"
        if a >= 1e6:
            return f"{prefix}{v / 1e6:,.2f}M"
        if a >= 1e4:
            return f"{prefix}{v / 1e3:,.1f}K"
    if fmt == "integer" or (a >= 100 and float(v).is_integer()):
        return f"{prefix}{v:,.0f}"
    return f"{prefix}{v:,.2f}"


# ── internals ─────────────────────────────────────────────────────────────────

def _resolve(df: pd.DataFrame, mapping: Dict[str, str], fname: Optional[str]):
    if not fname:
        return None
    col = mapping.get(fname)
    return col if col in df.columns else None


def _agg_series(df, ycol, agg):
    if ycol is None or agg == "count":
        return pd.Series(1, index=df.index), "count"
    return df[ycol], agg


def _by_period(df, xcol, ycol, agg):
    dates = pd.to_datetime(df[xcol], errors="coerce")
    ok = dates.notna()
    if ok.sum() < 2:
        return None, None
    grain = auto_grain(dates[ok])
    periods = dates[ok].dt.to_period(grain).dt.to_timestamp()
    s, agg = _agg_series(df[ok], ycol, agg)
    out = s.groupby(periods).agg("sum" if agg == "count" else agg)
    return out.sort_index(), grain


def _grouped(df, xcol, ycol, agg, top_n, absolute=False):
    s, agg = _agg_series(df, ycol, agg)
    if absolute:
        s = s.abs()
    g = s.groupby(df[xcol].astype(str)).agg("sum" if agg == "count" else agg)
    g = g.sort_values(ascending=False)
    if len(g) > top_n:
        others = g.iloc[top_n:].sum()
        g = g.head(top_n)
        if agg in ("sum", "count") and others:
            g["Others"] = others
    return g


def _base_layout(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(
        title=title, template=TEMPLATE, margin=dict(l=10, r=10, t=48, b=10),
        height=380, colorway=PALETTE,
    )
    return fig


# ── public: build one chart ───────────────────────────────────────────────────

def build_chart(spec: ChartSpec, df: pd.DataFrame, mapping: Dict[str, str],
                preset: Optional[PresetSpec] = None) -> Optional[go.Figure]:
    """Render a ChartSpec; returns None when required fields are unmapped/empty."""
    try:
        x = _resolve(df, mapping, spec.x)
        y = _resolve(df, mapping, spec.y)
        color = _resolve(df, mapping, spec.color)
        if df.empty:
            return None

        if spec.kind == "line":
            if x is None:
                return None
            series, grain = _by_period(df, x, y, spec.agg)
            if series is None or len(series) < 2:
                return None
            fig = go.Figure(go.Scatter(
                x=series.index, y=series.values, mode="lines+markers"
                if len(series) < 30 else "lines", line=dict(color=ACCENT, width=2.5)))
            # moving average when noisy
            if len(series) >= 10:
                deltas = series.pct_change().dropna()
                if len(deltas) and deltas.std() > 0.4:
                    ma = series.rolling(7, min_periods=3).mean()
                    fig.add_scatter(x=ma.index, y=ma.values, mode="lines",
                                    name="trend", line=dict(dash="dash",
                                                            color="#94A3B8"))
            return _base_layout(fig, spec.title)

        if spec.kind == "bar":
            if x is None:
                return None
            g = _grouped(df, x, y, spec.agg, spec.top_n,
                         absolute=spec.options.get("absolute", False))
            if g.empty:
                return None
            long_labels = pd.Series(g.index.astype(str)).str.len().mean() > 12
            if long_labels:
                g = g.iloc[::-1]
                fig = go.Figure(go.Bar(x=g.values, y=g.index.astype(str),
                                       orientation="h", marker_color=ACCENT))
            else:
                fig = go.Figure(go.Bar(x=g.index.astype(str), y=g.values,
                                       marker_color=ACCENT))
            return _base_layout(fig, spec.title)

        if spec.kind == "donut":
            if x is None:
                return None
            g = _grouped(df, x, y, spec.agg, 6)
            if g.empty:
                return None
            if len(g) > 6:  # too many slices → bar
                return build_chart(ChartSpec("bar", spec.title, x=spec.x, y=spec.y,
                                             agg=spec.agg), df, mapping, preset)
            fig = go.Figure(go.Pie(labels=g.index.astype(str), values=g.values,
                                   hole=0.5))
            return _base_layout(fig, spec.title)

        if spec.kind == "stacked_bar":
            if x is None or color is None:
                return None
            work = df[[c for c in {x, y, color} if c]].copy()
            if pd.api.types.is_datetime64_any_dtype(work[x]):
                grain = auto_grain(work[x])
                work[x] = pd.to_datetime(work[x], errors="coerce") \
                    .dt.to_period(grain).dt.to_timestamp()
            s, agg = _agg_series(work, y, spec.agg)
            work["_v"] = s
            top_colors = work.groupby(color)["_v"].sum().abs() \
                             .sort_values(ascending=False).head(8).index
            work.loc[~work[color].isin(top_colors), color] = "Others"
            pivot = work.groupby([x, color])["_v"] \
                        .agg("sum" if agg == "count" else agg).reset_index()
            fig = px.bar(pivot, x=x, y="_v", color=color, title=spec.title,
                         template=TEMPLATE, color_discrete_sequence=PALETTE)
            fig.update_layout(margin=dict(l=10, r=10, t=48, b=10), height=380,
                              yaxis_title=y or "count")
            return fig

        if spec.kind == "box":
            if x is None or y is None:
                return None
            counts = df.groupby(df[x].astype(str))[y].count()
            keep = counts[counts >= 8].sort_values(ascending=False).head(12).index
            sub = df[df[x].astype(str).isin(keep)]
            if sub.empty:
                return None
            fig = px.box(sub, x=x, y=y, title=spec.title, template=TEMPLATE,
                         points="outliers", color_discrete_sequence=[ACCENT])
            fig.update_layout(margin=dict(l=10, r=10, t=48, b=10), height=380)
            return fig

        if spec.kind == "scatter":
            if x is None or y is None:
                return None
            work = df
            gb = spec.options.get("group_by")
            gcol = _resolve(df, mapping, gb) if gb else None
            if gcol:
                aggd = {x: "sum", y: "sum"}
                work = df.groupby(gcol, as_index=False).agg(aggd)
            if not (pd.api.types.is_numeric_dtype(work[x])
                    and pd.api.types.is_numeric_dtype(work[y])):
                return None
            sample = work.sample(min(len(work), 3000), random_state=1)
            fig = px.scatter(sample, x=x, y=y,
                             color=color if color in sample.columns else None,
                             title=spec.title, template=TEMPLATE,
                             color_discrete_sequence=PALETTE)
            fig.update_layout(margin=dict(l=10, r=10, t=48, b=10), height=380)
            return fig

        if spec.kind == "hist":
            if x is None or not pd.api.types.is_numeric_dtype(df[x]):
                return None
            fig = px.histogram(df, x=x, title=spec.title, template=TEMPLATE,
                               marginal="box", color_discrete_sequence=[ACCENT])
            fig.update_layout(margin=dict(l=10, r=10, t=48, b=10), height=380)
            return fig

        if spec.kind == "heat_dow":
            if x is None:
                return None
            dates = pd.to_datetime(df[x], errors="coerce")
            ok = dates.notna()
            if ok.sum() < 14:
                return None
            s, _ = _agg_series(df[ok], y, spec.agg)
            dows = dates[ok].dt.dayofweek
            names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            if dates[ok].dt.hour.nunique() > 3:
                hours = dates[ok].dt.hour
                pivot = s.groupby([dows, hours]).sum().unstack(fill_value=0)
                fig = px.imshow(pivot.values, x=[str(h) for h in pivot.columns],
                                y=[names[i] for i in pivot.index],
                                color_continuous_scale="Purples",
                                title=spec.title, aspect="auto")
            else:
                agg = s.groupby(dows).sum()
                fig = go.Figure(go.Bar(x=[names[i] for i in agg.index],
                                       y=agg.values, marker_color=ACCENT))
                fig = _base_layout(fig, spec.title)
                return fig
            fig.update_layout(margin=dict(l=10, r=10, t=48, b=10), height=380)
            return fig

        if spec.kind == "funnel":
            if x is None:
                return None
            s, agg = _agg_series(df, y, spec.agg)
            g = s.groupby(df[x].astype(str)).agg("sum" if agg == "count" else agg)
            g = g.sort_values(ascending=False).head(8)
            if g.empty:
                return None
            fig = go.Figure(go.Funnel(y=g.index.astype(str), x=g.values,
                                      marker=dict(color=PALETTE)))
            return _base_layout(fig, spec.title)

    except Exception:
        return None
    return None


def build_dashboard_charts(preset: PresetSpec, df: pd.DataFrame,
                           mapping: Dict[str, str]) -> list:
    """All renderable charts for a preset, in declared order."""
    figs = []
    for spec in preset.charts:
        fig = build_chart(spec, df, mapping, preset)
        if fig is not None:
            figs.append((spec, fig))
    return figs
