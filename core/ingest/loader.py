"""
Resilient Ingestion Layer — loads real-world business exports, not just clean tables.

Handles:
  - Encoding + delimiter sniffing for CSV
  - Excel title rows above the real header (auto header-row detection)
  - Multi-sheet Excel (picks the first non-empty sheet, reports the rest)
  - Grand-total / total rows at the bottom
  - Currency strings: "₹1,23,456.00", "$1,234.50", "(500)" = negative, "45%"
  - Date columns stored as text (DD-MM-YYYY vs MM-DD-YYYY disambiguation)
  - Duplicate / blank column names

Every fix is recorded in a human-readable receipt shown to the user.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd
from loguru import logger

_CURRENCY_CHARS = "₹$€£"
_TIME_NAME_RE = re.compile(
    r"(date|time|day|month|year|period|created|updated|timestamp|doj|dob)", re.I
)
_DATEISH_RE = re.compile(r"^\s*\d{1,4}[-/\.\s]\w{1,9}[-/\.\s]\d{1,4}")
_TOTAL_RE = re.compile(r"^\s*(grand\s+)?(sub\s*)?total\b", re.I)


@dataclass
class IngestResult:
    df: pd.DataFrame
    receipt: List[str] = field(default_factory=list)
    currency_symbol: str = ""                       # most common symbol
    symbols: dict = field(default_factory=dict)     # per-column symbols (A5)
    sheet: Optional[str] = None
    other_sheets: List[str] = field(default_factory=list)


# ── Raw reading ───────────────────────────────────────────────────────────────

def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _read_raw_csv(data: bytes) -> pd.DataFrame:
    """Tolerant CSV read: sniffed delimiter, ragged rows padded, all cells str."""
    import csv as _csv
    text = _decode(data)
    sample = "\n".join(text.splitlines()[:30])
    try:
        delim = _csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except _csv.Error:
        delim = ","
    rows = list(_csv.reader(io.StringIO(text), delimiter=delim))
    if not rows:
        return pd.DataFrame()
    width = max(len(r) for r in rows)
    padded = [r + [None] * (width - len(r)) for r in rows]
    df = pd.DataFrame(padded)
    return df.replace({"": None})


def _read_raw_excel(data: bytes) -> tuple[pd.DataFrame, str, List[str]]:
    sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, dtype=object)
    best_name, best_df = None, None
    for name, sdf in sheets.items():
        sdf = sdf.dropna(how="all")
        if best_df is None or len(sdf) > len(best_df):
            if len(sdf) >= 2:
                best_name, best_df = name, sheets[name]
    if best_df is None:  # everything tiny — take the first sheet as-is
        best_name = list(sheets)[0]
        best_df = sheets[best_name]
    others = [n for n in sheets if n != best_name]
    return best_df, best_name, others


# ── Header detection ──────────────────────────────────────────────────────────

def _detect_header_row(raw: pd.DataFrame) -> int:
    """Find the row that holds column names (skips logo/title/date-range rows)."""
    limit = min(12, len(raw))
    for i in range(limit):
        row = raw.iloc[i]
        as_str = row.dropna().astype(str).str.strip()
        as_str = as_str[as_str != ""]
        if len(as_str) < 2 or len(as_str) / raw.shape[1] < 0.5:
            continue
        # Header cells are short and mostly non-numeric
        numeric_like = as_str.str.fullmatch(r"[\d\.,\-\s%()" + _CURRENCY_CHARS + r"]+").mean()
        if numeric_like < 0.3 and as_str.str.len().median() <= 40:
            return i
    return 0


def _apply_header(raw: pd.DataFrame, header_row: int, receipt: List[str]) -> pd.DataFrame:
    names = raw.iloc[header_row].astype(str).str.strip().tolist()
    df = raw.iloc[header_row + 1:].reset_index(drop=True)
    # Fill blank / nan names, dedupe
    seen: dict = {}
    cols = []
    for j, n in enumerate(names):
        n = n if n and n.lower() not in ("nan", "none", "") else f"column_{j + 1}"
        if n in seen:
            seen[n] += 1
            n = f"{n}.{seen[n]}"
        else:
            seen[n] = 0
        cols.append(n)
    df.columns = cols
    if header_row > 0:
        receipt.append(f"Skipped {header_row} title row(s) above the real header.")
    return df


# ── Structural cleanup ────────────────────────────────────────────────────────

def _drop_empty(df: pd.DataFrame, receipt: List[str]) -> pd.DataFrame:
    before_r, before_c = df.shape
    df = df.dropna(how="all").dropna(axis=1, how="all")
    dr, dc = before_r - df.shape[0], before_c - df.shape[1]
    if dr:
        receipt.append(f"Removed {dr} completely empty row(s).")
    if dc:
        receipt.append(f"Removed {dc} completely empty column(s).")
    return df.reset_index(drop=True)


def _drop_total_rows(df: pd.DataFrame, receipt: List[str]) -> pd.DataFrame:
    if df.empty:
        return df
    check_cols = df.columns[: min(2, df.shape[1])]
    tail_zone = range(max(0, len(df) - 3), len(df))
    drop_idx = []
    for i in tail_zone:
        for c in check_cols:
            v = df.iloc[i][c]
            if isinstance(v, str) and _TOTAL_RE.match(v):
                drop_idx.append(i)
                break
    if drop_idx:
        df = df.drop(index=df.index[drop_idx]).reset_index(drop=True)
        receipt.append(f"Removed {len(drop_idx)} total/subtotal row(s) at the bottom.")
    return df


# ── Type coercion ─────────────────────────────────────────────────────────────

def _try_numeric(series: pd.Series) -> tuple[Optional[pd.Series], str]:
    """Parse currency/percent/paren-negative strings. Returns (parsed, symbol) or (None, '')."""
    raw = series.dropna().astype(str).str.strip()
    raw = raw[raw != ""]
    if len(raw) < 3:
        return None, ""
    # Mostly alphabetic → not a number column
    alpha = raw.str.contains(r"[A-Za-z]", regex=True)
    if alpha.mean() > 0.2:
        return None, ""
    symbol = ""
    for ch in _CURRENCY_CHARS:
        if raw.str.contains(re.escape(ch)).mean() > 0.3:
            symbol = ch
            break

    def clean(s: pd.Series) -> pd.Series:
        s = s.astype(str).str.strip()
        s = s.str.replace(r"[,\s" + _CURRENCY_CHARS + r"]", "", regex=True)
        neg = s.str.match(r"^\(.*\)$")
        s = s.str.replace(r"[()%]", "", regex=True)
        out = pd.to_numeric(s, errors="coerce")
        return out.where(~neg, -out)

    parsed_sample = clean(raw)
    if parsed_sample.notna().mean() < 0.85:
        return None, ""
    full = clean(series.astype(str).where(series.notna(), other=np.nan))
    full[series.isna()] = np.nan
    return full, symbol


def _try_dates(series: pd.Series, name: str) -> Optional[pd.Series]:
    raw = series.dropna().astype(str).str.strip()
    raw = raw[raw != ""]
    if len(raw) < 3:
        return None
    name_hint = bool(_TIME_NAME_RE.search(name))
    content_hint = raw.head(50).str.match(_DATEISH_RE).mean() > 0.6
    if not (name_hint or content_hint):
        return None
    a = pd.to_datetime(series, errors="coerce", dayfirst=False)
    b = pd.to_datetime(series, errors="coerce", dayfirst=True)
    ok_a, ok_b = a.notna().mean(), b.notna().mean()
    if max(ok_a, ok_b) < 0.8:
        return None
    # Prefer day-first on ties (DD-MM is the common ambiguous export format)
    return b if ok_b >= ok_a else a


def _coerce_types(df: pd.DataFrame, receipt: List[str]):
    symbol = ""
    symbols: dict = {}
    n_num, n_date = 0, 0
    for col in df.columns:
        s = df[col]
        if not (s.dtype == object or str(s.dtype).startswith("str")):
            continue
        dates = _try_dates(s, col)
        if dates is not None:
            df[col] = dates
            n_date += 1
            continue
        nums, sym = _try_numeric(s)
        if nums is not None:
            df[col] = nums
            n_num += 1
            if sym:
                symbols[col] = sym
                if not symbol:
                    symbol = sym
        elif s.dtype == object:
            # normalize whitespace on text/categorical columns
            df[col] = s.where(s.isna(), s.astype(str).str.strip())
    if n_num:
        note = f"Parsed {n_num} text column(s) into numbers"
        note += f" (currency symbol {symbol} detected)." if symbol else "."
        receipt.append(note)
    if n_date:
        receipt.append(f"Parsed {n_date} text column(s) into dates.")
    return df, symbol, symbols


# ── Pivoted-report detection (months as columns) ─────────────────────────────

_MONTHISH_RE = re.compile(
    r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*([\s\-'/]*\d{2,4})?$"
    r"|^\d{4}[-/]\d{1,2}$", re.I,
)


def _maybe_unpivot(df: pd.DataFrame, receipt: List[str]) -> pd.DataFrame:
    month_cols = [c for c in df.columns if _MONTHISH_RE.match(str(c).strip())]
    id_cols = [c for c in df.columns if c not in month_cols]
    if len(month_cols) >= 5 and 1 <= len(id_cols) <= 4:
        long = df.melt(id_vars=id_cols, value_vars=month_cols,
                       var_name="period", value_name="value")
        long["period"] = pd.to_datetime(long["period"], errors="coerce", format="mixed")
        long["value"] = pd.to_numeric(long["value"], errors="coerce")
        if long["period"].notna().mean() > 0.7 and long["value"].notna().mean() > 0.5:
            receipt.append(
                f"Detected a pivoted report ({len(month_cols)} month columns) — "
                "reshaped to one row per period."
            )
            return long.dropna(subset=["period"])
    return df


# ── Public entry points ───────────────────────────────────────────────────────

def load_bytes(name: str, data: bytes) -> IngestResult:
    """Load a CSV/Excel file from raw bytes with full cleanup + receipt."""
    receipt: List[str] = []
    sheet, others = None, []
    if name.lower().endswith((".xlsx", ".xls")):
        raw, sheet, others = _read_raw_excel(data)
        if others:
            receipt.append(f"Workbook has {len(others) + 1} sheets — analysing '{sheet}'. "
                           f"Others: {', '.join(others[:5])}.")
    else:
        raw = _read_raw_csv(data)

    raw = raw.dropna(how="all", axis=1)
    if raw.empty:
        receipt.append("File contains no data rows.")
        return IngestResult(df=pd.DataFrame(), receipt=receipt, sheet=sheet,
                            other_sheets=others)
    header_row = _detect_header_row(raw)
    df = _apply_header(raw, header_row, receipt)
    df = _drop_empty(df, receipt)
    df = _drop_total_rows(df, receipt)
    df, symbol, symbols = _coerce_types(df, receipt)
    df = _maybe_unpivot(df, receipt)
    df = df.reset_index(drop=True)

    logger.info(f"Ingest: {name} → {df.shape[0]:,} rows × {df.shape[1]} cols; "
                f"{len(receipt)} fix(es) applied.")
    return IngestResult(df=df, receipt=receipt, currency_symbol=symbol,
                        symbols=symbols, sheet=sheet, other_sheets=others)


def load_uploaded(uploaded) -> IngestResult:
    """Load a Streamlit UploadedFile."""
    return load_bytes(uploaded.name, uploaded.getvalue())
