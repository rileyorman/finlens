import yfinance as yf

# Data from yfinance — delayed ~15 mins. Verify before use in live analysis.


def search_ticker(company_name: str):
    """Search yfinance for a ticker by company name. Returns first symbol found, or None."""
    if not company_name or not company_name.strip():
        return None
    try:
        results = yf.Search(company_name.strip(), max_results=5)
        quotes = results.quotes
        if quotes:
            return quotes[0].get("symbol")
        return None
    except Exception:
        return None


_EMPTY = {
    "market_cap":          None,
    "current_price":       None,
    "shares_outstanding":  None,
    "pe_ratio":            None,
    "fifty_two_week_high": None,
    "fifty_two_week_low":  None,
}


def get_market_data(ticker: str) -> dict:
    """Return key market data for a ticker. All fields are None if ticker is
    missing, not found, or the fetch fails for any reason."""
    if not ticker or not ticker.strip():
        return dict(_EMPTY)

    try:
        info = yf.Ticker(ticker.strip()).info

        if not info or info.get("quoteType") is None:
            return dict(_EMPTY)

        raw_mc = info.get("marketCap")
        market_cap = round(raw_mc / 1_000_000, 2) if raw_mc else None

        current_price = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
        )

        return {
            "market_cap":          market_cap,
            "current_price":       current_price,
            "shares_outstanding":  info.get("sharesOutstanding"),
            "pe_ratio":            info.get("trailingPE"),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low":  info.get("fiftyTwoWeekLow"),
        }

    except Exception:
        return dict(_EMPTY)
