"""CB-016 period-picker pins (modules/sedar_periods.py).

The picker now carries the same annual preference as the canonical mapper,
so the row layer, fiscal_year label, and mapping.mapped agree by
construction on mixed-period Q4 packs (the CNQ FY2024 drift incident).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.sedar_periods import sedar_period_keys, sedar_statement_rows

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _cnq_income() -> list[dict]:
    fixture = json.loads(
        (FIXTURES_DIR / "cnq_fy2024_sedar.json").read_text(encoding="utf-8")
    )
    return fixture["statements"]["income_statement"]


def test_cnq_mixed_period_pack_picks_annual_current_and_annual_prior():
    """The incident fix: CNQ's four-column Q4 pack (quarterly columns FIRST)
    now picks the annual 2024 column as current and annual 2023 as prior —
    pre-fix it picked quarterly-2024 current and annual-2024 prior (a
    degenerate same-year prior, the PLD XBRL shape on the SEDAR path)."""
    current, prior = sedar_period_keys(_cnq_income())
    assert current == "Year Ended Dec 31 2024"
    assert prior == "Year Ended Dec 31 2023"


def test_cnq_statement_rows_now_carry_annual_values():
    income = _cnq_income()
    current, prior = sedar_period_keys(income)
    rows = sedar_statement_rows(income, current, prior)
    product_sales = next(r for r in rows if r["line_item"] == "Product sales")
    assert product_sales["value"] == 41509        # was 11064 (quarterly) pre-fix
    assert product_sales["value_prior"] == 40835  # was 41509 (same-year annual) pre-fix


def test_annual_only_columns_unchanged():
    items = [{"label": "Revenue", "values": {
        "Year Ended Dec 31 2025": 100,
        "Year Ended Dec 31 2024": 90,
    }}]
    assert sedar_period_keys(items) == ("Year Ended Dec 31 2025", "Year Ended Dec 31 2024")


def test_instant_date_balance_sheet_columns_unchanged():
    """Balance sheets carry instant dates with no annual labels — the
    original (year, -index) behavior is preserved."""
    items = [{"label": "Total assets", "values": {
        "Dec 31 2024": 500,
        "Dec 31 2023": 450,
    }}]
    assert sedar_period_keys(items) == ("Dec 31 2024", "Dec 31 2023")


def test_single_annual_column_gives_no_prior_rather_than_quarterly():
    """When only ONE annual column exists, prior is None — a quarterly prior
    would be exactly the wrong-class comparison this ruling removes."""
    items = [{"label": "Revenue", "values": {
        "Three Months Ended Dec 31 2024": 25,
        "Three Months Ended Dec 31 2023": 22,
        "Year Ended Dec 31 2024": 100,
    }}]
    current, prior = sedar_period_keys(items)
    assert current == "Year Ended Dec 31 2024"
    assert prior is None


def test_no_year_labels_fall_back_to_column_order():
    items = [{"label": "Revenue", "values": {"Current": 10, "Prior": 9}}]
    assert sedar_period_keys(items) == ("Current", "Prior")


def test_empty_statements_fall_back_to_default():
    assert sedar_period_keys([]) == ("Current", None)
