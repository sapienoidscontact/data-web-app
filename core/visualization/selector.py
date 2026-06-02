"""
Visualization Selector — recommends the best Plotly chart for any column combination.

Decision rules (in priority order):
  time + numeric           → line chart (time series)
  two numerics             → scatter (+ optional trendline if correlated)
  numeric + categorical    → box plot  (if categorical has ≤ 8 values)
                           → bar chart (if categorical has ≤ 20 values)
  single numeric           → histogram
  single categorical ≤ 8  → pie
  single categorical > 8  → bar
  three+ numerics          → scatter matrix
  all columns              → heatmap (correlation matrix)

Output is a list of ChartRecommendation objects that D1.py renders directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace as dc_replace
from typing import Dict, List, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from ..schema.detector import SchemaProfile


@dataclass
class ChartRecommendation:
    """A single chart recommendation with enough context to render it."""
    chart_type: str             # 'line', 'scatter', 'bar', 'histogram', 'box', 'pie', 'heatmap'
    title: str
    x_col: Optional[str]
    y_col: Optional[str]
    color_col: Optional[str]   = None
    reasoning: str              = ""
    priority: int               = 0   # lower = more important


def recommend_charts(
    df: pd.DataFrame,
    schema: SchemaProfile,
    max_recommendations: int = 5,
) -> List[ChartRecommendation]:
    """
    Analyse the schema and return up to max_recommendations chart suggestions.

    Args:
        df:                  The pandas DataFrame to visualise.
        schema:              SchemaProfile from detect_schema().
        max_recommendations: Maximum number of suggestions to return.

    Returns:
        List of ChartRecommendation, sorted by priority (ascending).
    """
    recs: List[ChartRecommendation] = []
    num  = schema.numeric_cols
    cats = schema.categorical_cols
    time = schema.temporal_cols

    # Rule 1: time + first numeric → line chart
    if time and num:
        recs.append(ChartRecommendation(
            chart_type="line",
            title=f"{num[0]} over {time[0]}",
            x_col=time[0],
            y_col=num[0],
            reasoning="Time column detected — line chart shows trends clearly.",
            priority=0,
        ))

    # Rule 2: two or more numerics → scatter
    if len(num) >= 2:
        color = cats[0] if cats else None
        recs.append(ChartRecommendation(
            chart_type="scatter",
            title=f"{num[0]} vs {num[1]}",
            x_col=num[0],
            y_col=num[1],
            color_col=color,
            reasoning="Two numeric columns — scatter reveals correlation.",
            priority=1,
        ))

    # Rule 3: numeric + categorical → box or bar
    if num and cats:
        cat_cardinality = schema.columns[cats[0]].cardinality
        if cat_cardinality <= 8:
            recs.append(ChartRecommendation(
                chart_type="box",
                title=f"{num[0]} distribution by {cats[0]}",
                x_col=cats[0],
                y_col=num[0],
                reasoning=f"{cats[0]} has {cat_cardinality} categories — box plot shows distribution per group.",
                priority=2,
            ))
        else:
            # Aggregate and show bar
            recs.append(ChartRecommendation(
                chart_type="bar",
                title=f"{num[0]} by {cats[0]}",
                x_col=cats[0],
                y_col=num[0],
                reasoning=f"Bar chart aggregates {num[0]} across {cats[0]} groups.",
                priority=2,
            ))

    # Rule 4: single numeric → histogram
    if num:
        recs.append(ChartRecommendation(
            chart_type="histogram",
            title=f"Distribution of {num[0]}",
            x_col=num[0],
            y_col=None,
            reasoning=f"Histogram reveals the distribution shape of {num[0]}.",
            priority=3,
        ))

    # Rule 5: single categorical → pie or bar
    if cats:
        cat_cardinality = schema.columns[cats[0]].cardinality
        if cat_cardinality <= 8:
            recs.append(ChartRecommendation(
                chart_type="pie",
                title=f"Breakdown of {cats[0]}",
                x_col=cats[0],
                y_col=None,
                reasoning=f"{cats[0]} has {cat_cardinality} categories — pie chart shows proportions.",
                priority=4,
            ))
        else:
            vc = df[cats[0]].value_counts().reset_index()
            vc.columns = [cats[0], "count"]
            recs.append(ChartRecommendation(
                chart_type="bar",
                title=f"Value counts of {cats[0]}",
                x_col=cats[0],
                y_col="count",
                reasoning=f"Bar chart of value frequencies for {cats[0]}.",
                priority=4,
            ))

    return sorted(recs, key=lambda r: r.priority)[:max_recommendations]


def render_recommendation(
    rec: ChartRecommendation,
    df: pd.DataFrame,
) -> go.Figure:
    """
    Convert a ChartRecommendation into a Plotly figure ready to display.

    Args:
        rec: A ChartRecommendation from recommend_charts().
        df:  The DataFrame to plot.

    Returns:
        A Plotly Figure object.
    """
    try:
        if rec.chart_type == "line":
            ts = df[[rec.x_col, rec.y_col]].copy()
            ts[rec.x_col] = pd.to_datetime(ts[rec.x_col], errors="coerce")
            ts = ts.dropna().sort_values(rec.x_col)
            return px.line(ts, x=rec.x_col, y=rec.y_col,
                           title=rec.title, template="seaborn", markers=True)

        if rec.chart_type == "scatter":
            return px.scatter(df, x=rec.x_col, y=rec.y_col, color=rec.color_col,
                              title=rec.title, template="seaborn", trendline="ols",
                              trendline_options={"log_x": False})

        if rec.chart_type == "box":
            return px.box(df, x=rec.x_col, y=rec.y_col,
                          title=rec.title, template="seaborn", points="outliers")

        if rec.chart_type == "bar":
            if rec.y_col and rec.y_col in df.columns:
                agg = df.groupby(rec.x_col)[rec.y_col].sum().reset_index()
            else:
                agg = df[rec.x_col].value_counts().reset_index()
                agg.columns = [rec.x_col, "count"]
                rec = dc_replace(rec, y_col="count")
            return px.bar(agg, x=rec.x_col, y=rec.y_col,
                          title=rec.title, template="seaborn")

        if rec.chart_type == "histogram":
            return px.histogram(df, x=rec.x_col, marginal="box",
                                title=rec.title, template="seaborn")

        if rec.chart_type == "pie":
            vc = df[rec.x_col].value_counts().reset_index()
            vc.columns = [rec.x_col, "count"]
            return px.pie(vc, names=rec.x_col, values="count", title=rec.title)

        if rec.chart_type == "heatmap":
            num_df = df.select_dtypes("number")
            return px.imshow(num_df.corr(), text_auto=".2f",
                             color_continuous_scale="RdBu_r", title=rec.title)

    except Exception:
        pass  # return empty figure on any render error

    return go.Figure().update_layout(title=f"Could not render: {rec.title}")
