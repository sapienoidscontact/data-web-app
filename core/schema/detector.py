"""
Schema Detection Engine — classifies every column in a DataFrame.

Output is a SchemaProfile dataclass containing:
  - per-column ColumnProfile (type, role, cardinality, completeness, samples)
  - dataset-level summary (row count, col count, temporal columns, numeric cols)

Rule matrix used for classification:
  identifier   : cardinality ratio > 0.9  OR keyword match (id/uuid/key/code/sku)
  temporal     : dtype datetime64  OR keyword match (date/time/timestamp/created)
  binary       : exactly 2 unique values
  categorical  : object dtype + cardinality <= 50  OR numeric + cardinality <= 15
  numeric_cont : float/int dtype + cardinality > 15 + NOT identifier
  text         : object dtype + average string length > 60
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


# ── Column roles ──────────────────────────────────────────────────────────────
COL_ROLES = (
    "identifier",
    "temporal",
    "binary",
    "categorical",
    "numeric_continuous",
    "numeric_discrete",
    "text",
    "unknown",
)

_ID_KEYWORDS   = {"id", "uuid", "key", "code", "sku", "serial", "ref", "no", "num", "idx"}
_TIME_KEYWORDS = {"date", "time", "timestamp", "created", "updated", "modified",
                  "at", "on", "year", "month", "week", "day"}
_TEXT_KEYWORDS = {"description", "notes", "comment", "text", "review", "feedback",
                  "summary", "body", "message", "detail", "remark"}


@dataclass
class ColumnProfile:
    """Full profile for a single DataFrame column."""
    name: str
    dtype: str
    role: str                   # one of COL_ROLES
    cardinality: int            # unique non-null value count
    cardinality_ratio: float    # cardinality / total rows
    completeness: float         # 1.0 = no nulls
    null_count: int
    sample_values: List        = field(default_factory=list)
    min_val: Optional[float]   = None
    max_val: Optional[float]   = None
    mean_val: Optional[float]  = None
    std_val: Optional[float]   = None


@dataclass
class SchemaProfile:
    """Full schema profile for a DataFrame."""
    row_count: int
    col_count: int
    columns: Dict[str, ColumnProfile] = field(default_factory=dict)

    @property
    def temporal_cols(self) -> List[str]:
        return [n for n, p in self.columns.items() if p.role == "temporal"]

    @property
    def numeric_cols(self) -> List[str]:
        return [n for n, p in self.columns.items()
                if p.role in ("numeric_continuous", "numeric_discrete")]

    @property
    def categorical_cols(self) -> List[str]:
        return [n for n, p in self.columns.items() if p.role == "categorical"]

    @property
    def identifier_cols(self) -> List[str]:
        return [n for n, p in self.columns.items() if p.role == "identifier"]

    @property
    def text_cols(self) -> List[str]:
        return [n for n, p in self.columns.items() if p.role == "text"]

    def summary_string(self) -> str:
        """
        Return a compact natural-language summary suitable for sending to Gemini.
        Never exposes raw row data — only column names, types, and aggregate stats.
        """
        lines = [
            f"Dataset: {self.row_count:,} rows × {self.col_count} columns.",
            f"Numeric columns ({len(self.numeric_cols)}): {', '.join(self.numeric_cols) or 'none'}.",
            f"Categorical columns ({len(self.categorical_cols)}): {', '.join(self.categorical_cols) or 'none'}.",
            f"Temporal columns ({len(self.temporal_cols)}): {', '.join(self.temporal_cols) or 'none'}.",
            f"Identifier columns ({len(self.identifier_cols)}): {', '.join(self.identifier_cols) or 'none'}.",
        ]
        for name, p in self.columns.items():
            null_note = f"  {p.null_count} nulls ({1-p.completeness:.0%} missing)" if p.null_count else ""
            if p.role in ("numeric_continuous", "numeric_discrete") and p.mean_val is not None:
                lines.append(
                    f"  {name} [{p.role}]: mean={p.mean_val:.2f}, "
                    f"min={p.min_val:.2f}, max={p.max_val:.2f}{null_note}"
                )
            elif p.role == "categorical":
                lines.append(
                    f"  {name} [{p.role}]: {p.cardinality} categories, "
                    f"samples={p.sample_values[:5]}{null_note}"
                )
            else:
                lines.append(f"  {name} [{p.role}]{null_note}")
        return "\n".join(lines)


# ── Classifier ────────────────────────────────────────────────────────────────

def _col_keywords(name: str) -> set:
    """Return a set of lowercase tokens from a column name."""
    import re
    tokens = re.split(r"[_\s\-\.]+", name.lower())
    return set(tokens)


def _classify_column(series: pd.Series, name: str, n_rows: int) -> str:
    """
    Apply the rule matrix and return the role string for one column.

    Args:
        series:  The column as a pandas Series.
        name:    The column name (used for keyword matching).
        n_rows:  Total rows in the DataFrame.

    Returns:
        One of the strings in COL_ROLES.
    """
    keywords = _col_keywords(name)
    dtype_str = str(series.dtype)
    n_unique = series.nunique(dropna=True)
    card_ratio = n_unique / n_rows if n_rows > 0 else 0

    # 1. Temporal — dtype first, then keyword
    if "datetime" in dtype_str:
        return "temporal"
    if not keywords.isdisjoint(_TIME_KEYWORDS):
        # Attempt to parse a sample to confirm
        sample = series.dropna().head(5)
        try:
            pd.to_datetime(sample)
            return "temporal"
        except Exception:
            pass

    # 2. Identifier — keyword match, OR high cardinality on NON-numeric columns only
    # (numeric columns with unique values like revenue must not become identifiers)
    if keywords & _ID_KEYWORDS and (card_ratio > 0.5 or dtype_str == "object"):
        return "identifier"
    if card_ratio > 0.9 and n_unique > 20 and not pd.api.types.is_numeric_dtype(series):
        return "identifier"

    # 3. Text — long string columns
    if dtype_str == "object":
        avg_len = series.dropna().astype(str).str.len().mean() or 0
        if avg_len > 60 or not keywords.isdisjoint(_TEXT_KEYWORDS):
            return "text"

    # 4. Binary
    if n_unique == 2:
        return "binary"

    # 5. Categorical
    if dtype_str == "object" and n_unique <= 50:
        return "categorical"
    if dtype_str not in ("object",) and n_unique <= 15:
        return "categorical"

    # 6. Numeric discrete vs continuous
    if pd.api.types.is_integer_dtype(series):
        return "numeric_discrete"
    if pd.api.types.is_float_dtype(series):
        return "numeric_continuous"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric_continuous"

    return "unknown"


# ── Public entry point ────────────────────────────────────────────────────────

def detect_schema(df: pd.DataFrame) -> SchemaProfile:
    """
    Analyse a DataFrame and return a full SchemaProfile.

    Args:
        df: Any pandas DataFrame (the user's uploaded dataset).

    Returns:
        SchemaProfile with per-column ColumnProfile entries.
    """
    n_rows, n_cols = df.shape
    profile = SchemaProfile(row_count=n_rows, col_count=n_cols)

    for col in df.columns:
        series = df[col]
        role = _classify_column(series, col, n_rows)
        n_null = int(series.isnull().sum())
        n_unique = int(series.nunique(dropna=True))

        cp = ColumnProfile(
            name=col,
            dtype=str(series.dtype),
            role=role,
            cardinality=n_unique,
            cardinality_ratio=round(n_unique / n_rows, 4) if n_rows else 0,
            completeness=round(1 - n_null / n_rows, 4) if n_rows else 1.0,
            null_count=n_null,
            sample_values=series.dropna().unique()[:5].tolist(),
        )

        # Numeric stats
        if pd.api.types.is_numeric_dtype(series):
            cp.min_val  = float(series.min()) if not series.dropna().empty else None
            cp.max_val  = float(series.max()) if not series.dropna().empty else None
            cp.mean_val = float(series.mean()) if not series.dropna().empty else None
            cp.std_val  = float(series.std())  if not series.dropna().empty else None

        profile.columns[col] = cp

    return profile
