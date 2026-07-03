"""
Preset data model — declarative industry preset specifications.

A PresetSpec fully describes one industry's analytics:
  fields   → canonical schema (synonyms + role + value vocabulary) for auto-mapping
  kpis     → KPI pack built from ~10 reusable primitives (see kpis.py)
  tiles    → which KPI keys appear as headline metric tiles
  charts   → the preset dashboard, bound to canonical fields
  filters  → default slicers
  ai_prompt / report_tone → analyst persona

Charts and KPIs referencing unmapped canonical fields degrade gracefully (skipped).
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Dict, List, Optional, Tuple


# Role groups a canonical field will accept (from schema detector roles)
ROLE_GROUPS = {
    "temporal":    {"temporal"},
    "numeric":     {"numeric_continuous", "numeric_discrete", "binary"},
    "categorical": {"categorical", "binary", "text"},
    "identifier":  {"identifier", "categorical", "text", "numeric_discrete"},
    "any":         {"identifier", "temporal", "binary", "categorical",
                    "numeric_continuous", "numeric_discrete", "text", "unknown"},
}


@dataclass
class FieldSpec:
    name: str                                # canonical name, e.g. 'revenue'
    role: str                                # key of ROLE_GROUPS
    synonyms: List[str]                      # matched against real column headers
    required: bool = False
    value_vocab: List[str] = dc_field(default_factory=list)  # distinctive cell values


@dataclass
class KPISpec:
    key: str
    label: str
    kind: str          # sum|mean|median|distinct|rows|ratio|rate|growth|top_share|date_diff
    params: Dict = dc_field(default_factory=dict)
    fmt: str = "number"                      # number|currency|percent|integer|days|ratio
    polarity: str = "up_good"                # up_good|up_bad|neutral
    description: str = ""


@dataclass
class ChartSpec:
    kind: str          # line|bar|donut|stacked_bar|box|scatter|heat_dow|hist|funnel
    title: str
    x: Optional[str] = None                  # canonical field names
    y: Optional[str] = None
    color: Optional[str] = None
    agg: str = "sum"                         # sum|mean|count|nunique
    top_n: int = 10
    options: Dict = dc_field(default_factory=dict)

    def needed_fields(self) -> List[str]:
        return [f for f in (self.x, self.y, self.color) if f]


@dataclass
class PresetSpec:
    name: str
    label: str
    icon: str
    keywords: List[str]                      # dataset-level trigger tokens
    fields: List[FieldSpec]
    kpis: List[KPISpec]
    tiles: List[str]                         # KPI keys for the headline row
    charts: List[ChartSpec]
    filters: List[str] = dc_field(default_factory=list)
    ai_prompt: str = ""
    report_tone: str = "business review"
    primary_metric: Optional[str] = None     # canonical numeric field to forecast/decompose

    @property
    def required_fields(self) -> List[FieldSpec]:
        return [f for f in self.fields if f.required]

    def field(self, name: str) -> Optional[FieldSpec]:
        for f in self.fields:
            if f.name == name:
                return f
        return None


@dataclass
class DetectionResult:
    preset: PresetSpec
    confidence: int                          # 0–100
    mapping: Dict[str, str]                  # canonical field → dataframe column
    scores: Dict[str, float] = dc_field(default_factory=dict)
