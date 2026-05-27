"""
market_ticker.py — Fetches live market data for the scrolling ticker tape.
Cached for 5 minutes via st.cache_data to avoid hammering yfinance.
"""

import streamlit as st
import yfinance as yf


SYMBOLS = {
    # Indices
    "^GSPC":    "S&P 500",
    "^IXIC":    "Nasdaq",
    "^DJI":     "Dow",
    "^RUT":     "Russell 2000",
    "^GSPTSE":  "TSX",
    # Volatility
    "^VIX":     "VIX",
    # Rates
    "^TNX":     "US 10yr",
    "^TYX":     "US 30yr",
    # Currencies
    "USDCAD=X": "USD/CAD",
    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
    "CADUSD=X": "CAD/USD",
    # Commodities
    "GC=F":     "Gold",
    "CL=F":     "WTI Oil",
    "NG=F":     "Nat Gas",
    # Crypto
    "BTC-USD":  "Bitcoin",
    "ETH-USD":  "Ethereum",
}

_CURRENCIES = {"USDCAD=X", "EURUSD=X", "GBPUSD=X", "CADUSD=X"}
_CRYPTO     = {"BTC-USD", "ETH-USD"}
_RATES_VIX  = {"^VIX", "^TNX", "^TYX"}


def _fmt_price(symbol: str, price: float) -> str:
    if symbol in _CURRENCIES:
        return f"{price:.4f}"
    if symbol in _CRYPTO:
        return f"${price:,.2f}"
    if price > 1000:
        return f"{price:,.0f}"
    if price < 100:
        return f"{price:.2f}"
    return f"{price:,.2f}"


def _fetch_one(symbol: str) -> dict | None:
    """Fetch price and change for one symbol. Returns None on any failure — no retries."""
    try:
        info  = yf.Ticker(symbol).fast_info
        price = getattr(info, "last_price", None) or getattr(info, "regular_market_price", None)
        prev  = getattr(info, "previous_close", None)

        if price is None or prev is None:
            return None

        price  = float(price)
        prev   = float(prev)
        change = price - prev
        pct    = (change / prev * 100) if prev else 0.0

        return {
            "name":       SYMBOLS[symbol],
            "price":      price,
            "price_fmt":  _fmt_price(symbol, price),
            "change":     change,
            "pct_change": pct,
            "positive":   change >= 0,
        }
    except Exception:
        return None


@st.cache_data(ttl=300)
def get_ticker_data() -> list[dict]:
    """Return live market data for all configured symbols, skipping any that fail."""
    results = []
    for symbol in SYMBOLS:
        item = _fetch_one(symbol)
        if item is not None:
            results.append(item)
    return results
