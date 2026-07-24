"""Regression cover for the bank-CSV parser (M6).

`parse_transactions_csv` is the front door for bookkeeping — a user's real bank
export. It must tolerate the messy shapes banks actually produce (split
debit/credit columns, parenthesised negatives, currency symbols, a BOM, mixed
date formats) and reject rows it can't trust rather than inventing numbers.
"""
from __future__ import annotations

from app.utils.csv_parser import _to_amount, parse_transactions_csv


def test_simple_amount_and_type_inference():
    csv = "Date,Description,Amount\n2026-01-05,Client payment,1500\n2026-01-06,Coffee,-4.50\n"
    r = parse_transactions_csv(csv)
    assert r.errors == []
    assert [(x.description, x.amount, x.type) for x in r.rows] == [
        ("Client payment", 1500.0, "income"),
        ("Coffee", -4.5, "expense"),
    ]


def test_split_debit_credit_columns():
    csv = "Date,Narrative,Debit,Credit\n2026-02-01,Invoice paid,,2000\n2026-02-02,Software,50,\n"
    r = parse_transactions_csv(csv)
    assert [(x.amount, x.type) for x in r.rows] == [(2000.0, "income"), (-50.0, "expense")]


def test_parenthesised_negatives_and_currency_symbols():
    assert _to_amount("(1,234.50)") == -1234.5
    assert _to_amount("$1,000") == 1000.0
    assert _to_amount("£2.50") == 2.5
    assert _to_amount("nan") is None
    assert _to_amount("") is None


def test_bom_and_header_case_insensitivity():
    csv = "﻿DATE,Memo,VALUE\n2026-03-03,Retainer,900\n"
    r = parse_transactions_csv(csv)
    assert len(r.rows) == 1 and r.rows[0].amount == 900.0


def test_explicit_type_column_overrides_sign():
    csv = "Date,Description,Amount,Type\n2026-04-01,Refund issued,200,expense\n"
    r = parse_transactions_csv(csv)
    # Explicit type wins: a positive amount marked 'expense' becomes negative.
    assert r.rows[0].type == "expense" and r.rows[0].amount == -200.0


def test_bad_rows_are_skipped_with_an_error_not_dropped_silently():
    csv = ("Date,Description,Amount\n"
           "not-a-date,Ghost,100\n"       # bad date
           "2026-05-01,,50\n"             # missing description
           "2026-05-02,Good,75\n")        # the only valid row
    r = parse_transactions_csv(csv)
    assert len(r.rows) == 1 and r.rows[0].description == "Good"
    assert len(r.errors) == 2   # both bad rows reported, not swallowed


def test_missing_required_columns_is_a_clear_error():
    r = parse_transactions_csv("Foo,Bar\n1,2\n")
    assert r.rows == []
    assert any("Date and Description" in e for e in r.errors)


def test_header_only_file_reports_no_data():
    r = parse_transactions_csv("Date,Description,Amount\n")
    assert r.rows == []
    assert any("no data" in e.lower() for e in r.errors)
