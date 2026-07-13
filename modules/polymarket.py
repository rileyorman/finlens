import json
import platform
import re

import requests


MACRO_KEYWORDS = [
    "fed", "federal reserve", "interest rate", "rate cut", "rate hike",
    "recession", "inflation", "cpi", "gdp", "unemployment",
    "s&p", "nasdaq", "dow", "market crash", "bull market", "bear market",
    "economy", "economic", "treasury", "yield", "debt ceiling",
    "bitcoin", "crypto", "oil", "gold", "dollar", "usd", "cad",
    "bank", "tariff", "trade war", "earnings", "ipo"
]

# Keywords match on WORD BOUNDARIES, not substrings — found live 2026-07-13:
# "World Cup: Golden Boot Winner" topped the "macro" feed because "golden"
# contains "gold" (same trap: "turmoil"→"oil", "arcade"→"cad").
_MACRO_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in MACRO_KEYWORDS) + r")\b"
)

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
    """P(Yes) for a TRUE binary market; None otherwise.

    Found live 2026-07-13: Polymarket EVENTS contain multiple binary
    sub-markets ("How many rate cuts?" holds "0 cuts", "1 cut", ...).
    Taking outcomePrices[0] of whichever sub-market has volume and
    displaying it against the EVENT title produced incoherent lines like
    "How many Fed rate cuts in 2026? 78% Yes". A probability is only
    served when the market's own outcomes are literally Yes/No.
    """
    outcomes = _loads_if_json(market.get("outcomes"))
    if not isinstance(outcomes, list) or [str(o).strip().lower() for o in outcomes] != ["yes", "no"]:
        return None
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
    return bool(_MACRO_PATTERN.search(_event_text(event, market)))


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

            # Multi-market events: the probability belongs to ONE sub-market,
            # so the displayed question must be THAT market's question — the
            # event title asks a different (non-binary) question.
            event_markets = event.get("markets") or []
            multi = isinstance(event_markets, list) and len(event_markets) > 1
            question = str(
                (market.get("question") if multi else None)
                or event.get("title")
                or market.get("question")
                or ""
            )
            clean_markets.append({
                "question": question,
                "probability": max(0.0, min(1.0, probability)),
                "volume": _as_float(event.get("volume") or market.get("volume"), 0.0),
                "url": _event_url(event),
            })

    clean_markets.sort(key=lambda item: item["volume"], reverse=True)
    return clean_markets[:5]
