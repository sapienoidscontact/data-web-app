"""
Mapped KPI Engine — computes a preset's KPI pack from the canonical field mapping.

Unlike core/kpi (single-column), every primitive here works on *fields*: ratios span
columns, rates filter rows, growth uses the mapped date field, and every KPI also
gets a delta vs the previous time period for the metric tiles.

Primitives (kind →):
  sum, mean, median, max, distinct, rows, ratio, ratio_fields, rate, rate_notnull,
  growth, top_share, date_diff, share_where_num
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from loguru import logger

from .model import KPISpec, PresetSpec


@dataclass
class KPIValue:
    key: str
    label: str
    value: Optional[float]
    fmt: str
    polarity: str
    description: str
    delta_pct: Optional[float] = None      # vs previous period, when computable


# ── helpers ───────────────────────────────────────────────────────────────────

def _col(df: pd.DataFrame, mapping: Dict[str, str], field: Optional[str]):
    if not field:
        return None
    col = mapping.get(field)
    if col is None or col not in df.columns:
        return None
    return df[col]


def _norm_str(s: pd.Series) -> pd.Series:
    return s.astype(str).str.lower().str.strip()


def _match_values(s: pd.Series, values: List[str]) -> pd.Series:
    ns = _norm_str(s)
    vset = [v.lower().strip() for v in values]
    pattern = "|".join(rf"\b{re.escape(v)}\b" for v in vset)
    return ns.isin(vset) | ns.str.contains(pattern, regex=True, na=False)


def _date_field(preset: PresetSpec, mapping: Dict[str, str]) -> Optional[str]:
    for f in preset.fields:
        if f.role == "temporal" and f.name in mapping:
            return f.name
    return None


def auto_grain(dates: pd.Series) -> str:
    """Return a pandas period code based on the data span."""
    d = pd.to_datetime(dates, errors="coerce").dropna()
    if d.empty:
        return "M"
    span = (d.max() - d.min()).days
    if span <= 31:
        return "D"
    if span <= 183:
        return "W"
    if span <= 1100:
        return "M"
    return "Q"


def _grain_days(period, grain: str) -> float:
    if grain == "D":
        return 1
    if grain == "W":
        return 7
    if grain == "M":
        return period.days_in_month
    return 91  # Q


def is_partial_period(period, data_max: pd.Timestamp, grain: str) -> bool:
    """
    True when the data only covers part of `period` — comparing it to a full
    period would fabricate a decline. Data-relative: judged by how far into
    the period the latest record reaches (< 80% coverage = partial; a week
    missing its last two days already distorts a comparison by ~30%).
    """
    try:
        covered = (data_max - period.to_timestamp()).days + 1
        return covered / _grain_days(period, grain) < 0.8
    except Exception:
        return False


def last_two_full_periods(dates: pd.Series, grain: str):
    """
    Return (current, previous) periods for movement comparisons, skipping a
    partial trailing period (A1 fix). Returns (None, None) if unavailable.
    """
    d = pd.to_datetime(dates, errors="coerce").dropna()
    if len(d) < 4:
        return None, None
    periods = d.dt.to_period(grain)
    uniq = sorted(periods.unique())
    if len(uniq) < 2:
        return None, None
    if is_partial_period(uniq[-1], d.max(), grain):
        if len(uniq) < 3:
            return None, None
        return uniq[-2], uniq[-3]
    return uniq[-1], uniq[-2]


# ── single-KPI evaluation (memoised per df slice) ────────────────────────────

def _eval(kpi: KPISpec, df: pd.DataFrame, mapping: Dict[str, str],
          memo: Dict[str, Optional[float]],
          by_key: Dict[str, KPISpec], preset: PresetSpec,
          depth: int = 0) -> Optional[float]:
    if kpi.key in memo:
        return memo[kpi.key]
    if depth > 4:
        return None
    p = kpi.params
    val: Optional[float] = None
    try:
        kind = kpi.kind

        if kind in ("sum", "mean", "median", "max"):
            s = _col(df, mapping, p.get("field"))
            if s is not None and pd.api.types.is_numeric_dtype(s):
                if p.get("positive_only"):
                    s = s[s > 0]
                if p.get("negative_only"):
                    s = s[s < 0]
                wf = p.get("where_field")
                if wf:
                    ws = _col(df, mapping, wf)
                    if ws is not None:
                        mask = _match_values(ws, p.get("where_values", []))
                        s = s[mask.reindex(s.index, fill_value=False)]
                    elif not p.get("where_fallback"):
                        s = s.iloc[0:0]
                if len(s.dropna()):
                    val = float(getattr(s, kind)())
                    val *= p.get("scale", 1)

        elif kind == "distinct":
            s = _col(df, mapping, p.get("field"))
            if s is not None:
                val = float(s.nunique(dropna=True))
            elif p.get("fallback_rows"):
                val = float(len(df))

        elif kind == "rows":
            val = float(len(df))

        elif kind == "ratio":
            num = _eval(by_key[p["num"]], df, mapping, memo, by_key, preset, depth + 1) \
                if p.get("num") in by_key else None
            if p.get("den_sum"):
                parts = [_eval(by_key[k], df, mapping, memo, by_key, preset, depth + 1)
                         for k in p["den_sum"] if k in by_key]
                parts = [x for x in parts if x is not None]
                den = sum(parts) if parts else None
            else:
                den = _eval(by_key[p["den"]], df, mapping, memo, by_key, preset,
                            depth + 1) if p.get("den") in by_key else None
            if num is not None and den not in (None, 0):
                val = num / den
                if p.get("as_percent"):
                    val *= 100

        elif kind == "ratio_fields":
            ns = _col(df, mapping, p.get("num_field"))
            ds = _col(df, mapping, p.get("den_field"))
            if ns is not None and ds is not None:
                num, den = float(ns.sum()), float(ds.sum())
                if den != 0:
                    val = num / den * (100 if p.get("as_percent") else 1)

        elif kind == "rate":
            s = _col(df, mapping, p.get("field"))
            if s is not None and len(s.dropna()):
                val = float(_match_values(s, p.get("values", [])).mean() * 100)

        elif kind == "rate_notnull":
            s = _col(df, mapping, p.get("field"))
            if s is not None and len(df):
                val = float(s.notna().mean() * 100)

        elif kind == "growth":
            base = by_key.get(p.get("kpi"))
            dfield = _date_field(preset, mapping)
            if base is not None and dfield:
                dates = pd.to_datetime(_col(df, mapping, dfield), errors="coerce")
                ok = dates.notna()
                if ok.sum() >= 4:
                    grain = auto_grain(dates[ok])
                    cur_p, prev_p = last_two_full_periods(dates[ok], grain)
                    if cur_p is not None:
                        periods = dates[ok].dt.to_period(grain)
                        cur_df = df[ok][periods == cur_p]
                        prev_df = df[ok][periods == prev_p]
                        cur = _eval(base, cur_df, mapping, {}, by_key, preset, depth + 1)
                        prev = _eval(base, prev_df, mapping, {}, by_key, preset, depth + 1)
                        if cur is not None and prev not in (None, 0):
                            val = (cur - prev) / abs(prev) * 100

        elif kind == "top_share":
            vs = _col(df, mapping, p.get("field"))
            bs = _col(df, mapping, p.get("by"))
            if vs is not None and bs is not None and pd.api.types.is_numeric_dtype(vs):
                v = vs.abs() if p.get("absolute") else vs
                grouped = v.groupby(bs).sum().sort_values(ascending=False)
                total = grouped.sum()
                if total not in (0, None) and len(grouped):
                    val = float(grouped.head(p.get("n", 10)).sum() / total * 100)

        elif kind == "date_diff":
            s0 = _col(df, mapping, p.get("start"))
            s1 = _col(df, mapping, p.get("end"))
            if s0 is not None:
                start = pd.to_datetime(s0, errors="coerce")
                if s1 is not None:
                    end = pd.to_datetime(s1, errors="coerce")
                    if p.get("open_end") == "today":
                        end = end.fillna(pd.Timestamp.now())
                elif p.get("open_end") == "today":
                    end = pd.Series(pd.Timestamp.now(), index=start.index)
                else:
                    end = None
                if end is not None:
                    days = (end - start).dt.days.dropna()
                    days = days[days >= 0]
                    if len(days):
                        unit = p.get("unit", "days")
                        div = {"days": 1, "months": 30.44, "years": 365.25}[unit]
                        val = float(days.mean() / div)

        elif kind == "share_where_num":
            vs = _col(df, mapping, p.get("value_field"))
            cs = _col(df, mapping, p.get("cond_field"))
            if vs is not None and cs is not None:
                th, op = p.get("threshold", 0), p.get("op", ">")
                cond = cs > th if op == ">" else cs < th
                total = vs.sum()
                if total not in (0, None):
                    val = float(vs[cond.fillna(False)].sum() / total * 100)

    except Exception as exc:
        logger.debug(f"KPI '{kpi.key}' failed: {exc}")
        val = None

    if val is not None and (np.isnan(val) or np.isinf(val)):
        val = None
    memo[kpi.key] = val
    return val


# ── public entry point ────────────────────────────────────────────────────────

def compute_pack(df: pd.DataFrame, preset: PresetSpec,
                 mapping: Dict[str, str]) -> List[KPIValue]:
    """Compute every KPI in the preset's pack + per-KPI delta vs previous period."""
    by_key = {k.key: k for k in preset.kpis}
    memo: Dict[str, Optional[float]] = {}
    results: List[KPIValue] = []

    # Period slices for deltas — partial trailing periods excluded (A1)
    cur_df = prev_df = None
    dfield = _date_field(preset, mapping)
    if dfield:
        dates = pd.to_datetime(_col(df, mapping, dfield), errors="coerce")
        ok = dates.notna()
        if ok.sum() >= 4:
            grain = auto_grain(dates[ok])
            cur_p, prev_p = last_two_full_periods(dates[ok], grain)
            if cur_p is not None:
                periods = dates[ok].dt.to_period(grain)
                cur_df = df[ok][periods == cur_p]
                prev_df = df[ok][periods == prev_p]

    for kpi in preset.kpis:
        val = _eval(kpi, df, mapping, memo, by_key, preset)
        if val is None:
            continue
        delta = None
        if kpi.kind != "growth" and cur_df is not None and len(cur_df) and len(prev_df):
            cur = _eval(kpi, cur_df, mapping, {}, by_key, preset)
            prev = _eval(kpi, prev_df, mapping, {}, by_key, preset)
            if cur is not None and prev not in (None, 0):
                delta = (cur - prev) / abs(prev) * 100
        results.append(KPIValue(kpi.key, kpi.label, val, kpi.fmt, kpi.polarity,
                                kpi.description, delta))
    logger.info(f"Preset KPI pack: {len(results)}/{len(preset.kpis)} computed "
                f"({preset.name}).")
    return results


def pack_to_context(results: List[KPIValue]) -> str:
    """Compact aggregate-only summary for AI prompts (no raw rows)."""
    lines = ["Computed KPIs:"]
    for r in results:
        d = f" (Δ {r.delta_pct:+.1f}% vs prev period)" if r.delta_pct is not None else ""
        lines.append(f"  {r.label}: {r.value:,.2f}{d} — {r.description}")
    return "\n".join(lines)
