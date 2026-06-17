from copy import deepcopy

from modules.analysis_cache import CURRENT_SCHEMA_VERSION
from modules.claude_analyzer import (
    is_legacy_scaled_financial_data_stale,
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
