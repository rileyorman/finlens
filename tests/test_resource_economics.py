from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from modules.economics import resource_economics
from modules.economics.resource_economics import build_resource_economics_snapshot


class FakeTicker:
    def __init__(self, symbol: str):
        self.symbol = symbol
        if symbol == "AEM.TO":
            self.fast_info = SimpleNamespace(
                last_price=120.0,
                regular_market_price=None,
                market_cap=60_000_000_000,
                shares=500_000_000,
                currency="USD",
            )
        elif symbol == "GC=F":
            self.fast_info = SimpleNamespace(
                last_price=2400.0,
                regular_market_price=None,
                market_cap=None,
                shares=None,
            )
        else:
            self.fast_info = SimpleNamespace(
                last_price=None,
                regular_market_price=None,
                market_cap=None,
                shares=None,
            )
        self.info = {}

    def history(self, period: str = "1y"):
        if self.symbol == "GC=F":
            return pd.DataFrame(
                {"Close": [2100.0, 2250.0, 2400.0]},
                index=pd.to_datetime(["2025-01-01", "2025-06-30", "2025-12-31"]),
            )
        return pd.DataFrame()


class FallbackCommodityTicker:
    def __init__(self, symbol: str):
        self.symbol = symbol
        if symbol == "GC=F":
            raise RuntimeError("primary commodity proxy failed")
        if symbol == "GLD":
            self.fast_info = SimpleNamespace(
                last_price=225.0,
                regular_market_price=None,
                market_cap=None,
                shares=None,
            )
        elif symbol == "AEM.TO":
            self.fast_info = SimpleNamespace(
                last_price=120.0,
                regular_market_price=None,
                market_cap=60_000_000_000,
                shares=500_000_000,
            )
        else:
            self.fast_info = SimpleNamespace(
                last_price=None,
                regular_market_price=None,
                market_cap=None,
                shares=None,
            )
        self.info = {}

    def history(self, period: str = "1y"):
        if self.symbol == "GLD":
            return pd.DataFrame(
                {"Close": [200.0, 210.0, 225.0]},
                index=pd.to_datetime(["2025-01-01", "2025-06-30", "2025-12-31"]),
            )
        return pd.DataFrame()


class CompanyLookupFailureTicker:
    def __init__(self, symbol: str):
        self.symbol = symbol
        if symbol == "AEM.TO":
            raise RuntimeError("company lookup failed")
        if symbol == "GC=F":
            self.fast_info = SimpleNamespace(
                last_price=2400.0,
                regular_market_price=None,
                market_cap=None,
                shares=None,
            )
        else:
            self.fast_info = SimpleNamespace(
                last_price=None,
                regular_market_price=None,
                market_cap=None,
                shares=None,
            )
        self.info = {}

    def history(self, period: str = "1y"):
        if self.symbol == "GC=F":
            return pd.DataFrame(
                {"Close": [2100.0, 2400.0]},
                index=pd.to_datetime(["2025-01-01", "2025-12-31"]),
            )
        return pd.DataFrame()


class NoListingCurrencyTicker(FakeTicker):
    """FakeTicker whose company listing carries no currency anywhere."""

    def __init__(self, symbol: str):
        super().__init__(symbol)
        if hasattr(self.fast_info, "currency"):
            del self.fast_info.currency


def test_resource_economics_computes_core_metrics_with_mocked_yfinance(monkeypatch):
    monkeypatch.setattr(resource_economics.yf, "Ticker", FakeTicker)
    cache = {}

    result = build_resource_economics_snapshot(
        {
            "revenue": 11_907_851,
            "net_income": 4_461_461,
            "production_costs": 3_340_684,
            "mine_development_amortization": 1_645_297,
            "sector_inferred": "Gold Mining",
            "currency": "USD",
            "scale": "thousands",
            "fiscal_year_end": "2025-12-31",
        },
        "AEM.TO",
        cache=cache,
    )

    assert result["metrics"]["earnings_yield"] == 4_461_461_000 / 60_000_000_000
    assert result["metrics"]["revenue_to_market_cap"] == 11_907_851_000 / 60_000_000_000
    assert result["metrics"]["net_margin"] == 4_461_461_000 / 11_907_851_000
    assert result["market_data"]["company"]["share_price"] == 120.0
    assert result["market_data"]["company"]["market_cap"] == 60_000_000_000
    assert result["market_data"]["company"]["shares_outstanding"] == 500_000_000
    assert result["commodity_spot_price"]["value"] == 2400.0
    assert result["commodity_spot_price"]["proxy_used"] == "GC=F"
    assert result["commodity_trend"]["points"] == [
        {"date": "2025-01-01", "close": 2100.0},
        {"date": "2025-06-30", "close": 2250.0},
        {"date": "2025-12-31", "close": 2400.0},
    ]
    assert result["metadata"]["missing_inputs"] == []
    # Matched filing/listing currency (USD/USD): guard passes, nothing suppressed.
    guard = result["metadata"]["currency_guard"]
    assert guard["status"] == "match"
    assert guard["suppressed"] is False
    assert guard["note"] is None
    assert guard["filing_currency"] == "USD"
    assert guard["listing_currency"] == "USD"


def test_currency_mismatch_suppresses_market_cap_ratios_with_note(monkeypatch):
    # CAD filing figures vs USD listing market cap — the NGEx-class bug. The
    # market-cap ratios must be suppressed with an honest note; net_margin is
    # intra-filing (currency cancels) and must still compute.
    monkeypatch.setattr(resource_economics.yf, "Ticker", FakeTicker)

    result = build_resource_economics_snapshot(
        {
            "revenue": 11_907_851,
            "net_income": 4_461_461,
            "sector_inferred": "Gold Mining",
            "currency": "CAD",
            "scale": "thousands",
            "fiscal_year_end": "2025-12-31",
        },
        "AEM.TO",
        cache={},
    )

    assert result["metrics"]["earnings_yield"] is None
    assert result["metrics"]["revenue_to_market_cap"] is None
    assert result["metrics"]["net_margin"] == 4_461_461_000 / 11_907_851_000

    guard = result["metadata"]["currency_guard"]
    assert guard["status"] == "mismatch"
    assert guard["suppressed"] is True
    assert "CAD" in guard["note"] and "USD" in guard["note"]
    assert result["metadata"]["none_reasons"]["earnings_yield"] == guard["note"]
    assert result["metadata"]["none_reasons"]["revenue_to_market_cap"] == guard["note"]
    # Cheap-company flag depends on earnings_yield — it must carry the honest
    # currency reason, not silently flag off a wrong number.
    assert result["cheap_company_or_cheap_sector"]["company_flag"] is None
    assert result["cheap_company_or_cheap_sector"]["reason"] == guard["note"]


def test_currency_labels_with_scale_suffix_compare_by_code(monkeypatch):
    # Real filing currency labels carry scale suffixes ("USD, in thousands",
    # "CAD, in ones"). The guard must compare 3-letter codes, not raw labels —
    # otherwise a matched USD filer with a suffixed label is falsely suppressed.
    monkeypatch.setattr(resource_economics.yf, "Ticker", FakeTicker)

    matched = build_resource_economics_snapshot(
        {
            "revenue": 11_907_851,
            "net_income": 4_461_461,
            "sector_inferred": "Gold Mining",
            "currency": "USD, in thousands",
            "scale": "thousands",
        },
        "AEM.TO",
        cache={},
    )
    assert matched["metadata"]["currency_guard"]["status"] == "match"
    assert matched["metadata"]["currency_guard"]["filing_currency"] == "USD"
    assert matched["metrics"]["earnings_yield"] == 4_461_461_000 / 60_000_000_000

    mismatched = build_resource_economics_snapshot(
        {
            "revenue": 11_907_851,
            "net_income": 4_461_461,
            "sector_inferred": "Gold Mining",
            "currency": "CAD, in ones",
            "scale": "ones",
        },
        "AEM.TO",
        cache={},
    )
    guard = mismatched["metadata"]["currency_guard"]
    assert guard["status"] == "mismatch"
    assert guard["filing_currency"] == "CAD"
    assert mismatched["metrics"]["earnings_yield"] is None


def test_unknown_listing_currency_suppresses_market_cap_ratios_with_note(monkeypatch):
    # Listing currency undeterminable (neither fast_info nor info carries it):
    # cannot confirm it matches the filing currency, so suppress honestly.
    monkeypatch.setattr(resource_economics.yf, "Ticker", NoListingCurrencyTicker)

    result = build_resource_economics_snapshot(
        {
            "revenue": 11_907_851,
            "net_income": 4_461_461,
            "sector_inferred": "Gold Mining",
            "currency": "CAD",
            "scale": "thousands",
            "fiscal_year_end": "2025-12-31",
        },
        "AEM.TO",
        cache={},
    )

    assert result["metrics"]["earnings_yield"] is None
    assert result["metrics"]["revenue_to_market_cap"] is None
    assert result["metrics"]["net_margin"] == 4_461_461_000 / 11_907_851_000

    guard = result["metadata"]["currency_guard"]
    assert guard["status"] == "unknown"
    assert guard["suppressed"] is True
    assert guard["listing_currency"] is None
    assert "listing currency" in guard["note"]
    assert result["metadata"]["none_reasons"]["earnings_yield"] == guard["note"]
    assert result["metadata"]["none_reasons"]["revenue_to_market_cap"] == guard["note"]


def test_commodity_proxy_falls_back_when_primary_fails(monkeypatch):
    monkeypatch.setattr(resource_economics.yf, "Ticker", FallbackCommodityTicker)

    result = build_resource_economics_snapshot(
        {
            "revenue": 11_907_851,
            "net_income": 4_461_461,
            "sector_inferred": "Gold Mining",
            "scale": "thousands",
        },
        "AEM.TO",
        cache={},
    )

    assert result["commodity_spot_price"]["value"] == 225.0
    assert result["commodity_spot_price"]["proxy_used"] == "GLD"
    assert result["commodity_spot_price"]["proxy_role"] == "fallback"
    assert result["market_data"]["commodity"]["proxy_used"] == "GLD"
    assert result["metadata"]["proxy_used"] == "GLD"
    assert result["metadata"]["fetch_errors"]["commodity"] is None


def test_company_market_data_exception_returns_none_metrics_with_reasons(monkeypatch):
    monkeypatch.setattr(resource_economics.yf, "Ticker", CompanyLookupFailureTicker)

    result = build_resource_economics_snapshot(
        {
            "revenue": 11_907_851,
            "net_income": 4_461_461,
            "sector_inferred": "Gold Mining",
            "scale": "thousands",
        },
        "AEM.TO",
        cache={},
    )

    assert result["market_data"]["company"]["market_cap"] is None
    assert result["metrics"]["earnings_yield"] is None
    assert result["metrics"]["revenue_to_market_cap"] is None
    assert result["metrics"]["net_margin"] == 4_461_461_000 / 11_907_851_000
    assert "market_cap" in result["metadata"]["missing_inputs"]
    assert result["metadata"]["none_reasons"]["earnings_yield"] == (
        "missing required inputs: market_cap"
    )
    assert result["metadata"]["none_reasons"]["revenue_to_market_cap"] == (
        "missing required inputs: market_cap"
    )
    assert "company lookup failed" in result["metadata"]["fetch_errors"]["company"]
    assert result["commodity_spot_price"]["proxy_used"] == "GC=F"


def test_resource_economics_missing_net_income_returns_none_with_reason(monkeypatch):
    monkeypatch.setattr(resource_economics.yf, "Ticker", FakeTicker)

    result = build_resource_economics_snapshot(
        {
            "revenue": 11_907_851,
            "sector_inferred": "Gold Mining",
            "currency": "USD",
            "scale": "thousands",
            "fiscal_year_end": "2025-12-31",
        },
        "AEM.TO",
        cache={},
    )

    assert result["metrics"]["earnings_yield"] is None
    assert result["metrics"]["net_margin"] is None
    assert result["metrics"]["revenue_to_market_cap"] == 11_907_851_000 / 60_000_000_000
    assert "net_income" in result["metadata"]["missing_inputs"]
    assert result["metadata"]["none_reasons"]["earnings_yield"] == (
        "missing required inputs: net_income"
    )
    assert result["metadata"]["none_reasons"]["net_margin"] == (
        "missing required inputs: net_income"
    )


def test_gold_mining_selects_gold_primary_proxy(monkeypatch):
    monkeypatch.setattr(resource_economics.yf, "Ticker", FakeTicker)

    result = build_resource_economics_snapshot(
        {
            "mapping": {
                "mapped": {
                    "revenue": {"value": 1000},
                    "net_income": {"value": 100},
                }
            },
            "sector_inferred": "Gold Mining",
            "scale": "millions",
        },
        "AEM.TO",
        cache={},
    )

    assert result["metadata"]["commodity"] == "gold"
    assert result["metadata"]["proxy_used"] == "GC=F"
    assert result["commodity_spot_price"]["proxy_used"] == "GC=F"
    assert result["commodity_spot_price"]["value"] == 2400.0
