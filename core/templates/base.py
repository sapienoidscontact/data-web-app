"""
Base Template — abstract class that all domain templates extend.

A template defines:
  - Which KPI keys to surface by default
  - Which chart types to show first
  - The AI prompt prefix used when generating insights
  - A match_score() method for auto-detection
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List


class BaseTemplate(ABC):
    """Abstract base for all domain templates."""

    name: str = "base"
    description: str = ""

    # KPI keys from library.py to display prominently
    primary_kpi_keys: List[str] = []

    # Chart types to render first on the dashboard
    preferred_charts: List[str] = []

    # Column name tokens that strongly suggest this template
    trigger_keywords: List[str] = []

    @classmethod
    def match_score(cls, column_names: List[str]) -> int:
        """
        Count how many trigger_keywords appear in the combined column name string.
        Higher score = stronger match.

        Args:
            column_names: List of column names from the uploaded dataset.

        Returns:
            Integer match score (0 = no match).
        """
        combined = " ".join(column_names).lower()
        return sum(1 for kw in cls.trigger_keywords if kw in combined)

    @abstractmethod
    def ai_prompt_prefix(self) -> str:
        """
        Return a system context string prepended to every Gemini prompt.
        Tells Gemini what kind of data it is analysing.
        """

    @classmethod
    def render_label(cls) -> str:
        """Short label for display in the UI."""
        return f"{cls.name.upper()} — {cls.description}"
