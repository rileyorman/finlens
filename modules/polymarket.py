import json
import platform

import requests


MACRO_KEYWORDS = [
    "fed", "federal reserve", "interest rate", "rate cut", "rate hike",
    "recession", "inflation", "cpi", "gdp", "unemployment",
    "s&p", "nasdaq", "dow", "market crash", "bull market", "bear market",
    "economy", "economic", "treasury", "yield", "debt ceiling",
    "bitcoin", "crypto", "oil", "gold", "dollar", "usd", "cad",
    "bank", "tariff", "trade war", "earnings", "ipo"
]

_EVENTS_URL = "https://gamma-api.polymarket.com/events"


def _make_session():
    session = requests.Session()
    session.trust_env = False
    if platform.system() == "Windows":
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        session.verify = False
    return session


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _loads_if_json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _yes_probability(market):
    prices = _loads_if_json(market.get("outcomePrices"))
    if not isinstance(prices, list) or not prices:
        return None

    return _as_float(prices[0], None)


def _event_text(event, market=None):
    market = market or {}
    return " ".join(
        str(value or "")
        for value in (
            event.get("title"),
            market.get("question"),
        )
    ).lower()


def _is_macro_event(event, market=None):
    text = _event_text(event, market)
    return any(keyword in text for keyword in MACRO_KEYWORDS)


def _event_url(event):
    slug = event.get("slug")
    if slug:
        return f"https://polymarket.com/event/{slug}"
    return "https://polymarket.com"


def _highest_volume_market(event):
    markets = event.get("markets") or []
    if not isinstance(markets, list) or not markets:
        return None

    return max(
        (market for market in markets if isinstance(market, dict)),
        key=lambda market: _as_float(market.get("volumeNum") or market.get("volume"), 0.0),
        default=None,
    )


def get_macro_markets():
    """
    Return the top 5 macro/financial Polymarket markets by volume.

    The source request scans the top 300 open Polymarket events by volume,
    then applies the financial keyword filter locally.
    """
    session = _make_session()
    clean_markets = []
    for offset in (0, 100, 200):
        try:
            response = session.get(
                _EVENTS_URL,
                params={
                    "closed": "false",
                    "limit": 100,
                    "offset": offset,
                    "order": "volume",
                    "ascending": "false",
                },
                timeout=10,
            )
            response.raise_for_status()
            events = response.json()
        except Exception:
            continue

        if not isinstance(events, list):
            continue

        for event in events:
            if not isinstance(event, dict):
                continue

            market = _highest_volume_market(event)
            if not market or not _is_macro_event(event, market):
                continue

            probability = _yes_probability(market)
            if probability is None:
                continue

            clean_markets.append({
                "question": str(event.get("title") or market.get("question") or ""),
                "probability": max(0.0, min(1.0, probability)),
                "volume": _as_float(event.get("volume") or market.get("volume"), 0.0),
                "url": _event_url(event),
            })

    clean_markets.sort(key=lambda item: item["volume"], reverse=True)
    return clean_markets[:5]
