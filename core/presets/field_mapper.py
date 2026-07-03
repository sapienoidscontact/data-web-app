"""
Field Mapper — binds physical DataFrame columns to a preset's canonical fields.

Scoring per (canonical field, column) pair:
  exact normalized name match ........ 6
  synonym exact match ................ 5
  synonym is token-subset of column .. 3
  synonym substring of column ........ 2
  value-vocabulary overlap ........... +3
  role compatibility ................. required (score 0 if incompatible)

Assignment is greedy by score; each column binds to at most one canonical field.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

import pandas as pd

from ..schema.detector import SchemaProfile
from .model import FieldSpec, PresetSpec, ROLE_GROUPS


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def _tokens(s: str) -> set:
    return set(_norm(s).split())


def _vocab_overlap(series: pd.Series, vocab: List[str]) -> float:
    """Share of sampled cell values that appear in the field's value vocabulary."""
    if not vocab:
        return 0.0
    try:
        sample = series.dropna().astype(str).str.lower().str.strip().head(200)
        if sample.empty:
            return 0.0
        vset = {v.lower() for v in vocab}
        return sum(any(v in cell for v in vset) for cell in sample) / len(sample)
    except Exception:
        return 0.0


def score_pair(field: FieldSpec, col: str, schema: SchemaProfile,
               df: pd.DataFrame) -> float:
    profile = schema.columns.get(col)
    if profile is None:
        return 0.0
    role_ok = profile.role in ROLE_GROUPS.get(field.role, set())
    # low-cardinality integer columns (e.g. Qty 1–9) classify as categorical,
    # but they are perfectly valid numeric fields
    if not role_ok and field.role == "numeric" \
            and pd.api.types.is_numeric_dtype(df[col]):
        role_ok = True
    if not role_ok:
        return 0.0

    col_norm, col_toks = _norm(col), _tokens(col)
    score = 0.0
    if col_norm == _norm(field.name):
        score = 6.0
    for syn in field.synonyms:
        syn_norm, syn_toks = _norm(syn), _tokens(syn)
        if col_norm == syn_norm:
            score = max(score, 5.0)
        elif syn_toks and syn_toks <= col_toks:
            score = max(score, 3.0)
        elif syn_norm and syn_norm in col_norm:
            score = max(score, 2.0)

    if field.value_vocab and profile.role in ("categorical", "binary", "text"):
        if _vocab_overlap(df[col], field.value_vocab) > 0.5:
            score += 3.0
    return score


def map_fields(df: pd.DataFrame, schema: SchemaProfile,
               preset: PresetSpec) -> Tuple[Dict[str, str], Dict[str, float]]:
    """
    Returns (mapping canonical→column, per-field best scores).
    Greedy: highest-scoring pairs claim their column first.
    """
    pairs: List[Tuple[float, str, str]] = []
    for f in preset.fields:
        for col in df.columns:
            s = score_pair(f, col, schema, df)
            if s >= 2.0:
                pairs.append((s, f.name, col))
    pairs.sort(key=lambda t: -t[0])

    mapping: Dict[str, str] = {}
    used_cols: set = set()
    scores: Dict[str, float] = {}
    for s, fname, col in pairs:
        if fname in mapping or col in used_cols:
            continue
        mapping[fname] = col
        used_cols.add(col)
        scores[fname] = s
    return mapping, scores
