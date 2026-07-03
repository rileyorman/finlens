"""
Resource economics calculations.

This module is UI-agnostic by design: pure functions in, structured dict out.
Callers may pass a plain dict cache to reuse yfinance data across Streamlit
reruns or other repeated calls.
"""
from __future__ import annotations

import re
from typing import Any

import yfinance as yf

from modules.market_data import _patch_windows_ssl, _to_yfinance_ticker


COMMODITY_PROXIES = {
    "gold": {
        "primary": "GC=F",
        "fallback": "GLD",
        "label": "Gold futures; GLD ETF fallback",
    },
    "copper": {
        "primary": "HG=F",
        "fallback": "COPX",
        "label": "Copper futures; COPX ETF fallback",
    },
    "crude oil": {
        "primary": "CL=F",
        "fallback": "USO",
        "label": "WTI crude futures; USO ETF fallback",
    },
    "natural gas": {
        "primary": "NG=F",
        "fallback": "UNG",
        "label": "Henry Hub natural gas futures; UNG ETF fallback",
    },
}

_SCALE_FACTORS = {
    "ones": 1,
    "": 1,
    "thousand": 1_000,
    "thousands": 1_000,
    "million": 1_000_000,
    "millions": 1_000_000,
    "billion": 1_000_000_000,
    "billions": 1_000_000_000,
}


_patch_windows_ssl()


def _to_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _scale_factor(scale: str | None) -> int:
    return _SCALE_FACTORS.get(str(scale or "").strip().lower(), 1)


def _extract_field(fundamentals: dict[str, Any], field: str) -> float | None:
    """Read `field` from flat input or existing mapping output shapes."""
    if field in fundamentals:
        value = fundamentals[field]
        if isinstance(value, dict):
            return _to_number(value.get("value"))
        return _to_number(value)

    mapped = fundamentals.get("mapped")
    if isinstance(mapped, dict) and field in mapped:
        value = mapped[field]
        if isinstance(value, dict):
            return _to_number(value.get("value"))
        return _to_number(value)

    mapping = fundamentals.get("mapping")
    if isinstance(mapping, dict):
        mapped = mapping.get("mapped")
        if isinstance(mapped, dict) and field in mapped:
            value = mapped[field]
            if isinstance(value, dict):
                return _to_number(value.get("value"))
            return _to_number(value)

    return None


def _extract_text(fundamentals: dict[str, Any], field: str) -> str | None:
    value = fundamentals.get(field)
    if value is None and isinstance(fundamentals.get("metadata"), dict):
        value = fundamentals["metadata"].get(field)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def infer_commodity(sector_inferred: str | None, commodity_hint: str | None = None) -> str | None:
    """Infer a commodity key supported by COMMODITY_PROXIES."""
    if commodity_hint:
        hint = commodity_hint.strip().lower()
        if hint in COMMODITY_PROXIES:
            return hint

    sector = str(sector_inferred or "").lower()
    if "gold" in sector:
        return "gold"
    if "copper" in sector:
        return "copper"
    has_oil_keyword = any(keyword in sector for keyword in ("oil", "crude", "petroleum"))
    if "natural gas" in sector and not has_oil_keyword:
        return "natural gas"
    if has_oil_keyword:
        return "crude oil"
    return None


def _cache_get(cache: dict | None, key: tuple) -> Any:
    if cache is None:
        return None
    return cache.get(key)


def _cache_set(cache: dict | None, key: tuple, value: Any) -> None:
    if cache is not None:
        cache[key] = value


def _fetch_company_market_data(ticker: str, cache: dict | None = None) -> dict[str, Any]:
    cache_key = ("company_market_data", ticker)
    cached = _cache_get(cache, cache_key)
    if cached is not None:
        return cached

    empty = {
        "share_price": None,
        "market_cap": None,
        "shares_outstanding": None,
        "currency": None,
        "ticker_used": _to_yfinance_ticker(ticker),
        "error": None,
    }
    if not ticker or not ticker.strip():
        empty["error"] = "missing ticker"
        return empty

    try:
        ticker_used = _to_yfinance_ticker(ticker)
        yt = yf.Ticker(ticker_used)
        fast_info = yt.fast_info
        share_price = (
            getattr(fast_info, "last_price", None)
            or getattr(fast_info, "regular_market_price", None)
        )
        market_cap = getattr(fast_info, "market_cap", None)
        shares = getattr(fast_info, "shares", None)
        # Listing currency — the currency market_cap is quoted in. Needed by the
        # filing-vs-listing currency guard on the market-cap ratios.
        listing_currency = getattr(fast_info, "currency", None)

        if market_cap is None or shares is None or listing_currency is None:
            try:
                info = yt.info or {}
                market_cap = market_cap if market_cap is not None else info.get("marketCap")
                shares = shares if shares is not None else info.get("sharesOutstanding")
                share_price = share_price or info.get("currentPrice") or info.get("regularMarketPrice")
                listing_currency = listing_currency or info.get("currency")
            except Exception:
                pass

        currency_text = str(listing_currency).strip().upper() if listing_currency else ""
        result = {
            "share_price": _to_number(share_price),
            "market_cap": _to_number(market_cap),
            "shares_outstanding": _to_number(shares),
            "currency": currency_text or None,
            "ticker_used": ticker_used,
            "error": None,
        }
    except Exception as exc:
        result = dict(empty)
        result["error"] = str(exc)

    _cache_set(cache, cache_key, result)
    return result


def _resolve_company_market_data(
    ticker: str,
    filing_currency: str | None,
    cache: dict | None = None,
) -> dict[str, Any]:
    """Fetch company market data, preferring the listing whose currency
    matches the filing currency.

    Dual-listed filers (SU on NYSE in USD vs SU.TO in CAD) otherwise resolve
    to a listing whose market cap is in the wrong currency, and the currency
    guard then suppresses every market-cap ratio. Trying the sibling listing
    first keeps the guard honest AND the ratios alive.

    Falls back to the primary resolution when no candidate matches.
    """
    primary = _fetch_company_market_data(ticker, cache)
    if not filing_currency:
        return primary
    if _currency_code(primary.get("currency")) == filing_currency:
        return primary

    primary_symbol = str(primary.get("ticker_used") or "").strip().upper()
    if not primary_symbol:
        return primary

    if primary_symbol.endswith((".TO", ".V")):
        # Toronto listing mismatched (e.g. USD filer like Agnico): try the
        # bare US-style symbol.
        alternates = [primary_symbol.rsplit(".", 1)[0]]
    else:
        # US listing mismatched (e.g. CAD filer like Suncor): try Toronto,
        # then TSX Venture.
        alternates = [f"{primary_symbol}.TO", f"{primary_symbol}.V"]

    for alternate in alternates:
        if not alternate or alternate == primary_symbol:
            continue
        candidate = _fetch_company_market_data(alternate, cache)
        if (
            candidate.get("market_cap") is not None
            and _currency_code(candidate.get("currency")) == filing_currency
        ):
            return candidate

    return primary


def _history_to_points(history: Any) -> list[dict[str, Any]]:
    if history is None or getattr(history, "empty", True):
        return []
    if "Close" not in history:
        return []

    points = []
    close_series = history["Close"].dropna()
    for index, value in close_series.items():
        if hasattr(index, "date"):
            date_value = index.date().isoformat()
        else:
            date_value = str(index)
        points.append({"date": date_value, "close": float(value)})
    return points


def _fetch_proxy_data(symbol: str, cache: dict | None = None) -> dict[str, Any]:
    cache_key = ("commodity_proxy_data", symbol)
    cached = _cache_get(cache, cache_key)
    if cached is not None:
        return cached

    result = {"spot_price": None, "trend": [], "error": None}
    try:
        yt = yf.Ticker(symbol)
        fast_info = yt.fast_info
        spot = (
            getattr(fast_info, "last_price", None)
            or getattr(fast_info, "regular_market_price", None)
        )
        history = yt.history(period="1y")
        trend = _history_to_points(history)
        if spot is None and trend:
            spot = trend[-1]["close"]
        result = {
            "spot_price": _to_number(spot),
            "trend": trend,
            "error": None,
        }
    except Exception as exc:
        result["error"] = str(exc)

    _cache_set(cache, cache_key, result)
    return result


def _fetch_commodity_market_data(commodity: str | None, cache: dict | None = None) -> dict[str, Any]:
    if commodity not in COMMODITY_PROXIES:
        return {
            "commodity": commodity,
            "proxy_used": None,
            "proxy_role": None,
            "spot_price": None,
            "trend": [],
            "error": "unsupported or missing commodity",
        }

    proxy_config = COMMODITY_PROXIES[commodity]
    for role in ("primary", "fallback"):
        symbol = proxy_config[role]
        data = _fetch_proxy_data(symbol, cache)
        if data["spot_price"] is not None or data["trend"]:
            return {
                "commodity": commodity,
                "proxy_used": symbol,
                "proxy_role": role,
                "spot_price": data["spot_price"],
                "trend": data["trend"],
                "error": data["error"],
            }

    return {
        "commodity": commodity,
        "proxy_used": proxy_config["primary"],
        "proxy_role": "primary",
        "spot_price": None,
        "trend": [],
        "error": "primary and fallback proxy fetch failed",
    }


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _reason(metric_name: str, required: list[str], missing: list[str]) -> str | None:
    missing_required = [field for field in required if field in missing]
    if missing_required:
        return f"missing required inputs: {', '.join(missing_required)}"
    return None


def _currency_code(text: str | None) -> str | None:
    """Extract an ISO-style 3-letter currency code from a currency label.

    Filing currency labels can carry a scale suffix (e.g. "CAD, in ones",
    "USD, in thousands"), while yfinance listing currency is a bare code
    ("USD"). Compare codes, not raw labels. Returns None when no 3-letter
    code is present — the guard then skips honestly rather than guessing.
    """
    if not text:
        return None
    match = re.search(r"\b[A-Z]{3}\b", str(text).upper())
    return match.group(0) if match else None


def _market_cap_currency_check(
    filing_currency: str | None,
    listing_currency: str | None,
    ticker_used: str | None,
) -> tuple[str, str | None]:
    """Check that filing and listing currencies match before market-cap ratios.

    Market-cap ratios divide filing-currency figures by yfinance market_cap,
    which is quoted in the LISTING currency. If the two differ (e.g. a CAD
    filer resolved to a USD listing) the ratio is silently wrong. No FX
    conversion here — an honest skip beats a wrong number (integrity-first).

    Returns (status, note): status is "match" / "mismatch" / "unknown";
    note explains the skip (None on match).
    """
    if filing_currency and listing_currency:
        if filing_currency == listing_currency:
            return "match", None
        return "mismatch", (
            f"Market-cap ratios not shown: filing currency {filing_currency} vs "
            f"listing currency {listing_currency} — a cross-currency ratio would "
            f"be incorrect."
        )
    if not filing_currency and not listing_currency:
        return "unknown", (
            "Market-cap ratios not shown: filing and listing currencies could "
            "not be determined — cannot confirm they match."
        )
    if not filing_currency:
        return "unknown", (
            f"Market-cap ratios not shown: filing currency unknown — cannot "
            f"confirm it matches the listing currency ({listing_currency})."
        )
    return "unknown", (
        f"Market-cap ratios not shown: listing currency for "
        f"{ticker_used or 'the resolved ticker'} unknown — cannot confirm it "
        f"matches the filing currency ({filing_currency})."
    )


def build_resource_economics_snapshot(
    fundamentals: dict[str, Any],
    ticker: str,
    commodity_hint: str | None = None,
    cache: dict | None = None,
) -> dict[str, Any]:
    """Build Tier 1 resource economics metrics from filing + yfinance data."""
    fundamentals = fundamentals or {}
    scale = _extract_text(fundamentals, "scale")
    factor = _scale_factor(scale)

    raw_values = {
        "revenue": _extract_field(fundamentals, "revenue"),
        "production_costs": _extract_field(fundamentals, "production_costs"),
        "net_income": _extract_field(fundamentals, "net_income"),
        "mine_development_amortization": _extract_field(
            fundamentals, "mine_development_amortization"
        ),
    }
    values = {
        field: (value * factor if value is not None else None)
        for field, value in raw_values.items()
    }
    sector_inferred = _extract_text(fundamentals, "sector_inferred")
    currency = _extract_text(fundamentals, "currency")
    fiscal_year_end = _extract_text(fundamentals, "fiscal_year_end")

    commodity = infer_commodity(sector_inferred, commodity_hint)
    # Resolve the filing currency first so the company lookup can prefer the
    # listing quoted in the same currency (see _resolve_company_market_data).
    filing_currency = _currency_code(currency)
    company_market = _resolve_company_market_data(ticker, filing_currency, cache)
    commodity_market = _fetch_commodity_market_data(commodity, cache)

    # Company share-price history for the indexed company-vs-commodity chart.
    # Reuses the proxy fetcher (same 1y window and point shape as the
    # commodity trend). Empty on failure — the chart simply doesn't render.
    company_symbol = company_market.get("ticker_used")
    company_trend_points: list[dict[str, Any]] = []
    if company_symbol:
        company_trend_points = _fetch_proxy_data(company_symbol, cache).get("trend", [])

    market_cap = company_market.get("market_cap")
    missing_inputs = [
        field
        for field, value in {
            **values,
            "market_cap": market_cap,
            "sector_inferred": sector_inferred,
            "commodity": commodity,
            "commodity_spot_price": commodity_market.get("spot_price"),
        }.items()
        if value is None
    ]

    earnings_yield = _ratio(values["net_income"], market_cap)
    revenue_to_market_cap = _ratio(values["revenue"], market_cap)
    net_margin = _ratio(values["net_income"], values["revenue"])

    reasons = {
        "earnings_yield": _reason("earnings_yield", ["net_income", "market_cap"], missing_inputs),
        "revenue_to_market_cap": _reason(
            "revenue_to_market_cap", ["revenue", "market_cap"], missing_inputs
        ),
        "net_margin": _reason("net_margin", ["net_income", "revenue"], missing_inputs),
        "commodity_spot_price": _reason(
            "commodity_spot_price", ["commodity", "commodity_spot_price"], missing_inputs
        ),
    }

    # Currency guard on the market-cap ratios (earnings_yield, revenue_to_market_cap).
    # net_margin is intra-filing (currency cancels) and is deliberately untouched.
    # Only overrides ratios that would otherwise compute — if inputs are missing,
    # the missing-inputs reason above is the true cause and stands.
    # (filing_currency was resolved above, before the company lookup.)
    listing_currency = _currency_code(company_market.get("currency"))
    currency_status, currency_note = _market_cap_currency_check(
        filing_currency, listing_currency, company_market.get("ticker_used")
    )
    currency_suppressed = False
    if currency_status != "match":
        if earnings_yield is not None:
            earnings_yield = None
            reasons["earnings_yield"] = currency_note
            currency_suppressed = True
        if revenue_to_market_cap is not None:
            revenue_to_market_cap = None
            reasons["revenue_to_market_cap"] = currency_note
            currency_suppressed = True

    cheap_company_or_cheap_sector = {
        "company_earnings_yield": earnings_yield,
        "commodity": commodity,
        "commodity_proxy": commodity_market.get("proxy_used"),
        "commodity_spot_available": commodity_market.get("spot_price") is not None,
        "company_flag": None,
        "sector_context_flag": None,
        "reason": None,
    }
    if earnings_yield is None:
        cheap_company_or_cheap_sector["reason"] = reasons["earnings_yield"]
    else:
        cheap_company_or_cheap_sector["company_flag"] = (
            "high_earnings_yield" if earnings_yield >= 0.08 else "not_high_earnings_yield"
        )
        cheap_company_or_cheap_sector["sector_context_flag"] = (
            "commodity_price_available"
            if commodity_market.get("spot_price") is not None
            else "commodity_price_unavailable"
        )

    return {
        "metrics": {
            "earnings_yield": earnings_yield,
            "revenue_to_market_cap": revenue_to_market_cap,
            "net_margin": net_margin,
        },
        "market_data": {
            "company": company_market,
            "commodity": {
                "commodity": commodity,
                "spot_price": commodity_market.get("spot_price"),
                "proxy_used": commodity_market.get("proxy_used"),
                "proxy_role": commodity_market.get("proxy_role"),
            },
        },
        "commodity_spot_price": {
            "value": commodity_market.get("spot_price"),
            "proxy_used": commodity_market.get("proxy_used"),
            "proxy_role": commodity_market.get("proxy_role"),
            "reason": reasons["commodity_spot_price"],
        },
        "commodity_trend": {
            "proxy_used": commodity_market.get("proxy_used"),
            "points": commodity_market.get("trend", []),
        },
        "company_trend": {
            "ticker_used": company_symbol,
            "points": company_trend_points,
        },
        "cheap_company_or_cheap_sector": cheap_company_or_cheap_sector,
        "metadata": {
            "ticker": ticker,
            "ticker_used": company_market.get("ticker_used"),
            "commodity": commodity,
            "proxy_used": commodity_market.get("proxy_used"),
            "fiscal_year_end": fiscal_year_end,
            "currency": currency,
            "currency_guard": {
                "filing_currency": filing_currency,
                "listing_currency": listing_currency,
                "status": currency_status,
                "suppressed": currency_suppressed,
                "note": currency_note,
            },
            "scale": scale,
            "scale_factor_applied": factor,
            "missing_inputs": missing_inputs,
            "none_reasons": reasons,
            "fetch_errors": {
                "company": company_market.get("error"),
                "commodity": commodity_market.get("error"),
            },
        },
    }
