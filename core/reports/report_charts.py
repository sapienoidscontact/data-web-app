"""
Report Exhibits — matplotlib chart renderer for the analyst report.

Produces PNG bytes (no browser/kaleido dependency) styled to match the app's
visual system: single accent hue, light grid, compact axis formatting
(₹ lakh/crore aware), anomaly markers, confidence bands.

All functions return PNG bytes or None on failure — the report degrades
gracefully to text when a chart cannot be drawn.
"""

from __future__ import annotations

import io
from typing import Dict, List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import numpy as np
import pandas as pd
from loguru import logger

ACCENT = "#6366F1"
GOOD = "#22C55E"
BAD = "#EF4444"
MUTED = "#94A3B8"
FILL = "#C7CAF9"

_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _compact(v, symbol=""):
    a = abs(v)
    if symbol == "₹":
        if a >= 1e7:
            return f"{v / 1e7:.1f}Cr"
        if a >= 1e5:
            return f"{v / 1e5:.1f}L"
    if a >= 1e9:
        return f"{v / 1e9:.1f}B"
    if a >= 1e6:
        return f"{v / 1e6:.1f}M"
    if a >= 1e3:
        return f"{v / 1e3:.0f}K"
    return f"{v:.0f}" if a >= 10 else f"{v:.1f}"


def _axis_fmt(symbol=""):
    return FuncFormatter(lambda v, _: _compact(v, symbol))


def _new_fig(w=7.4, h=3.1):
    fig, ax = plt.subplots(figsize=(w, h), dpi=150)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#CBD5E1")
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.tick_params(colors="#475569", labelsize=8)
    return fig, ax


def _png(fig) -> Optional[bytes]:
    try:
        buf = io.BytesIO()
        fig.tight_layout(pad=0.6)
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()
    except Exception as exc:
        logger.debug(f"exhibit render failed: {exc}")
        plt.close(fig)
        return None


def _period_x(series: pd.Series):
    idx = series.index
    try:
        return idx.to_timestamp()
    except (AttributeError, TypeError):
        return np.arange(len(series))


# ── exhibits ──────────────────────────────────────────────────────────────────

def trend_chart(series: pd.Series, label: str, symbol: str = "",
                anomalies: Optional[List] = None) -> Optional[bytes]:
    """Primary-metric trend with rolling average, best/worst and anomaly flags."""
    try:
        fig, ax = _new_fig()
        x = _period_x(series)
        y = series.values.astype(float)
        ax.plot(x, y, color=ACCENT, linewidth=2, marker="o" if len(y) < 35
                else None, markersize=3.5, label=label)
        if len(y) >= 8:
            roll = pd.Series(y).rolling(4, min_periods=2).mean()
            ax.plot(x, roll, color=MUTED, linewidth=1.4, linestyle="--",
                    label="4-period average")
        # best / worst
        bi, wi = int(np.argmax(y)), int(np.argmin(y))
        ax.annotate(f"peak {_compact(y[bi], symbol)}", (x[bi], y[bi]),
                    textcoords="offset points", xytext=(0, 8), fontsize=7.5,
                    color="#334155", ha="center")
        ax.annotate(f"low {_compact(y[wi], symbol)}", (x[wi], y[wi]),
                    textcoords="offset points", xytext=(0, -12), fontsize=7.5,
                    color="#334155", ha="center")
        # anomaly markers
        for a in (anomalies or []):
            if a in series.index:
                pos = list(series.index).index(a)
                ax.scatter([x[pos]], [y[pos]], s=90, facecolors="none",
                           edgecolors=BAD, linewidths=2, zorder=5)
        ax.yaxis.set_major_formatter(_axis_fmt(symbol))
        ax.legend(fontsize=7.5, frameon=False, loc="upper left")
        fig.autofmt_xdate(rotation=0, ha="center")
        return _png(fig)
    except Exception as exc:
        logger.debug(f"trend_chart failed: {exc}")
        return None


def seasonality_chart(share_by_dow: pd.Series) -> Optional[bytes]:
    """Weekday share bars with the peak highlighted."""
    try:
        fig, ax = _new_fig(7.4, 2.5)
        idx = share_by_dow.index.astype(int)
        labels = [_DOW[i] for i in idx]
        colors = [ACCENT if v == share_by_dow.max() else FILL
                  for v in share_by_dow.values]
        ax.bar(labels, share_by_dow.values, color=colors)
        for i, v in enumerate(share_by_dow.values):
            ax.text(i, v, f"{v:.1f}%", ha="center", va="bottom", fontsize=7.5,
                    color="#334155")
        ax.set_ylabel("share of value", fontsize=8, color="#475569")
        return _png(fig)
    except Exception as exc:
        logger.debug(f"seasonality_chart failed: {exc}")
        return None


def segment_bar(g: pd.Series, symbol: str = "",
                moves: Optional[Dict[str, float]] = None) -> Optional[bytes]:
    """Horizontal top-N bars; labels show value + share; color by last move."""
    try:
        g = g.head(8).iloc[::-1]
        total = g.sum()
        fig, ax = _new_fig(7.4, 0.45 * len(g) + 1.0)
        colors = []
        for name in g.index:
            mv = (moves or {}).get(str(name))
            colors.append(GOOD if mv is not None and mv > 5
                          else BAD if mv is not None and mv < -5 else ACCENT)
        ax.barh([str(i)[:26] for i in g.index], g.values, color=colors)
        for i, (name, v) in enumerate(g.items()):
            mv = (moves or {}).get(str(name))
            tag = f"  {_compact(v, symbol)} ({v / total * 100:.0f}%)"
            if mv is not None:
                tag += f"  {mv:+.0f}%"
            ax.text(v, i, tag, va="center", fontsize=7.5, color="#334155")
        ax.xaxis.set_major_formatter(_axis_fmt(symbol))
        ax.grid(axis="y", linewidth=0)
        ax.grid(axis="x", color="#E2E8F0", linewidth=0.7)
        ax.margins(x=0.18)
        return _png(fig)
    except Exception as exc:
        logger.debug(f"segment_bar failed: {exc}")
        return None


def pareto_chart(g: pd.Series, symbol: str = "") -> Optional[bytes]:
    """Concentration exhibit: sorted bars + cumulative share line + 80% marker."""
    try:
        g = g.sort_values(ascending=False).head(15)
        cum = g.cumsum() / g.sum() * 100
        fig, ax = _new_fig(7.4, 2.9)
        xs = np.arange(len(g))
        ax.bar(xs, g.values, color=FILL, edgecolor=ACCENT, linewidth=0.6)
        ax.set_xticks(xs)
        ax.set_xticklabels([str(i)[:12] for i in g.index], rotation=35,
                           ha="right", fontsize=7)
        ax.yaxis.set_major_formatter(_axis_fmt(symbol))
        ax2 = ax.twinx()
        ax2.plot(xs, cum.values, color=BAD, linewidth=1.8, marker="o",
                 markersize=3)
        ax2.axhline(80, color=MUTED, linewidth=1, linestyle=":")
        ax2.set_ylim(0, 105)
        ax2.set_ylabel("cumulative %", fontsize=8, color=BAD)
        ax2.tick_params(colors=BAD, labelsize=7.5)
        ax2.spines[["top"]].set_visible(False)
        return _png(fig)
    except Exception as exc:
        logger.debug(f"pareto_chart failed: {exc}")
        return None


def distribution_chart(values: pd.Series, symbol: str = "") -> Optional[bytes]:
    """Histogram of the primary metric with median and P90 markers."""
    try:
        v = values.dropna().astype(float)
        if len(v) < 20:
            return None
        fig, ax = _new_fig(7.4, 2.6)
        ax.hist(v, bins=min(40, max(10, len(v) // 15)), color=FILL,
                edgecolor=ACCENT, linewidth=0.5)
        med, p90 = v.median(), v.quantile(0.9)
        ax.axvline(med, color=ACCENT, linewidth=1.6)
        ax.text(med, ax.get_ylim()[1] * 0.95, f" median {_compact(med, symbol)}",
                fontsize=7.5, color=ACCENT)
        ax.axvline(p90, color=BAD, linewidth=1.2, linestyle="--")
        ax.text(p90, ax.get_ylim()[1] * 0.82, f" P90 {_compact(p90, symbol)}",
                fontsize=7.5, color=BAD)
        ax.xaxis.set_major_formatter(_axis_fmt(symbol))
        ax.set_ylabel("records", fontsize=8, color="#475569")
        return _png(fig)
    except Exception as exc:
        logger.debug(f"distribution_chart failed: {exc}")
        return None


def forecast_chart(hist: pd.DataFrame, fc: pd.DataFrame,
                   symbol: str = "") -> Optional[bytes]:
    """History + forecast line with shaded confidence band."""
    try:
        fig, ax = _new_fig()
        ax.plot(hist["date"], hist["value"], color=ACCENT, linewidth=2,
                label="actual")
        ax.plot(fc["date"], fc["forecast"], color=BAD, linewidth=1.8,
                linestyle="--", label="forecast")
        if {"lower", "upper"} <= set(fc.columns):
            ax.fill_between(fc["date"], fc["lower"], fc["upper"],
                            color=BAD, alpha=0.12, label="confidence range")
        ax.yaxis.set_major_formatter(_axis_fmt(symbol))
        ax.legend(fontsize=7.5, frameon=False, loc="upper left")
        fig.autofmt_xdate(rotation=0, ha="center")
        return _png(fig)
    except Exception as exc:
        logger.debug(f"forecast_chart failed: {exc}")
        return None


def waterfall_chart(prev_total: float, contribs: pd.Series, cur_total: float,
                    labels: tuple = ("previous", "current"),
                    symbol: str = "") -> Optional[bytes]:
    """
    Bridge from last period's total to this period's, one floating bar per
    segment contribution (B1). Green = added value, red = removed.
    """
    try:
        items = [(labels[0], prev_total, "base")]
        items += [(str(k)[:14], float(v), "delta") for k, v in contribs.items()]
        items += [(labels[1], cur_total, "base")]
        fig, ax = _new_fig(7.4, 3.0)
        running = 0.0
        for i, (name, val, kind) in enumerate(items):
            if kind == "base":
                ax.bar(i, val, color=FILL, edgecolor=ACCENT, linewidth=0.8)
                ax.text(i, val, f" {_compact(val, symbol)}", ha="center",
                        va="bottom", fontsize=7.5, color="#334155")
                running = val if i == 0 else running
            else:
                color = GOOD if val >= 0 else BAD
                ax.bar(i, val, bottom=running, color=color, alpha=0.85)
                ax.text(i, running + val + (abs(cur_total) * 0.01),
                        f"{'+' if val >= 0 else ''}{_compact(val, symbol)}",
                        ha="center", va="bottom", fontsize=7, color=color)
                running += val
        ax.set_xticks(range(len(items)))
        ax.set_xticklabels([n for n, _, _ in items], rotation=30, ha="right",
                           fontsize=7.5)
        ax.yaxis.set_major_formatter(_axis_fmt(symbol))
        ax.axhline(0, color="#CBD5E1", linewidth=0.8)
        return _png(fig)
    except Exception as exc:
        logger.debug(f"waterfall_chart failed: {exc}")
        return None


def yoy_chart(pivot: pd.DataFrame, symbol: str = "",
              month_labels: Optional[list] = None) -> Optional[bytes]:
    """Month-of-year comparison lines, one per year (calendar or fiscal)."""
    try:
        fig, ax = _new_fig(7.4, 2.9)
        months = month_labels or ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        palette = [MUTED, "#F59E0B", ACCENT, BAD]
        years = list(pivot.columns)[-4:]
        for i, yr in enumerate(years):
            ax.plot(pivot.index, pivot[yr],
                    color=palette[i % len(palette)],
                    linewidth=2.2 if yr == years[-1] else 1.4,
                    marker="o", markersize=3, label=str(yr))
        ax.set_xticks(range(1, 13))
        ax.set_xticklabels(months, fontsize=7.5)
        ax.yaxis.set_major_formatter(_axis_fmt(symbol))
        ax.legend(fontsize=7.5, frameon=False, ncol=4)
        return _png(fig)
    except Exception as exc:
        logger.debug(f"yoy_chart failed: {exc}")
        return None
