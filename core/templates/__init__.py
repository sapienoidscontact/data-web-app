from .base import BaseTemplate
from .sales import SalesTemplate
from .hr import HRTemplate
from .finance import FinanceTemplate
from typing import List, Optional, Type

_ALL_TEMPLATES: List[Type[BaseTemplate]] = [SalesTemplate, HRTemplate, FinanceTemplate]

# Domain name → template class
TEMPLATE_REGISTRY = {t.name: t for t in _ALL_TEMPLATES}


def auto_detect_template(column_names: List[str]) -> Optional[Type[BaseTemplate]]:
    """
    Score all templates against column names and return the best match.

    Args:
        column_names: List of column name strings from the dataset.

    Returns:
        The best-matching Template class, or None if no template scores > 0.
    """
    scores = {t: t.match_score(column_names) for t in _ALL_TEMPLATES}
    best_template = max(scores, key=lambda t: scores[t])
    return best_template if scores[best_template] > 0 else None


def get_template(domain: str) -> Optional[Type[BaseTemplate]]:
    """Return a Template class by domain name, or None."""
    return TEMPLATE_REGISTRY.get(domain)


__all__ = [
    "BaseTemplate", "SalesTemplate", "HRTemplate", "FinanceTemplate",
    "auto_detect_template", "get_template", "TEMPLATE_REGISTRY",
]
