"""
Data Audit — trust score + receipt, run before any analysis is shown.

Checks: duplicates, nulls in mapped required fields, time-series continuity gaps,
categorical near-duplicates ("Delhi"/"DELHI "), impossible negatives, constant
columns, partial current period. Each issue carries a severity that reduces the
0–100 trust score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from .model import PresetSpec

_SEVERITY_COST = {"high": 18, "medium": 8, "low": 3}


@dataclass
class AuditIssue:
    kind: str
    severity: str          # high | medium | low
    message: str


@dataclass
class AuditReport:
    score: int
    issues: List[AuditIssue] = field(default_factory=list)

    @property
    def grade(self) -> str:
        return "A" if self.score >= 90 else "B" if self.score >= 75 else \
               "C" if self.score >= 60 else "D"


def run_audit(df: pd.DataFrame, preset: Optional[PresetSpec],
              mapping: Dict[str, str]) -> AuditReport:
    issues: List[AuditIssue] = []
    n = len(df)
    if n == 0:
        return AuditReport(score=0, issues=[AuditIssue("empty", "high",
                                                       "Dataset has no rows.")])

    # 1. Exact duplicate rows
    dupes = int(df.duplicated().sum())
    if dupes:
        sev = "high" if dupes / n > 0.05 else "medium" if dupes / n > 0.01 else "low"
        issues.append(AuditIssue("duplicates", sev,
                                 f"{dupes:,} exact duplicate row(s) ({dupes / n:.1%})."))

    # 2. Nulls in mapped required fields
    if preset:
        for f in preset.required_fields:
            col = mapping.get(f.name)
            if col and col in df.columns:
                null_rate = df[col].isna().mean()
                if null_rate > 0.02:
                    sev = "high" if null_rate > 0.2 else "medium"
                    issues.append(AuditIssue("missing", sev,
                        f"Key field '{col}' ({f.name}) is {null_rate:.0%} empty."))

    # 3. Date continuity + partial current period
    date_cols = [c for c in df.columns
                 if pd.api.types.is_datetime64_any_dtype(df[c])]
    if date_cols:
        d = df[date_cols[0]].dropna()
        if len(d) >= 10:
            days = pd.Series(sorted(d.dt.normalize().unique()))
            if len(days) >= 10:
                gaps = days.diff().dt.days.dropna()
                typical = gaps.median()
                big = gaps[gaps > max(7, typical * 6)]
                if len(big):
                    issues.append(AuditIssue("gap", "medium",
                        f"{len(big)} gap(s) in the timeline of '{date_cols[0]}' — "
                        f"largest is {int(big.max())} days. Dips there may be "
                        "missing data, not real declines."))
            last = d.max()
            now = pd.Timestamp.now()
            if last.to_period("M") == now.to_period("M") and now.day < 25:
                issues.append(AuditIssue("partial", "low",
                    "The latest month is incomplete — treat current-period "
                    "comparisons as provisional."))

    # 4. Categorical near-duplicates (case/whitespace collisions)
    for c in df.columns:
        s = df[c]
        if s.dtype == object and 2 <= s.nunique(dropna=True) <= 200:
            vals = s.dropna().astype(str)
            folded = vals.str.lower().str.strip()
            n_raw, n_fold = vals.nunique(), folded.nunique()
            if n_raw - n_fold >= 1:
                issues.append(AuditIssue("inconsistent", "medium",
                    f"'{c}' has {n_raw - n_fold} value(s) that differ only by "
                    "case/spacing (e.g. 'Delhi' vs 'DELHI') — groups will split."))

    # 5. Impossible negatives in quantity-like mapped fields
    if preset:
        for fname in ("quantity", "units_sold", "output_qty", "beneficiaries",
                      "area_sqft", "impressions", "clicks"):
            col = mapping.get(fname)
            if col and col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
                neg = int((df[col] < 0).sum())
                if neg:
                    issues.append(AuditIssue("negative", "medium",
                        f"'{col}' has {neg} negative value(s) — check for "
                        "returns/corrections mixed into the data."))

    # 6. Constant columns
    const = [c for c in df.columns if df[c].nunique(dropna=True) <= 1]
    if const:
        issues.append(AuditIssue("constant", "low",
            f"{len(const)} column(s) have a single value ({', '.join(const[:4])}"
            f"{'…' if len(const) > 4 else ''}) — they add no signal."))

    score = max(0, 100 - sum(_SEVERITY_COST[i.severity] for i in issues))
    return AuditReport(score=score, issues=issues)
