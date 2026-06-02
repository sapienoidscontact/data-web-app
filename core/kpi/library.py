"""
KPI Formula Library — 24 reusable KPI formulas organised by domain.

Each formula is a callable:  fn(df, col) -> float | int | str

All formulas are pure Python/pandas — no data is ever sent to an AI model.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, NamedTuple

import numpy as np
import pandas as pd


class KPIDefinition(NamedTuple):
    name: str                       # human-readable label
    key: str                        # machine key used in results dict
    domain: str                     # 'universal', 'sales', 'hr', 'finance', 'marketing'
    formula: Callable               # fn(df, col_name) -> value
    description: str                # one-line explanation
    format: str                     # 'number', 'currency', 'percent', 'integer'


# ── Universal (work on any numeric column) ────────────────────────────────────
def _sum(df, col):         return df[col].sum()
def _mean(df, col):        return df[col].mean()
def _median(df, col):      return df[col].median()
def _std(df, col):         return df[col].std()
def _min(df, col):         return df[col].min()
def _max(df, col):         return df[col].max()
def _count_notnull(df, col): return int(df[col].notna().sum())
def _null_rate(df, col):   return round(df[col].isnull().mean() * 100, 2)
def _cv(df, col):
    """Coefficient of variation = std / mean * 100."""
    m = df[col].mean()
    return round(df[col].std() / m * 100, 2) if m and m != 0 else None

def _pct25(df, col):       return df[col].quantile(0.25)
def _pct75(df, col):       return df[col].quantile(0.75)
def _iqr(df, col):         return df[col].quantile(0.75) - df[col].quantile(0.25)
def _skewness(df, col):    return round(df[col].skew(), 4)
def _outlier_count(df, col):
    """Z-score outliers (|z| > 3)."""
    z = np.abs((df[col] - df[col].mean()) / df[col].std())
    return int((z > 3).sum())


# ── Sales-specific (operate on revenue / price / quantity cols) ───────────────
def _total_revenue(df, col):  return df[col].sum()
def _avg_order_value(df, col): return df[col].mean()
def _revenue_std(df, col):    return df[col].std()
def _top_pct_contribution(df, col):
    """% of total revenue coming from top 20% of records (Pareto)."""
    sorted_vals = df[col].sort_values(ascending=False)
    top_n = max(1, int(len(sorted_vals) * 0.2))
    return round(sorted_vals.head(top_n).sum() / sorted_vals.sum() * 100, 1)


# ── HR-specific ───────────────────────────────────────────────────────────────
def _headcount(df, col):       return int(df[col].nunique())
def _avg_salary(df, col):      return df[col].mean()
def _salary_gini(df, col):
    """Gini coefficient of salary distribution (0=equal, 1=total inequality)."""
    vals = df[col].dropna().sort_values().values
    n = len(vals)
    if n == 0: return None
    index = np.arange(1, n + 1)
    return round((2 * (index * vals).sum() / (n * vals.sum()) - (n + 1) / n), 4)


# ── Finance-specific ──────────────────────────────────────────────────────────
def _net_total(df, col):       return df[col].sum()
def _positive_sum(df, col):    return df[col][df[col] > 0].sum()
def _negative_sum(df, col):    return df[col][df[col] < 0].sum()
def _pos_neg_ratio(df, col):
    """Ratio of positive to absolute-negative totals."""
    pos = df[col][df[col] > 0].sum()
    neg = abs(df[col][df[col] < 0].sum())
    return round(pos / neg, 4) if neg != 0 else None


# ── Registry ──────────────────────────────────────────────────────────────────
KPI_LIBRARY: List[KPIDefinition] = [
    # Universal
    KPIDefinition("Total",              "total",         "universal", _sum,               "Sum of all values",                  "number"),
    KPIDefinition("Mean",               "mean",          "universal", _mean,              "Arithmetic mean",                    "number"),
    KPIDefinition("Median",             "median",        "universal", _median,            "50th percentile value",              "number"),
    KPIDefinition("Std Dev",            "std",           "universal", _std,               "Standard deviation",                 "number"),
    KPIDefinition("Min",                "min",           "universal", _min,               "Minimum value",                      "number"),
    KPIDefinition("Max",                "max",           "universal", _max,               "Maximum value",                      "number"),
    KPIDefinition("Non-Null Count",     "count",         "universal", _count_notnull,     "Records with a value",               "integer"),
    KPIDefinition("Missing %",          "null_rate",     "universal", _null_rate,         "Percentage of missing values",       "percent"),
    KPIDefinition("Coeff. of Variation","cv",            "universal", _cv,                "Relative variability (std/mean %)",  "percent"),
    KPIDefinition("25th Percentile",    "p25",           "universal", _pct25,             "Lower quartile",                     "number"),
    KPIDefinition("75th Percentile",    "p75",           "universal", _pct75,             "Upper quartile",                     "number"),
    KPIDefinition("IQR",                "iqr",           "universal", _iqr,               "Interquartile range",                "number"),
    KPIDefinition("Skewness",           "skewness",      "universal", _skewness,          "Distribution symmetry (0=normal)",   "number"),
    KPIDefinition("Outlier Count",      "outliers",      "universal", _outlier_count,     "Values beyond 3 standard deviations","integer"),
    # Sales
    KPIDefinition("Total Revenue",      "total_revenue", "sales",     _total_revenue,     "Sum of revenue column",              "currency"),
    KPIDefinition("Avg Order Value",    "aov",           "sales",     _avg_order_value,   "Mean revenue per record",            "currency"),
    KPIDefinition("Revenue Std Dev",    "rev_std",       "sales",     _revenue_std,       "Revenue variability",                "currency"),
    KPIDefinition("Pareto 80/20",       "pareto",        "sales",     _top_pct_contribution, "% revenue from top 20% records", "percent"),
    # HR
    KPIDefinition("Unique Headcount",   "headcount",     "hr",        _headcount,         "Distinct values (people/roles)",     "integer"),
    KPIDefinition("Avg Salary",         "avg_salary",    "hr",        _avg_salary,        "Mean compensation value",            "currency"),
    KPIDefinition("Salary Gini",        "gini",          "hr",        _salary_gini,       "Pay inequality index (0–1)",         "number"),
    # Finance
    KPIDefinition("Net Total",          "net_total",     "finance",   _net_total,         "Sum including negatives",            "currency"),
    KPIDefinition("Inflows Total",      "inflows",       "finance",   _positive_sum,      "Sum of positive values",             "currency"),
    KPIDefinition("Outflows Total",     "outflows",      "finance",   _negative_sum,      "Sum of negative values",             "currency"),
    KPIDefinition("In/Out Ratio",       "in_out_ratio",  "finance",   _pos_neg_ratio,     "Inflows ÷ |Outflows|",               "number"),
]

KPI_BY_KEY: Dict[str, KPIDefinition] = {k.key: k for k in KPI_LIBRARY}
