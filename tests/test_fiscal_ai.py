"""Pinning tests for the fiscal.ai companyKey boundary normalization.

fiscal.ai keys TSX names on the bare symbol (TSX_RY), not the
yfinance-style suffixed form the app carries (RY.TO). Verified live
2026-07-07: TSX_RY.TO -> 404 "data not yet available"; TSX_RY -> resolves
(403 plan-gated on the free tier). The strip happens once at the boundary
so every fiscal.ai endpoint builds the same catalog-correct key.
"""

from modules.fiscal_ai import _company_key


def test_tsx_suffix_stripped():
    assert _company_key("RY.TO", "TSX") == "TSX_RY"
    assert _company_key("SU.TO", "TSX") == "TSX_SU"


def test_tsxv_suffix_stripped():
    assert _company_key("NFG.V", "TSX") == "TSX_NFG"


def test_us_tickers_unchanged():
    assert _company_key("AAPL", "NASDAQ") == "NASDAQ_AAPL"
    assert _company_key("JPM", "NYSE") == "NYSE_JPM"


def test_unit_ticker_keeps_unit_marker():
    # REIT units: only the exchange suffix strips; the unit marker stays.
    assert _company_key("REI-UN.TO", "TSX") == "TSX_REI-UN"


def test_case_and_whitespace_normalized():
    assert _company_key("  ry.to ", "TSX") == "TSX_RY"
