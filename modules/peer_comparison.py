from statistics import median

import yfinance as yf


peer_map = {
    "Technology": ["AAPL", "MSFT", "GOOGL", "META", "AMZN"],
    "Semiconductors": ["NVDA", "AMD", "INTC", "QCOM", "AVGO"],
    "Consumer Staples": ["KO", "PEP", "PG", "MDLZ", "CL"],
    "Healthcare": ["JNJ", "UNH", "PFE", "ABBV", "MRK"],
    "Financials": ["JPM", "BAC", "WFC", "GS", "MS"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG"],
    # WCSB (Western Canadian Sedimentary Basin) peer groups, per Riley's
    # framework (2026-07-10): Major Integrated / Mid-Cap Intermediate /
    # Pure-Play Unconventional. Dual-listed names use their US listing (more
    # reliable on yfinance); TSX-only names need the .TO suffix. The compared
    # metrics are all ratios, so mixed USD/CAD listings stay comparable.
    # The combined bucket is the auto-pick target for SEDAR energy filers;
    # the tier buckets are manual picks (the filing's sector string cannot
    # reveal the tier — the CB-027 lesson).
    "Energy — Canada (WCSB)": ["CNQ", "SU", "CVE", "TOU.TO", "OVV", "ARX.TO"],
    "WCSB — Integrated Majors": ["CNQ", "SU", "IMO"],
    "WCSB — Mid-Cap Producers": ["CVE", "TOU.TO", "ARX.TO"],
    "WCSB — Unconventional Drillers": ["OVV", "TOU.TO", "ARX.TO"],
    "Industrials": ["HON", "MMM", "CAT", "DE", "GE"],
    "Consumer Discretionary": ["TSLA", "HD", "MCD", "NKE", "SBUX"],
    "Real Estate": ["AMT", "PLD", "CCI", "EQIX", "PSA"],
    "Utilities": ["NEE", "DUK", "SO", "AEP", "EXC"],
    "Materials": ["LIN", "APD", "SHW", "FCX", "NEM"],
    "Metals & Mining": ["NEM", "GOLD", "AEM", "FNV", "WPM", "KGC", "TECK"],
    "Communications": ["GOOGL", "META", "NFLX", "DIS", "CMCSA"],
}


# Keyword rules mapping a filing's inferred sector text to a peer_map bucket.
# Order matters: more specific keywords first (semiconductor before software,
# oil/gas before generic energy would be redundant but harmless).
_SECTOR_KEYWORDS = [
    ("Semiconductors",         ["semiconductor", "chip", "gpu", "foundry"]),
    ("Metals & Mining",        ["gold", "silver", "copper", "mining", "miner", "metals"]),
    ("Energy",                 ["oil", "gas", "petroleum", "energy", "pipeline", "oil sands"]),
    ("Financials",             ["bank", "insurance", "insurer", "financial", "asset management"]),
    ("Real Estate",            ["reit", "real estate", "properties", "property"]),
    ("Healthcare",             ["health", "pharma", "biotech", "medical"]),
    ("Utilities",              ["utility", "utilities", "electric power"]),
    ("Consumer Staples",       ["staples", "food", "beverage", "grocery", "household products"]),
    ("Consumer Discretionary", ["retail", "restaurant", "apparel", "automotive", "e-commerce"]),
    ("Industrials",            ["industrial", "railway", "railroad", "machinery", "aerospace", "transport"]),
    ("Communications",         ["telecom", "media", "entertainment", "streaming", "communication"]),
    ("Materials",              ["chemical", "materials", "packaging", "forestry", "fertilizer"]),
    ("Technology",             ["software", "technology", "saas", "cloud", "internet", "it services"]),
]


# Buckets with a Canadian-specific peer set. A SEDAR filer that matches the
# generic bucket is steered to the Canadian variant instead — its natural
# comparables are Canadian issuers, not US supermajors.
_CANADIAN_BUCKET_VARIANTS = {
    "Energy": "Energy — Canada (WCSB)",
}


def suggest_sector(sector_text: str | None, *, canadian: bool = False) -> str | None:
    """Map a filing's inferred sector text to a peer_map bucket.

    SEDAR/EDGAR sector descriptions ("Integrated Oil & Gas", "Gold Mining")
    never match peer_map keys by substring, which used to leave the peer
    selector defaulting to Technology for an oil-sands producer. Returns
    None when nothing matches — the caller keeps its own default.

    Pass canadian=True for SEDAR filings so buckets with a Canadian variant
    (see _CANADIAN_BUCKET_VARIANTS) resolve to the Canadian peer set.
    """
    text = str(sector_text or "").lower()
    if not text.strip():
        return None
    for bucket, keywords in _SECTOR_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            if canadian and bucket in _CANADIAN_BUCKET_VARIANTS:
                return _CANADIAN_BUCKET_VARIANTS[bucket]
            return bucket
    return None


def _num(value):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _ticker_root(ticker: str) -> str:
    """Exchange-agnostic issuer root: 'TOU.TO' -> 'TOU', 'TECK.B' -> 'TECK'.

    Used to keep the analyzed company out of its own peer list even when the
    bucket carries a different listing of the same issuer (ARX vs ARX.TO)."""
    return (ticker or "").strip().upper().split(".")[0]


def _net_debt_to_cash_flow(info: dict):
    """Net debt / operating cash flow — the WCSB leverage metric (ability to
    service debt and fund shareholder returns). Returns None unless debt and a
    positive operating cash flow are both available; yfinance totalDebt
    includes leases, so treat this as a screening approximation."""
    total_debt = _num(info.get("totalDebt"))
    cash = _num(info.get("totalCash")) or 0.0
    ocf = _num(info.get("operatingCashflow"))
    if total_debt is None or ocf is None or ocf <= 0:
        return None
    return (total_debt - cash) / ocf


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
        "net_debt_cf": _net_debt_to_cash_flow(info),
    }


def get_peer_data(ticker: str, sector: str, tickers: list[str] | None = None) -> dict:
    """Fetch peer metrics. `tickers` overrides the sector's default peer set,
    letting the caller pass a user-edited list (e.g. Canadian energy names)."""
    try:
        ticker = (ticker or "").strip().upper()
        sector = (sector or "").strip()
        if tickers is None:
            tickers = peer_map.get(sector, [])
        tickers = [t.strip().upper() for t in tickers if t and t.strip()]
        if not tickers:
            return {"peers": [], "medians": {}, "error": f"No peer tickers for sector '{sector}'."}

        peer_tickers = [peer for peer in tickers if _ticker_root(peer) != _ticker_root(ticker)]
        peers = []
        for peer in peer_tickers:
            try:
                peers.append(_fetch_peer(peer))
            except Exception:
                continue

        if not peers:
            return {"peers": [], "medians": {}, "error": "No peer data could be fetched."}

        medians = {}
        for metric in ["pe", "ev_ebitda", "pb", "ps", "rev_growth", "gross_margin", "net_debt_cf"]:
            values = [row.get(metric) for row in peers if row.get(metric) is not None]
            medians[metric] = median(values) if values else None

        return {"peers": peers, "medians": medians, "error": None}
    except Exception as e:
        return {"peers": [], "medians": {}, "error": str(e)}
