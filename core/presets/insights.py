"""
Insight Cards Engine — automated findings, ranked by materiality.

Card types produced (statistically guarded, see docs/EXPERT_ANALYST_ENGINE.md §5):
  trend          significant slope on the primary metric over recent periods
  anomaly        period with residual > 2.5σ from the local level, with attribution
  variance       KPI moved beyond the series' own noise vs previous period
  concentration  top-N share above risk threshold
  leader         best/worst segment vs the average (min sample size enforced)
  dq_warning     high-severity audit issues surfaced as analysis caveats

Never sends data anywhere — pure pandas/scipy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy import stats

from .audit import AuditReport
from .kpis import KPIValue, auto_grain, is_partial_period
from .model import PresetSpec

_GRAIN_LABEL = {"D": "day", "W": "week", "M": "month", "Q": "quarter"}
_MIN_GROUP_N = 8


@dataclass
class InsightCard:
    type: str
    headline: str
    so_what: str = ""
    severity: str = "info"          # good | warn | risk | info
    materiality: float = 0.0
    evidence: Dict = field(default_factory=dict)


# ── helpers ───────────────────────────────────────────────────────────────────

def _mapped(df: pd.DataFrame, mapping: Dict[str, str], fname: Optional[str]):
    col = mapping.get(fname) if fname else None
    return (col, df[col]) if col and col in df.columns else (None, None)


def _date_series(df, preset, mapping):
    for f in preset.fields:
        if f.role == "temporal" and f.name in mapping:
            col = mapping[f.name]
            return col, pd.to_datetime(df[col], errors="coerce")
    return None, None


def _period_series(df, preset, mapping):
    """Aggregate the primary metric per period. Returns (period_index, values, grain)."""
    dcol, dates = _date_series(df, preset, mapping)
    mcol, metric = _mapped(df, mapping, preset.primary_metric)
    if dates is None:
        return None, None, None, None
    ok = dates.notna()
    if ok.sum() < 6:
        return None, None, None, None
    grain = auto_grain(dates[ok])
    periods = dates[ok].dt.to_period(grain)
    if mcol is not None and pd.api.types.is_numeric_dtype(metric):
        agg = metric[ok].groupby(periods).sum()
        label = mcol
    else:
        agg = periods.groupby(periods).size().astype(float)
        label = "records"
    agg = agg.sort_index()
    # A1: a partial trailing period fabricates a "drop" — exclude it from
    # every trend/anomaly/forecast computation downstream.
    if len(agg) >= 3 and is_partial_period(agg.index[-1], dates[ok].max(), grain):
        agg = agg.iloc[:-1]
    return agg, grain, label, (dcol or "")


def deseasonalize(series: pd.Series, grain: str):
    """
    Remove the seasonal component before trend testing (A3) so weekly or
    annual cycles are not mistaken for trends. Returns (adjusted, was_adjusted).
    """
    cycle = {"D": 7, "M": 12}.get(grain)
    if cycle is None or len(series) < 2 * cycle + 2:
        return series, False
    try:
        from statsmodels.tsa.seasonal import seasonal_decompose
        res = seasonal_decompose(series.astype(float).values, period=cycle,
                                 model="additive", extrapolate_trend="freq")
        adjusted = pd.Series(series.values - res.seasonal, index=series.index)
        return adjusted, True
    except Exception:
        return series, False


def _fmt_pct(x: float) -> str:
    return f"{x:+.1f}%"


# ── card generators ───────────────────────────────────────────────────────────

def _trend_card(series, grain, label) -> Optional[InsightCard]:
    if series is None or len(series) < 5:
        return None
    adjusted, seasonal_adj = deseasonalize(series, grain)
    tail = adjusted.tail(10)
    x = np.arange(len(tail), dtype=float)
    res = stats.linregress(x, tail.values.astype(float))
    mean = tail.mean()
    if mean == 0 or res.pvalue > 0.05:
        return None
    per_period = res.slope / abs(mean) * 100
    if abs(per_period) < 2:
        return None
    g = _GRAIN_LABEL.get(grain, "period")
    direction = "rising" if res.slope > 0 else "falling"
    adj_note = ", seasonally adjusted" if seasonal_adj else ""
    return InsightCard(
        type="trend", severity="good" if res.slope > 0 else "warn",
        headline=f"{label} is {direction} ≈{abs(per_period):.1f}% per {g}",
        so_what=(f"Consistent {direction} pattern over the last {len(tail)} {g}s "
                 f"(p={res.pvalue:.3f}{adj_note}) — treat it as a real trend, "
                 "not noise."),
        materiality=min(10, abs(per_period)),
        evidence={"slope_pct_per_period": per_period, "p": res.pvalue,
                  "seasonally_adjusted": seasonal_adj},
    )


def _attribute_period(df, period, grain, preset, mapping) -> str:
    """Find which segment explains most of one period's value."""
    dcol, dates = _date_series(df, preset, mapping)
    mcol, metric = _mapped(df, mapping, preset.primary_metric)
    if dates is None or mcol is None:
        return ""
    in_period = dates.dt.to_period(grain) == period
    cat_fields = [f.name for f in preset.fields
                  if f.role == "categorical" and f.name in mapping]
    best = None
    for fname in cat_fields[:4]:
        col, s = _mapped(df, mapping, fname)
        if s is None:
            continue
        share = metric[in_period].groupby(s[in_period]).sum()
        if len(share) and share.abs().sum():
            top = share.abs().idxmax()
            frac = float(share.abs().max() / share.abs().sum())
            if best is None or frac > best[2]:
                best = (col, top, frac)
    if best and best[2] > 0.4:
        return (f" '{best[1]}' ({best[0]}) accounts for {best[2]:.0%} of that "
                f"{_GRAIN_LABEL.get(grain, 'period')}.")
    return ""


def _anomaly_cards(df, series, grain, label, preset, mapping,
                   max_anomalies: int = 3) -> List[InsightCard]:
    """Up to 3 significant deviations from the local level (A4)."""
    if series is None or len(series) < 8:
        return []
    vals = series.astype(float)
    roll = vals.rolling(5, center=True, min_periods=3).median()
    resid = vals - roll
    sd = resid.std()
    if not sd or np.isnan(sd) or sd == 0:
        return []
    z = (resid / sd).dropna()
    hits = z[z.abs() >= 2.5].abs().sort_values(ascending=False)
    cards = []
    for period in hits.index[:max_anomalies]:
        zval = float(z.loc[period])
        kind = "spike" if zval > 0 else "drop"
        attribution = _attribute_period(df, period, grain, preset, mapping)
        cards.append(InsightCard(
            type="anomaly", severity="warn",
            headline=f"Unusual {kind} in {label} around {period}",
            so_what=(f"That {_GRAIN_LABEL.get(grain, 'period')} sits "
                     f"{abs(zval):.1f}σ away from its neighbours.{attribution} "
                     "Verify whether it's an event, a one-off, or a data issue."),
            materiality=min(10, abs(zval) * 2),
            evidence={"period": str(period), "z": zval},
        ))
    return cards


def _variance_cards(kpis: List[KPIValue]) -> List[InsightCard]:
    cards = []
    for k in kpis:
        if k.delta_pct is None or abs(k.delta_pct) < 10:
            continue
        good = (k.delta_pct > 0) == (k.polarity == "up_good")
        if k.polarity == "neutral":
            sev = "info"
        else:
            sev = "good" if good else "risk"
        cards.append(InsightCard(
            type="variance", severity=sev,
            headline=f"{k.label} moved {_fmt_pct(k.delta_pct)} vs the previous period",
            so_what=("A favourable move — confirm what drove it and protect it."
                     if sev == "good" else
                     "An adverse move — drill into the breakdown charts to find "
                     "the segment responsible." if sev == "risk" else
                     "Composition shift worth being aware of."),
            materiality=min(10, abs(k.delta_pct) / 5),
            evidence={"kpi": k.key, "delta_pct": k.delta_pct},
        ))
    return cards


def _concentration_card(kpis: List[KPIValue]) -> Optional[InsightCard]:
    for k in kpis:
        if k.kind_hint() == "top_share" and k.value is not None and k.value >= 60:
            return InsightCard(
                type="concentration", severity="warn",
                headline=f"{k.label}: {k.value:.0f}% — heavy concentration",
                so_what=("A small set of items drives most of the value. Growth and "
                         "risk both hinge on them — diversify or double down "
                         "deliberately."),
                materiality=min(10, (k.value - 50) / 5),
                evidence={"kpi": k.key, "share": k.value},
            )
    return None


def _leader_card(df, preset, mapping) -> Optional[InsightCard]:
    mcol, metric = _mapped(df, mapping, preset.primary_metric)
    if metric is None or not pd.api.types.is_numeric_dtype(metric):
        return None
    for f in preset.fields:
        if f.role != "categorical" or f.name not in mapping:
            continue
        col, s = _mapped(df, mapping, f.name)
        counts = s.groupby(s).size()
        groups = counts[counts >= _MIN_GROUP_N].index
        if len(groups) < 3:
            continue
        sums = metric.groupby(s).sum().loc[groups].sort_values(ascending=False)
        total = sums.sum()
        if total == 0:
            continue
        top, bottom = sums.index[0], sums.index[-1]
        top_share = sums.iloc[0] / total * 100
        return InsightCard(
            type="leader", severity="info",
            headline=f"'{top}' leads {col} with {top_share:.0f}% of {mcol}",
            so_what=(f"Across {len(sums)} {col} groups, '{top}' contributes the "
                     f"most and '{bottom}' the least. Compare their playbooks "
                     "before averaging them away."),
            materiality=min(8, top_share / 10),
            evidence={"dimension": col, "top": str(top), "bottom": str(bottom)},
        )
    return None


def _dq_cards(audit: Optional[AuditReport]) -> List[InsightCard]:
    if not audit:
        return []
    return [InsightCard(
        type="dq_warning", severity="risk",
        headline=f"Data quality: {i.message}",
        so_what="Findings on affected fields carry this caveat.",
        materiality=6.0,
    ) for i in audit.issues if i.severity == "high"]


# small helper so _concentration_card can identify top_share KPIs without spec access
def _kind_hint(self: KPIValue) -> str:
    return "top_share" if "share" in self.key else ""


KPIValue.kind_hint = _kind_hint  # type: ignore[attr-defined]


# ── public entry point ────────────────────────────────────────────────────────

def generate_cards(df: pd.DataFrame, preset: PresetSpec, mapping: Dict[str, str],
                   kpis: List[KPIValue],
                   audit: Optional[AuditReport] = None,
                   max_cards: int = 7) -> List[InsightCard]:
    series, grain, label, _ = _period_series(df, preset, mapping)
    cards: List[InsightCard] = []
    cards += _dq_cards(audit)
    c = _trend_card(series, grain, label)
    if c:
        cards.append(c)
    cards += _anomaly_cards(df, series, grain, label, preset, mapping)
    cards += _variance_cards(kpis)
    c = _concentration_card(kpis)
    if c:
        cards.append(c)
    c = _leader_card(df, preset, mapping)
    if c:
        cards.append(c)
    cards.sort(key=lambda x: -x.materiality)
    return cards[:max_cards]


def cards_to_context(cards: List[InsightCard]) -> str:
    """Aggregate-only card summary for AI prompts."""
    lines = ["Automated findings (statistically checked):"]
    for c in cards:
        lines.append(f"  [{c.type}] {c.headline} — {c.so_what}")
    return "\n".join(lines)
