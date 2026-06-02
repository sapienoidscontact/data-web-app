"""
Entity Registry — stores and retrieves SchemaProfile + domain for the session.

Kept deliberately simple for a single-user local app.
In a multi-user deployment this would be backed by a database or cache.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from .detector import SchemaProfile

# ── In-memory registry (process lifetime) ────────────────────────────────────
_registry: Dict[str, Tuple[SchemaProfile, str]] = {}


def register(filename: str, schema: SchemaProfile, domain: str) -> None:
    """
    Store a SchemaProfile and its detected domain under the given filename key.

    Args:
        filename: The uploaded file name — used as the registry key.
        schema:   The SchemaProfile produced by detect_schema().
        domain:   The domain string from map_domain() ('sales', 'hr', etc.).
    """
    _registry[filename] = (schema, domain)


def get(filename: str) -> Optional[Tuple[SchemaProfile, str]]:
    """
    Retrieve a previously registered (SchemaProfile, domain) pair.

    Args:
        filename: The key used when register() was called.

    Returns:
        (SchemaProfile, domain) tuple, or None if not found.
    """
    return _registry.get(filename)


def clear() -> None:
    """Remove all entries from the registry (e.g. on session reset)."""
    _registry.clear()


def all_keys() -> list:
    """Return all registered filenames."""
    return list(_registry.keys())
