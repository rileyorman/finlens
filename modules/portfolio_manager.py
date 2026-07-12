import json
from pathlib import Path

from modules.excel_exporter import _calc_summary_metrics
from modules.market_data import get_market_data
from modules.red_flag_detector import detect_flags
from config import FILING_LIBRARY_PATH

_LIBRARY_PATH = FILING_LIBRARY_PATH

_CHAR_REPLACEMENTS = {
    '—': '--',   # em dash
    '–': '-',    # en dash
    '‘': "'",    # left single quote
    '’': "'",    # right single quote
    '“': '"',    # left double quote
    '”': '"',    # right double quote
    '•': '*',    # bullet
    'â': "'",  # UTF-8 mangled apostrophe
}


def _clean(text: str) -> str:
    if not text:
        return text
    # Catch already-mangled em dashes (Windows encoding corruption → ' ? ')
    text = text.replace(' ? ', ' -- ')
    for char, replacement in _CHAR_REPLACEMENTS.items():
        text = text.replace(char, replacement)
    return text


def _quality_score(m: dict):
    """0–100 quality score over the AVAILABLE RAG metrics only (Green=20,
    Amber=10, Red=0, rescaled to the available maximum). Missing data is
    not poor quality. Returns None when no metrics are available.

    Mirrors app.py _quality_score — keep the two in sync."""
    def pts(metric, value):
        if metric == "liquidity":  return 20 if value >= 2.0 else (10 if value >= 1.0 else 0)
        if metric == "leverage":   return 20 if value <= 1.5 else (10 if value <= 3.0 else 0)
        if metric == "rev_growth": return 20 if value >= 5.0 else (10 if value >= 0.0 else 0)
        if metric == "fcf_conv":   return 20 if value >= 100.0 else (10 if value >= 50.0 else 0)
        if metric == "int_cover":  return 20 if value >= 3.0 else (10 if value >= 1.5 else 0)
        return 0

    checks = [
        ("liquidity",  m.get("current_ratio")),
        ("leverage",   m.get("nd_ebitda")),
        ("rev_growth", m.get("rev_growth")),
        ("fcf_conv",   m.get("fcf_conv")),
        ("int_cover",  m.get("int_cover")),
    ]
    earned = 0
    available = 0
    for metric, value in checks:
        if value is None:
            continue
        available += 1
        earned += pts(metric, value)
    if available == 0:
        return None
    return round(earned / (available * 20) * 100)


def get_portfolio_display_data(tickers: list, filing_library_path: str = None) -> list:
    """For each ticker fetch live market data and merge FinLens analysis if available.

    Never raises — missing market data or library entries degrade to None / '—'.
    """
    lib_path = Path(filing_library_path) if filing_library_path else _LIBRARY_PATH
    try:
        with open(lib_path, "r", encoding="utf-8") as f:
            lib_entries = json.load(f).get("entries", [])
    except Exception:
        lib_entries = []

    # Build ticker → entry lookup (only entries with a real ticker)
    ticker_map = {}
    for entry in lib_entries:
        t = (entry.get("ticker") or "").upper().strip()
        if t and t != "—":
            ticker_map[t] = entry

    result = []
    for ticker in tickers:
        ticker_upper = ticker.upper().strip()

        # Wrong-issuer guard (bare-ticker collision class, 2026-07-12): when
        # the portfolio ticker matches a library entry, arm the name-agreement
        # guard with the FILING's company name (and prefer .TO/.V listings for
        # SEDAR filers) — bare "ARX" must never serve Accelerant's market cap
        # against ARC's fundamentals. User-added tickers with no library
        # context keep the bare fetch (the user chose the listing symbol).
        entry = ticker_map.get(ticker_upper)
        guard_name = None
        prefer_canadian = False
        if entry:
            fd_for_guard = entry.get("financial_data") or {}
            guard_name = (
                fd_for_guard.get("company_name")
                or fd_for_guard.get("company")
                or (entry.get("summary_data") or {}).get("company_name")
            )
            prefer_canadian = fd_for_guard.get("source") == "sedar_pdf"

        try:
            md = get_market_data(ticker_upper, company_name=guard_name,
                                 prefer_canadian=prefer_canadian)
        except Exception:
            md = {}
        if entry:
            fd = entry.get("financial_data") or {}
            sd = entry.get("summary_data") or {}
            dd = entry.get("dashboard_data") or {}

            try:
                metrics = _calc_summary_metrics(fd)
            except Exception:
                metrics = {}

            qs = _quality_score(metrics)

            try:
                flag_result  = detect_flags(fd)
                red_count    = flag_result["red_count"]
                yellow_count = flag_result["yellow_count"]
                red_flags    = [f for f in flag_result["flags"] if f["severity"] == "red"]
                top_red_flag = red_flags[0]["label"] if red_flags else None
            except Exception:
                red_count, yellow_count, top_red_flag = 0, 0, None

            analysis = {
                "has_analysis":      True,
                "company_name":      fd.get("company_name", ticker_upper),
                "fiscal_year":       fd.get("fiscal_year") or "—",
                "signal":            (sd.get("signal") or "—").upper(),
                "quality_score":     qs,
                "lynch_category":    dd.get("lynch_category") or "—",
                "lynch_story":       _clean(dd.get("lynch_story") or "—"),
                "red_flag_count":    red_count,
                "yellow_flag_count": yellow_count,
                "top_red_flag":      top_red_flag,
                "dalio_view":        _clean(dd.get("dalio_view") or "—"),
                "marks_view":        _clean(dd.get("marks_view") or "—"),
                "current_ratio":     metrics.get("current_ratio"),
                "net_margin":        metrics.get("ni_margin"),
                "revenue_yoy":       metrics.get("yoy_rev"),
                "fcf_conv":          metrics.get("fcf_conv"),
                "gross_margin":      metrics.get("gp_margin"),
            }
        else:
            analysis = {
                "has_analysis":      False,
                "company_name":      ticker_upper,
                "fiscal_year":       "—",
                "signal":            None,
                "quality_score":     None,
                "lynch_category":    "—",
                "lynch_story":       "—",
                "red_flag_count":    0,
                "yellow_flag_count": 0,
                "top_red_flag":      None,
                "dalio_view":        "—",
                "marks_view":        "—",
                "current_ratio":     None,
                "net_margin":        None,
                "revenue_yoy":       None,
                "fcf_conv":          None,
                "gross_margin":      None,
            }

        result.append({
            "ticker":              ticker_upper,
            "price":               md.get("current_price"),
            "market_cap":          md.get("market_cap"),
            "pe_ratio":            md.get("pe_ratio"),
            "fifty_two_week_high": md.get("fifty_two_week_high"),
            "fifty_two_week_low":  md.get("fifty_two_week_low"),
            **analysis,
        })

    return result
