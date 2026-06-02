"""
KPI Engine — auto-selects and computes KPIs from a SchemaProfile + DataFrame.

Flow:
  1. Receive schema (from detector.py) + domain (from mapper.py)
  2. Select relevant KPI definitions from the library
  3. Run each formula against the appropriate column
  4. Return a structured KPIResult dict ready for display

All computation is in Python/pandas. No data is sent to any AI model.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
from loguru import logger

from ..schema.detector import SchemaProfile
from .library import KPI_LIBRARY, KPIDefinition


# ── Result types ──────────────────────────────────────────────────────────────
class KPIResult:
    """A single computed KPI value with metadata."""
    def __init__(self, kpi: KPIDefinition, column: str, value: Any):
        self.name        = kpi.name
        self.key         = kpi.key
        self.domain      = kpi.domain
        self.column      = column
        self.value       = value
        self.format      = kpi.format
        self.description = kpi.description

    def formatted_value(self) -> str:
        """Return a display-ready string."""
        if self.value is None:
            return "N/A"
        try:
            v = float(self.value)
            if self.format == "currency":
                return f"{v:,.2f}"
            if self.format == "percent":
                return f"{v:.2f}%"
            if self.format == "integer":
                return f"{int(v):,}"
            return f"{v:,.4g}"
        except (TypeError, ValueError):
            return str(self.value)

    def to_dict(self) -> dict:
        return {
            "name":        self.name,
            "key":         self.key,
            "column":      self.column,
            "value":       self.value,
            "formatted":   self.formatted_value(),
            "format":      self.format,
            "description": self.description,
        }


# ── KPI selector ──────────────────────────────────────────────────────────────

def _select_kpis(domain: str) -> List[KPIDefinition]:
    """
    Return KPI definitions relevant for the given domain.
    Always includes universal KPIs; adds domain-specific ones on top.

    Args:
        domain: One of 'sales', 'hr', 'finance', 'marketing', 'logistics', 'general'.

    Returns:
        List of KPIDefinition objects to compute.
    """
    selected = [k for k in KPI_LIBRARY if k.domain == "universal"]
    domain_kpis = [k for k in KPI_LIBRARY if k.domain == domain]
    selected.extend(domain_kpis)
    return selected


def _pick_column(schema: SchemaProfile, domain: str) -> Optional[str]:
    """
    Pick the most relevant numeric column for domain-specific KPIs.
    Prefers columns whose name contains domain-relevant keywords.

    Args:
        schema: The SchemaProfile of the dataset.
        domain: The detected business domain.

    Returns:
        Column name string, or None if no numeric columns exist.
    """
    numeric = schema.numeric_cols
    if not numeric:
        return None

    # Domain keyword hints for picking the primary KPI column
    hints = {
        "sales":     ["revenue", "sales", "amount", "price", "total"],
        "hr":        ["salary", "wage", "compensation", "pay"],
        "finance":   ["amount", "balance", "value", "cost", "expense"],
        "marketing": ["spend", "cost", "revenue", "value"],
    }
    for hint in hints.get(domain, []):
        for col in numeric:
            if hint in col.lower():
                return col
    return numeric[0]  # fallback: first numeric column


# ── Public entry point ────────────────────────────────────────────────────────

def compute_kpis(
    df: pd.DataFrame,
    schema: SchemaProfile,
    domain: str,
    target_col: Optional[str] = None,
) -> List[KPIResult]:
    """
    Auto-select and compute KPIs for a DataFrame based on its schema and domain.

    Args:
        df:         The pandas DataFrame to compute KPIs on.
        schema:     SchemaProfile from detect_schema().
        domain:     Business domain from map_domain().
        target_col: Override the auto-selected primary KPI column.

    Returns:
        List of KPIResult objects, one per computed KPI.
    """
    col = target_col or _pick_column(schema, domain)
    if col is None:
        logger.warning("No numeric column found — KPI computation skipped.")
        return []

    kpi_defs = _select_kpis(domain)
    results: List[KPIResult] = []

    for kpi in kpi_defs:
        try:
            value = kpi.formula(df, col)
            results.append(KPIResult(kpi=kpi, column=col, value=value))
        except Exception as exc:
            logger.debug(f"KPI '{kpi.key}' skipped for column '{col}': {exc}")

    logger.info(
        f"KPI engine: {len(results)} KPIs computed on column '{col}' "
        f"(domain={domain}, rows={len(df):,})"
    )
    return results


def kpis_to_context_string(results: List[KPIResult], col: str) -> str:
    """
    Produce a compact natural-language KPI summary for sending to Gemini.
    Never passes raw data — only aggregate statistics.

    Args:
        results: Output of compute_kpis().
        col:     The column name that was analysed.

    Returns:
        Multi-line string summarising the KPIs.
    """
    lines = [f"KPI summary for column '{col}':"]
    for r in results:
        lines.append(f"  {r.name}: {r.formatted_value()}  ({r.description})")
    return "\n".join(lines)
