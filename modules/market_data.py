import os
import ssl
import sys
import tempfile
import yfinance as yf

# Data from yfinance — delayed ~15 mins. Verify before use in live analysis.


def _patch_windows_ssl():
    """Export Windows system cert store to a PEM file and set CURL_CA_BUNDLE /
    REQUESTS_CA_BUNDLE so that yfinance (curl_cffi + requests) trusts the
    Avast CA. No-op on non-Windows or if the env var is already set."""
    if sys.platform != "win32":
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
        cert_path = os.path.join(tempfile.gettempdir(), "finlens_win_certs.pem")
        with open(cert_path, "w") as f:
            f.write("\n".join(pem_parts))
        os.environ["CURL_CA_BUNDLE"]    = cert_path
        os.environ["REQUESTS_CA_BUNDLE"] = cert_path
    except Exception:
        pass  # fail silently — yfinance will attempt without the custom bundle


_patch_windows_ssl()


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
        t = yf.Ticker(ticker.strip())
        fi = t.fast_info  # lightweight endpoint — reliable for small-caps

        current_price = getattr(fi, "last_price", None)
        if not current_price:
            return dict(_EMPTY)

        raw_mc = getattr(fi, "market_cap", None)
        market_cap = round(raw_mc / 1_000_000, 2) if raw_mc else None

        # P/E requires the heavier info call — best-effort, won't block the rest
        pe_ratio = None
        try:
            pe_ratio = t.info.get("trailingPE")
        except Exception:
            pass

        return {
            "market_cap":          market_cap,
            "current_price":       current_price,
            "shares_outstanding":  getattr(fi, "shares", None),
            "pe_ratio":            pe_ratio,
            "fifty_two_week_high": getattr(fi, "fifty_two_week_high", None),
            "fifty_two_week_low":  getattr(fi, "fifty_two_week_low", None),
        }

    except Exception:
        return dict(_EMPTY)
