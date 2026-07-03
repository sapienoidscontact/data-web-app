"""
Analysis Bundle — one call that runs the whole preset pipeline on a DataFrame:

  schema detection → preset ranking → field mapping → data audit
  → mapped KPI pack → insight cards

The bundle is what the dashboard page renders, and what gets rebuilt when the
user overrides the preset or edits the field mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd
from loguru import logger

from ..schema.detector import SchemaProfile, detect_schema
from .audit import AuditReport, run_audit
from .detect import rank_presets
from .field_mapper import map_fields
from .insights import InsightCard, generate_cards
from .kpis import KPIValue, compute_pack
from .memory import recall
from .model import DetectionResult, PresetSpec
from .specs import ALL_PRESETS, PRESET_BY_NAME


@dataclass
class AnalysisBundle:
    schema: SchemaProfile
    preset: Optional[PresetSpec]
    confidence: int
    mapping: Dict[str, str]
    audit: AuditReport
    kpis: List[KPIValue] = field(default_factory=list)
    cards: List[InsightCard] = field(default_factory=list)
    ranking: List[DetectionResult] = field(default_factory=list)
    currency_symbol: str = ""
    remembered: bool = False        # mapping came from the saved registry

    @property
    def preset_label(self) -> str:
        return f"{self.preset.icon} {self.preset.label}" if self.preset else "📄 General"


def build_bundle(df: pd.DataFrame,
                 schema: Optional[SchemaProfile] = None,
                 preset_name: Optional[str] = None,
                 mapping_override: Optional[Dict[str, str]] = None,
                 currency_symbol: str = "",
                 column_symbols: Optional[Dict[str, str]] = None,
                 min_confidence: int = 40) -> AnalysisBundle:
    """
    Run the full pipeline. `preset_name` forces a preset; `mapping_override`
    replaces individual canonical→column bindings (empty string = unmap).
    """
    schema = schema or detect_schema(df)
    ranking = rank_presets(df, schema, ALL_PRESETS)

    preset: Optional[PresetSpec] = None
    confidence = 0
    mapping: Dict[str, str] = {}
    remembered = False

    # D1: a previously confirmed mapping for this exact column set wins
    if preset_name is None and not mapping_override:
        hit = recall(list(df.columns))
        if hit and hit.get("preset") in PRESET_BY_NAME:
            preset = PRESET_BY_NAME[hit["preset"]]
            mapping = dict(hit["mapping"])
            confidence, remembered = 100, True

    if preset is None:
        if preset_name and preset_name in PRESET_BY_NAME:
            preset = PRESET_BY_NAME[preset_name]
            mapping, _ = map_fields(df, schema, preset)
            confidence = next((r.confidence for r in ranking
                               if r.preset.name == preset_name), 0)
        elif ranking and ranking[0].confidence >= min_confidence:
            preset = ranking[0].preset
            confidence = ranking[0].confidence
            mapping = dict(ranking[0].mapping)

    if mapping_override:
        for fname, col in mapping_override.items():
            if col:
                # steal the column from any field currently holding it
                for other, existing in list(mapping.items()):
                    if existing == col and other != fname:
                        del mapping[other]
                mapping[fname] = col
            else:
                mapping.pop(fname, None)

    # A5: prefer the currency symbol found in the primary metric's own
    # column over the file-level guess
    if preset and column_symbols:
        pm_col = mapping.get(preset.primary_metric)
        if pm_col and pm_col in column_symbols:
            currency_symbol = column_symbols[pm_col]

    audit = run_audit(df, preset, mapping)
    kpis: List[KPIValue] = []
    cards: List[InsightCard] = []
    if preset:
        kpis = compute_pack(df, preset, mapping)
        cards = generate_cards(df, preset, mapping, kpis, audit)

    logger.info(f"Bundle: preset={preset.name if preset else 'general'} "
                f"({confidence}%), {len(mapping)} fields mapped, "
                f"trust={audit.score}, {len(kpis)} KPIs, {len(cards)} cards.")
    return AnalysisBundle(schema=schema, preset=preset, confidence=confidence,
                          mapping=mapping, audit=audit, kpis=kpis, cards=cards,
                          ranking=ranking, currency_symbol=currency_symbol,
                          remembered=remembered)
