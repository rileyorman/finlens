import json
from pathlib import Path

from modules.excel_exporter import _calc_summary_metrics
from modules.market_data import get_market_data
from modules.red_flag_detector import detect_flags

_LIBRARY_PATH = Path(__file__).parent.parent / "filing_library.json"


def _quality_score(m: dict) -> int:
    """0–100 from 5 RAG metrics. Green=20, Amber=10, Red/None=0."""
    def pts(metric, value):
        if value is None:
            return 0
        if metric == "liquidity":  return 20 if value >= 2.0 else (10 if value >= 1.0 else 0)
        if metric == "leverage":   return 20 if value <= 1.5 else (10 if value <= 3.0 else 0)
        if metric == "rev_growth": return 20 if value >= 5.0 else (10 if value >= 0.0 else 0)
        if metric == "fcf_conv":   return 20 if value >= 100.0 else (10 if value >= 50.0 else 0)
        if metric == "int_cover":  return 20 if value >= 3.0 else (10 if value >= 1.5 else 0)
        return 0
    return sum([
        pts("liquidity",  m.get("current_ratio")),
        pts("leverage",   m.get("nd_ebitda")),
        pts("rev_growth", m.get("rev_growth")),
        pts("fcf_conv",   m.get("fcf_conv")),
        pts("int_cover",  m.get("int_cover")),
    ])


def get_portfolio_data() -> list:
    """Read all Filing Library entries and return clean dicts for portfolio display.

    Never calls the Claude API — reads only from filing_library.json.
    Degrades cleanly: missing fields return None or '—', never raise.
    """
    if not _LIBRARY_PATH.exists():
        return []
    try:
        with open(_LIBRARY_PATH, "r", encoding="utf-8") as f:
            library = json.load(f)
    except Exception:
        return []

    result = []
    for entry in library.get("entries", []):
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

        result.append({
            "company_name":      fd.get("company_name", "Unknown"),
            "ticker":            sd.get("ticker") or "—",
            "fiscal_year":       fd.get("fiscal_year") or "—",
            "signal":            (sd.get("signal") or "—").upper(),
            "quality_score":     qs,
            "lynch_category":    dd.get("lynch_category") or "—",
            "lynch_story":       dd.get("lynch_story") or "—",
            "revenue":           metrics.get("rev_c"),
            "revenue_yoy":       metrics.get("yoy_rev"),
            "gross_margin":      metrics.get("gp_margin"),
            "net_margin":        metrics.get("ni_margin"),
            "current_ratio":     metrics.get("current_ratio"),
            "red_flag_count":    red_count,
            "yellow_flag_count": yellow_count,
            "top_red_flag":      top_red_flag,
            "dalio_view":        dd.get("dalio_view") or "—",
            "marks_view":        dd.get("marks_view") or "—",
        })

    return result


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

        try:
            md = get_market_data(ticker_upper)
        except Exception:
            md = {}

        entry = ticker_map.get(ticker_upper)
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
                "lynch_story":       dd.get("lynch_story") or "—",
                "red_flag_count":    red_count,
                "yellow_flag_count": yellow_count,
                "top_red_flag":      top_red_flag,
                "dalio_view":        dd.get("dalio_view") or "—",
                "marks_view":        dd.get("marks_view") or "—",
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
