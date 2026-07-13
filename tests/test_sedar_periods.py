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

from modules.sedar_periods import (
    parse_period_window,
    sedar_period_keys,
    sedar_statement_rows,
    select_current_period_value,
)

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


# ---------------------------------------------------------------------------
# CB-040 pins — window-class parser + quarter-only selection mode
# (spec: docs/SEDAR_INTERIM_SPEC.md)
# ---------------------------------------------------------------------------

def test_parse_period_window_classes():
    assert parse_period_window("Three Months Ended Jun 30 2026") == {"window": "Q", "year": 2026}
    assert parse_period_window("Six Months Ended Jun 30 2026") == {"window": "H1", "year": 2026}
    assert parse_period_window("Nine months ended September 30, 2025") == {"window": "9M", "year": 2025}
    assert parse_period_window("Twelve months ended Dec 31 2024") == {"window": "FY", "year": 2024}
    assert parse_period_window("Year Ended Dec 31 2024") == {"window": "FY", "year": 2024}


def test_parse_period_window_honest_exclusions():
    # No window declaration, no year, or an AMBIGUOUS combined header —
    # all unusable for pairing (the label-parse analogue of CB-039's
    # duration-taxonomy exclusion).
    assert parse_period_window("Dec 31 2024") is None                       # instant date
    assert parse_period_window("Three Months Ended") is None                # no year
    assert parse_period_window("Three and six months ended Jun 30 2026") is None  # ambiguous
    assert parse_period_window("") is None
    assert parse_period_window(None) is None


def test_quarter_only_pack_pairs_within_the_window_class():
    """THE LOCATED CB-016 TRAP, pinned as a regression case: pre-CB-040 the
    year-sort fallback paired current = 3-month 2026 with prior = the SAME
    YEAR'S six-month column. Window-class pairing makes that impossible."""
    items = [{"label": "Revenue", "values": {
        "Three Months Ended Jun 30 2026": 25,
        "Three Months Ended Jun 30 2025": 22,
        "Six Months Ended Jun 30 2026": 48,
        "Six Months Ended Jun 30 2025": 41,
    }}]
    current, prior = sedar_period_keys(items)
    assert current == "Three Months Ended Jun 30 2026"
    assert prior == "Three Months Ended Jun 30 2025"      # NOT the 6-month column


def test_quarter_only_pack_without_comparative_gives_no_prior():
    """Same class one year earlier or nothing — a different window class is
    never a substitute prior."""
    items = [{"label": "Revenue", "values": {
        "Three Months Ended Jun 30 2026": 25,
        "Six Months Ended Jun 30 2026": 48,
        "Six Months Ended Jun 30 2025": 41,
    }}]
    current, prior = sedar_period_keys(items)
    assert current == "Three Months Ended Jun 30 2026"
    assert prior is None


def test_ytd_only_pack_pairs_the_h1_columns():
    """A filer printing only YTD cash-flow columns gets the honest H1 pair
    (labeled as such) — never a cross-class mix."""
    items = [{"label": "Operating activities", "values": {
        "Six Months Ended Jun 30 2026": 48,
        "Six Months Ended Jun 30 2025": 41,
    }}]
    assert sedar_period_keys(items) == (
        "Six Months Ended Jun 30 2026",
        "Six Months Ended Jun 30 2025",
    )


def test_twelve_months_header_beats_quarter_windows():
    """A 'twelve months' annual header (which the annual predicate misses)
    wins over quarter windows — CB-016's annual-first spirit."""
    items = [{"label": "Revenue", "values": {
        "Three Months Ended Dec 31 2024": 25,
        "Three Months Ended Dec 31 2023": 22,
        "Twelve Months Ended Dec 31 2024": 100,
        "Twelve Months Ended Dec 31 2023": 90,
    }}]
    assert sedar_period_keys(items) == (
        "Twelve Months Ended Dec 31 2024",
        "Twelve Months Ended Dec 31 2023",
    )


def test_interim_balance_sheet_instant_pair_unchanged():
    """An interim balance sheet prints as-of vs prior YEAR-END instants —
    the pinned year-sort fallback already picks the filer's own comparative."""
    items = [{"label": "Total assets", "values": {
        "Jun 30 2026": 500,
        "Dec 31 2025": 450,
    }}]
    assert sedar_period_keys(items) == ("Jun 30 2026", "Dec 31 2025")


def test_mapper_feed_agrees_with_row_layer_on_ytd_first_column_order():
    """CB-040 layer-agreement pin: the mapper feed
    (select_current_period_value, consumed by
    sedar_extractor._first_statement_value and the registry script) picks
    the SAME column as the row layer even when the filer prints the YTD
    column FIRST — the old first-column fallback would have mapped the
    6-month value while the rows showed the discrete quarter (the CB-016
    layer-divergence class)."""
    values = {
        "Six Months Ended Jun 30 2026": 48,
        "Six Months Ended Jun 30 2025": 41,
        "Three Months Ended Jun 30 2026": 25,
        "Three Months Ended Jun 30 2025": 22,
    }
    assert select_current_period_value(values) == 25       # NOT 48 (first column)
    current, _prior = sedar_period_keys([{"label": "Revenue", "values": values}])
    assert values[current] == select_current_period_value(values)


def test_mapper_feed_annual_selection_unchanged():
    """The delegation preserves the pinned annual behavior byte-for-byte
    (the corpus-wide proof is the value-snapshot suite)."""
    values = {
        "Three Months Ended Dec 31 2024": 11_064,
        "Three Months Ended Dec 31 2023": 10_002,
        "Year Ended Dec 31 2024": 41_509,
        "Year Ended Dec 31 2023": 40_835,
    }
    assert select_current_period_value(values) == 41_509
    assert select_current_period_value({}) is None
    assert select_current_period_value(None) is None
