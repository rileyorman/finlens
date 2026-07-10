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
    "silver": {
        "primary": "SI=F",
        "fallback": "SLV",
        "label": "Silver futures; SLV ETF fallback",
    },
    "uranium": {
        # No liquid uranium futures on the free tier — both proxies are
        # uranium-sector ETFs, honestly labeled as such in the UI.
        "primary": "URA",
        "fallback": "URNM",
        "label": "Uranium sector ETFs (no liquid uranium futures on the free tier)",
    },
}

# Minimum overlapping daily returns before correlation/beta are reported.
# Below this the numbers are noise, so the card shows an honest skip instead.
MIN_CORRELATION_POINTS = 20

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


# CB-027 (ratified 2026-07-09): commodity families FinLens RECORDS even though
# no liquid free-tier benchmark proxy exists for them. They appear in
# metadata.commodities with proxy_available False and the UI says so honestly —
# never borrow a lookalike proxy for them.
RECORD_ONLY_COMMODITIES = ("oil sands", "ngls")


def classify_commodities(
    sector_inferred: str | None, commodity_hint: str | None = None
) -> list[dict[str, Any]]:
    """CB-027: ALL commodity families evidenced for the filer, none primary.

    Many producers sell several commodities at once (oil + natural gas + NGLs;
    oil sands filers realize crude-blend pricing) and a sector string like
    "Upstream Oil & Gas" cannot reveal the revenue weighting — so FinLens
    records EVERY family the evidence names and claims no primary. Entries:
    {"name", "source", "proxy_available"}. Order is deliberate: the first
    proxy-available entry is the legacy single-commodity benchmark (kept for
    back-compat), matching infer_commodity()'s historical choice exactly.
    Revenue weighting from the IFRS 15 disaggregation note is the future
    upgrade; until then no weighting is claimed anywhere.
    """
    found: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(name: str, source: str) -> None:
        if name not in seen:
            seen.add(name)
            found.append({
                "name": name,
                "source": source,
                "proxy_available": name in COMMODITY_PROXIES,
            })

    if commodity_hint:
        hint = commodity_hint.strip().lower()
        if hint in COMMODITY_PROXIES or hint in RECORD_ONLY_COMMODITIES:
            _add(hint, "hint")

    sector = str(sector_inferred or "").lower()
    # Insertion order preserves infer_commodity()'s historical precedence
    # (gold before silver; crude before natural gas), so benchmark #1 is
    # unchanged for every previously-supported shape.
    if "gold" in sector:
        _add("gold", "sector_description")
    if "silver" in sector:
        _add("silver", "sector_description")
    if "copper" in sector:
        _add("copper", "sector_description")
    if "uranium" in sector:
        _add("uranium", "sector_description")
    has_oil_keyword = any(keyword in sector for keyword in ("oil", "crude", "petroleum"))
    if has_oil_keyword:
        _add("crude oil", "sector_description")
    # Natural gas needs the explicit phrase, OR a bare "gas" word alongside
    # oil evidence (the "Oil & Gas" family form). A bare "gas" alone stays
    # unclassified — "Gas Gathering and Processing" is midstream, not a
    # producer, and gets no commodity benchmark (pinned test).
    if "natural gas" in sector or (has_oil_keyword and re.search(r"\bgas\b", sector)):
        _add("natural gas", "sector_description")
    if "oil sands" in sector:
        _add("oil sands", "sector_description")
    if "ngl" in sector or "natural gas liquids" in sector:
        _add("ngls", "sector_description")
    return found


def infer_commodity(sector_inferred: str | None, commodity_hint: str | None = None) -> str | None:
    """Legacy single-commodity view: first proxy-available family (CB-027).

    Kept for callers/tests that want one benchmark key; behavior is identical
    to the historical implementation for every previously-supported shape.
    """
    for entry in classify_commodities(sector_inferred, commodity_hint):
        if entry["proxy_available"]:
            return entry["name"]
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


def _daily_return_stats(
    company_points: list[dict[str, Any]],
    commodity_points: list[dict[str, Any]],
    min_points: int = MIN_CORRELATION_POINTS,
) -> dict[str, Any]:
    """Correlation and beta of daily returns: company vs commodity proxy.

    Answers "is this equity a commodity proxy or an operating story?" using
    the two 1y price series the snapshot already fetches. Pure python —
    aligned by shared dates, Pearson correlation, beta = cov / var(commodity).
    """
    insufficient = {
        "correlation": None,
        "beta": None,
        "points_used": 0,
        "reason": "insufficient overlapping price history",
    }
    company = {p["date"]: p["close"] for p in company_points or []}
    commodity = {p["date"]: p["close"] for p in commodity_points or []}
    common_dates = sorted(set(company) & set(commodity))
    if len(common_dates) < min_points + 1:
        insufficient["points_used"] = max(len(common_dates) - 1, 0)
        return insufficient

    company_returns: list[float] = []
    commodity_returns: list[float] = []
    for prev_date, cur_date in zip(common_dates, common_dates[1:]):
        prev_co, cur_co = company[prev_date], company[cur_date]
        prev_cm, cur_cm = commodity[prev_date], commodity[cur_date]
        if prev_co and prev_cm:
            company_returns.append(cur_co / prev_co - 1)
            commodity_returns.append(cur_cm / prev_cm - 1)

    n = len(company_returns)
    if n < min_points:
        insufficient["points_used"] = n
        return insufficient

    mean_co = sum(company_returns) / n
    mean_cm = sum(commodity_returns) / n
    cov = sum(
        (a - mean_co) * (b - mean_cm)
        for a, b in zip(company_returns, commodity_returns)
    ) / n
    var_cm = sum((b - mean_cm) ** 2 for b in commodity_returns) / n
    var_co = sum((a - mean_co) ** 2 for a in company_returns) / n
    if var_cm == 0 or var_co == 0:
        return {
            "correlation": None,
            "beta": None,
            "points_used": n,
            "reason": "zero variance in one of the return series",
        }

    return {
        "correlation": cov / (var_cm ** 0.5 * var_co ** 0.5),
        "beta": cov / var_cm,
        "points_used": n,
        "reason": None,
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

    # raw_values holds ONLY the Tier-1 ratio inputs — the fields that feed a
    # displayed ratio (earnings_yield, revenue_to_market_cap, net_margin) and
    # therefore the missing_inputs list scoped to them. production_costs and
    # mine_development_amortization are cost-structure-only (no displayed ratio
    # consumes them) and are read below with the other cost fields, so they no
    # longer surface as false "missing inputs" on a filer that maps the same
    # concept under a different sector name (O&G: operating_expense /
    # depletion_depreciation_amortization). Re-audit 2026-07-07 (Option B).
    raw_values = {
        "revenue": _extract_field(fundamentals, "revenue"),
        "net_income": _extract_field(fundamentals, "net_income"),
    }
    values = {
        field: (value * factor if value is not None else None)
        for field, value in raw_values.items()
    }
    sector_inferred = _extract_text(fundamentals, "sector_inferred")
    currency = _extract_text(fundamentals, "currency")
    fiscal_year_end = _extract_text(fundamentals, "fiscal_year_end")

    # Statement-level cost fields for the cost-structure waterfall. The
    # mining and resource sector profiles map different canonical names
    # (production_costs vs operating_expense; mine_development_amortization
    # vs depletion_depreciation_amortization), so extract them all and let
    # the UI render whichever are present. Kept OUT of raw_values so
    # missing_inputs semantics stay scoped to the Tier 1 ratio inputs.
    _cost_fields = (
        "production_costs",
        "mine_development_amortization",
        "exploration_expense",
        "royalties",
        "operating_expense",
        "depletion_depreciation_amortization",
    )
    cost_structure = {"revenue": None}  # filled after scaling below
    for field in _cost_fields:
        value = _extract_field(fundamentals, field)
        cost_structure[field] = value * factor if value is not None else None

    # CB-027 (2026-07-09): record ALL commodity families evidenced for the
    # filer and benchmark EACH proxy-available one — no primary is claimed.
    # "Upstream Oil & Gas" (CNQ, TOU, ARX) records crude oil AND natural gas;
    # record-only families (oil sands, NGLs) appear in metadata.commodities
    # with an honest no-proxy marker. The legacy single-commodity keys below
    # stay wired to benchmark #1 (identical to the old infer_commodity pick)
    # so single-commodity filers and existing consumers are unchanged.
    commodities = classify_commodities(sector_inferred, commodity_hint)
    proxied_commodities = [c for c in commodities if c["proxy_available"]]
    commodity = proxied_commodities[0]["name"] if proxied_commodities else None
    # Resolve the filing currency first so the company lookup can prefer the
    # listing quoted in the same currency (see _resolve_company_market_data).
    filing_currency = _currency_code(currency)
    company_market = _resolve_company_market_data(ticker, filing_currency, cache)

    # Company share-price history for the indexed company-vs-commodity chart.
    # Reuses the proxy fetcher (same 1y window and point shape as the
    # commodity trend). Empty on failure — the chart simply doesn't render.
    company_symbol = company_market.get("ticker_used")
    company_trend_points: list[dict[str, Any]] = []
    if company_symbol:
        company_trend_points = _fetch_proxy_data(company_symbol, cache).get("trend", [])

    commodity_benchmarks: list[dict[str, Any]] = []
    for entry in proxied_commodities:
        market = _fetch_commodity_market_data(entry["name"], cache)
        stats = _daily_return_stats(company_trend_points, market.get("trend", []))
        stats["proxy_used"] = market.get("proxy_used")
        commodity_benchmarks.append({
            "commodity": entry["name"],
            "source": entry["source"],
            "spot_price": market.get("spot_price"),
            "proxy_used": market.get("proxy_used"),
            "proxy_role": market.get("proxy_role"),
            "trend": market.get("trend", []),
            "correlation": stats,
            "error": market.get("error"),
        })

    _first_benchmark = commodity_benchmarks[0] if commodity_benchmarks else {}
    commodity_market = {
        "spot_price": _first_benchmark.get("spot_price"),
        "proxy_used": _first_benchmark.get("proxy_used"),
        "proxy_role": _first_benchmark.get("proxy_role"),
        "trend": _first_benchmark.get("trend", []),
        "error": _first_benchmark.get("error"),
    }

    # Fill the scaled revenue shared with the Tier 1 ratios (revenue is both a
    # ratio input and the waterfall's opening bar). production_costs and
    # mine_development_amortization are already filled by the cost-field loop.
    cost_structure["revenue"] = values["revenue"]

    correlation_stats = _first_benchmark.get("correlation") or _daily_return_stats(
        company_trend_points, []
    )
    correlation_stats["proxy_used"] = commodity_market.get("proxy_used")

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
        "commodity_correlation": correlation_stats,
        # CB-027: one block per proxy-available commodity family, no primary
        # claimed. Blocks [1:] are the families the legacy single-commodity
        # keys above cannot carry (e.g. natural gas for an "Oil & Gas" filer).
        "commodity_benchmarks": commodity_benchmarks,
        "cost_structure": cost_structure,
        "cheap_company_or_cheap_sector": cheap_company_or_cheap_sector,
        "metadata": {
            "ticker": ticker,
            "ticker_used": company_market.get("ticker_used"),
            "commodity": commodity,
            "commodities": commodities,
            "multi_commodity": len(proxied_commodities) > 1,
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
