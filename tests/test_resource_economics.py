from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from modules.economics import resource_economics
from modules.economics.resource_display import build_commodity_display_text
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


def test_infer_commodity_sector_keyword_precedence():
    cases = [
        ("Upstream Oil & Gas / Integrated Energy", "crude oil"),
        ("Integrated Oil & Gas", "crude oil"),
        ("Upstream Oil & Gas", "crude oil"),
        ("Natural Gas Production", "natural gas"),
        ("Gas Gathering and Processing", None),
        ("Gold Mining", "gold"),
        ("Gold-Silver Mining", "gold"),  # gold precedence over silver
        ("Silver Mining", "silver"),
        ("Uranium Mining", "uranium"),
        ("Mineral Exploration", None),
    ]

    for sector, expected in cases:
        assert resource_economics.infer_commodity(sector) == expected


def test_commodity_display_keeps_inferred_qualifier_out_of_spot_title():
    display = build_commodity_display_text("crude oil", "CL=F")

    assert display["header_label"] == "Crude Oil (inferred from sector description)"
    assert display["spot_title"] == "Crude Oil Spot"
    assert "inferred" not in display["spot_title"].lower()


def test_crude_proxy_caveat_names_resolved_proxy():
    wti = build_commodity_display_text("crude oil", "CL=F")
    fallback = build_commodity_display_text("crude oil", "USO")

    assert wti["crude_caveat"] == (
        "Proxy is WTI futures (CL=F); "
        "Canadian producers may realize WCS-differential pricing."
    )
    assert fallback["crude_caveat"] == (
        "Proxy is USO; Canadian producers may realize WCS-differential pricing."
    )
    assert "WTI" not in fallback["crude_caveat"]
    assert "CL=F" not in fallback["crude_caveat"]


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


class DualListingTicker:
    """Suncor-class dual listing: SU (NYSE, USD) and SU.TO (TSX, CAD)."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        if symbol == "SU":
            self.fast_info = SimpleNamespace(
                last_price=40.0, regular_market_price=None,
                market_cap=50_000_000_000, shares=1_250_000_000,
                currency="USD",
            )
        elif symbol == "SU.TO":
            self.fast_info = SimpleNamespace(
                last_price=55.0, regular_market_price=None,
                market_cap=68_000_000_000, shares=1_250_000_000,
                currency="CAD",
            )
        elif symbol == "CL=F":
            self.fast_info = SimpleNamespace(
                last_price=68.0, regular_market_price=None,
                market_cap=None, shares=None,
            )
        else:
            self.fast_info = SimpleNamespace(
                last_price=None, regular_market_price=None,
                market_cap=None, shares=None,
            )
        self.info = {}

    def history(self, period: str = "1y"):
        if self.symbol == "CL=F":
            return pd.DataFrame(
                {"Close": [60.0, 68.0]},
                index=pd.to_datetime(["2025-01-01", "2025-12-31"]),
            )
        return pd.DataFrame()


def test_cad_filer_prefers_toronto_listing_over_us_primary(monkeypatch):
    # The Suncor case: ticker "SU" resolves to the NYSE listing (USD), which
    # mismatches the CAD filing and suppresses every market-cap ratio. The
    # resolver must try SU.TO and use its CAD market cap instead.
    monkeypatch.setattr(resource_economics.yf, "Ticker", DualListingTicker)

    result = build_resource_economics_snapshot(
        {
            "revenue": 52_375,
            "net_income": 5_920,
            "sector_inferred": "Integrated Oil & Gas",
            "currency": "CAD",
            "scale": "millions",
            "fiscal_year_end": "2025-12-31",
        },
        "SU",
        cache={},
    )

    company = result["market_data"]["company"]
    assert company["ticker_used"] == "SU.TO"
    assert company["currency"] == "CAD"
    guard = result["metadata"]["currency_guard"]
    assert guard["status"] == "match"
    assert guard["suppressed"] is False
    assert result["metrics"]["earnings_yield"] == 5_920_000_000 / 68_000_000_000
    assert result["metrics"]["revenue_to_market_cap"] == 52_375_000_000 / 68_000_000_000


class UsdFilerTorontoPrimaryTicker:
    """Agnico-class: files in USD; AEM.TO listing is CAD; bare AEM is USD."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        if symbol == "AEM.TO":
            self.fast_info = SimpleNamespace(
                last_price=160.0, regular_market_price=None,
                market_cap=82_000_000_000, shares=500_000_000,
                currency="CAD",
            )
        elif symbol == "AEM":
            self.fast_info = SimpleNamespace(
                last_price=120.0, regular_market_price=None,
                market_cap=60_000_000_000, shares=500_000_000,
                currency="USD",
            )
        elif symbol == "GC=F":
            self.fast_info = SimpleNamespace(
                last_price=2400.0, regular_market_price=None,
                market_cap=None, shares=None,
            )
        else:
            self.fast_info = SimpleNamespace(
                last_price=None, regular_market_price=None,
                market_cap=None, shares=None,
            )
        self.info = {}

    def history(self, period: str = "1y"):
        if self.symbol == "GC=F":
            return pd.DataFrame(
                {"Close": [2100.0, 2400.0]},
                index=pd.to_datetime(["2025-01-01", "2025-12-31"]),
            )
        return pd.DataFrame()


def test_usd_filer_with_toronto_primary_falls_back_to_us_listing(monkeypatch):
    monkeypatch.setattr(
        resource_economics.yf, "Ticker", UsdFilerTorontoPrimaryTicker
    )

    result = build_resource_economics_snapshot(
        {
            "revenue": 11_907_851,
            "net_income": 4_461_461,
            "sector_inferred": "Gold Mining",
            "currency": "USD",
            "scale": "thousands",
        },
        "AEM.TO",
        cache={},
    )

    company = result["market_data"]["company"]
    assert company["ticker_used"] == "AEM"
    assert company["currency"] == "USD"
    assert result["metadata"]["currency_guard"]["status"] == "match"
    assert result["metrics"]["earnings_yield"] == 4_461_461_000 / 60_000_000_000


class CorrelatedHistoryTicker(DualListingTicker):
    """DualListingTicker whose SU.TO and CL=F share 30 trading days where
    the company's daily return is exactly 2x the commodity's return."""

    _DATES = pd.bdate_range("2026-01-05", periods=30)
    # Commodity closes: alternating +1% / -0.5% daily moves.
    _CMD_CLOSES = [100.0]
    for _i in range(29):
        _CMD_CLOSES.append(_CMD_CLOSES[-1] * (1.01 if _i % 2 == 0 else 0.995))
    # Company closes: exactly double each commodity return.
    _CO_CLOSES = [50.0]
    for _prev, _cur in zip(_CMD_CLOSES, _CMD_CLOSES[1:]):
        _CO_CLOSES.append(_CO_CLOSES[-1] * (1 + 2 * (_cur / _prev - 1)))

    def history(self, period: str = "1y"):
        if self.symbol == "CL=F":
            return pd.DataFrame({"Close": self._CMD_CLOSES}, index=self._DATES)
        if self.symbol == "SU.TO":
            return pd.DataFrame({"Close": self._CO_CLOSES}, index=self._DATES)
        return pd.DataFrame()


def test_commodity_correlation_and_beta_from_shared_history(monkeypatch):
    monkeypatch.setattr(resource_economics.yf, "Ticker", CorrelatedHistoryTicker)

    result = build_resource_economics_snapshot(
        {
            "revenue": 52_375,
            "net_income": 5_920,
            "sector_inferred": "Integrated Oil & Gas",
            "currency": "CAD",
            "scale": "millions",
        },
        "SU",
        cache={},
    )

    stats = result["commodity_correlation"]
    # Company returns are exactly 2x commodity returns -> perfect
    # correlation, beta of 2.
    assert stats["reason"] is None
    assert stats["points_used"] == 29
    assert abs(stats["correlation"] - 1.0) < 1e-9
    assert abs(stats["beta"] - 2.0) < 1e-9
    assert stats["proxy_used"] == "CL=F"


def test_commodity_correlation_insufficient_history_skips_honestly(monkeypatch):
    # FakeTicker gives the company no history at all -> honest skip.
    monkeypatch.setattr(resource_economics.yf, "Ticker", FakeTicker)

    result = build_resource_economics_snapshot(
        {
            "revenue": 11_907_851,
            "net_income": 4_461_461,
            "sector_inferred": "Gold Mining",
            "currency": "USD",
            "scale": "thousands",
        },
        "AEM.TO",
        cache={},
    )

    stats = result["commodity_correlation"]
    assert stats["correlation"] is None
    assert stats["beta"] is None
    assert stats["reason"] == "insufficient overlapping price history"


def test_cost_structure_scales_mapped_sector_fields(monkeypatch):
    monkeypatch.setattr(resource_economics.yf, "Ticker", FakeTicker)

    result = build_resource_economics_snapshot(
        {
            "revenue": 11_907_851,
            "net_income": 4_461_461,
            "production_costs": 3_340_684,
            "mine_development_amortization": 1_645_297,
            "exploration_expense": 250_000,
            "sector_inferred": "Gold Mining",
            "currency": "USD",
            "scale": "thousands",
        },
        "AEM.TO",
        cache={},
    )

    cs = result["cost_structure"]
    assert cs["revenue"] == 11_907_851_000
    assert cs["production_costs"] == 3_340_684_000
    assert cs["mine_development_amortization"] == 1_645_297_000
    assert cs["exploration_expense"] == 250_000_000
    # Fields the mining profile does not map stay None (UI skips them).
    assert cs["royalties"] is None
    assert cs["operating_expense"] is None


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
