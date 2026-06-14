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
