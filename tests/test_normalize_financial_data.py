from copy import deepcopy

from modules.analysis_cache import CURRENT_SCHEMA_VERSION
from modules.claude_analyzer import (
    is_legacy_scaled_financial_data_stale,
    is_per_share_line_item,
    normalize_financial_data,
)


def test_normalize_preserves_cad_currency_and_is_idempotent():
    financial_data = {
        "company_name": "NGEx-shaped CAD filer",
        "currency": "CAD",
        "scale": "millions",
        "income_statement": [
            {"line_item": "Net loss for the year", "value": -123.3, "value_prior": -63.6}
        ],
        "balance_sheet": [
            {"line_item": "Total assets", "value": 456.6, "value_prior": 208.6}
        ],
        "cash_flow_statement": [
            {"line_item": "Cash, end of the year", "value": 192.5, "value_prior": 153.4}
        ],
        "revenue": 10,
        "net_income": -123.3,
        "total_assets": 456.6,
    }

    normalized = normalize_financial_data(deepcopy(financial_data))

    assert normalized["currency"] == "CAD"
    assert normalized["_normalized"] is True
    assert normalized["income_statement"][0]["value"] == -123_300_000
    assert normalized["income_statement"][0]["value_prior"] == -63_600_000
    assert normalized["balance_sheet"][0]["value"] == 456_600_000
    assert normalized["cash_flow_statement"][0]["value"] == 192_500_000
    assert normalized["revenue"] == 10_000_000
    assert normalized["net_income"] == -123_300_000
    assert normalized["total_assets"] == 456_600_000

    renormalized = normalize_financial_data(deepcopy(normalized))

    assert renormalized == normalized


def test_normalize_preserves_already_raw_fmp_data_with_numeric_scale():
    financial_data = {
        "company_name": "FMP-shaped filer",
        "currency": "USD",
        "scale": 1_000_000,
        "_normalized": True,
        "income_statement": [
            {"line_item": "Revenue", "value": 130_497_000_000, "value_prior": 96_773_000_000}
        ],
        "balance_sheet": [
            {"line_item": "Total assets", "value": 111_601_000_000, "value_prior": 65_728_000_000}
        ],
        "cash_flow_statement": [
            {"line_item": "Free cash flow", "value": 60_853_000_000, "value_prior": 27_021_000_000}
        ],
        "revenue": 130_497_000_000,
        "net_income": 72_880_000_000,
        "free_cash_flow": 60_853_000_000,
        "total_assets": 111_601_000_000,
    }

    normalized = normalize_financial_data(deepcopy(financial_data))

    assert normalized["currency"] == "USD"
    assert normalized["_normalized"] is True
    assert normalized == financial_data


def test_legacy_scaled_stored_data_is_stale_before_reload_normalization():
    stored = {
        "company_name": "Legacy REIT entry",
        "currency": "USD",
        "scale": "thousands",
        "income_statement": [
            {"line_item": "Revenue", "value": 1_176_428_000, "value_prior": 1_000_000_000}
        ],
        "revenue": 1_176_428_000,
    }

    assert is_legacy_scaled_financial_data_stale(
        stored,
        schema_version=CURRENT_SCHEMA_VERSION - 1,
        current_schema_version=CURRENT_SCHEMA_VERSION,
    )

    reload_value = stored["income_statement"][0]["value"]
    assert reload_value == 1_176_428_000
    assert reload_value != 1_176_428_000_000


def test_normalize_does_not_scale_per_share_line_items():
    """Per-share figures (EPS, DPS) must NOT be multiplied by the unit scale."""
    financial_data = {
        "company_name": "Thousands filer with EPS",
        "currency": "USD",
        "scale": "thousands",
        "income_statement": [
            {"line_item": "Net income for the year", "value": 4_500_000, "value_prior": 1_900_000},
            {"line_item": "Earnings per share - Basic", "value": 8.9, "value_prior": 3.8},
            {"line_item": "Earnings per share - Diluted", "value": 8.7, "value_prior": 3.7},
            {"line_item": "Dividends per share", "value": 1.6, "value_prior": 1.4},
            {"line_item": "Cash dividends declared per common share", "value": 1.6, "value_prior": 1.4},
        ],
    }

    normalized = normalize_financial_data(deepcopy(financial_data))
    rows = normalized["income_statement"]

    # Regular line item is scaled by 1000.
    assert rows[0]["value"] == 4_500_000_000
    assert rows[0]["value_prior"] == 1_900_000_000
    # Per-share rows are left untouched (no 1000x), including "per common share".
    assert rows[1]["value"] == 8.9
    assert rows[1]["value_prior"] == 3.8
    assert rows[2]["value"] == 8.7
    assert rows[3]["value"] == 1.6
    assert rows[4]["value"] == 1.6
    assert rows[4]["value_prior"] == 1.4


def test_is_per_share_line_item_detection():
    assert is_per_share_line_item("Earnings per share - Basic")
    assert is_per_share_line_item("Net income per share – diluted")
    assert is_per_share_line_item("Dividends per share")
    assert is_per_share_line_item("Cash dividends declared per common share")
    assert is_per_share_line_item("Net income per diluted share")
    assert is_per_share_line_item("Diluted EPS")
    assert not is_per_share_line_item("Weighted average shares outstanding")
    assert not is_per_share_line_item("Share based liabilities (Note 17)")
    assert not is_per_share_line_item("Revenue")
    assert not is_per_share_line_item("Total assets")
    assert not is_per_share_line_item(None)
