from statistics import median

import yfinance as yf


peer_map = {
    "Technology": ["AAPL", "MSFT", "GOOGL", "META", "AMZN"],
    "Semiconductors": ["NVDA", "AMD", "INTC", "QCOM", "AVGO"],
    "Consumer Staples": ["KO", "PEP", "PG", "MDLZ", "CL"],
    "Healthcare": ["JNJ", "UNH", "PFE", "ABBV", "MRK"],
    "Financials": ["JPM", "BAC", "WFC", "GS", "MS"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG"],
    "Industrials": ["HON", "MMM", "CAT", "DE", "GE"],
    "Consumer Discretionary": ["TSLA", "HD", "MCD", "NKE", "SBUX"],
    "Real Estate": ["AMT", "PLD", "CCI", "EQIX", "PSA"],
    "Utilities": ["NEE", "DUK", "SO", "AEP", "EXC"],
    "Materials": ["LIN", "APD", "SHW", "FCX", "NEM"],
    "Communications": ["GOOGL", "META", "NFLX", "DIS", "CMCSA"],
}


def _num(value):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _fetch_peer(ticker: str) -> dict:
    stock = yf.Ticker(ticker)
    info = stock.info or {}
    return {
        "ticker": ticker,
        "company": info.get("longName") or info.get("shortName") or ticker,
        "pe": _num(info.get("trailingPE")),
        "ev_ebitda": _num(info.get("enterpriseToEbitda")),
        "pb": _num(info.get("priceToBook")),
        "ps": _num(info.get("priceToSalesTrailing12Months")),
        "rev_growth": _num(info.get("revenueGrowth")),
        "gross_margin": _num(info.get("grossMargins")),
    }


def get_peer_data(ticker: str, sector: str) -> dict:
    try:
        ticker = (ticker or "").strip().upper()
        sector = (sector or "").strip()
        tickers = peer_map.get(sector, [])
        if not tickers:
            return {"peers": [], "medians": {}, "error": f"No peer map found for sector '{sector}'."}

        peer_tickers = [peer for peer in tickers if peer.upper() != ticker]
        peers = []
        for peer in peer_tickers:
            try:
                peers.append(_fetch_peer(peer))
            except Exception:
                continue

        if not peers:
            return {"peers": [], "medians": {}, "error": "No peer data could be fetched."}

        medians = {}
        for metric in ["pe", "ev_ebitda", "pb", "ps", "rev_growth", "gross_margin"]:
            values = [row.get(metric) for row in peers if row.get(metric) is not None]
            medians[metric] = median(values) if values else None

        return {"peers": peers, "medians": medians, "error": None}
    except Exception as e:
        return {"peers": [], "medians": {}, "error": str(e)}
