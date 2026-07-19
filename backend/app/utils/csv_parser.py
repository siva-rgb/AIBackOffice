from __future__ import annotations

import io
from dataclasses import dataclass, field

import pandas as pd

# Tolerant CSV parsing with pandas (SKILL.md §2 — "pandas makes CSV parsing far
# simpler"). Handles header auto-detection, debit/credit split columns, BOM,
# and common date formats.


@dataclass
class ParsedRow:
    date: str
    description: str
    amount: float
    type: str  # 'income' | 'expense'


@dataclass
class ParseResult:
    rows: list[ParsedRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


_DATE_CANDIDATES = ["date", "transaction date", "posted"]
_DESC_CANDIDATES = ["description", "memo", "details", "narrative", "name"]
_AMOUNT_CANDIDATES = ["amount", "value"]
_DEBIT_CANDIDATES = ["debit", "withdrawal"]
_CREDIT_CANDIDATES = ["credit", "deposit"]
_TYPE_CANDIDATES = ["type"]


def _find_col(cols: list[str], candidates: list[str]) -> str | None:
    for c in candidates:
        if c in cols:
            return c
    for c in candidates:
        for col in cols:
            if c in col:
                return col
    return None


def _to_amount(raw) -> float | None:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip()
    if s == "" or s.lower() == "nan":
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.replace("(", "-").replace(")", "")
    for ch in "$£€,  ":
        s = s.replace(ch, "")
    try:
        val = float(s)
    except ValueError:
        return None
    return -abs(val) if neg else val


def parse_transactions_csv(text: str) -> ParseResult:
    result = ParseResult()
    text = text.lstrip("﻿")  # strip BOM
    try:
        df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    except Exception as exc:  # pragma: no cover - defensive
        result.errors.append(f"Could not read CSV: {exc}")
        return result

    if df.empty:
        result.errors.append("File has a header row but no data rows.")
        return result

    cols = [c.strip().lower() for c in df.columns]
    df.columns = cols

    date_col = _find_col(cols, _DATE_CANDIDATES)
    desc_col = _find_col(cols, _DESC_CANDIDATES)
    amount_col = _find_col(cols, _AMOUNT_CANDIDATES)
    debit_col = _find_col(cols, _DEBIT_CANDIDATES)
    credit_col = _find_col(cols, _CREDIT_CANDIDATES)
    type_col = _find_col(cols, _TYPE_CANDIDATES)

    if not date_col or not desc_col:
        result.errors.append(
            "Could not detect Date and Description columns. "
            "Expected headers like: Date,Description,Amount,Type"
        )
        return result
    if not amount_col and not debit_col and not credit_col:
        result.errors.append("Could not detect an Amount (or Debit/Credit) column.")
        return result

    for idx, row in df.iterrows():
        raw_date = str(row.get(date_col, "")).strip()
        description = str(row.get(desc_col, "")).strip()
        dt = pd.to_datetime(raw_date, errors="coerce", dayfirst=False)
        if pd.isna(dt) or not description:
            result.errors.append(f"Row {idx + 2}: skipped (missing/invalid date or description).")
            continue
        date_iso = dt.date().isoformat()

        if amount_col:
            amount = _to_amount(row.get(amount_col))
        else:
            debit = _to_amount(row.get(debit_col)) or 0.0
            credit = _to_amount(row.get(credit_col)) or 0.0
            amount = credit - abs(debit)
        if amount is None:
            result.errors.append(f"Row {idx + 2}: skipped (unreadable amount).")
            continue

        explicit = str(row.get(type_col, "")).strip().lower() if type_col else ""
        if explicit in ("income", "expense"):
            t = explicit
            amount = -abs(amount) if t == "expense" else abs(amount)
        else:
            t = "income" if amount >= 0 else "expense"

        result.rows.append(ParsedRow(date=date_iso, description=description, amount=round(amount, 2), type=t))

    return result
