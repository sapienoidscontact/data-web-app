"""
Mapping Memory (D1) — persistent registry so month 2 is zero-click.

When the user confirms a preset/mapping (by editing the mapping or overriding
the preset), the decision is saved keyed by the dataset's column fingerprint.
The next upload with the same columns skips detection and applies the
remembered mapping directly.

Storage: JSON at ~/.sapienoids/registry.json — survives app restarts, never
contains data values, only column names and the mapping.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

_REG_DIR = Path(os.environ.get("SAPIENOIDS_HOME", str(Path.home()))) / ".sapienoids"
_REG_FILE = _REG_DIR / "registry.json"


def column_fingerprint(columns: List[str]) -> str:
    """Order-independent fingerprint of a dataset's column names."""
    normalized = sorted(str(c).strip().lower() for c in columns)
    return hashlib.sha1("|".join(normalized).encode("utf-8")).hexdigest()[:16]


def _load() -> Dict:
    try:
        if _REG_FILE.exists():
            return json.loads(_REG_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug(f"Mapping registry unreadable: {exc}")
    return {}


def _save(reg: Dict) -> None:
    try:
        _REG_DIR.mkdir(parents=True, exist_ok=True)
        _REG_FILE.write_text(json.dumps(reg, indent=1), encoding="utf-8")
    except Exception as exc:
        logger.debug(f"Mapping registry not saved: {exc}")


def remember(columns: List[str], preset_name: str,
             mapping: Dict[str, str]) -> None:
    """Persist a confirmed preset + mapping for this column set."""
    reg = _load()
    reg[column_fingerprint(columns)] = {
        "preset": preset_name,
        "mapping": mapping,
        "columns": [str(c) for c in columns],
        "saved": datetime.now().isoformat(timespec="seconds"),
    }
    _save(reg)
    logger.info(f"Mapping remembered for {len(columns)} columns "
                f"(preset={preset_name}).")


def recall(columns: List[str]) -> Optional[Dict]:
    """Return {'preset', 'mapping'} if this column set was seen before and
    the remembered mapping still fits the current columns."""
    entry = _load().get(column_fingerprint(columns))
    if not entry:
        return None
    colset = set(map(str, columns))
    mapping = {f: c for f, c in entry.get("mapping", {}).items() if c in colset}
    if not mapping:
        return None
    return {"preset": entry.get("preset"), "mapping": mapping,
            "saved": entry.get("saved", "")}


def forget(columns: List[str]) -> None:
    reg = _load()
    reg.pop(column_fingerprint(columns), None)
    _save(reg)
