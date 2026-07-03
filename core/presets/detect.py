"""
Preset Detection — ranks all industry presets against an uploaded dataset.

Confidence blends four signals (see docs/INDUSTRY_PRESETS.md):
  1. required-field coverage (weight 3) — % of required canonical fields mapped
  2. optional-field coverage (weight 1)
  3. keyword hits in column names (weight 1, capped)
  4. value-vocabulary hits (already baked into field mapping scores)
"""

from __future__ import annotations

import re
from typing import List

import pandas as pd

from ..schema.detector import SchemaProfile
from .field_mapper import map_fields
from .model import DetectionResult, PresetSpec


def _keyword_hits(columns: List[str], keywords: List[str]) -> int:
    joined = " ".join(re.sub(r"[^a-z0-9]+", " ", str(c).lower()) for c in columns)
    toks = set(joined.split())
    return sum(1 for kw in keywords if kw in toks or kw in joined)


def rank_presets(df: pd.DataFrame, schema: SchemaProfile,
                 presets: List[PresetSpec]) -> List[DetectionResult]:
    results: List[DetectionResult] = []
    for preset in presets:
        mapping, scores = map_fields(df, schema, preset)
        req = preset.required_fields
        req_cov = (sum(1 for f in req if f.name in mapping) / len(req)) if req else 0.0
        opt = [f for f in preset.fields if not f.required]
        opt_cov = (sum(1 for f in opt if f.name in mapping) / len(opt)) if opt else 0.0
        kw = min(_keyword_hits(list(df.columns), preset.keywords), 6) / 6.0
        vocab_bonus = sum(1 for s in scores.values() if s >= 6.5) * 0.05

        raw = 0.55 * req_cov + 0.20 * opt_cov + 0.25 * kw + vocab_bonus
        confidence = int(round(min(0.99, raw) * 100))
        results.append(DetectionResult(
            preset=preset, confidence=confidence, mapping=mapping,
            scores={"required": req_cov, "optional": opt_cov, "keywords": kw},
        ))
    results.sort(key=lambda r: -r.confidence)
    return results


def detect_preset(df: pd.DataFrame, schema: SchemaProfile,
                  presets: List[PresetSpec],
                  min_confidence: int = 45) -> DetectionResult | None:
    """Best preset above the confidence floor, else None (caller falls back to general)."""
    ranked = rank_presets(df, schema, presets)
    if ranked and ranked[0].confidence >= min_confidence:
        return ranked[0]
    return None
