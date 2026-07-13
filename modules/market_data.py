import os
import platform
import ssl
import tempfile
from difflib import SequenceMatcher
import yfinance as yf

# Data from yfinance — delayed ~15 mins. Verify before use in live analysis.


def _patch_windows_ssl():
    """Export Windows system cert store to a PEM file and set CURL_CA_BUNDLE /
    REQUESTS_CA_BUNDLE so that yfinance (curl_cffi + requests) trusts the
    Avast CA. No-op on non-Windows or if the env var is already set."""
    if platform.system() != "Windows":
        return
    if os.environ.get("CURL_CA_BUNDLE"):
        return
    try:
        pem_parts = []
        for store in ("ROOT", "CA"):
            for cert, enc, _ in ssl.enum_certificates(store):
                if enc == "x509_asn":
                    pem_parts.append(ssl.DER_cert_to_PEM_cert(cert))
        if not pem_parts:
            return
        # Deliberate temp usage: per-session generated cert, rebuilt on every launch — not persistent app data. Audited Jun 2026.
        cert_path = os.path.join(tempfile.gettempdir(), "finlens_win_certs.pem")
        with open(cert_path, "w") as f:
            f.write("\n".join(pem_parts))
        os.environ["CURL_CA_BUNDLE"]    = cert_path
        os.environ["REQUESTS_CA_BUNDLE"] = cert_path
    except Exception:
        pass  # fail silently — yfinance will attempt without the custom bundle


_patch_windows_ssl()


def _to_yfinance_ticker(ticker: str) -> str:
    """Translate TSX dot-format tickers to yfinance format (e.g. REI.UN -> REI-UN.TO)."""
    t = (ticker or "").strip().upper()
    if not t:
        return t
    if t in _TICKER_OVERRIDES:
        return _TICKER_OVERRIDES[t]
    if any(t.endswith(sfx) for sfx in (".TO", ".V", ".CN", ".NE")):
        return t
    if "." in t:
        return t.replace(".", "-") + ".TO"
    return t


# Tier 0 = major US exchanges (NYSE + NASDAQ peers). Foreign/unknown = 99.
# Within the same tier, name similarity breaks ties.
_EXCHANGE_RANK = {
    "NYQ": 0, "NYSE": 0,                    # New York Stock Exchange
    "NMS": 0, "NGS": 0, "NAS": 0,           # NASDAQ Global Select Market
    "NASDAQ": 0,                             # NASDAQ generic
    "NGM": 1,                                # NASDAQ Global Market
    "NCM": 2,                                # NASDAQ Capital Market
    "ASE": 3, "AMEX": 3,                    # NYSE American (formerly AMEX)
    "PCX": 4,                                # NYSE Arca
    "BTS": 5,                                # BATS
    "NYB": 6,                                # NYSE Bonds
}


# Canadian listings ranked just below US (keyed on symbol suffix, which is more
# reliable than Yahoo's exchange codes) so a TSX-primary name (e.g. Tourmaline
# -> TOU.TO) outranks its German/Mexican cross-listings (08T.DU, etc.).
_CA_SUFFIX_RANK = {".TO": 10, ".V": 11, ".CN": 12, ".NE": 13}

# Campaign-scoped override; intentionally shadows National Fuel Gas (NYSE: NFG).
_TICKER_OVERRIDES = {
    "NFG": "NFG.V",
}


def _exchange_rank(quote: dict) -> int:
    code = (quote.get("exchange") or "").upper()
    if code in _EXCHANGE_RANK:
        return _EXCHANGE_RANK[code]
    symbol = (quote.get("symbol") or "").upper()
    for suffix, rank in _CA_SUFFIX_RANK.items():
        if symbol.endswith(suffix):
            return rank
    return 99


def _name_similarity(query: str, quote: dict) -> float:
    """Similarity score 0.0–1.0 between search query and company name."""
    name = (quote.get("longname") or quote.get("shortname") or "").lower().strip()
    if not name:
        return 0.0
    return SequenceMatcher(None, query.lower().strip(), name).ratio()


def _sort_key(query: str):
    """Sort key: US exchange tier first, then name similarity (higher = better)."""
    def key(quote: dict):
        return (_exchange_rank(quote), -_name_similarity(query, quote))
    return key


def search_ticker_details(company_name: str, max_results: int = 5) -> list:
    """Return yfinance search results sorted US-first, then by name match."""
    if not company_name or not company_name.strip():
        return []
    try:
        results = yf.Search(company_name.strip(), max_results=max_results)
        return sorted(results.quotes, key=_sort_key(company_name.strip()))
    except Exception:
        return []


def search_ticker(company_name: str):
    """Search yfinance for a ticker by company name. Returns the best US-listed symbol, or None."""
    quotes = search_ticker_details(company_name)
    if quotes:
        return quotes[0].get("symbol")
    return None


_EMPTY = {
    "market_cap":          None,
    "currency":            None,
    "current_price":       None,
    "shares_outstanding":  None,
    "pe_ratio":            None,
    "beta":                None,
    "ev_ebitda":           None,
    "pb":                  None,
    "ps":                  None,
    "rev_growth":          None,
    "gross_margin":        None,
    "fifty_two_week_high": None,
    "fifty_two_week_low":  None,
    "sector":              None,
    "industry":            None,
    "resolved_symbol":     None,
    "resolved_name":       None,
    "resolution_note":     None,
}


_CA_SUFFIXES = (".TO", ".V", ".CN", ".NE")

# Legal-form words carry no identity signal and inflate mismatch scores
# ("ARC Resources Ltd." vs "ARC Resources" must agree).
_LEGAL_NAME_WORDS = {
    "ltd", "ltd.", "limited", "inc", "inc.", "incorporated", "corp", "corp.",
    "corporation", "plc", "co", "co.", "company", "the", "trust", "lp", "llc",
}

# Minimum normalized-name similarity to accept a listing as the filing's
# issuer. Calibrated on the reference collision: "ARC Resources Ltd." vs
# "Accelerant Holdings" scores ~0.35 (reject); true matches score ~1.0.
_NAME_AGREE_THRESHOLD = 0.60


def _normalize_company_name(name: str) -> str:
    text = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in str(name or "").lower())
    words = [w for w in text.split() if w not in _LEGAL_NAME_WORDS]
    return " ".join(words)


def _names_agree(filing_name: str, listing_name: str) -> bool:
    """True when the yfinance listing plausibly IS the filing's issuer."""
    a = _normalize_company_name(filing_name)
    b = _normalize_company_name(listing_name)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    return SequenceMatcher(None, a, b).ratio() >= _NAME_AGREE_THRESHOLD


def _candidate_symbols(ticker: str, prefer_canadian: bool = False) -> list[str]:
    """Symbols to try, in order. A bare ticker on a Canadian filing tries the
    TSX/TSXV listings before the bare symbol — a bare TSX-only ticker resolves
    on yfinance to whatever US issuer holds that symbol (reference collision:
    bare 'ARX' = Accelerant Holdings, an insurance broker; ARC Resources is
    ARX.TO)."""
    translated = _to_yfinance_ticker(ticker)
    if not translated:
        return []
    if prefer_canadian and not any(translated.endswith(sfx) for sfx in _CA_SUFFIXES):
        return [f"{translated}.TO", f"{translated}.V", translated]
    return [translated]


def _fetch_symbol_payload(symbol: str) -> dict | None:
    """Fetch one symbol's market payload; None when it has no live price."""
    t = yf.Ticker(symbol)
    fi = t.fast_info  # lightweight endpoint — reliable for small-caps

    current_price = getattr(fi, "last_price", None)
    if not current_price:
        return None

    raw_mc = getattr(fi, "market_cap", None)
    market_cap = round(raw_mc / 1_000_000, 2) if raw_mc else None
    # Listing currency travels WITH the market cap (boundary principle) —
    # consumers gate cross-currency math on it (the FX-guard discipline:
    # abstain, never convert).
    listing_currency = getattr(fi, "currency", None)

    # Ratios, classification, and the listing's company name need the heavier
    # info call — best-effort, won't block the rest.
    pe_ratio = None
    beta = None
    ev_ebitda = None
    pb = None
    ps = None
    rev_growth = None
    gross_margin = None
    sector = None
    industry = None
    resolved_name = None
    try:
        info = t.info
        listing_currency = listing_currency or info.get("currency")
        pe_ratio = info.get("trailingPE")
        beta = info.get("beta")
        ev_ebitda = info.get("enterpriseToEbitda")
        pb = info.get("priceToBook")
        ps = info.get("priceToSalesTrailing12Months")
        rev_growth = info.get("revenueGrowth")
        gross_margin = info.get("grossMargins")
        sector = info.get("sector")
        industry = info.get("industry")
        resolved_name = info.get("longName") or info.get("shortName")
    except Exception:
        pass

    return {
        "market_cap":          market_cap,
        "currency":            (str(listing_currency).strip().upper() or None) if listing_currency else None,
        "current_price":       current_price,
        "shares_outstanding":  getattr(fi, "shares", None),
        "pe_ratio":            pe_ratio,
        "beta":                beta,
        "ev_ebitda":           ev_ebitda,
        "pb":                  pb,
        "ps":                  ps,
        "rev_growth":          rev_growth,
        "gross_margin":        gross_margin,
        "fifty_two_week_high": getattr(fi, "fifty_two_week_high", None),
        "fifty_two_week_low":  getattr(fi, "fifty_two_week_low", None),
        "sector":              sector,
        "industry":            industry,
        "resolved_symbol":     symbol,
        "resolved_name":       resolved_name,
        "resolution_note":     None,
    }


def get_market_data(ticker: str, company_name: str | None = None,
                    prefer_canadian: bool = False) -> dict:
    """Return key market data for a ticker. All fields are None if ticker is
    missing, not found, or the fetch fails for any reason.

    company_name arms the wrong-issuer guard: a candidate listing whose
    company name disagrees with the filing's is REJECTED rather than served
    (honest absence beats a confident wrong market cap). prefer_canadian
    (pass for SEDAR filings) tries .TO/.V listings before the bare symbol.
    """
    if not ticker or not ticker.strip():
        return dict(_EMPTY)

    rejected_names = []
    try:
        for symbol in _candidate_symbols(ticker, prefer_canadian=prefer_canadian):
            try:
                payload = _fetch_symbol_payload(symbol)
            except Exception:
                continue
            if payload is None:
                continue

            resolved_name = payload.get("resolved_name")
            if company_name:
                if resolved_name:
                    if not _names_agree(company_name, resolved_name):
                        rejected_names.append(f"{symbol} ({resolved_name})")
                        continue
                elif prefer_canadian and not any(symbol.endswith(sfx) for sfx in _CA_SUFFIXES):
                    # Bare US symbol for a Canadian filer with an unverifiable
                    # name is exactly the collision case — refuse it honestly.
                    rejected_names.append(f"{symbol} (name unavailable)")
                    continue
            return payload

        empty = dict(_EMPTY)
        if rejected_names:
            empty["resolution_note"] = (
                f"No listing matched the filing company name '{company_name}' — "
                f"rejected: {', '.join(rejected_names)}."
            )
        return empty
    except Exception:
        return dict(_EMPTY)
