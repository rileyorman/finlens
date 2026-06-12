from dotenv import load_dotenv
load_dotenv()

import os
import io
import re
import json
import logging
import tempfile
from html import escape
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus
import streamlit as st
import yfinance as yf
from streamlit_cookies_manager import CookieManager

from modules.pdf_extractor import extract_text_from_pdf
from modules.document_converter import convert_to_markdown
from modules.claude_analyzer import (
    analyze_financials,
    analyze_summary,
    analyze_bear_bull,
    analyze_dashboard_insights,
    analyze_mda_sentiment,
    build_filing_context,
    normalize_financial_data,
    normalize_and_validate,
)
from modules.integrity import cross_validate_filing
from modules.filing_comparison import compare_filings
from modules.scenario_simulator import run_scenario
from modules.excel_exporter import create_excel_file, _calc_summary_metrics
from modules.memo_exporter import create_memo
from modules.edgar_fetcher import (
    get_cik,
    get_filing_text,
    get_recent_filings,
    get_ticker_for_cik,
    get_financial_data as get_edgar_financial_data,
    search_companies as search_edgar_companies,
    _fmt as _fmt_edgar_value,
)
from modules.education_content import EDUCATION
from modules.red_flag_detector import detect_flags
from modules.market_data import get_market_data, search_ticker, search_ticker_details
from modules.peer_comparison import get_peer_data, peer_map
from modules.dcf_calculator import calculate_dcf
from modules.cache import get_cache_key, load_cache, save_cache, clear_cache, cache_count
from modules.analysis_cache import load_analysis, save_analysis
from modules.filing_library import (
    add_entry as lib_add,
    get_entries as lib_get,
    delete_entry as lib_delete,
    import_entries as lib_import_entries,
)
from modules import supabase_storage
from modules.portfolio_registry import (
    get_portfolio_names, create_portfolio,
    delete_portfolio as del_portfolio_reg,
    add_ticker as reg_add_ticker, remove_ticker as reg_remove_ticker,
    bulk_add_tickers, get_tickers,
)
from modules.portfolio_manager import get_portfolio_display_data
from modules.position_tracker import (
    load_positions, save_position, delete_position, calculate_portfolio_pl,
    sell_position,
)
from modules.market_ticker import get_ticker_data
from modules.fmp import build_financial_data_from_fmp
from config import (
    EXTRACTION_MODEL,
    ANALYSIS_MODEL,
    MAX_FILING_CHARS,
    ANALYSIS_CACHE_DIR,
    CACHE_DIR,
    EDGAR_TEXT_DIR,
    LIBRARY_DIR,
    LIBRARY_PDFS_DIR,
    FILING_LIBRARY_PATH,
    safe_write_bytes,
    safe_write_text,
)
import plotly.graph_objects as go

logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="FinLens",
    page_icon="assets/finlens_favicon.svg",
    layout="wide",
)

cookies = CookieManager()
cookies._default_expiry = datetime.now() + timedelta(days=30)
if not cookies.ready():
    st.stop()

API_KEY = os.getenv("ANTHROPIC_API_KEY")


def _get_filing_context(filing_text: str, ticker: str | None, period: str | None) -> list:
    ticker_key = (ticker or "unknown").strip().upper() or "unknown"
    period_key = re.sub(r"\s+", "_", (period or "unknown").strip()) or "unknown"
    cache_key = f"filing_context::{ticker_key}::{period_key}"
    if cache_key not in st.session_state:
        st.session_state[cache_key] = build_filing_context(filing_text)
    return st.session_state[cache_key]


def get_model():
    if st.session_state.get("demo_mode", False):
        return "claude-opus-4-8"
    return ANALYSIS_MODEL


def get_mda_model():
    return EXTRACTION_MODEL


def _run_integrity_checks(
    financial_data: dict | None,
    summary_data: dict | None,
    ticker: str | None,
    source: str,
    filing_date: str | None = None,
    accession: str | None = None,
) -> dict | None:
    """Attach integrity metadata without letting checks block analysis."""
    if not isinstance(financial_data, dict):
        return financial_data

    ticker_value = (ticker or (summary_data or {}).get("ticker") or financial_data.get("ticker") or "").strip().upper()
    sector_value = (summary_data or {}).get("sector_inferred")
    filing_metadata = {
        "source": source,
        "filing_date": filing_date,
        "accession": accession,
    }

    try:
        normalize_and_validate(financial_data, ticker_value, sector_value, filing_metadata)
    except Exception:
        logger.exception("Integrity validation failed for %s", ticker_value)

    try:
        fiscal_year = financial_data.get("fiscal_year") or financial_data.get("period")
        if ticker_value and fiscal_year:
            cv_result = cross_validate_filing(financial_data, ticker_value, fiscal_year, filing_metadata)
            financial_data["_cross_validation"] = cv_result.to_dict()
    except Exception:
        logger.exception("Integrity cross-validation failed for %s", ticker_value)

    return financial_data


def _integrity_flag_names(financial_data: dict | None) -> list[str]:
    checks = ((financial_data or {}).get("_integrity") or {}).get("checks") or []
    return [
        str(check.get("rule_id"))
        for check in checks
        if isinstance(check, dict) and not check.get("passed") and not check.get("skipped")
    ]


def _upload_analysis_source(resolved_ticker: str | None) -> str:
    ticker_value = (resolved_ticker or "").strip().upper()
    sedar_company = st.session_state.get("sedar_company") or {}
    sedar_ticker = (
        sedar_company.get("ticker")
        or sedar_company.get("symbol")
        or ""
    ).strip().upper()
    if ticker_value and sedar_ticker and ticker_value == sedar_ticker:
        return "sedar"
    if ticker_value.endswith(".TO"):
        return "sedar"
    return "pdf"


LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
LIBRARY_PDFS_DIR.mkdir(parents=True, exist_ok=True)
ANALYSIS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
EDGAR_TEXT_DIR.mkdir(parents=True, exist_ok=True)
FILING_LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)


def _fmt_market_cap(mc_millions):
    """Format market cap (stored in millions) as $X.XT / $X.XB / $X.XM."""
    if not mc_millions:
        return "—"
    if mc_millions >= 1_000_000:
        return f"${mc_millions / 1_000_000:.1f}T"
    if mc_millions >= 1_000:
        return f"${mc_millions / 1_000:.1f}B"
    return f"${mc_millions:.0f}M"


SEDAR_SEARCH_URL = "https://www.sedarplus.ca/csa-party/party/search.html"
SEDAR_FILING_TYPES = [
    "Annual MD&A",
    "Interim MD&A (Q1 / Q2 / Q3)",
    "Annual Information Form (AIF)",
    "Annual Financial Statements",
    "Interim Financial Statements",
]
SEDAR_QUICK_LINKS = [
    ("Annual MD&A", "Annual MD&A"),
    ("Interim MD&A", "Interim MD&A"),
    ("AIF", "Annual Information Form (AIF)"),
    ("Annual Financial Statements", "Annual Financial Statements"),
    ("Interim Financial Statements", "Interim Financial Statements"),
]
CANADIAN_EXCHANGES = {"TOR", "TSX", "CNQ", "VAN"}
US_EXCHANGES = {"NMS", "NYQ", "NGM", "NCM", "ASE", "AMEX", "PCX", "NASDAQ", "NYSE"}


def _ensure_yfinance_cache_location():
    try:
        cache_dir = os.path.join(tempfile.gettempdir(), "finlens_yfinance_cache")
        os.makedirs(cache_dir, exist_ok=True)
        yf.set_tz_cache_location(cache_dir)
    except Exception:
        pass


def _sedar_search_url(company_name: str, filing_type: str | None = None) -> str:
    query = (company_name or "").strip()
    url = f"{SEDAR_SEARCH_URL}?query={quote_plus(query)}"
    if filing_type:
        url = f"{url}&filing_type={quote_plus(filing_type)}"
    return url


def _external_link(label: str, url: str):
    safe_url = escape(url, quote=True)
    safe_label = escape(label)
    st.markdown(
        f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer">{safe_label}</a>',
        unsafe_allow_html=True,
    )


def _yf_quote_name(quote: dict) -> str:
    return (
        quote.get("shortName")
        or quote.get("shortname")
        or quote.get("longName")
        or quote.get("longname")
        or quote.get("displayName")
        or quote.get("symbol")
        or "Unknown company"
    )


def _yf_quote_label(quote: dict) -> str:
    name = _yf_quote_name(quote)
    symbol = quote.get("symbol") or ""
    exchange = quote.get("exchange") or ""
    return f"{name} — {symbol} ({exchange})"


def _search_yfinance_equities(query: str, max_results: int = 8) -> list[dict]:
    try:
        query = (query or "").strip()
        if not query:
            return []
        _ensure_yfinance_cache_location()
        results = yf.Search(query, max_results=max_results).quotes
        return [
            quote for quote in results
            if isinstance(quote, dict) and (quote.get("quoteType") or "").upper() == "EQUITY"
        ]
    except Exception:
        return []


def _is_canadian_quote(quote: dict) -> bool:
    symbol = (quote.get("symbol") or "").upper()
    exchange = (quote.get("exchange") or "").upper()
    return symbol.endswith(".TO") or exchange in CANADIAN_EXCHANGES


def _is_us_quote(quote: dict) -> bool:
    symbol = (quote.get("symbol") or "").upper()
    exchange = (quote.get("exchange") or "").upper()
    return "." not in symbol and exchange in US_EXCHANGES


def _resolve_sedar_company_from_yfinance(ticker: str) -> dict | None:
    symbol = (ticker or "").strip().upper()
    if not symbol:
        return None

    _ensure_yfinance_cache_location()

    candidates = [symbol]
    if "." not in symbol:
        candidates.extend([f"{symbol}.TO", f"{symbol}.V"])

    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            info = yf.Ticker(candidate).info or {}
        except Exception:
            continue

        company_name = (
            info.get("longName")
            or info.get("shortName")
            or info.get("displayName")
            or info.get("name")
        )
        quote_type = (info.get("quoteType") or "").upper()
        if company_name and quote_type in {"EQUITY", "ETF", ""}:
            return {"symbol": candidate, "company_name": company_name}
    return None


def _quality_score(m: dict) -> int:
    """0–100 quality score from 5 RAG health metrics. Green=20, Amber=10, Red/None=0."""
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


def _dash_rag(metric: str, value) -> tuple:
    """Return (bg_hex, label) for dashboard RAG cells — mirrors excel_exporter thresholds."""
    if value is None:
        return "#D9D9D9", "N/A"
    if metric == "liquidity":  c = "G" if value >= 2.0 else ("A" if value >= 1.0 else "R")
    elif metric == "leverage": c = "G" if value <= 1.5 else ("A" if value <= 3.0 else "R")
    elif metric == "rev_growth": c = "G" if value >= 5.0 else ("A" if value >= 0.0 else "R")
    elif metric == "fcf_conv": c = "G" if value >= 100.0 else ("A" if value >= 50.0 else "R")
    elif metric == "int_cover": c = "G" if value >= 3.0 else ("A" if value >= 1.5 else "R")
    else: return "#D9D9D9", "N/A"
    return {"G": ("#70AD47", "GREEN"), "A": ("#FFC000", "AMBER"), "R": ("#C00000", "RED")}[c]


def _pdf_cache_path(ticker: str | None, period: str | None) -> str | None:
    """Return disk cache path for a filing PDF, or None if ticker/period unavailable."""
    if not ticker or not period:
        return None
    safe = re.sub(r"[^\w\-]", "_", f"{ticker}_{period}")
    return str(LIBRARY_PDFS_DIR / f"{safe}.pdf")


def _text_cache_path(ticker: str | None, period: str | None) -> str | None:
    """Return disk cache path for extracted filing text, or None if identifiers are unavailable."""
    if not ticker or not period:
        return None
    safe = re.sub(r"[^\w\-]", "_", f"{ticker}_{period}")
    return str(LIBRARY_PDFS_DIR / f"{safe}.txt")


def _edgar_filing_cache_path(ticker: str | None, accession: str | None) -> str | None:
    """Disk cache path keyed by ticker+accession (unique per SEC filing)."""
    if not ticker or not accession:
        return None
    safe = re.sub(r"[^\w\-]", "_", f"{ticker}_{accession}")
    return str(LIBRARY_PDFS_DIR / f"{safe}.txt")


def _read_text_cache(path: str | None) -> str | None:
    if not path:
        return None
    try:
        text_file = Path(path)
        if text_file.exists():
            with text_file.open("r", encoding="utf-8") as _f:
                return _f.read()
    except Exception:
        return None
    return None


def _library_text_for_entry(entry: dict) -> str | None:
    """Return cached filing text for library entries that store source text on disk."""
    text = _read_text_cache(entry.get("file_path"))
    if text:
        return text
    if entry.get("source") == "edgar":
        text = _read_text_cache(
            _text_cache_path(
                entry.get("ticker") if entry.get("ticker") != "—" else None,
                entry.get("fiscal_year") or entry.get("period", ""),
            )
        )
        if text:
            return text
    return entry.get("raw_text")


def _supabase_row_to_library_entry(row: dict) -> dict:
    data = row.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    financial_data = data.get("financial_data") if isinstance(data.get("financial_data"), dict) else {}
    summary_data = data.get("summary_data") if isinstance(data.get("summary_data"), dict) else None
    bear_bull_data = data.get("bear_bull_data") if isinstance(data.get("bear_bull_data"), dict) else None
    dashboard_data = data.get("dashboard_data") if isinstance(data.get("dashboard_data"), dict) else None
    mda_sentiment = data.get("mda_sentiment") if isinstance(data.get("mda_sentiment"), dict) else None
    raw_text = data.get("raw_text") if isinstance(data.get("raw_text"), str) else None

    ticker = row.get("ticker") or (summary_data or {}).get("ticker") or "—"
    period = row.get("period") or financial_data.get("period", "")
    company = row.get("company") or financial_data.get("company_name", "Unknown")

    return {
        "id": row.get("id") or f"{ticker}_{period}",
        "company_name": company,
        "ticker": ticker,
        "period": period,
        "fiscal_year": financial_data.get("fiscal_year") or period,
        "analysed_at": row.get("created_at", ""),
        "file_name": data.get("file_name") or (f"{ticker}_{period}.pdf" if ticker and period else ""),
        "file_size_bytes": data.get("file_size_bytes", 0),
        "financial_data": financial_data,
        "summary_data": summary_data,
        "bear_bull_data": bear_bull_data,
        "dashboard_data": dashboard_data,
        "mda_sentiment": mda_sentiment,
        "raw_text": raw_text,
        "source": data.get("source", "pdf"),
        "file_path": data.get("file_path"),
    }


def _hydrate_library_from_supabase() -> None:
    try:
        if lib_get():
            return
        rows = supabase_storage.load_all_filings()
        if not rows:
            return
        lib_import_entries([_supabase_row_to_library_entry(row) for row in rows])
    except Exception:
        pass


def _analysis_period(financial_data: dict) -> str:
    return financial_data.get("fiscal_year") or financial_data.get("period", "")


def _supabase_analysis_payload(
    financial_data: dict,
    summary_data: dict | None,
    bear_bull_data: dict | None,
    dashboard_data: dict | None,
    raw_text: str | None = None,
    mda_sentiment: dict | None = None,
    file_name: str = "",
    file_size: int = 0,
    source: str = "pdf",
    file_path: str | None = None,
) -> dict:
    return {
        "financial_data": financial_data,
        "summary_data": summary_data,
        "bear_bull_data": bear_bull_data,
        "dashboard_data": dashboard_data,
        "mda_sentiment": mda_sentiment,
        "raw_text": raw_text,
        "file_name": file_name,
        "file_size_bytes": file_size,
        "source": source,
        "file_path": file_path,
    }


def _save_analysis_to_supabase(
    ticker: str | None,
    financial_data: dict,
    summary_data: dict | None,
    bear_bull_data: dict | None,
    dashboard_data: dict | None,
    raw_text: str | None = None,
    mda_sentiment: dict | None = None,
    file_name: str = "",
    file_size: int = 0,
    pdf_bytes: bytes | None = None,
    source: str = "pdf",
    file_path: str | None = None,
) -> None:
    try:
        period = _analysis_period(financial_data)
        company = financial_data.get("company_name", "Unknown")
        ticker = ticker or (summary_data or {}).get("ticker")
        if ticker == "—":
            ticker = None
        payload = _supabase_analysis_payload(
            financial_data,
            summary_data,
            bear_bull_data,
            dashboard_data,
            raw_text=raw_text,
            mda_sentiment=mda_sentiment,
            file_name=file_name,
            file_size=file_size,
            source=source,
            file_path=file_path,
        )
        supabase_storage.save_filing(ticker, company, period, payload)
        if pdf_bytes:
            supabase_storage.save_pdf(ticker, period, pdf_bytes)
    except Exception as e:
        logger.warning(f"Supabase save failed: {e}")


def _analysis_cache_payload(
    ticker: str | None,
    period: str | None,
    source: str,
    financial_data: dict | None,
    summary_data: dict | None,
    bear_bull_data: dict | None,
    dashboard_data: dict | None,
    mda_sentiment: dict | None,
    market_data: dict | None,
    sector_value: str | None = None,
    hurdle_rate_value: float | None = None,
) -> dict | None:
    if not ticker or not period or not financial_data:
        return None

    payload = {
        "ticker": ticker,
        "period": period,
        "source": source,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "company_name": financial_data.get("company_name", "Unknown"),
        "financial_data": financial_data,
    }

    optional_values = {
        "summary": summary_data,
        "summary_data": summary_data,
        "bear_bull": bear_bull_data,
        "bear_bull_data": bear_bull_data,
        "dashboard_insights": dashboard_data,
        "dashboard_data": dashboard_data,
        "mda_sentiment": mda_sentiment,
        "market_data": market_data,
        "sector": sector_value or (summary_data or {}).get("sector_inferred") or financial_data.get("sector"),
        "sec_filing_date": (summary_data or {}).get("sec_filing_date") or financial_data.get("sec_filing_date"),
        "hurdle_rate": hurdle_rate_value,
        "market_cap": (market_data or {}).get("market_cap"),
    }

    for key, value in optional_values.items():
        if value is not None:
            payload[key] = value

    try:
        flags = detect_flags(financial_data)
        payload["red_flags"] = flags.get("flags", [])
    except Exception as e:
        logger.warning(f"detect_flags failed: {e}")

    try:
        payload["ratio_data"] = _calc_summary_metrics(financial_data)
    except Exception as e:
        logger.warning(f"_calc_summary_metrics failed: {e}")

    return payload


def _save_analysis_cache(
    ticker: str | None,
    period: str | None,
    source: str,
    financial_data: dict | None = None,
    summary_data: dict | None = None,
    bear_bull_data: dict | None = None,
    dashboard_data: dict | None = None,
    mda_sentiment: dict | None = None,
    market_data: dict | None = None,
    sector_value: str | None = None,
    hurdle_rate_value: float | None = None,
) -> bool:
    payload = _analysis_cache_payload(
        ticker,
        period,
        source,
        financial_data if financial_data is not None else st.session_state.get("financial_data"),
        summary_data if summary_data is not None else st.session_state.get("summary_data"),
        bear_bull_data if bear_bull_data is not None else st.session_state.get("bear_bull_data"),
        dashboard_data if dashboard_data is not None else st.session_state.get("dashboard_data"),
        mda_sentiment if mda_sentiment is not None else st.session_state.get("mda_sentiment"),
        market_data if market_data is not None else st.session_state.get("market_data"),
        sector_value,
        hurdle_rate_value,
    )
    if not payload:
        return False
    return save_analysis(ticker, period, payload)


def _restore_analysis_cache(cached: dict, entry: dict | None = None) -> bool:
    financial_data = cached.get("financial_data")
    if not isinstance(financial_data, dict):
        return False
    financial_data = normalize_financial_data(financial_data)

    summary_data = cached.get("summary_data") or cached.get("summary")
    bear_bull_data = cached.get("bear_bull_data") or cached.get("bear_bull")
    dashboard_data = cached.get("dashboard_data") or cached.get("dashboard_insights")
    market_data = cached.get("market_data") or {}
    if not market_data and cached.get("market_cap") is not None:
        market_data = {"market_cap": cached.get("market_cap")}

    st.session_state.financial_data = financial_data
    st.session_state.summary_data = summary_data
    st.session_state.bear_bull_data = bear_bull_data
    st.session_state.dashboard_data = dashboard_data
    st.session_state.mda_sentiment = cached.get("mda_sentiment")
    st.session_state.market_data = market_data
    st.session_state.last_filename = (entry or {}).get("file_name", "")
    st.session_state.resolved_ticker = cached.get("ticker") or (entry or {}).get("ticker")
    st.session_state.cache_hit = False
    st.session_state.dcf_result = None
    st.session_state.loaded_from_library = True
    st.session_state.loaded_from_edgar = cached.get("source") == "edgar"
    st.session_state.loaded_from_sedar = False
    st.session_state.loaded_from_quick = False
    st.session_state.analysis_loaded_from_cache = True
    st.session_state.analysis_cache_is_stale = bool(cached.get("_is_stale"))
    st.session_state.analysis_cache_stale_reason = cached.get("_stale_reason")

    if st.session_state.resolved_ticker and st.session_state.resolved_ticker != "—":
        st.session_state["manual_ticker"] = st.session_state.resolved_ticker

    try:
        market_cap = (market_data or {}).get("market_cap") or 0.0
        st.session_state.excel_bytes = create_excel_file(
            financial_data,
            summary_data,
            market_cap,
            bear_bull_data,
        )
    except Exception:
        st.session_state.excel_bytes = None

    return True


def _financial_data_to_text(financial_data: dict) -> str:
    lines = [
        f"Company: {financial_data.get('company_name', '')}",
        f"Period: {financial_data.get('period', '')}",
        f"Currency: {financial_data.get('currency', '')}",
        "",
    ]
    for key, label in [
        ("income_statement", "Income Statement"),
        ("balance_sheet", "Balance Sheet"),
        ("cash_flow_statement", "Cash Flow Statement"),
    ]:
        lines.append(label)
        for row in financial_data.get(key, []):
            lines.append(
                f"- {row.get('line_item', '')}: "
                f"{financial_data.get('fiscal_year', 'Current')}={row.get('value')}; "
                f"{financial_data.get('fiscal_year_prior', 'Prior')}={row.get('value_prior')}"
            )
        lines.append("")
    return "\n".join(lines)


def _edgar_cache_identifier() -> str:
    identifier = (
        st.session_state.get("edgar_selected_ticker")
        or ""
    )
    identifier = str(identifier).strip().upper()
    if identifier:
        return identifier
    return (
        str(st.session_state.get("edgar_cik", "UNKNOWN"))
        .replace("000", "", 1)
        .lstrip("0")
        or "UNKNOWN"
    )


def _persist_loaded_edgar_to_library() -> None:
    if not st.session_state.get("loaded_from_edgar"):
        return

    financial_data = st.session_state.get("financial_data")
    accession = st.session_state.get("edgar_loaded_accession")
    cik = st.session_state.get("edgar_cik")
    if not financial_data or not accession or not cik:
        return

    ticker = _edgar_cache_identifier()
    period = _analysis_period(financial_data)
    if not ticker or not period:
        return

    filing_text = st.session_state.get("cached_filing_text") or _financial_data_to_text(financial_data)
    text_path = _text_cache_path(ticker, period)
    if text_path and (not Path(text_path).exists()):
        try:
            safe_write_text(text_path, filing_text)
        except Exception as _e:
            st.warning(f"Could not save EDGAR text cache: {_e}")
            text_path = None

    entry_id = f"edgar_{cik}_{accession}"
    existing = next((entry for entry in lib_get() if entry.get("id") == entry_id), None)
    if existing and existing.get("source") == "edgar" and existing.get("file_path"):
        return

    try:
        lib_add(
            entry_id,
            st.session_state.get("last_filename") or f"{ticker}_{period}.edgar",
            len(filing_text),
            financial_data,
            st.session_state.get("summary_data"),
            st.session_state.get("bear_bull_data"),
            st.session_state.get("dashboard_data"),
            raw_text=filing_text[:MAX_FILING_CHARS],
            mda_sentiment=st.session_state.get("mda_sentiment"),
            source="edgar",
            file_path=text_path,
        )
        st.session_state["filing_library"] = lib_get()
    except Exception as _e:
        st.warning(f"Could not save to library: {_e}")


def _education_topic_param() -> str | None:
    try:
        topic = st.query_params.get("education")
        if isinstance(topic, list):
            topic = topic[0] if topic else None
        return topic if topic in EDUCATION else None
    except Exception:
        return None


def _has_education_topic_param() -> bool:
    try:
        return "education" in st.query_params
    except Exception:
        return False


def _learn_more(topic: str, label: str | None = None) -> None:
    if topic not in EDUCATION:
        return
    link_text = f"Learn more about {label} →" if label else "Learn more →"
    st.markdown(
        f'<a href="?education={topic}#education-topic" target="_self" '
        f'style="font-size:12px;color:#378ADD;text-decoration:none;font-weight:600">'
        f'{link_text}</a>',
        unsafe_allow_html=True,
    )


def _render_education_entry(topic: str) -> None:
    import html as _html

    entry = EDUCATION[topic]
    title = entry.get("title") or entry.get("term") or topic
    emoji = entry.get("emoji") or ""
    st.markdown(f"## {emoji + ' ' if emoji else ''}{title}")
    st.markdown(entry.get("plain_english", ""))

    if entry.get("formula"):
        st.markdown("**Formula**")
        st.code(entry["formula"])
    if entry.get("interpretation"):
        st.markdown("**Interpretation**")
        st.markdown(entry["interpretation"])
    if entry.get("key_items"):
        st.markdown("**Key Items**")
        for item in entry["key_items"]:
            st.markdown(f"**{item['name']}** — {item['description']}")
    if entry.get("key_metrics"):
        st.markdown("**Key Metrics**")
        for item in entry["key_metrics"]:
            st.markdown(f"- {item}")

    st.markdown("**Why It Matters**")
    st.markdown(entry.get("why_it_matters", ""))

    if entry.get("example"):
        st.markdown("**Example**")
        st.markdown(entry["example"])
    if entry.get("finlens_connection"):
        st.markdown("**FinLens Connection**")
        st.markdown(entry["finlens_connection"])

    if entry.get("good_sign") or entry.get("red_flag"):
        good, bad = st.columns(2)
        with good:
            st.markdown(
                f'<div style="background:#052e16;border:1px solid #166534;'
                f'border-radius:8px;padding:14px 16px;color:#CFFFE0">'
                f'<div style="font-weight:700;color:#4ADE80;margin-bottom:6px">Good Sign</div>'
                f'{_html.escape(entry.get("good_sign", ""))}</div>',
                unsafe_allow_html=True,
            )
        with bad:
            st.markdown(
                f'<div style="background:#1F0000;border:1px solid #991B1B;'
                f'border-radius:8px;padding:14px 16px;color:#FFE1E1">'
                f'<div style="font-weight:700;color:#F87171;margin-bottom:6px">Red Flag</div>'
                f'{_html.escape(entry.get("red_flag", ""))}</div>',
                unsafe_allow_html=True,
            )


def _render_education_page(default_topic: str | None = None) -> None:
    st.markdown("## FinLens Education")
    st.caption("Plain-English explanations of the financial statements, valuation metrics, and analysis tools used in FinLens.")

    education_sections = {
        "Markets & Investing Fundamentals": [
            "what_is_a_stock", "what_is_a_bond", "what_is_a_market",
            "what_is_a_10k", "what_is_venture_capital",
            "options", "warrants", "preferred_shares", "convertible_notes", "etfs", "derivatives",
            "short_interest",
        ],
        "Financial Statements": ["income_statement", "balance_sheet", "cash_flow"],
        "Valuation & Market Metrics": [
            "pe_ratio", "ev_ebitda", "wacc", "dcf", "beta", "margin_of_safety",
            "ttm", "earnings_beat_miss",
        ],
        "FinLens Analysis Tools": [
            "signal", "quality_score", "distress_score", "red_flags",
            "mda_sentiment", "scenario_simulator", "bull_bear", "lynch_category",
            "dalio_framework", "lynch_story", "marks_framework",
            "quick_analysis", "financial_snapshot", "business_segments",
        ],
    }

    for section_title, section_topics in education_sections.items():
        st.markdown(f"### {section_title}")
        topic_links = [
            f'<a href="?education={topic}#education-topic" target="_self" '
            f'style="color:#378ADD;text-decoration:none;font-weight:600">'
            f'{EDUCATION[topic].get("title") or EDUCATION[topic].get("term") or topic}</a>'
            for topic in section_topics
            if topic in EDUCATION
        ]
        st.markdown(" &nbsp; · &nbsp; ".join(topic_links), unsafe_allow_html=True)

    st.divider()

    topics = [
        topic
        for section_topics in education_sections.values()
        for topic in section_topics
        if topic in EDUCATION
    ]
    default_topic = default_topic if default_topic in EDUCATION else topics[0]
    if _has_education_topic_param():
        st.session_state["education_topic_select"] = default_topic
    topic = st.selectbox(
        "Topic",
        topics,
        index=topics.index(default_topic),
        format_func=lambda key: EDUCATION[key].get("title") or EDUCATION[key].get("term") or key,
        key="education_topic_select",
    )
    st.divider()
    st.markdown('<div id="education-topic"></div>', unsafe_allow_html=True)
    _render_education_entry(topic)


# --- Password gate ---
try:
    _APP_PASSWORD = st.secrets["APP_PASSWORD"]
except (KeyError, FileNotFoundError):
    _APP_PASSWORD = os.environ.get("APP_PASSWORD", "[dev-password-removed]")

if os.environ.get("STREAMLIT_ENV") == "dev":
    st.session_state["authenticated"] = True
    if "nav_mode" not in st.session_state:
        st.session_state["nav_mode"] = "Single Analysis"

if cookies.get("finlens_auth") == "true":
    st.session_state["authenticated"] = True

_education_topic_requested = _has_education_topic_param()
_education_topic = _education_topic_param()
if _education_topic_requested:
    st.session_state["onboarding_complete"] = True
    st.session_state["nav_mode"] = "Education"

_NAV_ITEMS = [
    (
        "Single Analysis",
        "single",
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>',
    ),
    (
        "Portfolio Manager",
        "portfolio",
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.21 15.89A10 10 0 1 1 8 2.83"/><path d="M22 12A10 10 0 0 0 12 2v10z"/></svg>',
    ),
    (
        "Filing Comparison",
        "comparison",
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><line x1="6" y1="9" x2="6" y2="21"/></svg>',
    ),
    (
        "Stock Tracker",
        "stocks",
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>',
    ),
    (
        "Education",
        "education",
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>',
    ),
]

_NAV_LABEL_BY_SLUG = {slug: label for label, slug, _ in _NAV_ITEMS}
_page_from_url = st.query_params.get("page", "")
if _page_from_url and _page_from_url in _NAV_LABEL_BY_SLUG:
    st.session_state["onboarding_complete"] = True
    st.session_state["nav_mode"] = _NAV_LABEL_BY_SLUG[_page_from_url]

if "onboarding_complete" not in st.session_state:
    st.session_state["onboarding_complete"] = False

with open("assets/style.css") as _f:
    st.markdown(f"<style>{_f.read()}</style>", unsafe_allow_html=True)

if not st.session_state.get("authenticated"):
    st.markdown(
        """
        <div style="display:flex;flex-direction:column;align-items:center;margin-top:5rem;">
            <svg width="56" height="56" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="FinLens">
              <circle cx="28" cy="32" r="20" fill="none" stroke="#4D9FFF" stroke-width="4.5"/>
              <path d="M5 25 L28 25 L56 32" fill="none" stroke="#9FD0FF" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M5 39 L28 39 L56 32" fill="none" stroke="#9FD0FF" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>
              <circle cx="56" cy="32" r="4" fill="#FFB454"/>
            </svg>
            <h2 style="margin-top:0.75rem;margin-bottom:0.25rem;">FinLens</h2>
            <p style="color:#94A3B8;margin-bottom:2rem;">Financial Statement Analyzer</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _, _login_col, _ = st.columns([1, 1, 1])
    with _login_col:
        _pw = st.text_input("Password", type="password", placeholder="Enter password",
                            label_visibility="collapsed")
        remember_me = st.checkbox("Remember me for 30 days")
        if st.button("Login", width='stretch', type="primary"):
            if _pw == _APP_PASSWORD:
                if remember_me:
                    cookies["finlens_auth"] = "true"
                    cookies.save()
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Incorrect password")
    st.stop()

if not st.session_state["onboarding_complete"]:
    st.markdown(
        """
        <style>
        .onboarding-wrap {
            max-width: 920px;
            margin: 3.5rem auto 0;
            text-align: center;
        }
        .onboarding-logo {
            display: flex;
            justify-content: center;
            margin-bottom: 0.9rem;
        }
        .onboarding-title {
            font-size: 42px;
            font-weight: 500;
            color: #F1F5F9;
            letter-spacing: -0.02em;
            line-height: 1;
        }
        .onboarding-tagline {
            margin-top: 0.4rem;
            color: #94A3B8;
            font-size: 15px;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }
        .onboarding-copy {
            max-width: 720px;
            margin: 1.6rem auto 2rem;
            color: #CBD5E1;
            font-size: 17px;
            line-height: 1.65;
        }
        </style>
        <div class="onboarding-wrap">
            <div class="onboarding-logo">
                <svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="FinLens logo">
                  <circle cx="28" cy="32" r="20" fill="none" stroke="#4D9FFF" stroke-width="4.5"/>
                  <path d="M5 25 L28 25 L56 32" fill="none" stroke="#9FD0FF" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>
                  <path d="M5 39 L28 39 L56 32" fill="none" stroke="#9FD0FF" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>
                  <circle cx="56" cy="32" r="4" fill="#FFB454"/>
                </svg>
            </div>
            <div class="onboarding-title">Fin<span style="color:#378ADD;font-weight:300">Lens</span></div>
            <div class="onboarding-tagline">AI-Powered Investment Analysis Platform</div>
            <div class="onboarding-copy">
                FinLens transforms raw filings, market data, and portfolio signals into institutional-grade investment intelligence.
                Fetch filings from SEC EDGAR or SEDAR+, analyse financials with AI, track short interest and momentum, and stress-test your assumptions — all in one workspace.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    feature_rows = [
        [
            (
                "Single Analysis",
                "Upload or fetch a 10-K or 10-Q via SEC EDGAR or SEDAR+, get AI-powered investment analysis, red flag detection, and scenario simulation",
            ),
            (
                "Filing Comparison",
                "Compare two filings year-over-year from your library or manual upload to spot language shifts and sentiment changes",
            ),
        ],
        [
            (
                "Stock Tracker",
                "Track live price, momentum, short interest, RSI, and moving averages for any ticker",
            ),
            (
                "Portfolio Manager",
                "Analyse multiple holdings, score distress and momentum, and get a portfolio-level investment view",
            ),
        ],
    ]

    for row in feature_rows:
        _, left, right, _ = st.columns([1, 2, 2, 1])
        for col, (title, copy) in zip((left, right), row):
            with col:
                st.markdown(
                    f"""
                    <div class="feature-card">
                        <h3>{title}</h3>
                        <p>{copy}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    _, start_col, _ = st.columns([1, 2, 1])
    with start_col:
        if st.button("Get Started →", type="primary", width='stretch'):
            st.session_state["onboarding_complete"] = True
            st.rerun()
    st.stop()

def _svg_b64(path: str) -> str:
    import base64
    return base64.b64encode(open(path, "rb").read()).decode()


st.markdown("""
<div style="display:flex;align-items:center;gap:16px;margin-bottom:1.5rem;padding-bottom:1.5rem;border-bottom:0.5px solid #2D3650;">
    <svg width="52" height="52" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="FinLens">
      <circle cx="28" cy="32" r="20" fill="none" stroke="#4D9FFF" stroke-width="4.5"/>
      <path d="M5 25 L28 25 L56 32" fill="none" stroke="#9FD0FF" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M5 39 L28 39 L56 32" fill="none" stroke="#9FD0FF" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="56" cy="32" r="4" fill="#FFB454"/>
    </svg>
    <div>
        <div style="font-size:32px;font-weight:500;color:#F1F5F9;letter-spacing:-0.03em;line-height:1">
            Fin<span style="color:#378ADD;font-weight:300">Lens</span>
        </div>
        <div style="font-size:11px;color:#64748B;letter-spacing:0.12em;text-transform:uppercase;margin-top:4px">
            AI Financial Analysis
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# --- Market Ticker Tape ------------------------------------------------
def _fetch_tape_index(symbol: str, name: str) -> dict | None:
    try:
        _ensure_yfinance_cache_location()
        info = yf.Ticker(symbol).fast_info
        price = getattr(info, "last_price", None) or getattr(info, "regular_market_price", None)
        prev = getattr(info, "previous_close", None)
        if price is None or prev is None:
            return None
        price = float(price)
        prev = float(prev)
        change = price - prev
        pct = (change / prev * 100) if prev else 0.0
        if symbol == "^TNX":
            price_fmt = f"{price:.2f}%"
        elif symbol == "^VIX":
            price_fmt = f"{price:.2f}"
        elif price >= 1000:
            price_fmt = f"{price:,.0f}"
        else:
            price_fmt = f"{price:,.2f}"
        return {
            "name": name,
            "price": price,
            "price_fmt": price_fmt,
            "change": change,
            "pct_change": pct,
            "positive": change >= 0,
        }
    except Exception:
        return None


_equity_index_symbols = [
    ("^GSPC", "S&P 500"),
    ("^IXIC", "Nasdaq"),
    ("^DJI", "DOW"),
    ("^GSPTSE", "TSX"),
    ("^RUT", "Russell 2000"),
    ("^VIX", "VIX"),
    ("^TNX", "US 10yr Yield"),
]
_equity_index_data = [
    item for symbol, name in _equity_index_symbols
    if (item := _fetch_tape_index(symbol, name)) is not None
]
_existing_ticker_data = get_ticker_data()
_index_names = {
    "S&P 500", "Nasdaq", "Dow", "DOW", "TSX", "Russell 2000",
    "VIX", "US 10yr", "US 10yr Yield", "US 30yr",
}
_ticker_data = _equity_index_data + [
    item for item in _existing_ticker_data
    if item.get("name") not in _index_names
]

if not _ticker_data:
    st.markdown(
        "<div style='width:100%;background:rgba(0,0,0,0.3);"
        "border-bottom:1px solid rgba(255,255,255,0.08);padding:6px 16px;margin-bottom:1.5rem;"
        "font-size:0.85rem;color:#64748B;font-family:sans-serif'>Loading market data...</div>",
        unsafe_allow_html=True,
    )
else:
    def _ticker_item_html(item: dict) -> str:
        arrow = "▲" if item["positive"] else "▼"
        cls   = "ticker-change-pos" if item["positive"] else "ticker-change-neg"
        return (
            f"<div class='ticker-item'>"
            f"<span class='ticker-name'>{item['name']}</span>"
            f"<span class='ticker-price'>{item['price_fmt']}</span>"
            f"<span class='{cls}'>{arrow} {abs(item['pct_change']):.2f}%</span>"
            f"<span class='ticker-dot'>·</span>"
            f"</div>"
        )

    _items_html = "".join(_ticker_item_html(i) for i in _ticker_data)
    # Duplicate so the seamless loop never shows a gap
    _items_html = _items_html * 2

    st.markdown(f"""
<style>
.ticker-wrap {{
    position: sticky;
    top: 0;
    z-index: 999;
    width: 100%;
    overflow: hidden;
    background: rgba(0,0,0,0.3);
    backdrop-filter: blur(10px);
    border-bottom: 1px solid rgba(255,255,255,0.08);
    box-shadow: 0 1px 8px rgba(0,0,0,0.3);
    padding: 6px 0;
    margin-bottom: 1.5rem;
}}
.ticker-content {{
    display: inline-flex;
    gap: 0;
    animation: ticker-scroll 70s linear infinite;
    white-space: nowrap;
    will-change: transform;
}}
.ticker-content:hover {{
    animation-play-state: paused;
}}
.ticker-item {{
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 0 12px;
    font-size: 0.85rem;
    font-family: sans-serif;
}}
.ticker-name {{
    color: #CBD5E1;
    font-weight: 700;
    letter-spacing: 0.03em;
}}
.ticker-price {{
    color: #F1F5F9;
    font-weight: 500;
}}
.ticker-change-pos {{
    color: #00c896;
    font-size: 0.85rem;
    font-weight: 600;
}}
.ticker-change-neg {{
    color: #ff4d4d;
    font-size: 0.85rem;
    font-weight: 600;
}}
.ticker-dot {{
    color: rgba(255,255,255,0.28);
    font-weight: 600;
    padding-left: 12px;
}}
@keyframes ticker-scroll {{
    0%   {{ transform: translateX(0); }}
    100% {{ transform: translateX(-50%); }}
}}
</style>
<div class="ticker-wrap">
    <div class="ticker-content">
        {_items_html}
    </div>
</div>
""", unsafe_allow_html=True)

_hydrate_library_from_supabase()
_education_topic = _education_topic_param()
if _education_topic:
    st.session_state["nav_mode"] = "Education"

_NAV_SLUG_BY_LABEL = {label: slug for label, slug, _ in _NAV_ITEMS}


def _query_param_value(name: str) -> str | None:
    value = st.query_params.get(name)
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _filing_key(entry: dict) -> str:
    ticker = entry.get("ticker") or "NA"
    period = entry.get("fiscal_year") or entry.get("period") or "unknown"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{ticker}_{period}_{entry['id']}")


def _library_ticker(entry: dict) -> str:
    ticker = str(entry.get("ticker") or "").strip().upper()
    return ticker if ticker and ticker != "—" else "N/A"


def _library_period_label(entry: dict) -> str:
    return str(entry.get("fiscal_year") or entry.get("period") or "").strip()


def _library_period_sort_key(entry: dict):
    label = _library_period_label(entry)
    years = [int(y) for y in re.findall(r"(?:19|20)\d{2}", label)]
    if years:
        return (0, -max(years), label.lower())
    return (1, label.lower())


def _library_company_header(ticker: str, entries: list[dict]) -> str:
    company_name = ""
    for entry in entries:
        company_name = str(entry.get("company_name") or "").strip()
        if company_name:
            break

    if not company_name and ticker and ticker != "N/A":
        cache_key = f"company_name_{ticker}"
        if cache_key not in st.session_state:
            try:
                _ensure_yfinance_cache_location()
                st.session_state[cache_key] = (
                    yf.Ticker(ticker).info or {}
                ).get("longName", "") or ""
            except Exception:
                st.session_state[cache_key] = ""
        company_name = str(st.session_state.get(cache_key) or "").strip()

    if company_name and ticker and ticker != "N/A":
        return f"{company_name.upper()} ({ticker})"
    if company_name:
        return company_name.upper()
    return ticker


def _library_comparison_label(entry: dict) -> str:
    ticker = _library_ticker(entry)
    period = _library_period_label(entry) or "Unknown period"
    return f"{_library_company_header(ticker, [entry])} — {period}"

# --- Sidebar -----------------------------------------------------------
with st.sidebar:
    st.markdown(
        """
        <div class="finlens-sidebar-brand">
            <div class="finlens-sidebar-wordmark">
                <span class="finlens-sidebar-wordmark-fin">Fin</span><span class="finlens-sidebar-wordmark-lens">Lens</span>
            </div>
            <div class="finlens-sidebar-tagline">AI INVESTMENT ANALYSIS PLATFORM</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.session_state.get("nav_mode") not in _NAV_SLUG_BY_LABEL:
        st.session_state["nav_mode"] = "Education" if _education_topic else "Single Analysis"
    page = st.session_state["nav_mode"]
    _active_slug = _NAV_SLUG_BY_LABEL[page]
    st.markdown(
        f"""
        <style>
        section[data-testid="stSidebar"] [class*="st-key-nav_{_active_slug}"] button {{
            background: rgba(24,95,165,0.1) !important;
            border-left-color: #185FA5 !important;
            color: #F1F5F9 !important;
            font-weight: 500 !important;
        }}
        section[data-testid="stSidebar"] [class*="st-key-nav_{_active_slug}"] button p {{
            color: #F1F5F9 !important;
            font-weight: 500 !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<div class="sidebar-nav" aria-label="Primary navigation">', unsafe_allow_html=True)
    for _label, _slug, _ in _NAV_ITEMS:
        if st.button(_label, key=f"nav_{_slug}", width='stretch'):
            st.session_state["nav_mode"] = _label
            st.query_params["page"] = _slug
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
    if page != "Education" and _education_topic:
        try:
            del st.query_params["education"]
        except Exception:
            pass
    if st.button("Logout", width='stretch'):
        cookies["finlens_auth"] = ""
        cookies.save()
        st.session_state["authenticated"] = False
        st.rerun()
    st.divider()

    # --- Portfolio management (Portfolio Manager mode only) ---------------
    selected_portfolio = None
    if page == "Portfolio Manager":
        pf_names = get_portfolio_names()
        options  = pf_names + ["+ New Portfolio"]
        active   = st.session_state.get("pm_active_portfolio")
        sel_idx  = pf_names.index(active) if active in pf_names else 0

        sel_pf = st.selectbox(
            "Portfolio",
            options,
            index=min(sel_idx, len(options) - 1),
        )

        if sel_pf == "+ New Portfolio":
            new_pf_name = st.text_input("Portfolio name", key="pm_new_name")
            if st.button("Create Portfolio", width='stretch', type="primary"):
                n = new_pf_name.strip()
                if n:
                    if create_portfolio(n):
                        st.session_state.pm_active_portfolio = n
                        st.rerun()
                    else:
                        st.warning("A portfolio with that name already exists.")
                else:
                    st.warning("Enter a portfolio name.")
        else:
            st.session_state.pm_active_portfolio = sel_pf
            selected_portfolio = sel_pf
            cur_tickers = get_tickers(sel_pf)

            with st.expander(f"Manage Tickers ({len(cur_tickers)})", expanded=False):
                for t in cur_tickers:
                    tc, rc = st.columns([3, 1])
                    with tc:
                        st.markdown(f"`{t}`")
                    with rc:
                        if st.button("✕", key=f"rm_{sel_pf}_{t}", width='stretch'):
                            reg_remove_ticker(sel_pf, t)
                            st.rerun()

                if cur_tickers:
                    st.markdown(
                        "<hr style='margin:4px 0;border:none;border-top:0.5px solid #e0e0e0'>",
                        unsafe_allow_html=True,
                    )

                st.markdown("""
<script>
document.addEventListener('focusin', function(e) {
    if (e.target.tagName === 'INPUT' &&
        e.target.type === 'text' &&
        e.target.placeholder === 'e.g. AAPL, RY.TO') {
        e.target.select();
    }
});
</script>
""", unsafe_allow_html=True)

                with st.form(key=f"add_ticker_form_{sel_pf}", clear_on_submit=True):
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        new_tk = st.text_input("",
                            placeholder="e.g. AAPL, RY.TO",
                            label_visibility="collapsed")
                    with col2:
                        add_clicked = st.form_submit_button("Add",
                            width='stretch')

                st.caption("US: AAPL, MSFT  |  TSX: RY.TO, CNQ.TO  |  LSE: SHEL.L  |  Other: Yahoo Finance suffix format")

                if add_clicked:
                    t_up = new_tk.strip().upper()
                    if t_up:
                        st.session_state.pm_ticker_not_found = None
                        with st.spinner(f"Validating {t_up}…"):
                            try:
                                vmd      = get_market_data(t_up)
                                is_valid = bool(vmd.get("current_price"))
                            except Exception:
                                is_valid = False
                        if is_valid:
                            if reg_add_ticker(sel_pf, t_up):
                                st.rerun()
                            else:
                                st.warning(f"{t_up} already in portfolio.")
                        else:
                            st.session_state.pm_ticker_not_found = t_up
                    else:
                        st.warning("Enter a ticker symbol.")

                if st.session_state.get("pm_ticker_not_found"):
                    _nf = st.session_state.pm_ticker_not_found
                    st.warning(
                        f"'{_nf}' not found via yfinance — may be delisted or rate-limited."
                    )
                    ov1, ov2 = st.columns(2)
                    with ov1:
                        if st.button("Add anyway", key=f"pm_add_anyway_{sel_pf}",
                                     width='stretch', type="primary"):
                            if reg_add_ticker(sel_pf, _nf):
                                st.session_state.pm_ticker_not_found = None
                                st.rerun()
                            else:
                                st.session_state.pm_ticker_not_found = None
                                st.warning(f"{_nf} already in portfolio.")
                    with ov2:
                        if st.button("Cancel", key=f"pm_cancel_anyway_{sel_pf}",
                                     width='stretch'):
                            st.session_state.pm_ticker_not_found = None
                            st.rerun()

                csv_up = st.file_uploader(
                    "Bulk add (.csv)", type=["csv"], key=f"pm_csv_{sel_pf}",
                )
                if csv_up is not None:
                    import io, csv as _csv
                    content = csv_up.read().decode("utf-8", errors="ignore")
                    reader  = _csv.reader(io.StringIO(content))
                    raw_tks = []
                    for i, row in enumerate(reader):
                        if not row:
                            continue
                        val = row[0].strip().upper()
                        if i == 0 and val in ("TICKER", "TICKERS", "SYMBOL", "SYMBOLS"):
                            continue
                        if val:
                            raw_tks.append(val)
                    if raw_tks:
                        br = bulk_add_tickers(sel_pf, raw_tks)
                        st.success(f"Added {len(br['added'])}, skipped {len(br['skipped'])}.")
                        st.rerun()
                    else:
                        st.warning("No tickers found in CSV.")

                st.markdown(
                    "<hr style='margin:4px 0;border:none;border-top:0.5px solid #e0e0e0'>",
                    unsafe_allow_html=True,
                )
                if st.session_state.get("pm_confirm_delete") == sel_pf:
                    st.caption(f"Delete **{sel_pf}**? This cannot be undone.")
                    dc1, dc2 = st.columns(2)
                    with dc1:
                        if st.button("Yes, delete", key=f"pm_del_yes_{sel_pf}",
                                     type="primary", width='stretch'):
                            del_portfolio_reg(sel_pf)
                            st.session_state.pm_confirm_delete   = None
                            st.session_state.pm_active_portfolio = None
                            st.rerun()
                    with dc2:
                        if st.button("Cancel", key=f"pm_del_no_{sel_pf}",
                                     width='stretch'):
                            st.session_state.pm_confirm_delete = None
                            st.rerun()
                else:
                    if st.button("🗑️ Delete Portfolio", key=f"pm_del_{sel_pf}",
                                 width='stretch'):
                        st.session_state.pm_confirm_delete = sel_pf
                        st.rerun()

            # --- Analysis Library (read-only, re-analyse only) ----------------
            st.markdown(
                "<hr style='margin:6px 0;border:none;border-top:0.5px solid #e0e0e0'>",
                unsafe_allow_html=True,
            )
            st.markdown("""
            <style>
            section[data-testid="stSidebar"] .stButton button {
                padding: 1px 8px;
                font-size: 11px;
                line-height: 1.3;
                min-height: 0px;
            }
            </style>
            """, unsafe_allow_html=True)
            st.markdown(
                "<span style='font-size:10px;font-weight:700;color:#888;"
                "text-transform:uppercase;letter-spacing:0.06em'>Analysis Library</span>",
                unsafe_allow_html=True,
            )
            st.markdown(
                "<span style='font-size:10px;color:#888'>"
                "🟢 In current portfolio  ⚫ Not in portfolio</span>",
                unsafe_allow_html=True,
            )
            if st.session_state.get("al_no_text_warning"):
                st.warning(
                    f"No PDF stored for **{st.session_state.al_no_text_warning}** — "
                    "switch to Single Analysis to re-upload."
                )
                st.session_state.al_no_text_warning = None
            al_entries = lib_get()
            if not al_entries:
                st.caption("No analyses yet — add filings via Single Analysis")
            else:
                _pf_tickers_upper = {t.upper() for t in cur_tickers}
                for entry in al_entries:
                    eid    = entry["id"]
                    ticker = entry.get("ticker", "—")
                    fy     = entry.get("fiscal_year") or (entry.get("period") or "")[:20]
                    in_pf  = bool(ticker and ticker != "—" and ticker.upper() in _pf_tickers_upper)
                    dot    = "🟢" if in_pf else "⚫"
                    st.markdown(
                        f"<span style='font-size:13px;font-weight:500;color:#F1F5F9'>"
                        f"{dot} {entry.get('company_name') or entry.get('file_name') or 'Unknown'}</span>",
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"<small style='color:#888;font-size:11px'>{ticker} · {fy}</small>",
                        unsafe_allow_html=True,
                    )
                    if st.button("♻️ Re-Analyse $", key=f"al_ra_{eid}",
                                 width='stretch',
                                 help="Re-analyse with fresh Claude calls"):
                        st.session_state.al_confirm_reanalyse = eid
                        st.rerun()
                    st.caption("~$0.08 per analysis")
                    if st.session_state.get("al_confirm_reanalyse") == eid:
                        st.caption(
                            f"Re-analyse **{entry.get('company_name') or entry.get('file_name') or 'Unknown'}**? This will run 4 Claude "
                            f"API calls (~$0.10–0.15 cost) and overwrite the existing result."
                        )
                        al_yes, al_no = st.columns(2)
                        with al_yes:
                            if st.button("Yes, re-analyse", key=f"al_ra_yes_{eid}",
                                         width='stretch', type="primary"):
                                st.session_state.al_confirm_reanalyse = None
                                _entry_text = _library_text_for_entry(entry)
                                if _entry_text:
                                    st.session_state.pending_reanalyse = {
                                        "raw_text":     _entry_text[:MAX_FILING_CHARS],
                                        "company_name": entry.get("company_name") or entry.get("file_name") or "Unknown",
                                        "entry_id":     eid,
                                        "file_name":    entry.get("file_name", ""),
                                        "file_size":    entry.get("file_size_bytes", 0),
                                        "ticker":       entry.get("ticker"),
                                        "period":       entry.get("fiscal_year") or entry.get("period", ""),
                                        "source":       entry.get("source", "pdf"),
                                        "file_path":    entry.get("file_path"),
                                        "file_type":    entry.get("file_type", "pdf"),
                                    }
                                else:
                                    _period = entry.get("fiscal_year") or entry.get("period", "")
                                    _pdf_bytes = None
                                    try:
                                        _pdf_path = _pdf_cache_path(
                                            ticker if ticker != "—" else None,
                                            _period,
                                        )
                                        if _pdf_path and Path(_pdf_path).exists():
                                            with Path(_pdf_path).open("rb") as _f:
                                                _pdf_bytes = _f.read()
                                    except Exception:
                                        _pdf_bytes = None
                                    if _pdf_bytes is None:
                                        _pdf_bytes = supabase_storage.load_pdf(
                                            ticker if ticker != "—" else None,
                                            _period,
                                        )
                                    if _pdf_bytes:
                                        try:
                                            _file_type = entry.get("file_type", "pdf")
                                            if _file_type == "docx":
                                                with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as _tmp:
                                                    _tmp.write(_pdf_bytes)
                                                    _tmp_path = _tmp.name
                                                _extracted_text = convert_to_markdown(_tmp_path) or ""
                                                try:
                                                    os.unlink(_tmp_path)
                                                except Exception:
                                                    pass
                                                if not _extracted_text:
                                                    raise ValueError("No text extracted from Word document")
                                            else:
                                                _extracted_text = extract_text_from_pdf(io.BytesIO(_pdf_bytes))
                                            st.session_state.pending_reanalyse = {
                                                "raw_text":     _extracted_text[:MAX_FILING_CHARS],
                                                "company_name": entry.get("company_name") or entry.get("file_name") or "Unknown",
                                                "entry_id":     eid,
                                                "file_name":    entry.get("file_name", ""),
                                                "file_size":    entry.get("file_size_bytes", 0),
                                                "ticker":       entry.get("ticker"),
                                                "period":       entry.get("fiscal_year") or entry.get("period", ""),
                                                "source":       entry.get("source", "pdf"),
                                                "file_path":    entry.get("file_path"),
                                                "pdf_bytes":    _pdf_bytes,
                                                "file_type":    _file_type,
                                            }
                                        except Exception:
                                            st.session_state.al_no_text_warning = entry.get("company_name") or entry.get("file_name") or "Unknown"
                                    else:
                                        st.session_state.al_no_text_warning = entry.get("company_name") or entry.get("file_name") or "Unknown"
                                st.rerun()
                        with al_no:
                            if st.button("Cancel", key=f"al_ra_no_{eid}",
                                         width='stretch'):
                                st.session_state.al_confirm_reanalyse = None
                                st.rerun()
                    st.markdown(
                        "<hr style='margin:2px 0;border:none;border-top:0.5px solid #e0e0e0'>",
                        unsafe_allow_html=True,
                    )

        st.divider()

    demo_mode = st.sidebar.toggle(" Demo Mode", value=False, key="demo_mode")
    if demo_mode:
        st.sidebar.caption("⚡ Opus 4.8 — Premium Analysis")
    else:
        st.sidebar.caption(" Haiku — Dev Mode")

    # --- Filing Library (Single Analysis mode only) --------------------
    if page == "Single Analysis":
        st.markdown("""
        <style>
        section[data-testid="stSidebar"] .stButton button {
            padding: 1px 8px;
            font-size: 11px;
            line-height: 1.3;
            min-height: 0px;
        }
        </style>
        """, unsafe_allow_html=True)

        lib_entries = lib_get()
        lib_count   = len(lib_entries)
        label       = f"Filing Library ({lib_count} filing{'s' if lib_count != 1 else ''})"
        st.markdown(
            f"<span style='font-size:10px;font-weight:700;color:#888;"
            f"text-transform:uppercase;letter-spacing:0.06em'>{label}</span>",
            unsafe_allow_html=True,
        )
        if not lib_entries:
            st.caption("No filings saved yet. Analyse a PDF to add it here.")
        else:
            grouped_entries = {}
            for entry in lib_entries:
                grouped_entries.setdefault(_library_ticker(entry), []).append(entry)
            expand_single_company = len(grouped_entries) == 1

            for group_ticker in sorted(grouped_entries):
                company_entries = sorted(
                    grouped_entries[group_ticker],
                    key=_library_period_sort_key,
                )
                with st.sidebar.expander(
                    _library_company_header(group_ticker, company_entries),
                    expanded=expand_single_company,
                ):
                    for entry in company_entries:
                        eid        = entry["id"]
                        ticker     = entry.get("ticker", "—")
                        fy         = entry.get("fiscal_year") or (entry.get("period") or "")[:20]
                        filing_key = _filing_key(entry)
                        expanded   = st.session_state.get("sidebar_expanded_filing") == filing_key
                        row_ticker  = ticker if ticker and ticker != "—" else "N/A"
                        row_period  = fy or "Unknown period"
                        if entry.get("source") == "edgar":
                            row_period = f"{row_period} · EDGAR"
                        elif entry.get("file_type") == "docx":
                            row_period = f"{row_period} · DOCX"
                        else:
                            row_period = f"{row_period} · PDF"
                        chevron     = "⌃" if expanded else "⌄"
                        if st.button(
                            f"**{row_ticker}**    {row_period}    {chevron}",
                            key=f"filing_row_{filing_key}",
                            width='stretch',
                        ):
                            st.session_state["sidebar_expanded_filing"] = None if expanded else filing_key
                            st.rerun()
                        if expanded:
                            load_col, reanalyse_col = st.columns(2)
                            with load_col:
                                if st.button("Load", key=f"lib_load_{eid}", width='stretch'):
                                    _entry_period = entry.get("fiscal_year") or entry.get("period", "")
                                    _entry_ticker = ticker if ticker != "—" else None
                                    _entry_text = _library_text_for_entry(entry)
                                    st.session_state.cached_filing_text = _entry_text
                                    _cached_analysis = load_analysis(_entry_ticker, _entry_period)
                                    if _cached_analysis and _restore_analysis_cache(_cached_analysis, entry):
                                        st.session_state.cached_pdf_bytes = None
                                        if entry.get("source") != "edgar":
                                            # Keep PDF bytes preloaded for a later paid Re-Analyse when available.
                                            try:
                                                _lp = _pdf_cache_path(_entry_ticker, _entry_period)
                                                st.session_state.cached_pdf_bytes = (
                                                    Path(_lp).read_bytes() if _lp and Path(_lp).exists() else None
                                                )
                                            except Exception:
                                                st.session_state.cached_pdf_bytes = None
                                        st.session_state.confirm_reanalyse    = None
                                        st.session_state.al_confirm_reanalyse = None
                                        st.rerun()

                                    fd = normalize_financial_data(entry["financial_data"])
                                    sd = entry.get("summary_data")
                                    bb = entry.get("bear_bull_data")
                                    st.session_state.financial_data      = fd
                                    st.session_state.summary_data        = sd
                                    st.session_state.bear_bull_data      = bb
                                    st.session_state.dashboard_data      = entry.get("dashboard_data")
                                    st.session_state.mda_sentiment       = entry.get("mda_sentiment")
                                    st.session_state.market_data         = {}
                                    try:
                                        st.session_state.excel_bytes = create_excel_file(fd, sd, 0.0, bb)
                                    except Exception:
                                        st.session_state.excel_bytes = None
                                    st.session_state.last_filename       = entry.get("file_name", "")
                                    st.session_state.resolved_ticker     = ticker if ticker != "—" else None
                                    st.session_state.cache_hit           = False
                                    st.session_state.dcf_result          = None
                                    st.session_state.loaded_from_library = True
                                    st.session_state.loaded_from_edgar   = entry.get("source") == "edgar"
                                    st.session_state.loaded_from_sedar   = False
                                    st.session_state.loaded_from_quick   = False
                                    st.session_state.cached_filing_text  = (
                                        _entry_text if entry.get("source") == "edgar" else None
                                    )
                                    st.session_state.analysis_loaded_from_cache = False
                                    st.session_state.analysis_cache_is_stale = False
                                    st.session_state.analysis_cache_stale_reason = None
                                    if ticker and ticker != "—":
                                        st.session_state["manual_ticker"] = ticker
                                    if entry.get("source") == "edgar":
                                        st.session_state.cached_pdf_bytes = None
                                    else:
                                        # Silently preload cached PDF bytes so Re-Analyse is instant if no raw_text
                                        try:
                                            _lp = _pdf_cache_path(
                                                ticker if ticker != "—" else None,
                                                entry.get("fiscal_year") or entry.get("period", ""),
                                            )
                                            st.session_state.cached_pdf_bytes = (
                                                Path(_lp).read_bytes() if _lp and Path(_lp).exists() else None
                                            )
                                            if st.session_state.cached_pdf_bytes is None:
                                                st.session_state.cached_pdf_bytes = supabase_storage.load_pdf(
                                                    ticker if ticker != "—" else None,
                                                    entry.get("fiscal_year") or entry.get("period", ""),
                                                )
                                        except Exception:
                                            st.session_state.cached_pdf_bytes = None
                                    st.session_state.confirm_reanalyse    = None
                                    st.session_state.al_confirm_reanalyse = None
                                    st.rerun()
                            with reanalyse_col:
                                if st.button("Re-Analyse $", key=f"lib_reanalyse_{eid}", width='stretch',
                                             help="Re-analyse with fresh Claude calls"):
                                    st.session_state.confirm_reanalyse = eid
                                    st.session_state.confirm_delete    = None
                                    st.rerun()
                            st.caption("~$0.08 per analysis")
                            if st.button("Remove", key=f"lib_del_{eid}", width='stretch',
                                         help=f"Remove {entry.get('company_name') or entry.get('file_name') or 'Unknown'} from library"):
                                st.session_state.confirm_delete    = eid
                                st.session_state.confirm_reanalyse = None
                                st.rerun()

                        # --- Remove confirmation ---
                        if expanded and st.session_state.get("confirm_delete") == eid:
                            st.caption(f"Remove **{entry.get('company_name') or entry.get('file_name') or 'Unknown'}**? This cannot be undone.")
                            yes_col, no_col = st.columns(2)
                            with yes_col:
                                if st.button("Yes, remove", key=f"lib_del_yes_{eid}",
                                             width='stretch', type="primary"):
                                    lib_delete(eid)
                                    st.session_state.confirm_delete = None
                                    st.rerun()
                            with no_col:
                                if st.button("Cancel", key=f"lib_del_no_{eid}",
                                             width='stretch'):
                                    st.session_state.confirm_delete = None
                                    st.rerun()

                        # --- Re-analyse confirmation ---
                        if expanded and st.session_state.get("confirm_reanalyse") == eid:
                            st.caption(
                                f"Re-analyse **{entry.get('company_name') or entry.get('file_name') or 'Unknown'}**? This will run 4 Claude API calls "
                                f"(~$0.10–0.15 cost) and overwrite the existing result."
                            )
                            yes_col, no_col = st.columns(2)
                            with yes_col:
                                if st.button("Yes, re-analyse", key=f"lib_ra_yes_{eid}",
                                             width='stretch', type="primary"):
                                    st.session_state.confirm_reanalyse = None
                                    _entry_text = _library_text_for_entry(entry)
                                    if _entry_text:
                                        st.session_state.pending_reanalyse = {
                                            "raw_text":     _entry_text[:MAX_FILING_CHARS],
                                            "company_name": entry.get("company_name") or entry.get("file_name") or "Unknown",
                                            "entry_id":     eid,
                                            "file_name":    entry.get("file_name", ""),
                                            "file_size":    entry.get("file_size_bytes", 0),
                                            "ticker":       entry.get("ticker"),
                                            "period":       entry.get("fiscal_year") or entry.get("period", ""),
                                            "source":       entry.get("source", "pdf"),
                                            "file_path":    entry.get("file_path"),
                                            "file_type":    entry.get("file_type", "pdf"),
                                        }
                                    else:
                                        st.session_state.reanalyse_no_text = entry.get("company_name") or entry.get("file_name") or "Unknown"
                                        st.session_state.reanalyse_pdf_info = {
                                            "ticker":       entry.get("ticker"),
                                            "period":       entry.get("fiscal_year") or entry.get("period", ""),
                                            "entry_id":     eid,
                                            "company_name": entry.get("company_name") or entry.get("file_name") or "Unknown",
                                            "file_name":    entry.get("file_name", ""),
                                            "file_size":    entry.get("file_size_bytes", 0),
                                            "source":       entry.get("source", "pdf"),
                                            "file_path":    entry.get("file_path"),
                                            "file_type":    entry.get("file_type", "pdf"),
                                        }
                                        st.session_state.uploader_key += 1
                                    st.rerun()
                            with no_col:
                                if st.button("Cancel", key=f"lib_ra_no_{eid}",
                                             width='stretch'):
                                    st.session_state.confirm_reanalyse = None
                                    st.rerun()
        st.divider()
        n = cache_count()
        st.caption(f"Cache: {n} entr{'y' if n == 1 else 'ies'}" if n else "Cache: empty")
        if n:
            if st.button("Clear Cache", width='stretch'):
                cleared = clear_cache()
                st.session_state.uploader_key += 1  # force file uploader to reset
                st.success(f"Cleared {cleared} cached entr{'y' if cleared == 1 else 'ies'}.")
                st.rerun()

# --- Portfolio Manager page --------------------------------------------
if page == "Portfolio Manager":
    import pandas as pd

    # Re-analysis triggered from Analysis Library sidebar fires here
    # (Single Analysis handler is after st.stop() and unreachable in PM mode)
    if st.session_state.get("pending_reanalyse"):
        ra = st.session_state.pending_reanalyse
        st.info(f"Re-analysing **{ra['company_name']}** — running all 4 Claude calls fresh...")
        _ra_text = ra["raw_text"]
        _ra_context = _get_filing_context(
            _ra_text,
            ra.get("ticker") or ra.get("company_name"),
            ra.get("period") or ra.get("file_name"),
        )
        with st.spinner("Call 1: Extracting financials (Haiku)..."):
            _ra_fd = analyze_financials(_ra_text, API_KEY, model=get_model(), filing_context=_ra_context)
        with st.spinner("Call 2: Generating investment signal..."):
            _ra_sd = analyze_summary(_ra_text, _ra_fd, API_KEY, model=get_model(), filing_context=_ra_context)
        with st.spinner("Call 3: Generating bull/bear case..."):
            _ra_bb = analyze_bear_bull(_ra_text, API_KEY, model=get_model(), filing_context=_ra_context)
        with st.spinner("Call 4: Generating dashboard insights..."):
            _ra_dd = analyze_dashboard_insights(_ra_text, _ra_sd, _ra_fd, API_KEY, model=get_model(), filing_context=_ra_context)
        with st.spinner("Call 5: Scoring MD&A sentiment (Haiku)..."):
            _ra_mda = analyze_mda_sentiment(_ra_text, API_KEY, model=get_mda_model(), filing_context=_ra_context)
        _ra_fd = _run_integrity_checks(
            _ra_fd,
            _ra_sd,
            (ra.get("ticker") or (_ra_sd or {}).get("ticker")),
            ra.get("source", "pdf"),
            filing_date=(ra.get("sec_filing_date") or (ra.get("summary_data") or {}).get("sec_filing_date")),
            accession=ra.get("accession"),
        )
        if ra.get("source") == "edgar" and ra.get("file_path"):
            try:
                safe_write_text(ra["file_path"], _ra_text)
            except Exception:
                pass
        try:
            lib_add(ra["entry_id"], ra["file_name"], ra["file_size"],
                    _ra_fd, _ra_sd, _ra_bb, _ra_dd, raw_text=_ra_text,
                    mda_sentiment=_ra_mda,
                    source=ra.get("source", "pdf"),
                    file_path=ra.get("file_path"))
        except Exception as e:
            logger.warning(f"lib_add failed in PM re-analyse: {e}")
        _save_analysis_to_supabase(
            (_ra_sd or {}).get("ticker"),
            _ra_fd,
            _ra_sd,
            _ra_bb,
            _ra_dd,
            raw_text=_ra_text,
            mda_sentiment=_ra_mda,
            file_name=ra.get("file_name", ""),
            file_size=ra.get("file_size", 0),
            pdf_bytes=ra.get("pdf_bytes"),
            source=ra.get("source", "pdf"),
            file_path=ra.get("file_path"),
        )
        _save_analysis_cache(
            (_ra_sd or {}).get("ticker"),
            _analysis_period(_ra_fd),
            ra.get("source", "pdf"),
            financial_data=_ra_fd,
            summary_data=_ra_sd,
            bear_bull_data=_ra_bb,
            dashboard_data=_ra_dd,
            mda_sentiment=_ra_mda,
            market_data={},
        )
        st.session_state.al_reanalyse_complete = ra["company_name"]
        st.session_state.pending_reanalyse     = None
        st.rerun()

    if st.session_state.get("al_reanalyse_complete"):
        _co = st.session_state.al_reanalyse_complete
        st.session_state.al_reanalyse_complete = None
        st.success(f"✅ {_co} re-analysed — portfolio view updated")

    pf_names = get_portfolio_names()
    if not pf_names:
        st.info("No portfolios yet. Create one in the sidebar to get started.")
        st.stop()

    if not selected_portfolio:
        st.info("Select or create a portfolio in the sidebar.")
        st.stop()

    tickers = get_tickers(selected_portfolio)
    if not tickers:
        st.info(f"**{selected_portfolio}** has no tickers yet. Add some via the sidebar.")
        st.stop()

    st.caption(
        f"Portfolio: **{selected_portfolio}** · "
        f"{len(tickers)} holding{'s' if len(tickers) != 1 else ''}"
    )

    with st.spinner(f"Fetching live market data for {len(tickers)} holding(s)…"):
        portfolio = get_portfolio_display_data(tickers)

    analysed = [r for r in portfolio if r["has_analysis"]]
    pass_n   = sum(1 for r in analysed if r["signal"] == "PASS")
    inv_n    = sum(1 for r in analysed if r["signal"] == "INVESTIGATE")
    dec_n    = sum(1 for r in analysed if r["signal"] == "DECLINE")
    avg_qs   = (sum(r["quality_score"] for r in analysed) / len(analysed)) if analysed else None

    # --- Section 1: Portfolio Summary ---
    st.markdown("##### Portfolio Summary")
    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("Holdings", len(tickers))
    s2.metric("🟢 PASS", pass_n)
    s3.metric("🟡 INVESTIGATE", inv_n)
    s4.metric("🔴 DECLINE", dec_n)
    qs_color = "#70AD47" if (avg_qs or 0) >= 70 else ("#FFC000" if (avg_qs or 0) >= 40 else "#C00000")
    with s5:
        qs_str = f"{avg_qs:.0f}" if avg_qs is not None else "—"
        st.markdown(
            f'<div style="border:1px solid #ddd;border-radius:6px;padding:8px 12px;text-align:center;margin-top:4px">'
            f'<div style="font-size:11px;color:#888">Avg Quality</div>'
            f'<div style="font-size:22px;font-weight:700;color:{qs_color}">{qs_str}</div>'
            f'<div style="font-size:10px;color:#aaa">/ 100</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.divider()

    # --- Section 2: Holdings Table ---
    st.markdown("##### Holdings")
    _SIG = {"PASS": "🟢 PASS", "INVESTIGATE": "🟡 INVESTIGATE", "DECLINE": "🔴 DECLINE"}

    def _fp(v):
        return f"{v:.1f}%" if v is not None else "—"

    table_rows = []
    for r in sorted(portfolio, key=lambda x: (x["quality_score"] is None, -(x["quality_score"] or 0))):
        table_rows.append({
            "Ticker":    r["ticker"],
            "Company":   r["company_name"],
            "Price":     f"${r['price']:,.2f}" if r["price"] else "—",
            "Mkt Cap":   _fmt_market_cap(r["market_cap"]),
            "P/E":       f"{r['pe_ratio']:.1f}x" if r["pe_ratio"] else "—",
            "Signal":    _SIG.get(r["signal"], "🔍 No analysis") if r["has_analysis"] else "🔍 No analysis",
            "Quality":   r["quality_score"] if r["has_analysis"] else None,
            "Lynch":     r["lynch_category"],
            "Red Flags": f"🔴 {r['red_flag_count']}  🟡 {r['yellow_flag_count']}" if r["has_analysis"] else "—",
        })

    st.dataframe(
        table_rows,
        width='stretch',
        hide_index=True,
        column_config={
            "Quality": st.column_config.ProgressColumn(
                "Quality", min_value=0, max_value=100, format="%d",
            ),
        },
    )

    unanalysed = [r for r in portfolio if not r["has_analysis"]]
    if unanalysed:
        st.caption(
            f"💡 {len(unanalysed)} holding(s) have no FinLens analysis — "
            f"switch to Single Analysis and upload the filing PDF to add them."
        )

    # --- Section 2b: Positions ---
    st.markdown("##### Positions")
    st.caption("Track actual purchased positions — shares, cost basis, and unrealized P&L")

    _positions = load_positions(selected_portfolio)
    _price_map = {r["ticker"]: r["price"] for r in portfolio if r["price"] is not None}
    _signal_map = {r["ticker"]: r.get("signal") for r in portfolio}

    def _fmt_dollars(v):
        av = abs(v)
        if av >= 1_000_000_000_000:
            return f"${v / 1_000_000_000_000:.2f}T"
        if av >= 1_000_000_000:
            return f"${v / 1_000_000_000:.1f}B"
        if av >= 1_000_000:
            return f"${v / 1_000_000:.1f}M"
        return f"${v:,.2f}"

    if not _positions:
        st.info("No positions tracked yet. Use **Add Buy Lot** below to add your first position.")
    else:
        _pl_data = calculate_portfolio_pl(_positions, _price_map)
        _pl_rows = _pl_data["positions"]

        if _pl_rows:
            # Summary metric cards
            pc1, pc2, pc3, pc4 = st.columns(4)
            _total_cost  = _pl_data["total_cost_basis"]
            _total_val   = _pl_data["total_current_value"]
            _total_gain  = _pl_data["total_unrealized_gain"]
            _total_pct   = _pl_data["total_unrealized_gain_pct"]

            pc1.metric("Total Cost Basis", _fmt_dollars(_total_cost))
            pc2.metric("Current Value",    _fmt_dollars(_total_val))

            _gain_color = "#4ADE80" if _total_gain >= 0 else "#F87171"
            _gain_sign  = "+" if _total_gain >= 0 else ""
            with pc3:
                st.markdown(
                    f'<div style="border:1px solid #2D3650;border-radius:8px;padding:10px 14px;'
                    f'text-align:center;margin-top:4px">'
                    f'<div style="font-size:11px;color:#94A3B8;margin-bottom:4px">Unrealized Gain/Loss</div>'
                    f'<div style="font-size:20px;font-weight:700;color:{_gain_color}">'
                    f'{_gain_sign}{_fmt_dollars(_total_gain)}</div></div>',
                    unsafe_allow_html=True,
                )
            _pct_color = "#4ADE80" if _total_pct >= 0 else "#F87171"
            _pct_sign  = "+" if _total_pct >= 0 else ""
            with pc4:
                st.markdown(
                    f'<div style="border:1px solid #2D3650;border-radius:8px;padding:10px 14px;'
                    f'text-align:center;margin-top:4px">'
                    f'<div style="font-size:11px;color:#94A3B8;margin-bottom:4px">Total Return</div>'
                    f'<div style="font-size:20px;font-weight:700;color:{_pct_color}">'
                    f'{_pct_sign}{_total_pct:.2f}%</div></div>',
                    unsafe_allow_html=True,
                )

            st.markdown("<div style='margin-top:10px'></div>", unsafe_allow_html=True)

            # Positions table
            _weights = _pl_data["position_weights"]
            _pos_table = []
            for _r in _pl_rows:
                _tk = _r["ticker"]
                _sig = _signal_map.get(_tk, "")
                _pos_table.append({
                    "Ticker":        _tk,
                    "Shares":        _r["shares"],
                    "Avg Cost":      _r["avg_cost"],
                    "Current Price": _r["current_price"],
                    "Cost Basis":    _r["cost_basis"],
                    "Current Value": _r["current_value"],
                    "Gain/Loss $":   _r["unrealized_gain"],
                    "Gain/Loss %":   _r["unrealized_gain_pct"],
                    "Weight %":      _weights.get(_tk, 0.0),
                    "Signal":        _SIG.get(_sig, "—") if _sig else "—",
                })

            def _pl_cell_color(col):
                return [
                    "color: #4ADE80" if v >= 0 else "color: #F87171"
                    for v in col
                ]

            _pos_df = pd.DataFrame(_pos_table)
            st.dataframe(
                _pos_df.style.apply(_pl_cell_color, subset=["Gain/Loss $", "Gain/Loss %"]),
                width='stretch',
                hide_index=True,
                column_config={
                    "Shares":        st.column_config.NumberColumn("Shares",        format="%.4f"),
                    "Avg Cost":      st.column_config.NumberColumn("Avg Cost",      format="$%.2f"),
                    "Current Price": st.column_config.NumberColumn("Current Price", format="$%.2f"),
                    "Cost Basis":    st.column_config.NumberColumn("Cost Basis",    format="$%.2f"),
                    "Current Value": st.column_config.NumberColumn("Current Value", format="$%.2f"),
                    "Gain/Loss $":   st.column_config.NumberColumn("Gain/Loss $",   format="$%.2f"),
                    "Gain/Loss %":   st.column_config.NumberColumn("Gain/Loss %",   format="%.2f%%"),
                    "Weight %":      st.column_config.NumberColumn("Weight %",      format="%.1f%%"),
                },
            )

            with st.expander("Show lots"):
                for _r in _pl_rows:
                    _lot_rows = []
                    for _lot in _r.get("lots", []):
                        _lot_shares = float(_lot.get("shares", 0) or 0)
                        _lot_price = float(_lot.get("price", 0) or 0)
                        _lot_rows.append({
                            "Lot ID":     _lot.get("lot_id", ""),
                            "Ticker":     _r["ticker"],
                            "Shares":     _lot_shares,
                            "Price":      _lot_price,
                            "Cost Basis": _lot_shares * _lot_price,
                            "Date":       _lot.get("date", ""),
                            "Notes":      _lot.get("notes", "") or "",
                        })
                    if _lot_rows:
                        st.markdown(f"**{_r['ticker']}**")
                        st.dataframe(
                            pd.DataFrame(_lot_rows),
                            width='stretch',
                            hide_index=True,
                            column_config={
                                "Shares":     st.column_config.NumberColumn("Shares",     format="%.4f"),
                                "Price":      st.column_config.NumberColumn("Price",      format="$%.2f"),
                                "Cost Basis": st.column_config.NumberColumn("Cost Basis", format="$%.2f"),
                            },
                        )

            # Per-position remove buttons with confirm step
            st.caption("Remove a position:")
            _rm_cols = st.columns(min(len(_pl_rows), 6))
            for _idx, _r in enumerate(_pl_rows):
                _tk = _r["ticker"]
                with _rm_cols[_idx % len(_rm_cols)]:
                    if st.session_state.get("pos_confirm_delete") == _tk:
                        st.caption(f"Remove **{_tk}**?")
                        _yc, _nc = st.columns(2)
                        with _yc:
                            if st.button("Yes", key=f"pos_del_yes_{_tk}",
                                         type="primary", width='stretch'):
                                delete_position(selected_portfolio, _tk)
                                st.session_state.pos_confirm_delete = None
                                st.rerun()
                        with _nc:
                            if st.button("No", key=f"pos_del_no_{_tk}",
                                         width='stretch'):
                                st.session_state.pos_confirm_delete = None
                                st.rerun()
                    else:
                        if st.button(f"✕ {_tk}", key=f"pos_rm_{_tk}",
                                     width='stretch'):
                            st.session_state.pos_confirm_delete = _tk
                            st.rerun()
        else:
            st.caption("None of the tracked positions have live price data available in this portfolio.")

    # Add Buy Lot form
    with st.expander("➕ Add Buy Lot"):
        with st.form("add_position_form"):
            _ticker_opts = get_tickers(selected_portfolio)
            _pos_ticker   = st.selectbox("Ticker", options=_ticker_opts)
            _pos_shares   = st.number_input("Shares", min_value=0.01, step=0.01, value=1.0)
            _pos_avg_cost = st.number_input("Purchase Price per Share ($)", min_value=0.01, step=0.01, value=1.0)
            _pos_date     = st.date_input("Purchase Date", value=datetime.today().date())
            _pos_notes    = st.text_input("Notes (optional)")
            if st.form_submit_button("Add Buy Lot"):
                _ok = save_position(
                    selected_portfolio,
                    _pos_ticker,
                    _pos_shares,
                    _pos_avg_cost,
                    str(_pos_date),
                    _pos_notes or None,
                )
                if _ok:
                    st.success(f"Buy lot added for {_pos_ticker}.")
                    st.rerun()
                else:
                    st.error("Failed to add buy lot.")

    with st.expander("Sell Position"):
        if not _positions:
            st.caption("Add a buy lot before recording a sale.")
        else:
            with st.form("sell_position_form"):
                _held_tickers = [p.get("ticker", "") for p in _positions if p.get("ticker")]
                _sell_ticker = st.selectbox("Ticker", options=_held_tickers, key="sell_position_ticker")
                _sell_shares = st.number_input("Shares to Sell", min_value=0.01, step=0.01, value=1.0)
                _sell_price = st.number_input("Sale Price per Share ($)", min_value=0.01, step=0.01, value=1.0)
                _sell_date = st.date_input("Sale Date", value=datetime.today().date())
                _sell_strategy = st.selectbox("Lot Strategy", options=["FIFO", "LIFO", "specific"])
                _sell_lot_ids = None
                if _sell_strategy == "specific":
                    _selected_pos = next((p for p in _positions if p.get("ticker") == _sell_ticker), None)
                    _lot_options = [lot.get("lot_id", "") for lot in (_selected_pos or {}).get("lots", []) if lot.get("lot_id")]
                    _sell_lot_ids = st.multiselect("Lots", options=_lot_options)
                    st.caption("Specific-lot sale uses the selected lots in the order shown.")
                if st.form_submit_button("Record Sale"):
                    try:
                        _sale = sell_position(
                            selected_portfolio,
                            _sell_ticker,
                            _sell_shares,
                            _sell_price,
                            str(_sell_date),
                            _sell_strategy,
                            _sell_lot_ids,
                        )
                        st.success(
                            f"Sale recorded for {_sell_ticker}: realized gain/loss "
                            f"{_fmt_dollars(_sale['realized_gain'])}."
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Failed to record sale: {exc}")

    if not analysed:
        st.info("No FinLens analysis available yet. Sections below require at least one analysed filing.")
        st.stop()

    st.divider()

    # --- Section 3: Predictive Analytics ---
    st.markdown("##### Predictive Analytics")
    st.caption("Forward-looking signals — distress probability, momentum, and concentration risk")

    pa_left, pa_mid, pa_right = st.columns([1, 1, 1])

    def _distress_score(r):
        score = 0
        cr  = r.get("current_ratio")
        nm  = r.get("net_margin")
        rf  = r.get("red_flag_count") or 0
        ry  = r.get("revenue_yoy")
        sig = r.get("signal")
        if cr is not None:
            if cr < 1.0:   score += 30
            elif cr < 1.5: score += 15
        if nm is not None:
            if nm < 0:    score += 25
            elif nm < 5:  score += 10
        if rf >= 2:   score += 20
        elif rf == 1: score += 10
        if ry is not None:
            if ry < -10:  score += 15
            elif ry < 0:  score += 8
        if sig == "DECLINE":       score += 10
        elif sig == "INVESTIGATE": score += 5
        return min(score, 100)

    def _ds_color(score):
        if score < 40:  return "#4ADE80"
        if score <= 70: return "#FCD34D"
        return "#F87171"

    def _momentum_label(r):
        sig = r.get("signal")
        rf  = r.get("red_flag_count") or 0
        if sig == "DECLINE" or rf >= 2:      return "Deteriorating"
        if sig == "INVESTIGATE" and rf >= 1: return "Mixed"
        if sig == "INVESTIGATE" and rf == 0: return "Improving"
        if sig == "PASS" and rf == 0:        return "Accelerating"
        return "Mixed"

    def _rev_trend(r):
        ry = r.get("revenue_yoy")
        if ry is None: return "Rev —"
        if ry > 3:     return "Rev ▲"
        if ry < -3:    return "Rev ▼"
        return "Rev →"

    _sorted_analysed = sorted(analysed, key=lambda x: _distress_score(x), reverse=True)
    _unanalysed      = [r for r in portfolio if not r["has_analysis"]]

    # ── Panel 1: Financial Distress Score ──────────────────────────────
    with pa_left:
        with st.container(border=True):
            st.markdown(
                '<div style="font-size:13px;font-weight:700;color:#F1F5F9;margin-bottom:2px">'
                'Financial Distress Score</div>'
                '<div style="font-size:11px;color:#64748B;margin-bottom:12px">'
                'Altman Z-Score derived · 0 = safe, 100 = distress</div>',
                unsafe_allow_html=True,
            )
            rows_html = ""
            for r in _sorted_analysed:
                score = _distress_score(r)
                col   = _ds_color(score)
                rows_html += (
                    f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:7px">'
                    f'<span style="font-size:12px;color:#94A3B8;width:44px;flex-shrink:0;'
                    f'font-family:monospace">{r["ticker"]}</span>'
                    f'<div style="flex:1;height:8px;background:#2D3650;border-radius:4px;overflow:hidden">'
                    f'<div style="width:{score}%;height:8px;background:{col};border-radius:4px"></div>'
                    f'</div>'
                    f'<span style="font-size:12px;font-weight:700;color:{col};width:26px;'
                    f'text-align:right;flex-shrink:0">{score}</span>'
                    f'</div>'
                )
            for r in _unanalysed:
                rows_html += (
                    f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:7px">'
                    f'<span style="font-size:12px;color:#64748B;width:44px;flex-shrink:0;'
                    f'font-family:monospace">{r["ticker"]}</span>'
                    f'<div style="flex:1;height:8px;background:#2D3650;border-radius:4px"></div>'
                    f'<span style="font-size:12px;color:#64748B;width:26px;'
                    f'text-align:right;flex-shrink:0">—</span>'
                    f'</div>'
                )
            st.markdown(rows_html, unsafe_allow_html=True)
            st.markdown(
                '<div style="font-size:11px;color:#64748B;margin-top:8px">'
                '<span style="color:#4ADE80">●</span> Safe &lt;40&nbsp;&nbsp;'
                '<span style="color:#FCD34D">●</span> Watch 40–70&nbsp;&nbsp;'
                '<span style="color:#F87171">●</span> Distress &gt;70'
                '</div>',
                unsafe_allow_html=True,
            )

    # ── Panel 2: Momentum Scorecard ────────────────────────────────────
    with pa_mid:
        with st.container(border=True):
            st.markdown(
                '<div style="font-size:13px;font-weight:700;color:#F1F5F9;margin-bottom:2px">'
                'Momentum Scorecard</div>'
                '<div style="font-size:11px;color:#64748B;margin-bottom:12px">'
                'YoY trend across revenue, margin, and cash flow</div>',
                unsafe_allow_html=True,
            )
            _MOM_STYLE = {
                "Accelerating":  ("#052e16", "#4ADE80"),
                "Improving":     ("#052e16", "#4ADE80"),
                "Mixed":         ("#252D40", "#94A3B8"),
                "Deteriorating": ("#1F0000", "#F87171"),
            }
            imp_n, mix_n, det_n = 0, 0, 0
            rows_html = ""
            for r in _sorted_analysed:
                label  = _momentum_label(r)
                bg, fg = _MOM_STYLE[label]
                rev    = _rev_trend(r)
                if label in ("Accelerating", "Improving"): imp_n += 1
                elif label == "Mixed":                     mix_n += 1
                else:                                      det_n += 1
                rows_html += (
                    f'<div style="display:flex;align-items:center;gap:8px;'
                    f'margin-bottom:5px;padding:2px 0">'
                    f'<span style="font-size:12px;font-weight:700;color:#F1F5F9;width:44px;'
                    f'flex-shrink:0;font-family:monospace">{r["ticker"]}</span>'
                    f'<span style="flex:1;font-size:12px;color:#64748B">{rev}</span>'
                    f'<span style="font-size:11px;font-weight:700;padding:2px 8px;'
                    f'border-radius:3px;background:{bg};color:{fg};flex-shrink:0">{label}</span>'
                    f'</div>'
                )
            for r in _unanalysed:
                rows_html += (
                    f'<div style="display:flex;align-items:center;gap:8px;'
                    f'margin-bottom:5px;padding:2px 0">'
                    f'<span style="font-size:12px;font-weight:700;color:#64748B;width:44px;'
                    f'flex-shrink:0;font-family:monospace">{r["ticker"]}</span>'
                    f'<span style="flex:1;font-size:12px;color:#64748B">—</span>'
                    f'<span style="font-size:11px;color:#64748B;padding:2px 8px">No data</span>'
                    f'</div>'
                )
            st.markdown(rows_html, unsafe_allow_html=True)
            parts = []
            if imp_n: parts.append(f'<span style="color:#4ADE80">{imp_n} improving</span>')
            if mix_n: parts.append(f'<span style="color:#94A3B8">{mix_n} mixed</span>')
            if det_n: parts.append(f'<span style="color:#F87171">{det_n} deteriorating</span>')
            st.markdown(
                '<div style="font-size:11px;color:#64748B;margin-top:8px">'
                + ' · '.join(parts) + '</div>',
                unsafe_allow_html=True,
            )

    # ── Panel 3: Concentration Risk ────────────────────────────────────
    with pa_right:
        with st.container(border=True):
            st.markdown(
                '<div style="font-size:13px;font-weight:700;color:#F1F5F9;margin-bottom:2px">'
                'Concentration Risk</div>'
                '<div style="font-size:11px;color:#64748B;margin-bottom:12px">'
                'Signal and sector distribution</div>',
                unsafe_allow_html=True,
            )
            total_h = len(portfolio)

            # Signal segmented bar
            _SIG_COLS = {
                "PASS":        "#4ADE80",
                "INVESTIGATE": "#FCD34D",
                "DECLINE":     "#F87171",
                "No analysis": "#2D3650",
            }
            sig_counts = {"PASS": 0, "INVESTIGATE": 0, "DECLINE": 0, "No analysis": 0}
            for r in portfolio:
                if r["has_analysis"]:
                    sig = r.get("signal") or ""
                    if sig in ("PASS", "INVESTIGATE", "DECLINE"):
                        sig_counts[sig] += 1
                    else:
                        sig_counts["No analysis"] += 1
                else:
                    sig_counts["No analysis"] += 1

            st.markdown(
                '<div style="font-size:11px;font-weight:600;color:#94A3B8;margin-bottom:4px">Signal</div>',
                unsafe_allow_html=True,
            )
            bar1 = '<div style="display:flex;height:14px;border-radius:4px;overflow:hidden;gap:1px;margin-bottom:5px">'
            leg1 = '<div style="font-size:11px;color:#64748B;line-height:2">'
            for label, count in sig_counts.items():
                if count == 0:
                    continue
                pct = count / total_h * 100
                c   = _SIG_COLS[label]
                bar1 += f'<div style="width:{pct:.1f}%;background:{c}" title="{label}: {count}"></div>'
                leg1 += f'<span style="color:{c}">■</span> {label} {pct:.0f}%&nbsp;&nbsp;'
            bar1 += '</div>'
            leg1 += '</div>'
            st.markdown(bar1 + leg1, unsafe_allow_html=True)

            # Lynch/sector segmented bar
            _LYNCH_MAP = {
                "Fast Grower":  "Technology/Growth",
                "Turnaround":   "Recovery",
                "Stalwart":     "Defensive",
                "Slow Grower":  "Value",
                "Asset Play":   "Special Situations",
            }
            _LYNCH_COLS = {
                "Technology/Growth":  "#185FA5",
                "Recovery":           "#1D9E75",
                "Defensive":          "#534AB7",
                "Value":              "#D85A30",
                "Special Situations": "#854F0B",
                "Unclassified":       "#64748B",
            }
            lynch_dist: dict[str, int] = {}
            for r in portfolio:
                cat = _LYNCH_MAP.get(r.get("lynch_category") or "—", "Unclassified")
                lynch_dist[cat] = lynch_dist.get(cat, 0) + 1

            st.markdown(
                '<div style="font-size:11px;font-weight:600;color:#94A3B8;margin:8px 0 4px 0">'
                'Sector (Lynch proxy)</div>',
                unsafe_allow_html=True,
            )
            bar2 = '<div style="display:flex;height:14px;border-radius:4px;overflow:hidden;gap:1px;margin-bottom:5px">'
            leg2 = '<div style="font-size:11px;color:#64748B;line-height:2">'
            for cat, count in lynch_dist.items():
                pct   = count / total_h * 100
                color = _LYNCH_COLS.get(cat, "#64748B")
                bar2 += f'<div style="width:{pct:.1f}%;background:{color}" title="{cat}: {count}"></div>'
                leg2 += f'<span style="color:{color}">■</span> {cat} {pct:.0f}%&nbsp;&nbsp;'
            bar2 += '</div>'
            leg2 += '</div>'
            st.markdown(bar2 + leg2, unsafe_allow_html=True)

            # Concentration warnings
            top_sig_pct   = max(sig_counts.values()) / total_h * 100
            top_lynch_pct = max(lynch_dist.values()) / total_h * 100 if lynch_dist else 0
            warn = ""
            if top_sig_pct   > 50: warn += '<div style="font-size:11px;color:#FCD34D;margin-top:6px">⚠ High signal concentration</div>'
            if top_lynch_pct > 50: warn += '<div style="font-size:11px;color:#FCD34D;margin-top:4px">⚠ High category concentration</div>'
            if warn:
                st.markdown(warn, unsafe_allow_html=True)

    st.divider()

    # --- Section 4: Portfolio Analytics ---
    st.markdown("##### Portfolio Analytics")
    st.caption("Trend analysis, valuation positioning, risk matrix, and earnings quality")

    def _dark(fig, height=280, **extra):
        """Apply shared dark theme to a plotly figure."""
        fig.update_layout(
            paper_bgcolor='#1E2433',
            plot_bgcolor='#1E2433',
            font=dict(color='#94A3B8', size=11),
            margin=dict(l=40, r=20, t=20, b=40),
            showlegend=False,
            height=height,
            **extra,
        )
        fig.update_xaxes(gridcolor='rgba(255,255,255,0.06)', zerolinecolor='rgba(255,255,255,0.1)')
        fig.update_yaxes(gridcolor='rgba(255,255,255,0.06)', zerolinecolor='rgba(255,255,255,0.1)')
        return fig

    def _panel_header(title, subtitle):
        st.markdown(
            f'<div style="font-size:13px;font-weight:700;color:#F1F5F9;margin-bottom:2px">{title}</div>'
            f'<div style="font-size:11px;color:#64748B;margin-bottom:8px">{subtitle}</div>',
            unsafe_allow_html=True,
        )

    row1_left, row1_right = st.columns([1, 1])
    row2_left, row2_right = st.columns([1, 1])

    # ── Panel 1: Portfolio Quality Trend ───────────────────────────────
    with row1_left:
        with st.container(border=True):
            _panel_header("Portfolio Quality Trend",
                          "Average quality score as filings are added")
            from collections import defaultdict as _dd
            fy_groups: dict = _dd(list)
            for r in analysed:
                if r["quality_score"] is not None:
                    fy_groups[str(r["fiscal_year"])].append(r["quality_score"])
            trend_pts = sorted(
                [(fy, sum(scores) / len(scores)) for fy, scores in fy_groups.items()],
                key=lambda p: p[0],
            )
            if len(trend_pts) < 2:
                st.info("Add more analysed filings to see quality trend")
            else:
                fy_labels = [p[0] for p in trend_pts]
                qs_vals   = [p[1] for p in trend_pts]
                avg_qs    = sum(qs_vals) / len(qs_vals)
                fig1 = go.Figure()
                fig1.add_trace(go.Scatter(
                    x=fy_labels, y=qs_vals,
                    mode='lines+markers',
                    line=dict(color='#378ADD', width=2),
                    fill='tozeroy',
                    fillcolor='rgba(55,138,221,0.1)',
                    marker=dict(size=6, color='#378ADD'),
                ))
                fig1.add_hline(
                    y=avg_qs, line_dash='dot',
                    line_color='rgba(148,163,184,0.5)',
                    annotation_text=f'Avg {avg_qs:.0f}',
                    annotation_font=dict(color='#94A3B8', size=10),
                )
                _dark(fig1)
                fig1.update_yaxes(range=[0, 100], title_text='Quality Score')
                st.plotly_chart(fig1, width='stretch')

    # ── Panel 2: Valuation Dashboard ───────────────────────────────────
    with row1_right:
        with st.container(border=True):
            _panel_header("Valuation Dashboard",
                          "Quality score vs P/E — top-left is the sweet spot")
            _SIG_PT_COLS = {
                "PASS": "#4ADE80", "INVESTIGATE": "#FCD34D",
                "DECLINE": "#F87171",
            }
            val_pts = [r for r in portfolio
                       if r.get("quality_score") is not None and r.get("pe_ratio") is not None]
            if len(val_pts) < 2:
                st.info("Fetch market data for holdings to see valuation positioning")
            else:
                max_pe = max(r["pe_ratio"] for r in val_pts) or 30
                fig2 = go.Figure(go.Scatter(
                    x=[r["pe_ratio"] for r in val_pts],
                    y=[r["quality_score"] for r in val_pts],
                    mode='markers+text',
                    text=[r["ticker"] for r in val_pts],
                    textposition='top center',
                    textfont=dict(size=10, color='#94A3B8'),
                    marker=dict(
                        size=10,
                        color=[_SIG_PT_COLS.get(r.get("signal"), "#64748B") for r in val_pts],
                    ),
                ))
                _dark(fig2)
                fig2.update_xaxes(title_text='P/E ratio', range=[0, max_pe * 1.2])
                fig2.update_yaxes(title_text='Quality Score', range=[0, 100])
                st.plotly_chart(fig2, width='stretch')

    # ── Panel 3: Risk / Return Matrix ──────────────────────────────────
    with row2_left:
        with st.container(border=True):
            _panel_header("Risk / Return Matrix",
                          "Distress score vs momentum — bottom-left is ideal")
            _MOM_NUM = {"Accelerating": 90, "Improving": 70, "Mixed": 50, "Deteriorating": 20}
            matrix_pts = []
            for r in analysed:
                ds = _distress_score(r)
                ml = _momentum_label(r)
                ms = _MOM_NUM.get(ml)
                if ms is None:
                    continue
                if ds < 40 and ms > 50:    pt_col = "#4ADE80"
                elif ds >= 40 and ms > 50: pt_col = "#FCD34D"
                elif ds < 40:              pt_col = "#94A3B8"
                else:                      pt_col = "#F87171"
                matrix_pts.append((r["ticker"], ds, ms, pt_col))

            if not matrix_pts:
                st.info("No analysed holdings to display")
            else:
                fig3 = go.Figure()
                for x0, x1, y0, y1, shade in [
                    (0,  40,  50, 100, 'rgba(74,222,128,0.05)'),
                    (40, 100, 50, 100, 'rgba(252,211,77,0.05)'),
                    (0,  40,  0,  50,  'rgba(148,163,184,0.05)'),
                    (40, 100, 0,  50,  'rgba(248,113,113,0.05)'),
                ]:
                    fig3.add_shape(type='rect', x0=x0, x1=x1, y0=y0, y1=y1,
                                   fillcolor=shade, line_width=0, layer='below')
                for x, y, txt in [
                    (20,  92, 'Safe + Improving'),
                    (70,  92, 'Risky + Improving'),
                    (20,   8, 'Safe + Declining'),
                    (70,   8, 'Risky + Declining'),
                ]:
                    fig3.add_annotation(x=x, y=y, text=txt, showarrow=False,
                                        font=dict(size=9, color='rgba(148,163,184,0.35)'))
                fig3.add_trace(go.Scatter(
                    x=[p[1] for p in matrix_pts],
                    y=[p[2] for p in matrix_pts],
                    mode='markers+text',
                    text=[p[0] for p in matrix_pts],
                    textposition='top center',
                    textfont=dict(size=10, color='#94A3B8'),
                    marker=dict(size=12, color=[p[3] for p in matrix_pts]),
                ))
                _dark(fig3)
                fig3.update_xaxes(title_text='Distress Score', range=[0, 100])
                fig3.update_yaxes(title_text='Momentum Score', range=[0, 100])
                st.plotly_chart(fig3, width='stretch')

    # ── Panel 4: Earnings Quality Scorecard ────────────────────────────
    with row2_right:
        with st.container(border=True):
            _panel_header("Earnings Quality Scorecard",
                          "FCF conversion and revenue quality per holding")
            eq_rows = []
            for r in sorted(analysed,
                            key=lambda x: (x.get("fcf_conv") is None, -(x.get("fcf_conv") or 0))):
                fcf = r.get("fcf_conv")
                ry  = r.get("revenue_yoy")
                gm  = r.get("gross_margin")
                rf  = r.get("red_flag_count") or 0

                if ry is not None and ry > 5 and gm is not None and gm > 30:
                    rev_qual = "High"
                elif (ry is not None and ry > 0) or (gm is not None and gm > 20):
                    rev_qual = "Med"
                else:
                    rev_qual = "Low"

                if fcf is not None and fcf > 80 and rf == 0:
                    rating = "Real ✓"
                elif (fcf is not None and fcf > 50) or rf <= 1:
                    rating = "Mixed ~"
                else:
                    rating = "Weak ✗"

                eq_rows.append({
                    "Ticker":      r["ticker"],
                    "FCF Conv.":   f"{fcf:.0f}%" if fcf is not None else "—",
                    "Rev Quality": rev_qual,
                    "Earnings":    rating,
                })
            if eq_rows:
                st.dataframe(
                    eq_rows,
                    width='stretch',
                    hide_index=True,
                    column_config={
                        "Ticker":      st.column_config.TextColumn("Ticker",      width="small"),
                        "FCF Conv.":   st.column_config.TextColumn("FCF Conv.",   width="small"),
                        "Rev Quality": st.column_config.TextColumn("Rev Quality", width="small"),
                        "Earnings":    st.column_config.TextColumn("Earnings",    width="small"),
                    },
                )
            else:
                st.info("No analysed holdings to display")

    st.divider()

    # --- Section 5: Framework Scores ---
    st.markdown("##### Framework Scores")
    st.dataframe(
        [
            {
                "Ticker":        r["ticker"],
                "Company":       r["company_name"],
                "Quality Score": r["quality_score"],
                "Dalio View":    (r["dalio_view"] or "—"),
                "Marks View":    (r["marks_view"] or "—"),
            }
            for r in analysed
        ],
        width='stretch',
        hide_index=True,
        column_config={
            "Quality Score": st.column_config.ProgressColumn(
                "Quality Score", min_value=0, max_value=100, format="%d",
            ),
            "Dalio View": st.column_config.TextColumn("Dalio View", width="large"),
            "Marks View": st.column_config.TextColumn("Marks View", width="large"),
        },
    )

    st.stop()


# --- Filing Comparison page --------------------------------------------
if page == "Filing Comparison":

    if not API_KEY:
        st.error("ANTHROPIC_API_KEY not found. Add it to your .env file and restart the app.")
        st.stop()

    st.markdown("### Filing Comparison")
    st.caption("Upload two filings from the same company to compare MD&A sentiment, theme shifts, and language changes year-over-year.")

    st.markdown("#### Compare from Library")
    _fc_library_entries = sorted(lib_get(), key=lambda entry: _library_comparison_label(entry).lower())
    _fc_library_options = [""] + [entry["id"] for entry in _fc_library_entries]
    _fc_library_by_id = {entry["id"]: entry for entry in _fc_library_entries}
    _fc_library_labels = {
        "": "— Select a filing —",
        **{entry["id"]: _library_comparison_label(entry) for entry in _fc_library_entries},
    }

    lib_col1, lib_col2 = st.columns(2)
    with lib_col1:
        fc_lib_1 = st.selectbox(
            "Library Filing 1",
            _fc_library_options,
            format_func=lambda option: _fc_library_labels.get(option, option),
            key="fc_library_1",
        )
    with lib_col2:
        fc_lib_2 = st.selectbox(
            "Library Filing 2",
            _fc_library_options,
            format_func=lambda option: _fc_library_labels.get(option, option),
            key="fc_library_2",
        )

    if st.button("Compare from Library", type="primary", width='stretch'):
        if not fc_lib_1 or not fc_lib_2:
            st.warning("Please select two filings to compare")
        else:
            _entry1 = _fc_library_by_id.get(fc_lib_1)
            _entry2 = _fc_library_by_id.get(fc_lib_2)
            _label1 = _fc_library_labels.get(fc_lib_1, "Filing 1")
            _label2 = _fc_library_labels.get(fc_lib_2, "Filing 2")
            _sorted_id_1, _sorted_id_2 = sorted([fc_lib_1, fc_lib_2])
            _comparison_cache_key = f"comparison_{_sorted_id_1}_{_sorted_id_2}"
            _cached_comparison = None
            try:
                _cached_comparison = load_cache(_comparison_cache_key)
            except Exception:
                _cached_comparison = None

            if _cached_comparison:
                st.session_state["filing_comparison"] = _cached_comparison
                st.session_state["filing_comparison_cache_note"] = True
                st.rerun()
            else:
                def _comparison_text_from_library(entry: dict | None, label: str) -> str | None:
                    if not entry:
                        return None
                    _pdf_path = _pdf_cache_path(
                        entry.get("ticker") if entry.get("ticker") != "—" else None,
                        _library_period_label(entry),
                    )
                    if _pdf_path and Path(_pdf_path).exists():
                        try:
                            _disk_bytes = Path(_pdf_path).read_bytes()
                            _file_label = entry.get("file_name") or Path(_pdf_path).name
                            with st.spinner(f"Extracting text from {_file_label}..."):
                                if entry.get("file_type") == "docx":
                                    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as _tmp:
                                        _tmp.write(_disk_bytes)
                                        _tmp_path = _tmp.name
                                    _disk_text = convert_to_markdown(_tmp_path) or ""
                                    try:
                                        os.unlink(_tmp_path)
                                    except Exception:
                                        pass
                                else:
                                    _disk_text = extract_text_from_pdf(io.BytesIO(_disk_bytes))
                            if _disk_text:
                                return _disk_text
                        except Exception:
                            pass
                    _cached_text = _library_text_for_entry(entry)
                    if _cached_text:
                        return _cached_text
                    st.warning(f"No data found for {label} — please load and analyse it first in Single Analysis, then try again")
                    return None

                _text1 = _comparison_text_from_library(_entry1, _label1)
                _text2 = _comparison_text_from_library(_entry2, _label2)
                if _text1 and _text2:

                    with st.spinner("Running comparison analysis (3 Claude calls)..."):
                        _fc_result = compare_filings(
                            _text1, _text2, _label1, _label2, API_KEY, model=get_model()
                        )

                    if not _fc_result.get("error"):
                        try:
                            CACHE_DIR.mkdir(parents=True, exist_ok=True)
                            safe_write_text(
                                CACHE_DIR / f"{_comparison_cache_key}.json",
                                json.dumps(_fc_result, indent=2, default=str),
                            )
                        except Exception:
                            pass

                    st.session_state["filing_comparison"] = _fc_result
                    st.session_state["filing_comparison_cache_note"] = False
                    st.rerun()

    st.divider()
    st.caption("— or upload files manually —")

    fc_col1, fc_col2 = st.columns(2)
    with fc_col1:
        st.markdown("**Filing 1 — Earlier Period**")
        fc_file1  = st.file_uploader("Filing 1 PDF", type=["pdf"], key="fc_file1", label_visibility="collapsed")
        fc_label1 = st.text_input("Period label", value="", placeholder="e.g. FY2024", key="fc_label1")
    with fc_col2:
        st.markdown("**Filing 2 — Later Period**")
        fc_file2  = st.file_uploader("Filing 2 PDF", type=["pdf"], key="fc_file2", label_visibility="collapsed")
        fc_label2 = st.text_input("Period label", value="", placeholder="e.g. FY2025", key="fc_label2")

    _both_uploaded = fc_file1 is not None and fc_file2 is not None

    if st.button("Compare Filings $", type="primary", width='stretch', disabled=not _both_uploaded):
        _lbl1 = fc_label1.strip() or "Filing 1"
        _lbl2 = fc_label2.strip() or "Filing 2"

        with st.spinner(f"Extracting text from {fc_file1.name}..."):
            _text1 = extract_text_from_pdf(fc_file1)
        with st.spinner(f"Extracting text from {fc_file2.name}..."):
            _text2 = extract_text_from_pdf(fc_file2)

        with st.spinner(f"Scoring MD&A sentiment — {_lbl1}..."):
            pass  # compare_filings handles all three calls internally

        with st.spinner("Running comparison analysis (3 Claude calls)..."):
            _fc_result = compare_filings(
                _text1, _text2, _lbl1, _lbl2, API_KEY, model=get_model()
            )

        st.session_state["filing_comparison"] = _fc_result
        st.session_state["filing_comparison_cache_note"] = False
        st.rerun()
    st.caption("~$0.03 per comparison")
    if st.session_state.get("filing_comparison_cache_note"):
        st.caption("Loaded from cache")

    # --- Display ---
    _fc = st.session_state.get("filing_comparison")
    if _fc:
        if _fc.get("error"):
            st.warning(f"Comparison could not be completed: {_fc['error']}")
        else:
            _s1   = _fc.get("sentiment_1") or {}
            _s2   = _fc.get("sentiment_2") or {}
            _comp = _fc.get("comparison") or {}
            _lbl1 = _fc.get("label_1", "Filing 1")
            _lbl2 = _fc.get("label_2", "Filing 2")

            _TONE_STYLE = {
                "Positive": {"bg": "#052e16", "color": "#4ADE80", "border": "#166534"},
                "Cautious":  {"bg": "#1C1200", "color": "#FCD34D", "border": "#92400E"},
                "Negative": {"bg": "#1F0000", "color": "#F87171", "border": "#991B1B"},
            }

            def _tone_card(sentiment: dict, label: str) -> str:
                tone = sentiment.get("overall_tone") or "—"
                ts   = _TONE_STYLE.get(tone, {"bg": "#1E2433", "color": "#94A3B8", "border": "#374B6B"})
                return (
                    f'<div style="background:{ts["bg"]};border:1px solid {ts["border"]};'
                    f'border-radius:8px;padding:14px 18px;text-align:center">'
                    f'<div style="font-size:11px;color:#64748B;letter-spacing:0.08em;'
                    f'text-transform:uppercase;margin-bottom:4px">{label}</div>'
                    f'<div style="font-size:20px;font-weight:500;color:{ts["color"]}">{tone}</div>'
                    f'</div>'
                )

            def _score_bar(label: str, value) -> str:
                if value is None:
                    return f'<div style="font-size:12px;color:#64748B;margin-bottom:4px">{label}: N/A</div>'
                filled = "■" * value
                empty  = "□" * (5 - value)
                return (
                    f'<div style="font-size:12px;color:#94A3B8;margin-bottom:4px">'
                    f'{label}: <span style="color:#378ADD;letter-spacing:2px">{filled}</span>'
                    f'<span style="color:#374B6B;letter-spacing:2px">{empty}</span>'
                    f' <span style="color:#64748B">({value}/5)</span></div>'
                )

            def _delta_badge(v1, v2) -> str:
                if v1 is None or v2 is None:
                    return '<span style="color:#64748B;font-size:12px">—</span>'
                d = v2 - v1
                if d > 0:
                    return f'<span style="color:#4ADE80;font-size:13px;font-weight:600">▲ +{d}</span>'
                if d < 0:
                    return f'<span style="color:#F87171;font-size:13px;font-weight:600">▼ {d}</span>'
                return '<span style="color:#64748B;font-size:12px">= 0</span>'

            # ── Section 1: Sentiment Comparison ──────────────────────────
            st.divider()
            st.markdown("#### Sentiment Comparison")

            sc1, sc_mid, sc2 = st.columns([5, 2, 5])

            with sc1:
                st.markdown(_tone_card(_s1, _lbl1), unsafe_allow_html=True)
                sc = (_s1.get("scores") or {})
                st.markdown(
                    _score_bar("Forward Outlook",      sc.get("forward_outlook")) +
                    _score_bar("Risk Language Density", sc.get("risk_language_density")) +
                    _score_bar("Management Confidence", sc.get("management_confidence")),
                    unsafe_allow_html=True,
                )

            with sc_mid:
                sc1s = _s1.get("scores") or {}
                sc2s = _s2.get("scores") or {}
                st.markdown(
                    '<div style="margin-top:52px;text-align:center">'
                    + _delta_badge(sc1s.get("forward_outlook"),      sc2s.get("forward_outlook"))      + "<br>"
                    + _delta_badge(sc1s.get("risk_language_density"), sc2s.get("risk_language_density")) + "<br>"
                    + _delta_badge(sc1s.get("management_confidence"), sc2s.get("management_confidence"))
                    + "</div>",
                    unsafe_allow_html=True,
                )

            with sc2:
                st.markdown(_tone_card(_s2, _lbl2), unsafe_allow_html=True)
                sc = (_s2.get("scores") or {})
                st.markdown(
                    _score_bar("Forward Outlook",      sc.get("forward_outlook")) +
                    _score_bar("Risk Language Density", sc.get("risk_language_density")) +
                    _score_bar("Management Confidence", sc.get("management_confidence")),
                    unsafe_allow_html=True,
                )

            # ── Tone shift summary ────────────────────────────────────────
            if _comp.get("tone_shift"):
                st.markdown(
                    f'<div style="background:#252D40;border:0.5px solid #2D3650;border-radius:8px;'
                    f'padding:14px 18px;margin-top:12px;font-size:14px;color:#94A3B8;line-height:1.6">'
                    f'<span style="font-size:11px;color:#64748B;text-transform:uppercase;'
                    f'letter-spacing:0.08em;display:block;margin-bottom:6px">Tone Shift</span>'
                    f'{_comp["tone_shift"]}</div>',
                    unsafe_allow_html=True,
                )

            # ── Section 2: Theme Changes ──────────────────────────────────
            themes = _comp.get("themes") or []
            if themes:
                st.divider()
                st.markdown("#### Theme Changes")
                for th in themes:
                    direction = (th.get("direction") or "").lower()
                    badge_bg    = "#052e16" if direction == "increased" else "#1F0000"
                    badge_color = "#4ADE80" if direction == "increased" else "#F87171"
                    badge_text  = "Increased" if direction == "increased" else "Decreased"
                    st.markdown(
                        f'<div style="background:#252D40;border:0.5px solid #2D3650;border-radius:8px;'
                        f'padding:12px 16px;margin-bottom:8px">'
                        f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:4px">'
                        f'<span style="font-size:14px;font-weight:500;color:#F1F5F9">{th.get("topic","")}</span>'
                        f'<span style="background:{badge_bg};color:{badge_color};border-radius:4px;'
                        f'padding:1px 8px;font-size:11px;font-weight:600;text-transform:uppercase;'
                        f'letter-spacing:0.06em">{badge_text}</span>'
                        f'</div>'
                        f'<div style="font-size:13px;color:#64748B">{th.get("detail","")}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

            # ── Section 3: Key Language Shifts ───────────────────────────
            shifts = _comp.get("language_shifts") or []
            if shifts:
                st.divider()
                st.markdown("#### Key Language Shifts")

                _SHIFT_STYLE = {
                    "appeared":   {"border": "#166534", "label": "Appeared",   "color": "#4ADE80"},
                    "disappeared": {"border": "#991B1B", "label": "Disappeared", "color": "#F87171"},
                    "changed":    {"border": "#92400E", "label": "Changed",    "color": "#FCD34D"},
                }

                for group_type in ("appeared", "disappeared", "changed"):
                    group = [s for s in shifts if (s.get("type") or "").lower() == group_type]
                    if not group:
                        continue
                    gs = _SHIFT_STYLE[group_type]
                    for s in group:
                        st.markdown(
                            f'<div style="display:flex;align-items:baseline;gap:8px;margin-bottom:6px">'
                            f'<span style="font-size:10px;font-weight:700;text-transform:uppercase;'
                            f'letter-spacing:0.08em;color:{gs["color"]};white-space:nowrap">{gs["label"]}</span>'
                            f'<blockquote style="border-left:3px solid {gs["border"]};margin:0;'
                            f'padding:5px 12px;color:#94A3B8;font-size:13px;font-style:italic;flex:1">'
                            f'{s.get("phrase","")}</blockquote>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

    st.stop()


# --- Education page ----------------------------------------------------
if page == "Education":
    _render_education_page(_education_topic)
    st.stop()


# --- Stock Tracker page ------------------------------------------------
if page == "Stock Tracker":
    import io

    from modules.fiscal_ai import (
        get_adjusted_metrics_with_values,
        get_company_logo,
        get_company_filings,
        get_company_news,
        get_ratios_with_values,
        get_segments_with_values,
        get_shares_outstanding,
    )
    from modules.stock_tracker import (
        _fiscal_ai_exchange_for_ticker,
        get_stock_data,
    )
    from modules.fmp import (
        get_balance_sheet as get_fmp_balance_sheet,
        get_cash_flow as get_fmp_cash_flow,
        get_earnings_calendar as get_fmp_earnings_calendar,
        get_income_statement as get_fmp_income_statement,
    )
    from modules.polymarket import get_macro_markets
    from modules.watchlist import load_watchlist, add_ticker as wl_add, remove_ticker as wl_remove
    from datetime import date as _date
    import pandas as _pd

    if "stock_data" not in st.session_state:
        st.session_state.stock_data = None
    if "st_current_ticker" not in st.session_state:
        st.session_state.st_current_ticker = ""

    st.markdown("## Stock Tracker")
    st.caption("Live price, momentum signals, analyst consensus, and earnings — no upload needed.")

    with st.form("st_form"):
        tk_c, btn_c = st.columns([4, 1])
        with tk_c:
            st_ticker = st.text_input(
                "Ticker", placeholder="e.g. AAPL, NVDA, MSFT",
                label_visibility="collapsed", key="st_ticker",
            )
        with btn_c:
            st_submitted = st.form_submit_button("Track", type="primary", width='stretch')

    if st_submitted and st_ticker.strip():
        with st.spinner(f"Fetching data for {st_ticker.strip().upper()}…"):
            st.session_state.stock_data = get_stock_data(st_ticker.strip())
            st.session_state.st_current_ticker = st_ticker.strip().upper()

    def _render_stock_tracker_sidebar_watchlist():
        with st.sidebar:
            st.divider()
            st.subheader(" Watchlist")
            cur_sidebar_ticker = st.session_state.get("st_current_ticker", "")
            if cur_sidebar_ticker:
                wl_now = load_watchlist()
                already_in = cur_sidebar_ticker.upper() in [t.upper() for t in wl_now]
                btn_label = "✓ Added to Watchlist" if already_in else "+ Add to Watchlist"
                btn_type = "secondary" if already_in else "primary"
                if st.button(btn_label, key="wl_add_btn", type=btn_type, disabled=already_in, width='stretch'):
                    wl_add(cur_sidebar_ticker)
                    st.success(f"{cur_sidebar_ticker} added to watchlist.")
                    st.rerun()

            wl_tickers = load_watchlist()
            if not wl_tickers:
                st.caption("Your watchlist is empty. Track a ticker above and add it here.")
            else:
                st.caption("Click a ticker to load it, or ✕ to remove.")
                cols_per_row = 2
                for row_start in range(0, len(wl_tickers), cols_per_row):
                    row_tickers = wl_tickers[row_start : row_start + cols_per_row]
                    row_cols = st.columns(cols_per_row)
                    for col, tk in zip(row_cols, row_tickers):
                        with col:
                            sub_a, sub_b = st.columns([3, 1])
                            with sub_a:
                                if st.button(tk, key=f"wl_load_{tk}", width='stretch'):
                                    with st.spinner(f"Loading {tk}…"):
                                        st.session_state.stock_data = get_stock_data(tk)
                                        st.session_state.st_current_ticker = tk
                                    st.rerun()
                            with sub_b:
                                if st.button("✕", key=f"wl_rm_{tk}", help=f"Remove {tk}"):
                                    wl_remove(tk)
                                    st.rerun()

                st.markdown("**Watchlist Summary**")

                @st.cache_data(ttl=300)
                def _wl_summary(tickers_tuple):
                    def _fmt_watchlist_market_cap(value):
                        if not value:
                            return "—"
                        value = float(value)
                        if value >= 1_000_000_000_000:
                            return f"${value / 1_000_000_000_000:.2f}T"
                        if value >= 1_000_000_000:
                            return f"${value / 1_000_000_000:.2f}B"
                        return f"${value / 1_000_000:.1f}M"

                    def _fmt_watchlist_volume(value):
                        if not value:
                            return "—"
                        return f"{int(value):,}"

                    def _watchlist_market_cap_and_volume(ticker):
                        try:
                            _ensure_yfinance_cache_location()
                            yt = yf.Ticker(ticker)
                            info = yt.info or {}
                            volume = info.get("volume")
                            if volume is None:
                                try:
                                    fast_info = yt.fast_info
                                    volume = getattr(fast_info, "last_volume", None)
                                    if volume is None and hasattr(fast_info, "get"):
                                        volume = fast_info.get("last_volume")
                                except Exception:
                                    volume = None
                            return info.get("marketCap"), volume
                        except Exception:
                            return None, None

                    rows = []
                    for tk in tickers_tuple:
                        d = get_stock_data(tk)
                        if d.get("error"):
                            rows.append({
                                "Ticker": tk,
                                "Price": "—",
                                "Day%": "—",
                                "Market Cap": "—",
                                "Volume": "—",
                                "52W High": "—",
                                "52W Low": "—",
                                "RSI": "—",
                            })
                            continue
                        p = d["price"]
                        m = d["momentum"]
                        market_cap, volume = _watchlist_market_cap_and_volume(tk)
                        rows.append({
                            "Ticker": tk,
                            "Price": f"${p['current']:,.2f}" if p["current"] else "—",
                            "Day%": f"{p['day_change_pct']:+.2f}%" if p["day_change_pct"] is not None else "—",
                            "Market Cap": _fmt_watchlist_market_cap(market_cap),
                            "Volume": _fmt_watchlist_volume(volume),
                            "52W High": f"${p['week_52_high']:,.2f}" if p["week_52_high"] else "—",
                            "52W Low": f"${p['week_52_low']:,.2f}" if p["week_52_low"] else "—",
                            "RSI": f"{m['rsi_14']:.1f}" if m["rsi_14"] is not None else "—",
                        })
                    return rows

                with st.spinner("Loading watchlist prices…"):
                    summary_rows = _wl_summary(tuple(wl_tickers))

                if summary_rows:
                    st.dataframe(_pd.DataFrame(summary_rows), width='stretch', hide_index=True)

    _render_stock_tracker_sidebar_watchlist()

    sd = st.session_state.stock_data
    if sd is None:
        st.info("Enter a ticker symbol above to get started.")
        st.stop()

    if sd.get("error"):
        st.error(sd["error"])
        st.stop()

    price = sd["price"]
    mom   = sd["momentum"]
    comp  = sd["company"]

    # Helper: coloured pill badge
    def _pill(label, ok):
        if ok is None:
            color, bg, sym = "#888", "#f5f5f5", "—"
        elif ok:
            color, bg, sym = "#2d7a2d", "#e8f5e9", "✓"
        else:
            color, bg, sym = "#c0392b", "#fdecea", "✗"
        return (
            f'<span style="background:{bg};color:{color};padding:5px 12px;'
            f'border-radius:20px;font-size:13px;font-weight:600;'
            f'display:inline-block;margin:2px 4px 6px 0">'
            f'{label} {sym}</span>'
        )

    # Helper: format market cap (stored in millions)
    def _fmt_mc(mc):
        if mc is None:
            return "—"
        if mc >= 1_000_000:
            return f"${mc / 1_000_000:.2f}T"
        if mc >= 1_000:
            return f"${mc / 1_000:.2f}B"
        return f"${mc:,.0f}M"

    def _fmt_short_pct(value):
        return f"{float(value) * 100:.1f}%" if value is not None else "—"

    def _fmt_short_ratio(value):
        return f"{float(value):.1f} days" if value is not None else "—"

    def _fmt_compact_int(value):
        if value is None:
            return "—"
        value = float(value)
        if abs(value) >= 1_000_000_000_000:
            return f"{value / 1_000_000_000_000:.2f}T"
        if abs(value) >= 1_000_000_000:
            return f"{value / 1_000_000_000:.1f}B"
        if abs(value) >= 1_000_000:
            return f"{value / 1_000_000:.1f}M"
        if abs(value) >= 1_000:
            return f"{value / 1_000:.1f}K"
        return f"{value:,.0f}"

    def _fmt_shares_outstanding(value):
        if value is None:
            return "—"
        value = float(value)
        if abs(value) >= 1_000_000_000_000:
            return f"{value / 1_000_000_000_000:.2f}T"
        if abs(value) >= 1_000_000_000:
            return f"{value / 1_000_000_000:.1f}B"
        if abs(value) >= 1_000_000:
            return f"{value / 1_000_000:.1f}M"
        return f"{value:,.0f}"

    def _fmt_month_year(date_text):
        if not date_text:
            return ""
        try:
            from datetime import datetime as _dt
            return _dt.strptime(str(date_text)[:10], "%Y-%m-%d").strftime("%b %Y")
        except Exception:
            return str(date_text)

    def _fmt_earnings_number(value, prefix=""):
        if value is None:
            return "—"
        try:
            value = float(value)
        except Exception:
            return "—"
        if abs(value) >= 1_000_000_000_000:
            return f"{prefix}{value / 1_000_000_000_000:.2f}T"
        if abs(value) >= 1_000_000_000:
            return f"{prefix}{value / 1_000_000_000:.2f}B"
        if abs(value) >= 1_000_000:
            return f"{prefix}{value / 1_000_000:.2f}M"
        return f"{prefix}{value:,.2f}"

    def _fmt_financial_snapshot_value(value):
        if value is None:
            return "—"
        try:
            value = float(value)
        except Exception:
            return "—"
        sign = "-" if value < 0 else ""
        value = abs(value)
        if value >= 1_000_000_000_000:
            return f"{sign}${value / 1_000_000_000_000:.2f}T"
        if value >= 1_000_000_000:
            return f"{sign}${value / 1_000_000_000:.2f}B"
        if value >= 1_000_000:
            return f"{sign}${value / 1_000_000:.2f}M"
        return f"{sign}${value:,.0f}"

    def _fmt_financial_margin(value):
        if value is None:
            return "—"
        try:
            return f"{float(value) * 100:.1f}%"
        except Exception:
            return "—"

    def _earnings_badge(actual, estimated):
        if actual is None or estimated is None:
            return '<span style="color:#94A3B8;font-size:12px">—</span>'
        try:
            actual = float(actual)
            estimated = float(estimated)
        except Exception:
            return '<span style="color:#94A3B8;font-size:12px">—</span>'
        if actual > estimated:
            label, color, bg = "Beat", "#2d7a2d", "#e8f5e9"
        elif actual < estimated:
            label, color, bg = "Miss", "#c0392b", "#fdecea"
        else:
            label, color, bg = "In Line", "#7d5a00", "#fffbea"
        return (
            f'<span style="background:{bg};color:{color};padding:2px 8px;'
            f'border-radius:999px;font-size:11px;font-weight:700">{label}</span>'
        )

    def _fmt_surprise_pct(actual, estimated):
        if actual is None or estimated in (None, 0):
            return "—"
        try:
            actual = float(actual)
            estimated = float(estimated)
            if estimated == 0:
                return "—"
            return f"{(actual - estimated) / abs(estimated) * 100:+.1f}%"
        except Exception:
            return "—"

    def _short_interest_badge(short_pct):
        if short_pct is None:
            return ("—", "#888", "#f5f5f5")
        short_pct = float(short_pct)
        if short_pct < 0.05:
            return ("LOW", "#2d7a2d", "#e8f5e9")
        if short_pct <= 0.15:
            return ("ELEVATED", "#7d5a00", "#fffbea")
        return ("HIGH", "#c0392b", "#fdecea")

    @st.cache_data(ttl=900, show_spinner=False)
    def _get_short_interest(ticker: str) -> dict:
        empty = {
            "short_percent_of_float": None,
            "short_ratio": None,
            "shares_short": None,
        }
        if not ticker or not ticker.strip():
            return empty
        try:
            _ensure_yfinance_cache_location()
            info = yf.Ticker(ticker.strip().upper()).info or {}
            return {
                "short_percent_of_float": info.get("shortPercentOfFloat"),
                "short_ratio": info.get("shortRatio"),
                "shares_short": info.get("sharesShort"),
            }
        except Exception:
            return empty

    # --- SECTION 1: Price & Momentum ---
    cur_ticker = st.session_state.get("st_current_ticker", "")
    cur_exchange = _fiscal_ai_exchange_for_ticker(cur_ticker) if cur_ticker else "NASDAQ"

    def _fiscal_session_cached(function_name, fetcher):
        cache_key = f"fiscal_{function_name}_{cur_ticker}"
        if cache_key not in st.session_state:
            st.session_state[cache_key] = fetcher()
        return st.session_state[cache_key]

    company_name = comp["name"] or cur_ticker or st_ticker.upper()
    logo_bytes = None
    if cur_ticker:
        logo_bytes = _fiscal_session_cached(
            "get_company_logo",
            lambda: get_company_logo(cur_ticker, cur_exchange),
        )

    cur = price["current"]
    day_pct = price["day_change_pct"]
    header_logo_col, header_identity_col, header_analyst_col = st.columns([1, 2, 2])
    with header_logo_col:
        if logo_bytes:
            st.image(io.BytesIO(logo_bytes), width=48)
    with header_identity_col:
        st.markdown(f"## **{company_name}**")
        sector_parts = [p for p in [comp.get("sector"), comp.get("industry")] if p]
        if sector_parts:
            for sector_part in sector_parts:
                st.badge(sector_part)
        desc = comp["description"]
        if desc:
            short_desc = desc[:200] + "..."
            st.markdown(short_desc)
            if len(desc) > 200:
                with st.expander("Read more"):
                    st.markdown(desc)
    with header_analyst_col:
        analyst = sd["analyst"]
        rec = (analyst["recommendation"] or "").upper()
        target = analyst["target_price"]
        upside = analyst["upside_pct"]
        num_an = analyst["num_analysts"]

        if rec in ("BUY", "STRONG_BUY", "STRONG BUY"):
            rec_color, rec_bg = "#2d7a2d", "#e8f5e9"
        elif rec in ("SELL", "STRONG_SELL", "STRONG SELL", "UNDERPERFORM"):
            rec_color, rec_bg = "#c0392b", "#fdecea"
        else:
            rec_color, rec_bg = "#7d5a00", "#fffbea"

        if rec:
            st.markdown(
                f'<span style="background:{rec_bg};color:{rec_color};padding:6px 18px;'
                f'border-radius:20px;font-size:15px;font-weight:700">'
                f'{rec.replace("_", " ").title()}</span>',
                unsafe_allow_html=True,
            )
            st.write("")

        ac1, ac2, ac3 = st.columns(3)
        with ac1:
            st.metric("Price Target", f"${target:,.2f}" if target else "—")
        with ac2:
            if upside is not None:
                st.metric("Upside / Downside", f"{upside:+.1f}%",
                          delta=f"{upside:+.1f}%")
            else:
                st.metric("Upside / Downside", "—")
        with ac3:
            st.metric("Analysts Covering", str(num_an) if num_an else "—")

        # Current vs target bar
        if cur and target:
            lo_b = min(cur, target) * 0.92
            hi_b = max(cur, target) * 1.08
            span = hi_b - lo_b or 1
            c_pct = (cur - lo_b) / span * 100
            t_pct = (target - lo_b) / span * 100
            fill_left = min(c_pct, t_pct)
            fill_width = abs(t_pct - c_pct)
            st.markdown(
                f'<div style="margin:10px 0 4px">'
                f'<div style="background:#e8e8e8;border-radius:6px;height:10px;position:relative">'
                f'<div style="position:absolute;left:{fill_left:.0f}%;width:{fill_width:.0f}%;'
                f'height:100%;background:#7cb9e8;border-radius:6px"></div>'
                f'<div style="position:absolute;left:{c_pct:.0f}%;transform:translateX(-50%);'
                f'width:3px;height:100%;background:#333;border-radius:2px" title="Current"></div>'
                f'<div style="position:absolute;left:{t_pct:.0f}%;transform:translateX(-50%);'
                f'width:3px;height:100%;background:#2d7a2d;border-radius:2px" title="Target"></div>'
                f'</div>'
                f'<div style="font-size:11px;color:#888;margin-top:4px">'
                f'&#9632; Current: ${cur:,.2f} &nbsp;&nbsp; '
                f'<span style="color:#2d7a2d">&#9632;</span> Target: ${target:,.2f}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.divider()

    price_metrics_col, price_chart_col = st.columns([1, 1])
    with price_metrics_col:
        st.markdown("#### Price & Momentum")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric(
                "Current Price",
                f"${cur:,.2f}" if cur else "—",
                delta=f"{day_pct:+.2f}%" if day_pct is not None else None,
            )
        with c2:
            hi52 = price["week_52_high"]
            pct_hi = price["pct_from_52_high"]
            st.metric(
                "52W High",
                f"${hi52:,.2f}" if hi52 else "—",
                delta=f"{pct_hi:.1f}% from high" if pct_hi is not None else None,
                delta_color="inverse",
            )
        with c3:
            lo52 = price["week_52_low"]
            pct_lo = price["pct_from_52_low"]
            st.metric(
                "52W Low",
                f"${lo52:,.2f}" if lo52 else "—",
                delta=f"{pct_lo:.1f}% from low" if pct_lo is not None else None,
            )
        with c4:
            st.metric("Market Cap", _fmt_mc(comp["market_cap"]))

        # Moving average badges
        st.markdown("**Moving Averages**")
        badges_html = (
            _pill("Above 50MA",  mom["above_50ma"]) +
            _pill("Above 200MA", mom["above_200ma"])
        )
        gc = mom["golden_cross"]
        if gc is not None:
            badges_html += _pill("Golden Cross" if gc else "Death Cross", gc)
        st.markdown(badges_html, unsafe_allow_html=True)

        # RSI
        rsi = mom["rsi_14"]
        if rsi is not None:
            if rsi < 30:
                rsi_label, rsi_color = "Oversold", "#2d7a2d"
                rsi_bg = "#e8f5e9"
            elif rsi < 70:
                rsi_label, rsi_color = "Neutral", "#555"
                rsi_bg = "#f5f5f5"
            else:
                rsi_label, rsi_color = "Overbought", "#c0392b"
                rsi_bg = "#fdecea"
            st.markdown(
                f'<div style="margin:8px 0 0 0">'
                f'<span style="font-weight:600">RSI (14):</span> {rsi:.1f} &nbsp;'
                f'<span style="background:{rsi_bg};color:{rsi_color};padding:3px 10px;'
                f'border-radius:12px;font-size:13px;font-weight:600">{rsi_label}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
    with price_chart_col:
        # --- SECTION 1b: Price Chart ---
        hist_df = sd.get("hist")
        if hist_df is not None and not hist_df.empty:
            st.markdown("#### 📈 Price Chart (1 Year)")

            closes = hist_df["Close"]
            ma50 = closes.rolling(50).mean()
            ma200 = closes.rolling(200).mean()
            dates = hist_df.index

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=dates, y=closes,
                name="Close", line=dict(color="#1f77b4", width=2),
            ))
            if len(closes) >= 50:
                fig.add_trace(go.Scatter(
                    x=dates, y=ma50,
                    name="50-Day MA", line=dict(color="#ff7f0e", width=1.5, dash="dot"),
                ))
            if len(closes) >= 200:
                fig.add_trace(go.Scatter(
                    x=dates, y=ma200,
                    name="200-Day MA", line=dict(color="#d62728", width=1.5, dash="dash"),
                ))
            fig.update_layout(
                height=320, margin=dict(l=0, r=0, t=10, b=0),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                xaxis_rangeslider_visible=False,
                yaxis_tickprefix="$",
            )
            st.plotly_chart(fig, width='stretch')

            # Volume bar chart
            if "Volume" in hist_df.columns:
                vol_fig = go.Figure()
                vol_fig.add_trace(go.Bar(
                    x=dates, y=hist_df["Volume"],
                    name="Volume", marker_color="#aec7e8", opacity=0.7,
                ))
                vol_fig.update_layout(
                    height=120, margin=dict(l=0, r=0, t=0, b=0),
                    showlegend=False,
                    yaxis=dict(tickformat=".2s"),
                )
                st.plotly_chart(vol_fig, width='stretch')

    st.divider()

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📡 Technicals",
        "📊 Fundamentals",
        "📈 Earnings",
        "🧩 Segments",
        "🗞️ News & Sentiment",
        "📂 Filings",
    ])

    with tab1:
        # --- SECTION 1a: Short Interest ---
        short_interest = _get_short_interest(cur_ticker)
        short_pct = short_interest.get("short_percent_of_float")
        short_ratio = short_interest.get("short_ratio")
        shares_short = short_interest.get("shares_short")
        si_badge, si_color, si_bg = _short_interest_badge(short_pct)
        st.markdown(
            f'''
            <div style="background:linear-gradient(135deg,#252D40 0%,#1E2840 100%);
                        border:0.5px solid rgba(255,255,255,0.08);border-radius:12px;
                        box-shadow:0 4px 24px rgba(0,0,0,0.3),0 1px 0 rgba(255,255,255,0.04) inset;
                        padding:0.85rem 1rem;margin:1rem 0 0.25rem">
                <div style="color:#F1F5F9;font-size:15px;font-weight:600;margin-bottom:0.85rem">
                    Short Interest
                </div>
                <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:0.75rem">
                    <div>
                        <div style="font-size:10px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:#64748B">
                            % of Float Shorted
                        </div>
                        <div style="font-size:24px;font-weight:600;color:#F1F5F9;letter-spacing:-0.02em">
                            {escape(_fmt_short_pct(short_pct))}
                        </div>
                    </div>
                    <div>
                        <div style="font-size:10px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:#64748B">
                            Days to Cover
                        </div>
                        <div style="font-size:24px;font-weight:600;color:#F1F5F9;letter-spacing:-0.02em">
                            {escape(_fmt_short_ratio(short_ratio))}
                        </div>
                    </div>
                    <div>
                        <div style="font-size:10px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:#64748B">
                            Shares Short
                        </div>
                        <div style="font-size:24px;font-weight:600;color:#F1F5F9;letter-spacing:-0.02em">
                            {escape(_fmt_compact_int(shares_short))}
                        </div>
                    </div>
                </div>
                <div style="margin-top:0.85rem">
                    <span style="background:{si_bg};color:{si_color};padding:5px 12px;
                                 border-radius:20px;font-size:13px;font-weight:600;
                                 display:inline-block;margin:2px 4px 0 0">
                        {escape(si_badge)}
                    </span>
                </div>
            </div>
            ''',
            unsafe_allow_html=True,
        )

    with tab4:
        segments = _fiscal_session_cached(
            "get_segments_with_values",
            lambda: get_segments_with_values(cur_ticker, cur_exchange),
        )
        if segments:
            chart_segments = sorted(segments, key=lambda row: row["value"])
            labels = [row["name"] for row in chart_segments]
            values = [row["value"] for row in chart_segments]
            text = [_fmt_mc(row["value"] / 1_000_000) for row in chart_segments]

            fig = go.Figure(
                go.Bar(
                    x=values,
                    y=labels,
                    orientation="h",
                    text=text,
                    textposition="auto",
                    marker=dict(color="#378ADD"),
                    hovertemplate="%{y}<br>%{text}<extra></extra>",
                )
            )
            fig.update_layout(
                height=max(260, 42 * len(chart_segments)),
                margin=dict(l=8, r=8, t=8, b=8),
                xaxis_title=None,
                yaxis_title=None,
                showlegend=False,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#CBD5E1"),
            )
            fig.update_xaxes(showgrid=True, gridcolor="rgba(148,163,184,0.18)")
            fig.update_yaxes(showgrid=False)
            st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})
            period = segments[0].get("period")
            period_text = f" · {period}" if period else ""
            st.markdown(
                f'<div style="color:#94A3B8;font-size:12px;margin-top:-0.5rem">'
                f'Source: Fiscal AI{period_text}</div>',
                unsafe_allow_html=True,
            )

    with tab3:
        # --- SECTION 3: Earnings Tracker ---
        earnings = sd["earnings"]
        next_date = earnings["next_earnings_date"]

        if next_date:
            st.markdown(f"**Next Earnings Date:** {next_date}")
            try:
                from datetime import datetime as _dt
                nd = _dt.strptime(next_date[:10], "%Y-%m-%d").date()
                days_until = (nd - _date.today()).days
                if 0 <= days_until <= 30:
                    st.warning(
                        f"Earnings approaching in {days_until} day{'s' if days_until != 1 else ''}"
                        " — elevated volatility risk."
                    )
            except Exception:
                pass
        else:
            st.caption("Next earnings date not available.")

        e1, e2 = st.columns(2)
        with e1:
            st.markdown("**EPS**")
            eps_est = earnings["eps_estimate"]
            eps_act = earnings["eps_actual_last"]
            surp = earnings["earnings_surprise_pct"]
            st.markdown(f"Estimate: **{'${:.2f}'.format(eps_est) if eps_est is not None else '—'}**")
            st.markdown(f"Last Actual: **{'${:.2f}'.format(eps_act) if eps_act is not None else '—'}**")
            if surp is not None:
                s_sign = "+" if surp >= 0 else ""
                s_label = "Beat" if surp >= 0 else "Miss"
                s_color = "#2d7a2d" if surp >= 0 else "#c0392b"
                s_bg = "#e8f5e9" if surp >= 0 else "#fdecea"
                st.markdown(
                    f'Last Quarter: <span style="background:{s_bg};color:{s_color};'
                    f'padding:2px 8px;border-radius:10px;font-size:13px;font-weight:600">'
                    f'{s_label} {s_sign}{surp:.1f}%</span>',
                    unsafe_allow_html=True,
                )
        with e2:
            st.markdown("**Revenue**")
            rev = earnings["revenue_estimate"]
            if rev:
                if rev >= 1_000_000_000_000:
                    rev_str = f"${rev / 1_000_000_000_000:.2f}T"
                elif rev >= 1_000_000_000:
                    rev_str = f"${rev / 1_000_000_000:.2f}B"
                elif rev >= 1_000_000:
                    rev_str = f"${rev / 1_000_000:.1f}M"
                else:
                    rev_str = f"${rev:,.0f}"
            else:
                rev_str = "—"
            st.metric("Revenue (TTM)", rev_str)

    with tab2:
        # --- SECTION 4: Valuation Metrics ---
        st.markdown("#### Valuation Metrics")
        val = sd["valuation"]

        def _val_note(key, v):
            if v is None:
                return ""
            if key == "pe_trailing":
                if v > 30: return "Premium valuation"
                if v < 15: return "Value territory"
                return "Fairly valued"
            if key == "pe_forward":
                if v > 25: return "Premium valuation"
                if v < 12: return "Value territory"
                return "Fairly valued"
            if key == "peg_ratio":
                if v > 2:  return "Expensive relative to growth"
                if v < 1:  return "Attractive relative to growth"
                return ""
            return ""

        val_items = [
            ("P/E (Trailing)", "pe_trailing",    val["pe_trailing"]),
            ("P/E (Forward)",  "pe_forward",     val["pe_forward"]),
            ("PEG Ratio",      "peg_ratio",      val["peg_ratio"]),
            ("EV/EBITDA",      "ev_ebitda",      val["ev_ebitda"]),
            ("Price / Book",   "price_to_book",  val["price_to_book"]),
            ("Price / Sales",  "price_to_sales", val["price_to_sales"]),
        ]
        vr1 = st.columns(3)
        vr2 = st.columns(3)
        for i, (label, key, v) in enumerate(val_items):
            col = vr1[i] if i < 3 else vr2[i - 3]
            with col:
                v_str = f"{v:.2f}x" if v is not None else "—"
                note  = _val_note(key, v)
                st.metric(label, v_str)
                if note:
                    st.caption(note)

        fiscal_ratio_values = _fiscal_session_cached(
            "get_ratios_with_values",
            lambda: get_ratios_with_values(cur_ticker, cur_exchange),
        )
        fiscal_ratio_map = {
            "P/E Ratio": "pe_ratio",
            "EV/EBITDA": "ev_ebitda",
            "P/B Ratio": "price_to_book",
            "P/S Ratio": "price_to_sales",
            "Gross Margin": "gross_margin",
            "Operating Margin": "operating_margin",
            "Net Margin": "net_margin",
        }
        fiscal_ratios = {
            label: fiscal_ratio_values[key]
            for label, key in fiscal_ratio_map.items()
            if isinstance(fiscal_ratio_values, dict) and key in fiscal_ratio_values
        }
        if fiscal_ratios:
            st.markdown("##### Institutional Ratios")

            def _fmt_fiscal_ratio(label, value):
                try:
                    value = float(value)
                except Exception:
                    return "—"
                if "Margin" in label:
                    return f"{value * 100:.2f}%"
                return f"{value:.2f}"

            ratio_items = list(fiscal_ratios.items())
            ratio_cols = st.columns(2)
            for idx, (label, value) in enumerate(ratio_items):
                with ratio_cols[idx % 2]:
                    st.metric(label, _fmt_fiscal_ratio(label, value))
            st.markdown(
                '<div style="color:#94A3B8;font-size:12px;margin-top:-0.25rem">'
                'Source: Fiscal AI</div>',
                unsafe_allow_html=True,
            )

        shares_outstanding = _fiscal_session_cached(
            "get_shares_outstanding",
            lambda: get_shares_outstanding(cur_ticker, cur_exchange),
        )
        if shares_outstanding:
            shares_value = shares_outstanding.get("shares_outstanding")
            share_class = shares_outstanding.get("share_class") or "Shares"
            share_date = _fmt_month_year(shares_outstanding.get("date"))
            subtitle_parts = [part for part in [share_class, share_date] if part]
            st.markdown(
                f'''
                <div style="border:1px solid rgba(148,163,184,0.22);border-radius:8px;
                            padding:0.85rem 1rem;margin:0.85rem 0;background:rgba(15,23,42,0.28);
                            max-width:360px">
                    <div style="font-size:12px;font-weight:700;color:#94A3B8;
                                text-transform:uppercase;letter-spacing:0.05em">
                        Shares Outstanding
                    </div>
                    <div style="font-size:28px;font-weight:700;color:#F1F5F9;margin-top:0.25rem">
                        {escape(_fmt_shares_outstanding(shares_value))}
                    </div>
                    <div style="font-size:12px;color:#94A3B8;margin-top:0.2rem">
                        {escape(" · ".join(subtitle_parts))}
                    </div>
                    <div style="font-size:12px;color:#94A3B8;margin-top:0.65rem">
                        Source: Fiscal AI
                    </div>
                </div>
                ''',
                unsafe_allow_html=True,
            )

        adjusted_metrics = _fiscal_session_cached(
            "get_adjusted_metrics_with_values",
            lambda: get_adjusted_metrics_with_values(cur_ticker, cur_exchange),
        )
        if adjusted_metrics:
            st.markdown("##### Adjusted Metrics")

            def _fmt_adjusted_metric(label, value):
                try:
                    value = float(value)
                except Exception:
                    return "—"
                if "Margin" in label:
                    return f"{value * 100:.2f}%"
                if "EPS" in label:
                    return f"${value:.2f}"
                if abs(value) >= 1_000_000_000_000:
                    return f"${value / 1_000_000_000_000:.2f}T"
                if abs(value) >= 1_000_000_000:
                    return f"${value / 1_000_000_000:.2f}B"
                if abs(value) >= 1_000_000:
                    return f"${value / 1_000_000:.2f}M"
                return f"${value:,.0f}"

            adjusted_items = list(adjusted_metrics.items())
            adjusted_cols = st.columns(2)
            for idx, (label, value) in enumerate(adjusted_items):
                with adjusted_cols[idx % 2]:
                    st.metric(label, _fmt_adjusted_metric(label, value))
            st.markdown(
                '<div style="color:#94A3B8;font-size:12px;margin-top:-0.25rem">'
                'Source: Fiscal AI — Adjusted figures</div>',
                unsafe_allow_html=True,
            )

    with tab5:
        company_news = get_company_news(
            cur_ticker,
            cur_exchange,
            limit=5,
        )
        if company_news:
            st.markdown("##### Latest News")
            for item in company_news:
                news_date = escape(str(item.get("date") or ""))
                category = escape(str(item.get("category") or "News").replace("_", " ").title())
                title = escape(str(item.get("title") or ""))
                url = escape(str(item.get("url") or ""), quote=True)
                summary = escape(str(item.get("summary") or ""))
                summary_html = (
                    f'<div style="color:#94A3B8;font-size:13px;line-height:1.45;margin-top:0.45rem">'
                    f'{summary}</div>'
                    if summary else ""
                )
                st.markdown(
                    f'''
                    <div style="border:1px solid rgba(148,163,184,0.22);border-radius:8px;
                                padding:0.85rem 1rem;margin:0.65rem 0;background:rgba(15,23,42,0.28)">
                        <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.45rem">
                            <span style="color:#94A3B8;font-size:12px">{news_date}</span>
                            <span style="background:#1E3A5F;color:#BFDBFE;border-radius:999px;
                                         padding:2px 8px;font-size:11px;font-weight:700">
                                {category}
                            </span>
                        </div>
                        <a href="{url}" target="_blank" rel="noopener noreferrer"
                           style="color:#F1F5F9;text-decoration:none;font-weight:700;font-size:15px">
                            {title}
                        </a>
                        {summary_html}
                    </div>
                    ''',
                    unsafe_allow_html=True,
                )
            st.markdown(
                '<div style="color:#94A3B8;font-size:12px;margin-top:-0.25rem">'
                'Source: Fiscal AI</div>',
                unsafe_allow_html=True,
            )

        if "polymarket_macro" not in st.session_state:
            st.session_state.polymarket_macro = get_macro_markets()
        polymarket_macro = st.session_state.polymarket_macro
        if polymarket_macro:
            st.markdown("### Prediction Market Intelligence")
            st.caption("Live prediction market probabilities on macro events")

            for market in polymarket_macro:
                probability = float(market.get("probability") or 0.0)
                pct = max(0, min(100, round(probability * 100)))
                question = market.get("question", "")
                url = market.get("url", "")
                volume = float(market.get("volume") or 0.0)

                col1, col2 = st.columns([4, 1])
                with col1:
                    st.markdown(f"**[{question}]({url})**")
                    st.progress(probability)
                with col2:
                    if probability > 0.60:
                        st.success(f"{pct}% Yes")
                    elif probability < 0.40:
                        st.error(f"{pct}% Yes")
                    else:
                        st.warning(f"{pct}% Yes")
                st.caption(f"Volume: ${volume / 1_000_000:.1f}M")
                st.divider()

            st.caption("Source: Polymarket · Prediction Market Intelligence")

    with tab3:
        fmp_earnings_key = f"fmp_earnings_{cur_ticker}"
        if fmp_earnings_key not in st.session_state:
            st.session_state[fmp_earnings_key] = get_fmp_earnings_calendar(cur_ticker)
        fmp_earnings = st.session_state[fmp_earnings_key]
        if fmp_earnings:
            rows_html = []
            for row in fmp_earnings:
                eps_actual = row.get("epsActual")
                eps_estimated = row.get("epsEstimated")
                rev_actual = row.get("revenueActual")
                rev_estimated = row.get("revenueEstimated")
                rows_html.append(
                    f'''
                    <tr>
                        <td style="padding:0.65rem 0.75rem;border-top:1px solid rgba(148,163,184,0.16);color:#F1F5F9">
                            {escape(str(row.get("date") or "—"))}
                        </td>
                        <td style="padding:0.65rem 0.75rem;border-top:1px solid rgba(148,163,184,0.16);color:#F1F5F9">
                            <div>{escape(_fmt_earnings_number(eps_actual, "$"))} vs {escape(_fmt_earnings_number(eps_estimated, "$"))}</div>
                            <div style="margin-top:0.25rem">{_earnings_badge(eps_actual, eps_estimated)}</div>
                        </td>
                        <td style="padding:0.65rem 0.75rem;border-top:1px solid rgba(148,163,184,0.16);color:#F1F5F9">
                            <div>{escape(_fmt_earnings_number(rev_actual, "$"))} vs {escape(_fmt_earnings_number(rev_estimated, "$"))}</div>
                            <div style="margin-top:0.25rem">{_earnings_badge(rev_actual, rev_estimated)}</div>
                        </td>
                        <td style="padding:0.65rem 0.75rem;border-top:1px solid rgba(148,163,184,0.16);color:#F1F5F9">
                            {escape(_fmt_surprise_pct(eps_actual, eps_estimated))}
                        </td>
                    </tr>
                    '''
                )
            st.markdown("##### Earnings History")
            table_html = (
                '<div style="border:1px solid rgba(148,163,184,0.22);border-radius:8px;'
                'margin:0.65rem 0;background:rgba(15,23,42,0.28);overflow-x:auto">'
                '<table style="width:100%;border-collapse:collapse;font-size:13px">'
                '<thead><tr>'
                '<th style="text-align:left;padding:0.65rem 0.75rem;color:#94A3B8;font-size:11px;text-transform:uppercase;letter-spacing:0.05em">Date</th>'
                '<th style="text-align:left;padding:0.65rem 0.75rem;color:#94A3B8;font-size:11px;text-transform:uppercase;letter-spacing:0.05em">EPS Actual vs Estimated</th>'
                '<th style="text-align:left;padding:0.65rem 0.75rem;color:#94A3B8;font-size:11px;text-transform:uppercase;letter-spacing:0.05em">Revenue Actual vs Estimated</th>'
                '<th style="text-align:left;padding:0.65rem 0.75rem;color:#94A3B8;font-size:11px;text-transform:uppercase;letter-spacing:0.05em">EPS Surprise %</th>'
                '</tr></thead>'
                f'<tbody>{"".join(rows_html)}</tbody>'
                '</table></div>'
            )
            st.markdown(table_html, unsafe_allow_html=True)
            st.caption("Source: Financial Modeling Prep")

    with tab2:
        fmp_financials_key = f"fmp_financials_{cur_ticker}"
        if fmp_financials_key not in st.session_state:
            _fmp_income = get_fmp_income_statement(cur_ticker)
            _fmp_balance = get_fmp_balance_sheet(cur_ticker)
            _fmp_cash_flow = get_fmp_cash_flow(cur_ticker)
            st.session_state[fmp_financials_key] = (
                {
                    "income": _fmp_income,
                    "balance": _fmp_balance,
                    "cash_flow": _fmp_cash_flow,
                }
                if _fmp_income and _fmp_balance and _fmp_cash_flow
                else None
            )
        fmp_financials = st.session_state[fmp_financials_key]
        if fmp_financials:
            income = fmp_financials["income"]
            balance = fmp_financials["balance"]
            cash_flow = fmp_financials["cash_flow"]
            fiscal_year = (
                income.get("fiscalYear")
                or balance.get("fiscalYear")
                or cash_flow.get("fiscalYear")
            )
            title_suffix = f" (FY{fiscal_year})" if fiscal_year else ""
            st.markdown(f"##### Financial Snapshot{title_suffix}")
            income_col, balance_col, cash_flow_col = st.columns(3)
            with income_col:
                st.markdown("**Income**")
                st.metric("Revenue", _fmt_financial_snapshot_value(income.get("revenue")))
                st.metric(
                    "Gross Profit",
                    _fmt_financial_snapshot_value(income.get("grossProfit")),
                    delta=f"Gross Margin {_fmt_financial_margin(income.get('grossProfitRatio'))}",
                    delta_color="off",
                )
                st.metric(
                    "Operating Income",
                    _fmt_financial_snapshot_value(income.get("operatingIncome")),
                    delta=f"Operating Margin {_fmt_financial_margin(income.get('operatingIncomeRatio'))}",
                    delta_color="off",
                )
                st.metric(
                    "Net Income",
                    _fmt_financial_snapshot_value(income.get("netIncome")),
                    delta=f"Net Margin {_fmt_financial_margin(income.get('netIncomeRatio'))}",
                    delta_color="off",
                )
                st.metric("EBITDA", _fmt_financial_snapshot_value(income.get("ebitda")))
            with balance_col:
                st.markdown("**Balance Sheet**")
                st.metric("Cash", _fmt_financial_snapshot_value(balance.get("cashAndCashEquivalents")))
                st.metric("Total Assets", _fmt_financial_snapshot_value(balance.get("totalAssets")))
                st.metric("Total Debt", _fmt_financial_snapshot_value(balance.get("totalDebt")))
                st.metric(
                    "Shareholders Equity",
                    _fmt_financial_snapshot_value(balance.get("totalStockholdersEquity")),
                )
            with cash_flow_col:
                st.markdown("**Cash Flow**")
                st.metric(
                    "Operating Cash Flow",
                    _fmt_financial_snapshot_value(cash_flow.get("operatingCashFlow")),
                )
                st.metric(
                    "Capital Expenditure",
                    _fmt_financial_snapshot_value(cash_flow.get("capitalExpenditure")),
                )
                st.metric("Free Cash Flow", _fmt_financial_snapshot_value(cash_flow.get("freeCashFlow")))
                st.metric("Dividends Paid", _fmt_financial_snapshot_value(cash_flow.get("dividendsPaid")))
            st.caption("Source: Financial Modeling Prep")

    with tab6:
        company_filings = _fiscal_session_cached(
            "get_company_filings",
            lambda: get_company_filings(cur_ticker, cur_exchange, limit=5),
        )
        if company_filings:
            st.markdown("##### Recent Filings")
            for filing in company_filings:
                filing_type = escape(str(filing.get("type") or "Filing"))
                filing_date = escape(str(filing.get("date") or ""))
                description = escape(str(filing.get("description") or ""))
                filing_url = escape(str(filing.get("url") or ""), quote=True)
                link_html = (
                    f'<a href="{filing_url}" target="_blank" rel="noopener noreferrer" '
                    f'style="color:#93C5FD;text-decoration:none;font-weight:700">View filing</a>'
                    if filing_url else ""
                )
                st.markdown(
                    f'''
                    <div style="border:1px solid rgba(148,163,184,0.22);border-radius:8px;
                                padding:0.85rem 1rem;margin:0.65rem 0;background:rgba(15,23,42,0.28)">
                        <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.45rem">
                            <span style="background:#1E3A5F;color:#BFDBFE;border-radius:999px;
                                         padding:2px 8px;font-size:11px;font-weight:700">
                                {filing_type}
                            </span>
                            <span style="color:#94A3B8;font-size:12px">{filing_date}</span>
                        </div>
                        <div style="color:#F1F5F9;font-size:15px;font-weight:700;margin-bottom:0.35rem">
                            {description}
                        </div>
                        {link_html}
                    </div>
                    ''',
                    unsafe_allow_html=True,
                )
            st.markdown(
                '<div style="color:#94A3B8;font-size:12px;margin-top:-0.25rem">'
                'Source: Fiscal AI</div>',
                unsafe_allow_html=True,
            )

    st.stop()


# --- Single Analysis page ----------------------------------------------
if page != "Single Analysis":
    st.stop()

if not API_KEY:
    st.error("ANTHROPIC_API_KEY not found. Add it to your .env file and restart the app.")
    st.stop()

st.markdown("""
<style>
button[kind="secondary"] { background: none; border: none; color: #4a9eda; font-size: 0.8rem; padding: 0; }
</style>
""", unsafe_allow_html=True)

# --- Session state — persists results across Streamlit reruns ----------
if "financial_data" not in st.session_state:
    st.session_state.financial_data      = None
    st.session_state.summary_data        = None
    st.session_state.bear_bull_data      = None
    st.session_state.dashboard_data      = None
    st.session_state.mda_sentiment       = None
    st.session_state.market_data         = None
    st.session_state.excel_bytes         = None
    st.session_state.last_filename       = None
    st.session_state.resolved_ticker     = None
    st.session_state.dcf_result          = None
    st.session_state.cache_hit           = False
    st.session_state.loaded_from_library = False
    st.session_state.loaded_from_edgar   = False
    st.session_state.loaded_from_sedar   = False
    st.session_state.loaded_from_quick   = False
    st.session_state.analysis_loaded_from_cache = False
    st.session_state.uploader_key        = 0
    LIBRARY_PDFS_DIR.mkdir(parents=True, exist_ok=True)

if "summary_data" not in st.session_state:
    st.session_state.summary_data = None

if "market_data" not in st.session_state:
    st.session_state.market_data = None

# --- Main area ---------------------------------------------------------
quick_analysis_slot = st.container()

with st.expander("Fetch from SEC EDGAR / SEDAR+", expanded=False):
    _edgar_tab, _sedar_tab = st.tabs(["SEC EDGAR", "SEDAR+"])

    with _edgar_tab:
        st.caption("Fetch full 10-K/10-Q filings from SEC EDGAR including MD&A, Risk Factors, and financial statements.")
        _edgar_query = st.text_input("Search by company name or ticker", placeholder="e.g. AAPL, Apple", key="edgar_ticker")
        if st.button("Search", type="primary", width='stretch', key="edgar_fetch_btn"):
            st.session_state["edgar_filings"] = []
            st.session_state["edgar_company_matches"] = []
            st.session_state.pop("edgar_yf_matches", None)
            st.session_state.loaded_from_edgar = False
            _query = _edgar_query.strip()
            _tk = _query.upper()
            if not _query:
                st.warning("Enter a company name or ticker first.")
            elif re.fullmatch(r"[A-Z]{1,5}", _tk):
                with st.spinner(f"Finding SEC filings for {_tk}..."):
                    _cik = get_cik(_tk)
                    _filings = get_recent_filings(_cik) if _cik else []
                if _cik and _filings:
                    st.session_state["edgar_cik"] = _cik
                    st.session_state["edgar_company_name"] = _tk
                    st.session_state["edgar_selected_ticker"] = _tk
                    st.session_state["edgar_filings"] = _filings
                    st.session_state["edgar_loaded_accession"] = None
                    st.success(f"Found {len(_filings)} recent 10-K filing(s) for {_tk}.")
                elif _cik:
                    st.error(f"No recent 10-K filings found for {_tk}.")
                else:
                    with st.spinner(f"Searching SEC EDGAR for {_query}..."):
                        _matches = search_edgar_companies(_query)
                    if not _matches:
                        st.error(f"No SEC EDGAR company results found for '{_query}'.")
                    else:
                        st.session_state["edgar_company_matches"] = _matches
                        st.success(f"Found {len(_matches)} possible match(es). Select one below.")
            else:
                with st.spinner(f"Searching SEC EDGAR for {_query}..."):
                    _matches = search_edgar_companies(_query)
                if not _matches:
                    st.error(f"No SEC EDGAR company results found for '{_query}'. Try a ticker symbol directly, e.g. AAPL.")
                else:
                    st.session_state["edgar_company_matches"] = _matches
                    st.success(f"Found {len(_matches)} possible match(es). Select one below.")

        _edgar_matches = st.session_state.get("edgar_company_matches") or []
        if _edgar_matches:
            _match_labels = [
                row.get("label") or f"{row.get('name') or 'Unknown company'} (CIK {row.get('cik') or 'N/A'})"
                for row in _edgar_matches
            ]
            _selected_company_label = st.selectbox("Matching companies", _match_labels, key="edgar_company_select")
            _selected_company = _edgar_matches[_match_labels.index(_selected_company_label)]
            if st.button("Find Recent 10-K Filings", width='stretch', key="edgar_find_company_filings_btn"):
                _symbol = (_selected_company.get("ticker") or "").upper()
                _company_name = (_selected_company.get("name") or "company").strip()
                _cik = _selected_company.get("cik")
                if not _symbol and _cik:
                    _resolved_symbol = get_ticker_for_cik(_cik)
                    if _resolved_symbol:
                        _symbol = _resolved_symbol
                with st.spinner(f"Finding SEC filings for {_company_name}..."):
                    _filings = get_recent_filings(_cik) if _cik else []
                if not _cik:
                    st.error(f"Could not find a CIK for {_company_name}.")
                elif not _filings:
                    st.error(f"No recent 10-K filings found for {_company_name}.")
                else:
                    st.session_state["edgar_cik"] = _cik
                    st.session_state["edgar_company_name"] = _company_name
                    st.session_state["edgar_selected_ticker"] = _symbol
                    st.session_state["edgar_filings"] = _filings
                    st.session_state["edgar_loaded_accession"] = None
                    st.success(f"Found {len(_filings)} recent 10-K filing(s) for {_company_name}.")

        _edgar_filings = st.session_state.get("edgar_filings") or []
        if _edgar_filings:
            _filing_labels = [
                f"{row.get('form')} filed {row.get('filingDate')} - report {row.get('reportDate')}"
                for row in _edgar_filings
            ]
            _selected_label = st.selectbox("Recent filings", _filing_labels, key="edgar_filing_select")
            _selected_idx = _filing_labels.index(_selected_label)
            _selected_filing = _edgar_filings[_selected_idx]
            _selected_accession = _selected_filing.get("accessionNumber")
            _load_selected = st.button(
                "Load Selected Filing $",
                type="primary",
                width='stretch',
                key="edgar_load_selected_btn",
            )

            if (
                _load_selected
                and _selected_accession
                and st.session_state.get("edgar_loaded_accession") != _selected_accession
            ):
                _tk = _edgar_cache_identifier()
                _company_name = (st.session_state.get("edgar_company_name") or _tk or "company").strip()
                _cik = st.session_state.get("edgar_cik")
                _raw_form_type = str(_selected_filing.get("form") or _selected_filing.get("formType") or "10-K").upper()
                if _raw_form_type.startswith("10-Q"):
                    _form_type = "10-Q"
                else:
                    _form_type = "10-K"
                _filing_cache_path = _edgar_filing_cache_path(_tk, _selected_accession)
                _cached_filing_text = None
                if _filing_cache_path and Path(_filing_cache_path).exists():
                    try:
                        _cached_filing_text = Path(_filing_cache_path).read_text(
                            encoding="utf-8",
                            errors="ignore",
                        )
                    except Exception:
                        _cached_filing_text = None

                with st.spinner("Fetching SEC filing (financials + MD&A + Risk Factors)..."):
                    _edgar_fd = get_edgar_financial_data(_cik, _selected_accession)
                    if _cached_filing_text:
                        _filing_text = _cached_filing_text
                        _filing_result = {"text": _cached_filing_text}
                    else:
                        _filing_result = get_filing_text(_cik, form_type=_form_type)
                        _filing_text = (_filing_result or {}).get("text")
                        if _filing_text and _filing_cache_path:
                            try:
                                safe_write_text(_filing_cache_path, _filing_text)
                            except Exception:
                                pass

                if not _edgar_fd and not _filing_text:
                    st.error("Could not fetch SEC financial data or filing text for that filing.")
                else:
                    if _filing_text:
                        _edgar_text = _filing_text
                    else:
                        _edgar_text = _financial_data_to_text(_edgar_fd)
                    st.session_state.cached_filing_text = _edgar_text
                    _edgar_period = (
                        _analysis_period(_edgar_fd)
                        if _edgar_fd
                        else (_filing_result or {}).get("report_date") or _selected_filing.get("reportDate") or ""
                    )
                    _edgar_context = _get_filing_context(_edgar_text, _tk, _edgar_period)
                    _edgar_text_path = _text_cache_path(_tk, _edgar_period)
                    if _edgar_text_path:
                        try:
                            safe_write_text(_edgar_text_path, _edgar_text)
                        except Exception:
                            _edgar_text_path = None
                    _sec_filing_date = _selected_filing.get("filingDate")
                    _edgar_sd = {"ticker": _tk, "sec_filing_date": _sec_filing_date}
                    _edgar_bb = None
                    _edgar_dd = None
                    with st.spinner("Generating investment signal from SEC data..."):
                        try:
                            _edgar_sd = analyze_summary(
                                _edgar_text, _edgar_fd, API_KEY, model=get_model(), filing_context=_edgar_context
                            )
                            if isinstance(_edgar_sd, dict):
                                _edgar_sd.setdefault("ticker", _tk)
                                _edgar_sd["sec_filing_date"] = _sec_filing_date
                        except Exception as e:
                            st.warning(f"Investment signal could not be generated: {e}.")
                    with st.spinner("Generating bull/bear case from SEC data..."):
                        try:
                            _edgar_bb = analyze_bear_bull(_edgar_text, API_KEY, model=get_model(), filing_context=_edgar_context)
                        except Exception as e:
                            st.warning(f"Bull/bear case could not be generated: {e}.")
                    with st.spinner("Generating dashboard insights from SEC data..."):
                        try:
                            _edgar_dd = analyze_dashboard_insights(
                                _edgar_text, _edgar_sd, _edgar_fd, API_KEY, model=get_model(), filing_context=_edgar_context
                            )
                        except Exception as e:
                            st.warning(f"Dashboard insights could not be generated: {e}.")
                    mda_result = None
                    with st.spinner("Scoring MD&A sentiment..."):
                        try:
                            mda_result = analyze_mda_sentiment(
                                _edgar_text, API_KEY, model=get_mda_model(), filing_context=_edgar_context
                            )
                        except Exception as e:
                            st.warning(f"MD&A sentiment could not be scored: {e}")

                    _edgar_md = {}
                    if _tk and re.fullmatch(r"[A-Z]{1,5}", _tk):
                        with st.spinner(f"Fetching market data for {_tk}..."):
                            _edgar_md = get_market_data(_tk)
                    _market_cap = _edgar_md.get("market_cap") or 0.0
                    try:
                        _excel_bytes = create_excel_file(_edgar_fd, _edgar_sd, _market_cap, _edgar_bb)
                    except Exception as e:
                        st.error(f"Could not generate Excel file: {e}")
                        st.stop()

                    _entry_id = f"edgar_{_cik}_{_selected_accession}"
                    _file_prefix = _tk or re.sub(r"[^A-Za-z0-9]+", "_", _company_name).strip("_") or "EDGAR"
                    _file_name = f"{_file_prefix}_{_selected_filing.get('form')}_{_selected_filing.get('reportDate')}.edgar"
                    _edgar_fd = _run_integrity_checks(
                        _edgar_fd,
                        _edgar_sd,
                        _tk,
                        "edgar",
                        filing_date=_sec_filing_date,
                        accession=_selected_accession,
                    )
                    st.session_state.financial_data      = _edgar_fd
                    st.session_state.summary_data        = _edgar_sd
                    st.session_state.bear_bull_data      = _edgar_bb
                    st.session_state.dashboard_data      = _edgar_dd
                    st.session_state.mda_sentiment       = mda_result
                    st.session_state.market_data         = _edgar_md
                    st.session_state.excel_bytes         = _excel_bytes
                    st.session_state.last_filename       = _file_name
                    st.session_state.resolved_ticker     = _tk
                    st.session_state.loaded_from_library = False
                    st.session_state.loaded_from_edgar   = True
                    st.session_state.loaded_from_sedar   = False
                    st.session_state.loaded_from_quick   = False
                    st.session_state.cache_hit           = False
                    st.session_state.analysis_loaded_from_cache = False
                    st.session_state.dcf_result          = None
                    st.session_state["manual_ticker"]    = _tk
                    st.session_state["edgar_loaded_accession"] = _selected_accession
                    st.session_state.pop("peer_data", None)
                    _save_analysis_cache(
                        _tk,
                        _edgar_period,
                        "edgar",
                        sector_value=(_edgar_sd or {}).get("sector_inferred"),
                        hurdle_rate_value=None,
                        mda_sentiment=mda_result,
                    )

                    try:
                        lib_add(
                            _entry_id,
                            _file_name,
                            len(_edgar_text),
                            _edgar_fd,
                            _edgar_sd,
                            _edgar_bb,
                            _edgar_dd,
                            raw_text=_edgar_text[:MAX_FILING_CHARS],
                            mda_sentiment=mda_result,
                            source="edgar",
                            file_path=_edgar_text_path,
                        )
                        st.session_state["filing_library"] = lib_get()
                    except Exception as _e:
                        st.warning(f"Could not save to library: {_e}")
                    _save_analysis_to_supabase(
                        _tk,
                        _edgar_fd,
                        _edgar_sd,
                        _edgar_bb,
                        _edgar_dd,
                        raw_text=_edgar_text[:MAX_FILING_CHARS],
                        file_name=_file_name,
                        file_size=len(_edgar_text),
                        source="edgar",
                        file_path=_edgar_text_path,
                    )
                    st.success(f"Loaded SEC EDGAR filing for {_tk or _company_name}.")
                    st.rerun()

    with _sedar_tab:
        st.caption("Search for a Canadian public company, open SEDAR+ in the right search context, then upload the downloaded PDF for Claude analysis.")
        _sedar_query = st.text_input("Search by company name or ticker", placeholder="e.g. Suncor, SU.TO, Shopify", key="sedar_ticker")
        if st.button("Search", type="primary", width='stretch', key="sedar_find_filings_btn"):
            st.session_state.pop("sedar_company", None)
            st.session_state.pop("sedar_yf_matches", None)
            st.session_state.pop("sedar_selected_filing_url", None)
            st.session_state.pop("sedar_selected_filing_type", None)
            st.session_state.loaded_from_sedar = False
            _query = _sedar_query.strip()
            if not _query:
                st.warning("Enter a company name or ticker first.")
            else:
                with st.spinner(f"Searching yfinance for {_query}..."):
                    _matches = _search_yfinance_equities(_query)
                if not _matches:
                    st.error(f"No results found for '{_query}'. Try a ticker symbol directly (e.g. AAPL or SU.TO)")
                else:
                    _query_symbol = _query.upper()
                    _direct_canadian = None
                    for _match in _matches:
                        _symbol = (_match.get("symbol") or "").upper()
                        if _is_canadian_quote(_match) and (
                            _symbol == _query_symbol
                            or _symbol.removesuffix(".TO") == _query_symbol
                        ):
                            _direct_canadian = _match
                            break
                    if _direct_canadian:
                        st.session_state["sedar_company"] = {
                            "ticker": _direct_canadian.get("symbol") or _query_symbol,
                            "symbol": _direct_canadian.get("symbol") or _query_symbol,
                            "company_name": _yf_quote_name(_direct_canadian),
                            "exchange": _direct_canadian.get("exchange") or "",
                        }
                        st.success(f"Resolved {_query} to {_yf_quote_name(_direct_canadian)}.")
                    else:
                        st.session_state["sedar_yf_matches"] = _matches
                        st.success(f"Found {len(_matches)} possible match(es). Select one below.")

        _sedar_matches = st.session_state.get("sedar_yf_matches") or []
        if _sedar_matches:
            _sedar_match_labels = [_yf_quote_label(row) for row in _sedar_matches]
            _selected_sedar_label = st.selectbox("Matching companies", _sedar_match_labels, key="sedar_company_select")
            _selected_sedar_company = _sedar_matches[_sedar_match_labels.index(_selected_sedar_label)]
            if st.button("Use Selected Company", width='stretch', key="sedar_use_company_btn"):
                if not _is_canadian_quote(_selected_sedar_company):
                    st.warning("This appears to be a US-listed company. For US filings, use the SEC EDGAR tab.")
                else:
                    _symbol = (_selected_sedar_company.get("symbol") or "").upper()
                    st.session_state["sedar_company"] = {
                        "ticker": _symbol,
                        "symbol": _symbol,
                        "company_name": _yf_quote_name(_selected_sedar_company),
                        "exchange": _selected_sedar_company.get("exchange") or "",
                    }
                    st.session_state.pop("sedar_selected_filing_url", None)
                    st.session_state.pop("sedar_selected_filing_type", None)
                    st.success(f"Resolved {_symbol} to {_yf_quote_name(_selected_sedar_company)}.")

        _sedar_company = st.session_state.get("sedar_company")
        if _sedar_company:
            _company_name = _sedar_company["company_name"]
            _ticker = _sedar_company["ticker"]
            st.info(f"Company resolved: **{_company_name}** ({_ticker})")

            with st.container(border=True):
                st.subheader("Find recent SEDAR+ filings")
                _selected_sedar_type = st.selectbox(
                    "Filing type",
                    SEDAR_FILING_TYPES,
                    key="sedar_filing_type_select",
                )
                if st.button("Find Recent SEDAR+ Filings", width='stretch', key="sedar_find_recent_by_type_btn"):
                    st.session_state["sedar_selected_filing_url"] = _sedar_search_url(_company_name, _selected_sedar_type)
                    st.session_state["sedar_selected_filing_type"] = _selected_sedar_type

                _selected_sedar_url = st.session_state.get("sedar_selected_filing_url")
                if _selected_sedar_url:
                    _selected_type = st.session_state.get("sedar_selected_filing_type", "selected filing type")
                    _external_link(f"Open {_selected_type} on SEDAR+", _selected_sedar_url)
                    st.info("Click the link above to open SEDAR+, download the PDF, then upload it below.")

            with st.container(border=True):
                st.subheader("Quick links — open filing type directly on SEDAR+")
                _cols = st.columns(2)
                for _idx, (_label, _filing_type) in enumerate(SEDAR_QUICK_LINKS):
                    _url = _sedar_search_url(_company_name, _filing_type)
                    with _cols[_idx % 2]:
                        _external_link(_label, _url)

                _profile_url = _sedar_search_url(_company_name)
                _external_link("Open filing on SEDAR+", _profile_url)

            st.info("Once you've downloaded a filing from SEDAR+, upload it below to analyze it with Claude.")

_persist_loaded_edgar_to_library()

with quick_analysis_slot.expander("⚡ Quick Analysis — Public Companies (No Upload Required)"):
    quick_company_query = st.text_input(
        "Search by Company Name",
        placeholder="e.g. Nvidia, Apple, Microsoft",
        key="quick_company_search",
    )
    if st.button("Search", width='stretch', key="quick_company_search_btn"):
        _quick_search_query = quick_company_query.strip()
        if not _quick_search_query:
            st.warning("Enter a company name first.")
        else:
            _quick_search_key = f"quick_search_{_quick_search_query.lower()}"
            if _quick_search_key not in st.session_state:
                with st.spinner("Searching yfinance..."):
                    st.session_state[_quick_search_key] = _search_yfinance_equities(_quick_search_query, max_results=8)
            st.session_state["quick_search_active_key"] = _quick_search_key

    _quick_active_search_key = st.session_state.get("quick_search_active_key")
    _quick_search_results = st.session_state.get(_quick_active_search_key, []) if _quick_active_search_key else []
    if _quick_active_search_key:
        if not _quick_search_results:
            st.warning("No results found — try a ticker symbol directly")
        else:
            st.markdown("**Search Results**")
            for _idx, _quote in enumerate(_quick_search_results[:5]):
                _symbol = (_quote.get("symbol") or "").upper()
                if not _symbol:
                    continue
                if st.button(_yf_quote_label(_quote), key=f"quick_search_result_{_idx}_{_symbol}", width='stretch'):
                    st.session_state["quick_analysis_ticker"] = _symbol

    quick_ticker = st.text_input(
        "Ticker Symbol",
        placeholder="e.g. NVDA or RY.TO",
        key="quick_analysis_ticker",
    )
    period_options = [
        "Latest Quarter",
        "Last 4 Quarters (TTM)",
        "Latest Annual",
        "Last 2 Years (Annual)",
        "Last 4 Years (Annual)",
    ]
    selected_period = st.selectbox("Period", period_options, index=2, key="quick_analysis_period")
    st.caption("Instantly analyse any US or Canadian public company using financial statement data. No PDF needed. ~$0.05 per analysis")

    def _fmt_quick_preview_value(value, scale=1):
        if value is None:
            return "—"
        try:
            value = float(value) * scale
        except (TypeError, ValueError):
            return "—"
        sign = "-" if value < 0 else ""
        abs_value = abs(value)
        if abs_value >= 1_000_000_000_000:
            return f"{sign}${abs_value / 1_000_000_000_000:,.2f}T"
        if abs_value >= 1_000_000_000:
            return f"{sign}${abs_value / 1_000_000_000:,.1f}B"
        if abs_value >= 1_000_000:
            return f"{sign}${abs_value / 1_000_000:,.1f}M"
        if abs_value >= 1_000:
            return f"{sign}${abs_value / 1_000:,.1f}K"
        return f"{sign}${abs_value:,.0f}"

    _quick_period_params = {
        "Latest Quarter": ("quarter", 1),
        "Last 4 Quarters (TTM)": ("quarter", 4),
        "Latest Annual": ("annual", 1),
        "Last 2 Years (Annual)": ("annual", 2),
        "Last 4 Years (Annual)": ("annual", 4),
    }
    _quick_period, _quick_limit = _quick_period_params[selected_period]
    _quick_current_ticker = quick_ticker.strip().upper()
    _quick_is_canadian = _quick_current_ticker.endswith(".TO")
    if _quick_is_canadian:
        st.warning("⚠️ Canadian companies require a Premium FMP subscription. Use SEDAR+ or PDF upload instead.")

    if st.button("Fetch Financials", width='stretch', key="quick_fetch_btn", disabled=_quick_is_canadian):
        _quick_ticker = quick_ticker.strip().upper()
        if not _quick_ticker:
            st.warning("Enter a ticker symbol first.")
        else:
            with st.spinner(f"Fetching financial statements for {_quick_ticker}..."):
                _quick_fd = build_financial_data_from_fmp(_quick_ticker, period=_quick_period, limit=_quick_limit)
            if not _quick_fd:
                st.error(f"Could not fetch data for {_quick_ticker} — check the ticker symbol and try again")
                st.stop()
            st.session_state["quick_financial_data"] = _quick_fd
            st.session_state["quick_financial_ticker"] = _quick_ticker
            st.session_state["quick_financial_period"] = selected_period

    _quick_fd_preview = st.session_state.get("quick_financial_data")
    _quick_preview_ticker = st.session_state.get("quick_financial_ticker")
    _quick_preview_period = st.session_state.get("quick_financial_period")
    if _quick_fd_preview and _quick_preview_ticker == _quick_current_ticker and _quick_preview_period == selected_period:
        _quick_company = _quick_fd_preview.get("company") or _quick_fd_preview.get("company_name") or _quick_preview_ticker
        _quick_year = _quick_fd_preview.get("fiscal_year") or "latest fiscal year"
        _quick_preview_scale = _quick_fd_preview.get("scale") or 1
        if selected_period == "Last 4 Quarters (TTM)":
            st.success(f"Fetched last 4 quarters for {_quick_company}. Analysis will use TTM (trailing twelve months) totals.")
        elif selected_period == "Latest Quarter":
            st.success(f"Fetched {_quick_year} data for {_quick_company}.")
        elif selected_period == "Latest Annual":
            st.success(f"Fetched {_quick_year} data for {_quick_company}.")
        elif selected_period == "Last 2 Years (Annual)":
            st.success(f"Fetched 2 years of data for {_quick_company}.")
        else:
            st.success(f"Fetched 4 years of data for {_quick_company}.")
        if _quick_limit > 1:
            _quick_metric_map = [
                ("Revenue", "revenue"),
                ("Gross Profit", "gross_profit"),
                ("Net Income", "net_income"),
                ("FCF", "free_cash_flow"),
                ("Total Debt", "total_debt"),
                ("Cash", "cash"),
            ]
            _quick_history = list(reversed(_quick_fd_preview.get("period_history") or []))
            preview_df = []
            for _label, _key in _quick_metric_map:
                _row = {"Metric": _label}
                for _period_row in _quick_history:
                    _row[_period_row.get("label") or "Period"] = _fmt_quick_preview_value(_period_row.get(_key), _quick_preview_scale)
                preview_df.append(_row)
        else:
            preview_df = [
                {"Metric": "Revenue", "Value": _fmt_quick_preview_value(_quick_fd_preview.get("revenue"), _quick_preview_scale)},
                {"Metric": "Gross Profit", "Value": _fmt_quick_preview_value(_quick_fd_preview.get("gross_profit"), _quick_preview_scale)},
                {"Metric": "Net Income", "Value": _fmt_quick_preview_value(_quick_fd_preview.get("net_income"), _quick_preview_scale)},
                {"Metric": "FCF", "Value": _fmt_quick_preview_value(_quick_fd_preview.get("free_cash_flow"), _quick_preview_scale)},
                {"Metric": "Total Debt", "Value": _fmt_quick_preview_value(_quick_fd_preview.get("total_debt"), _quick_preview_scale)},
                {"Metric": "Cash", "Value": _fmt_quick_preview_value(_quick_fd_preview.get("cash"), _quick_preview_scale)},
            ]
        st.dataframe(preview_df, hide_index=True, width='stretch')
        if selected_period == "Last 4 Quarters (TTM)":
            st.caption(" Preview shows individual quarters. Analysis uses TTM totals (sum of all 4 quarters).")

        if st.button("Analyse $", type="primary", width='stretch', key="quick_analysis_btn"):
            _quick_fd = _quick_fd_preview
            _quick_ticker = (_quick_preview_ticker or _quick_fd.get("ticker") or quick_ticker).strip().upper()

            _quick_text = _financial_data_to_text(_quick_fd)
            _quick_context = _get_filing_context(_quick_text, _quick_ticker, selected_period)
            _quick_sd = None
            with st.spinner("Generating investment signal from financial statements..."):
                try:
                    _quick_sd = analyze_summary(_quick_text, _quick_fd, API_KEY, model=get_model(), filing_context=_quick_context)
                    if isinstance(_quick_sd, dict):
                        _quick_sd.setdefault("ticker", _quick_ticker)
                except Exception as e:
                    st.warning(f"Investment signal could not be generated: {e}.")

            _quick_bb = None
            with st.spinner("Generating bull/bear case..."):
                try:
                    _quick_bb = analyze_bear_bull(_quick_text, API_KEY, model=get_model(), filing_context=_quick_context)
                except Exception as e:
                    st.warning(f"Bull/bear case could not be generated: {e}.")

            _quick_dd = None
            with st.spinner("Generating dashboard insights..."):
                try:
                    _quick_dd = analyze_dashboard_insights(
                        _quick_text,
                        _quick_sd,
                        _quick_fd,
                        API_KEY,
                        model=get_model(),
                        filing_context=_quick_context,
                    )
                except Exception as e:
                    st.warning(f"Dashboard insights could not be generated: {e}.")

            _quick_market_data = {}
            with st.spinner(f"Fetching market data for {_quick_ticker}..."):
                try:
                    _quick_market_data = get_market_data(_quick_ticker)
                except Exception:
                    _quick_market_data = {}

            _quick_market_cap = _quick_market_data.get("market_cap") or 0.0
            try:
                _quick_excel = create_excel_file(_quick_fd, _quick_sd, _quick_market_cap, _quick_bb)
            except Exception:
                _quick_excel = None

            _quick_fd = normalize_financial_data(_quick_fd)
            st.session_state.financial_data      = _quick_fd
            st.session_state.summary_data        = _quick_sd
            st.session_state.bear_bull_data      = _quick_bb
            st.session_state.dashboard_data      = _quick_dd
            st.session_state.mda_sentiment       = None
            st.session_state.market_data         = _quick_market_data
            st.session_state.excel_bytes         = _quick_excel
            st.session_state.last_filename       = f"{_quick_ticker}_quick_analysis"
            st.session_state.resolved_ticker     = _quick_ticker
            st.session_state["ticker"]           = _quick_ticker
            st.session_state.loaded_from_library = False
            st.session_state.loaded_from_edgar   = False
            st.session_state.loaded_from_sedar   = False
            st.session_state.loaded_from_quick   = True
            st.session_state.analysis_loaded_from_cache = False
            st.session_state.cache_hit           = False
            st.session_state.dcf_result          = None
            st.session_state["manual_ticker"]    = _quick_ticker
            st.session_state.pop("peer_data", None)
            _quick_period_label = _quick_fd.get("fiscal_year") or _quick_fd.get("period", "")
            _quick_entry_id = f"fmp_{_quick_ticker}_{_quick_period_label}"
            _save_analysis_cache(
                _quick_ticker,
                _quick_period_label,
                "fmp",
                mda_sentiment=None,
                sector_value=(_quick_sd or {}).get("sector_inferred"),
            )
            try:
                lib_add(
                    _quick_entry_id,
                    f"{_quick_ticker}_quick_analysis",
                    0,
                    _quick_fd,
                    _quick_sd,
                    _quick_bb,
                    _quick_dd,
                    raw_text=_quick_text[:MAX_FILING_CHARS] if _quick_text else None,
                    mda_sentiment=None,
                    source="fmp",
                )
                st.session_state["filing_library"] = lib_get()
                st.success("✓ Analysis saved to library")
            except Exception as _e:
                st.warning(f"Could not save to library: {_e}")
            st.info("ℹ️ MD&A Sentiment not available for Quick Analysis — upload a PDF for full analysis")
            st.rerun()

uploaded_file = st.file_uploader(
    "Upload Financial Statements (PDF or Word)",
    type=["pdf", "docx"],
    help="Annual reports, 10-K filings, or standalone financial statement PDFs work best. Word (.docx) documents are also accepted.",
    key=f"pdf_uploader_{st.session_state.uploader_key}",
)
# Clear stored results when the uploaded file changes.
# When data was loaded from the Filing Library there is no uploaded file,
# so we must NOT reset — library results should persist until the user
# explicitly uploads a different file.
if st.session_state.get("reanalyse_no_text"):
    _pdf_info = st.session_state.get("reanalyse_pdf_info") or {}
    if _pdf_info.get("source") == "edgar":
        _restored_text = _read_text_cache(_pdf_info.get("file_path"))
        if _restored_text:
            st.session_state.pending_reanalyse = {
                "raw_text":     _restored_text[:MAX_FILING_CHARS],
                "company_name": _pdf_info.get("company_name", st.session_state.reanalyse_no_text),
                "entry_id":     _pdf_info.get("entry_id"),
                "file_name":    _pdf_info.get("file_name", ""),
                "file_size":    _pdf_info.get("file_size", 0),
                "ticker":       _pdf_info.get("ticker"),
                "period":       _pdf_info.get("period"),
                "source":       "edgar",
                "file_path":    _pdf_info.get("file_path"),
            }
            st.session_state.reanalyse_no_text  = None
            st.session_state.reanalyse_pdf_info = None
            st.rerun()
        else:
            st.info(f"Cached EDGAR text was not found for **{st.session_state.reanalyse_no_text}**. Load the filing from EDGAR again.")
            st.session_state.reanalyse_no_text = None
            st.session_state.reanalyse_pdf_info = None
            st.stop()
    # Try session-state preload (set by Load button), then fall back to disk
    _cached_bytes = st.session_state.get("cached_pdf_bytes")
    if _cached_bytes is None:
        try:
            _cp = _pdf_cache_path(_pdf_info.get("ticker"), _pdf_info.get("period"))
            if _cp and Path(_cp).exists():
                with Path(_cp).open("rb") as _f:
                    _cached_bytes = _f.read()
        except Exception:
            _cached_bytes = None
    if _cached_bytes is None:
        _cached_bytes = supabase_storage.load_pdf(_pdf_info.get("ticker"), _pdf_info.get("period"))
    _reanalyse_file_type = _pdf_info.get("file_type", "pdf")
    if _cached_bytes:
        try:
            if _reanalyse_file_type == "docx":
                with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as _tmp:
                    _tmp.write(_cached_bytes)
                    _tmp_path = _tmp.name
                _restored_text = convert_to_markdown(_tmp_path) or ""
                try:
                    os.unlink(_tmp_path)
                except Exception:
                    pass
                if not _restored_text:
                    raise ValueError("No text extracted from Word document")
            else:
                _restored_text = extract_text_from_pdf(io.BytesIO(_cached_bytes))
            st.session_state.pending_reanalyse = {
                "raw_text":     _restored_text[:MAX_FILING_CHARS],
                "company_name": _pdf_info.get("company_name", st.session_state.reanalyse_no_text),
                "entry_id":     _pdf_info.get("entry_id"),
                "file_name":    _pdf_info.get("file_name", ""),
                "file_size":    _pdf_info.get("file_size", 0),
                "ticker":       _pdf_info.get("ticker"),
                "period":       _pdf_info.get("period"),
                "source":       _pdf_info.get("source", "pdf"),
                "file_path":    _pdf_info.get("file_path"),
                "pdf_bytes":    _cached_bytes,
                "file_type":    _reanalyse_file_type,
            }
            st.session_state.reanalyse_no_text  = None
            st.session_state.reanalyse_pdf_info = None
            st.session_state.cached_pdf_bytes   = None
            st.rerun()
        except Exception:
            _doc_label = "Word document" if _reanalyse_file_type == "docx" else "PDF"
            st.info(f"Re-upload the {_doc_label} to re-analyse **{st.session_state.reanalyse_no_text}**.")
    else:
        _doc_label = "Word document" if _reanalyse_file_type == "docx" else "PDF"
        st.info(f"Re-upload the {_doc_label} to re-analyse **{st.session_state.reanalyse_no_text}**.")

if uploaded_file is None:
    if (
        not st.session_state.get("loaded_from_library")
        and not st.session_state.get("loaded_from_edgar")
        and not st.session_state.get("loaded_from_sedar")
        and not st.session_state.get("loaded_from_quick")
    ):
        st.session_state.financial_data  = None
        st.session_state.summary_data    = None
        st.session_state.bear_bull_data  = None
        st.session_state.dashboard_data  = None
        st.session_state.mda_sentiment   = None
        st.session_state.market_data     = None
        st.session_state.excel_bytes     = None
        st.session_state.resolved_ticker = None
        st.session_state.dcf_result      = None
        st.session_state.cache_hit       = False
        st.session_state.analysis_loaded_from_cache = False
        st.session_state.loaded_from_quick = False
        st.session_state.pop("peer_data", None)
        st.session_state.pop("manual_ticker", None)
elif (not st.session_state.get("loaded_from_library", False) and
      st.session_state.last_filename and
      uploaded_file is not None and
      uploaded_file.name != st.session_state.last_filename):
    # A different file was dropped in — always reset, including the flag.
    st.session_state.financial_data      = None
    st.session_state.summary_data        = None
    st.session_state.bear_bull_data      = None
    st.session_state.dashboard_data      = None
    st.session_state.mda_sentiment       = None
    st.session_state.market_data         = None
    st.session_state.excel_bytes         = None
    st.session_state.resolved_ticker     = None
    st.session_state.dcf_result          = None
    st.session_state.cache_hit           = False
    st.session_state.loaded_from_library = False
    st.session_state.loaded_from_edgar   = False
    st.session_state.loaded_from_sedar   = False
    st.session_state.loaded_from_quick   = False
    st.session_state.analysis_loaded_from_cache = False
    st.session_state.pop("peer_data", None)
    st.session_state.pop("manual_ticker", None)

st.divider()

# --- Valuation inputs --------------------------------------------------
st.markdown("#### Valuation Inputs")
st.caption("Market cap is fetched automatically from yfinance when the filing contains a ticker. Sector is auto-detected when available.")
sector_options = [
    "Enterprise SaaS", "Specialty Retail", "IT Services",
    "Financial Services", "Upstream Oil & Gas", "Healthcare",
    "Consumer Staples", "Industrials", "Real Estate", "Other",
]
sector_mapping = {
    "Technology": "Enterprise SaaS",
    "Information Technology": "Enterprise SaaS",
    "Semiconductors": "Enterprise SaaS",
    "Consumer Cyclical": "Specialty Retail",
    "Consumer Defensive": "Consumer Staples",
    "Energy": "Upstream Oil & Gas",
    "Healthcare": "Healthcare",
    "Financial Services": "Financial Services",
    "Industrials": "Industrials",
    "Real Estate": "Real Estate",
    "Utilities": "Other",
    "Communication Services": "Enterprise SaaS",
    "Basic Materials": "Industrials",
}


def _map_sector_to_option(raw_sector):
    if not raw_sector:
        return None
    raw_sector = str(raw_sector).strip()
    if raw_sector in sector_options:
        return raw_sector
    mapped = sector_mapping.get(raw_sector)
    if mapped in sector_options:
        return mapped
    raw_lower = raw_sector.lower()
    for source, target in sector_mapping.items():
        if source.lower() in raw_lower or raw_lower in source.lower():
            return target if target in sector_options else None
    return None


def _lookup_yfinance_sector(ticker):
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return None
    cache_key = f"yf_sector_{ticker}"
    if cache_key not in st.session_state:
        try:
            _ensure_yfinance_cache_location()
            st.session_state[cache_key] = yf.Ticker(ticker).info.get("sector")
        except Exception:
            st.session_state[cache_key] = None
    return st.session_state.get(cache_key)


_sector_ticker = (
    st.session_state.get("resolved_ticker")
    or st.session_state.get("ticker")
    or st.session_state.get("manual_ticker")
    or (st.session_state.get("quick_financial_data") or {}).get("ticker")
)
_quick_financial_data = st.session_state.get("quick_financial_data") or {}
_raw_sector = (
    _quick_financial_data.get("sector")
    or _lookup_yfinance_sector(_sector_ticker)
    or (st.session_state.get("market_data") or {}).get("sector")
)
_auto_sector = _map_sector_to_option(_raw_sector)
if _auto_sector:
    st.session_state["auto_sector"] = _auto_sector
    if st.session_state.get("auto_sector_ticker") != _sector_ticker:
        st.session_state["valuation_sector"] = _auto_sector
        st.session_state["auto_sector_ticker"] = _sector_ticker

_sector_index = 0
if st.session_state.get("auto_sector") in sector_options:
    _sector_index = sector_options.index(st.session_state["auto_sector"])
vi_col1, vi_col2 = st.columns(2)
with vi_col1:
    sector = st.selectbox("Sector", sector_options, key="valuation_sector")
    if _auto_sector:
        st.caption("Auto-detected from company data")
with vi_col2:
    hurdle_rate = st.number_input("Hurdle Rate (%)", min_value=0.0, max_value=100.0, value=12.0, step=0.5)
st.components.v1.html("""
<script>
  const inputs = window.parent.document.querySelectorAll('input[type=number]');
  inputs.forEach(input => input.addEventListener('focus', function() { this.select(); }));
</script>
""", height=0)
st.divider()

# --- Re-analyse from Filing Library (fires when ♻️ button sets pending_reanalyse) ---
if st.session_state.get("pending_reanalyse"):
    ra = st.session_state.pending_reanalyse
    st.info(f"Re-analysing **{ra['company_name']}** — running all 4 Claude calls fresh...")

    _ra_text = ra["raw_text"]
    _ra_context = _get_filing_context(
        _ra_text,
        ra.get("ticker") or ra.get("company_name"),
        ra.get("period") or ra.get("file_name"),
    )

    with st.spinner("Call 1: Extracting financials (Haiku)..."):
        _ra_fd = analyze_financials(_ra_text, API_KEY, model=get_model(), filing_context=_ra_context)

    _ra_sd = None
    with st.spinner("Call 2: Generating investment signal..."):
        _ra_sd = analyze_summary(_ra_text, _ra_fd, API_KEY, model=get_model(), filing_context=_ra_context)

    _ra_bb = None
    with st.spinner("Call 3: Generating bull/bear case..."):
        _ra_bb = analyze_bear_bull(_ra_text, API_KEY, model=get_model(), filing_context=_ra_context)

    _ra_dd = None
    with st.spinner("Call 4: Generating dashboard insights..."):
        _ra_dd = analyze_dashboard_insights(_ra_text, _ra_sd, _ra_fd, API_KEY, model=get_model(), filing_context=_ra_context)

    _ra_mda = None
    with st.spinner("Call 5: Scoring MD&A sentiment (Haiku)..."):
        _ra_mda = analyze_mda_sentiment(_ra_text, API_KEY, model=get_mda_model(), filing_context=_ra_context)

    _ra_fd = _run_integrity_checks(
        _ra_fd,
        _ra_sd,
        (ra.get("ticker") or (_ra_sd or {}).get("ticker")),
        ra.get("source", "pdf"),
        filing_date=(ra.get("sec_filing_date") or (ra.get("summary_data") or {}).get("sec_filing_date")),
        accession=ra.get("accession"),
    )

    if ra.get("source") == "edgar" and ra.get("file_path"):
        try:
            safe_write_text(ra["file_path"], _ra_text)
        except Exception:
            pass

    try:
        lib_add(ra["entry_id"], ra["file_name"], ra["file_size"],
                _ra_fd, _ra_sd, _ra_bb, _ra_dd, raw_text=_ra_text,
                mda_sentiment=_ra_mda,
                source=ra.get("source", "pdf"),
                file_path=ra.get("file_path"),
                file_type=ra.get("file_type", "pdf"))
    except Exception as e:
        logger.warning(f"lib_add failed in SA re-analyse: {e}")
    _save_analysis_to_supabase(
        (_ra_sd or {}).get("ticker"),
        _ra_fd,
        _ra_sd,
        _ra_bb,
        _ra_dd,
        raw_text=_ra_text,
        mda_sentiment=_ra_mda,
        file_name=ra.get("file_name", ""),
        file_size=ra.get("file_size", 0),
        pdf_bytes=ra.get("pdf_bytes"),
        source=ra.get("source", "pdf"),
        file_path=ra.get("file_path"),
    )

    st.session_state.financial_data      = _ra_fd
    st.session_state.summary_data        = _ra_sd
    st.session_state.bear_bull_data      = _ra_bb
    st.session_state.dashboard_data      = _ra_dd
    st.session_state.mda_sentiment       = _ra_mda
    st.session_state.market_data         = {}
    _ra_has_statements = (
        _ra_fd
        and "error" not in _ra_fd
        and (
            _ra_fd.get("income_statement")
            or _ra_fd.get("balance_sheet")
            or _ra_fd.get("cash_flow_statement")
        )
    )
    if _ra_has_statements:
        try:
            st.session_state.excel_bytes = create_excel_file(_ra_fd, _ra_sd, 0.0, _ra_bb)
        except Exception:
            st.session_state.excel_bytes = None
    else:
        st.session_state.excel_bytes = None
    st.session_state.last_filename       = ra["file_name"]
    st.session_state.resolved_ticker     = None
    st.session_state.dcf_result          = None
    st.session_state.loaded_from_library = True
    st.session_state.loaded_from_edgar   = ra.get("source") == "edgar"
    st.session_state.loaded_from_sedar   = False
    st.session_state.loaded_from_quick   = False
    st.session_state.analysis_loaded_from_cache = False
    _save_analysis_cache(
        (_ra_sd or {}).get("ticker"),
        _analysis_period(_ra_fd),
        ra.get("source", "pdf"),
        financial_data=_ra_fd,
        summary_data=_ra_sd,
        bear_bull_data=_ra_bb,
        dashboard_data=_ra_dd,
        mda_sentiment=_ra_mda,
        market_data={},
        sector_value=sector,
        hurdle_rate_value=hurdle_rate,
    )
    st.session_state.pending_reanalyse   = None
    st.rerun()

if uploaded_file:
    if uploaded_file.size > 20 * 1024 * 1024:
        st.warning(
            f"Large PDF detected ({uploaded_file.size / (1024 * 1024):.0f} MB) — "
            "extraction may take longer on cloud deployment. "
            "Only the first 150 pages will be processed."
        )
    if st.button("Analyze Financials $", type="primary", width='stretch'):

        st.session_state.reanalyse_no_text = None  # clear prompt once user starts upload

        pdf_bytes = uploaded_file.getvalue()
        cache_key = get_cache_key(pdf_bytes)
        cached    = load_cache(cache_key)
        raw_text  = None  # populated in non-cached path; stored in library for future re-analysis
        _is_docx  = uploaded_file.name.lower().endswith(".docx")

        if cached:
            financial_data = normalize_financial_data(cached["financial_data"])
            summary_data   = cached.get("summary_data")
            bear_bull_data = cached.get("bear_bull_data")
            dashboard_data = cached.get("dashboard_data")
            mda_sentiment  = cached.get("mda_sentiment")
            if _is_docx:
                try:
                    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as _tmp:
                        _tmp.write(pdf_bytes)
                        _tmp_path = _tmp.name
                    raw_text = convert_to_markdown(_tmp_path) or ""
                    try:
                        os.unlink(_tmp_path)
                    except Exception:
                        pass
                except Exception:
                    pass
            if mda_sentiment is None:
                with st.spinner("Backfilling MD&A sentiment for cached document..."):
                    try:
                        if not raw_text:
                            raw_text = extract_text_from_pdf(io.BytesIO(pdf_bytes))
                        if len(raw_text or "") >= 200:
                            _cached_context = _get_filing_context(
                                raw_text,
                                (financial_data or {}).get("company_name") or uploaded_file.name,
                                (financial_data or {}).get("period") or uploaded_file.name,
                            )
                            mda_sentiment = analyze_mda_sentiment(
                                raw_text, API_KEY, model=get_mda_model(), filing_context=_cached_context
                            )
                            save_cache(
                                cache_key,
                                uploaded_file.name,
                                financial_data,
                                summary_data,
                                bear_bull_data,
                                dashboard_data,
                                mda_sentiment=mda_sentiment,
                            )
                        else:
                            st.warning("MD&A sentiment could not be backfilled because very little text was extracted.")
                    except Exception as e:
                        st.warning(f"MD&A sentiment could not be backfilled: {e}.")
            st.session_state.cache_hit = True
            st.success(f"Loaded **{uploaded_file.name}** from cache.")
        else:
            st.session_state.cache_hit = False

            # Step 1 — Extract text from the uploaded file
            if _is_docx:
                with st.spinner("Converting Word document to text..."):
                    try:
                        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as _tmp:
                            _tmp.write(pdf_bytes)
                            _tmp_path = _tmp.name
                        raw_text = convert_to_markdown(_tmp_path) or ""
                        try:
                            os.unlink(_tmp_path)
                        except Exception:
                            pass
                    except Exception as e:
                        st.error(f"Could not convert the Word document: {e}")
                        st.stop()
            else:
                with st.spinner("Extracting text from PDF..."):
                    try:
                        raw_text = extract_text_from_pdf(uploaded_file)
                    except Exception as e:
                        st.error(f"Could not read the PDF: {e}")
                        st.stop()

            char_count = len(raw_text)
            if char_count < 200:
                st.error("Very little text was extracted — the file may be scanned/image-based or empty. Try a text-based PDF or a Word document with readable text content.")
                st.stop()

            st.success(f"Extracted {char_count:,} characters from **{uploaded_file.name}**")
            _upload_context = _get_filing_context(raw_text, uploaded_file.name, cache_key)

            # Step 2 — Call 1: extract structured financials (claude-haiku)
            with st.spinner("Analyzing with Claude (this can take 30–60 seconds for large documents)..."):
                try:
                    financial_data = analyze_financials(raw_text, API_KEY, model=get_model(), filing_context=_upload_context)
                except Exception as e:
                    st.error(f"Claude analysis failed: {e}")
                    st.stop()

            # Step 3 — Call 2: generate investment signal
            summary_data = None
            with st.spinner("Generating investment signal — this may take 20–30 seconds..."):
                try:
                    summary_data = analyze_summary(raw_text, financial_data, API_KEY, model=get_model(), filing_context=_upload_context)
                except Exception as e:
                    st.warning(f"Investment signal could not be generated: {e}. The Excel report will be created without the Summary tab.")

            # Step 4 — Call 3: generate bull / bear case
            bear_bull_data = None
            with st.spinner("Generating bull/bear case — this may take 15–25 seconds..."):
                try:
                    bear_bull_data = analyze_bear_bull(raw_text, API_KEY, model=get_model(), filing_context=_upload_context)
                except Exception as e:
                    st.warning(f"Bull/bear case could not be generated: {e}.")

            # Step 5 — Call 4: generate dashboard insights (Dalio / Lynch / Marks)
            dashboard_data = None
            with st.spinner("Generating dashboard insights — this may take 15–20 seconds..."):
                try:
                    dashboard_data = analyze_dashboard_insights(
                        raw_text, summary_data, financial_data, API_KEY, model=get_model(), filing_context=_upload_context
                    )
                except Exception as e:
                    st.warning(f"Dashboard insights could not be generated: {e}.")

            # Step 6 — Call 5: score MD&A sentiment
            mda_sentiment = None
            with st.spinner("Scoring MD&A sentiment (Haiku)..."):
                try:
                    mda_sentiment = analyze_mda_sentiment(raw_text, API_KEY, model=get_mda_model(), filing_context=_upload_context)
                except Exception as e:
                    st.warning(f"MD&A sentiment could not be scored: {e}.")

            save_cache(cache_key, uploaded_file.name, financial_data, summary_data,
                       bear_bull_data, dashboard_data, mda_sentiment=mda_sentiment)

        # Step 4 — Fetch market data; fall back to company-name search if filing has no ticker
        market_data = {}
        resolved_ticker = (summary_data or {}).get("ticker")

        if not resolved_ticker:
            company_name_search = financial_data.get("company_name", "")
            if company_name_search:
                with st.spinner(f"No ticker in filing — searching for '{company_name_search}'..."):
                    resolved_ticker = search_ticker(company_name_search)
                    if resolved_ticker:
                        st.info(f"Found ticker **{resolved_ticker}** via company name search.")

        if resolved_ticker:
            with st.spinner(f"Fetching market data for {resolved_ticker}..."):
                market_data = get_market_data(resolved_ticker)
                if not market_data.get("current_price"):
                    st.warning(f"Could not fetch market data for '{resolved_ticker}'.")

        market_cap = market_data.get("market_cap") or 0.0
        _upload_source = _upload_analysis_source(resolved_ticker)
        financial_data = _run_integrity_checks(
            financial_data,
            summary_data,
            resolved_ticker,
            _upload_source,
            filing_date=(summary_data or {}).get("sec_filing_date"),
        )

        # Step 5 — Build Excel
        excel_bytes = None
        _has_statements = (
            financial_data
            and "error" not in financial_data
            and (
                financial_data.get("income_statement")
                or financial_data.get("balance_sheet")
                or financial_data.get("cash_flow_statement")
            )
        )
        if not _has_statements:
            st.info("Excel export unavailable — no structured financial data detected in this document.")
        else:
            try:
                excel_bytes = create_excel_file(financial_data, summary_data, market_cap, bear_bull_data)
            except Exception as e:
                st.error(f"Could not generate Excel file: {e}")
                st.stop()

        st.session_state.financial_data      = financial_data
        st.session_state.summary_data        = summary_data
        st.session_state.bear_bull_data      = bear_bull_data
        st.session_state.dashboard_data      = dashboard_data
        st.session_state.mda_sentiment       = mda_sentiment
        st.session_state.market_data         = market_data
        st.session_state.excel_bytes         = excel_bytes
        st.session_state.last_filename       = uploaded_file.name
        st.session_state.resolved_ticker     = resolved_ticker
        st.session_state.loaded_from_library = False
        st.session_state.loaded_from_edgar   = False
        st.session_state.loaded_from_sedar   = _upload_source == "sedar"
        st.session_state.loaded_from_quick   = False
        st.session_state.analysis_loaded_from_cache = False
        if resolved_ticker:
            st.session_state["manual_ticker"] = resolved_ticker
        _period_label = financial_data.get("fiscal_year") or financial_data.get("period", "")
        _save_analysis_cache(
            resolved_ticker,
            _period_label,
            _upload_source,
            mda_sentiment=mda_sentiment,
            sector_value=sector,
            hurdle_rate_value=hurdle_rate,
        )

        # Persist to Filing Library (permanent — survives cache clears).
        try:
            lib_add(
                cache_key,
                uploaded_file.name,
                len(pdf_bytes),
                financial_data,
                summary_data,
                bear_bull_data,
                dashboard_data,
                raw_text=raw_text[:MAX_FILING_CHARS] if raw_text else None,
                mda_sentiment=mda_sentiment,
                source=_upload_source,
                file_type="docx" if _is_docx else "pdf",
            )
        except Exception as e:
            logger.warning(f"lib_add failed on fresh upload: {e}")
        _save_analysis_to_supabase(
            resolved_ticker,
            financial_data,
            summary_data,
            bear_bull_data,
            dashboard_data,
            raw_text=raw_text[:MAX_FILING_CHARS] if raw_text else None,
            mda_sentiment=mda_sentiment,
            file_name=uploaded_file.name,
            file_size=len(pdf_bytes),
            pdf_bytes=pdf_bytes,
            source=_upload_source,
        )

        # Save PDF bytes to disk so Re-Analyse can run without re-uploading.
        try:
            _pdf_disk_path = _pdf_cache_path(resolved_ticker, _period_label)
            if _pdf_disk_path:
                safe_write_bytes(_pdf_disk_path, pdf_bytes)
        except Exception:
            pass  # PDF cache write failure must never block analysis

        # Rerun so sidebar counts (cache + library) reflect the new entry.
        st.rerun()
    st.caption("~$0.08 per analysis")

# --- Display results (runs on every rerun as long as data is in state) -
if st.session_state.financial_data:
    financial_data  = st.session_state.financial_data
    excel_bytes     = st.session_state.excel_bytes
    market_data     = st.session_state.market_data or {}
    summary_data    = st.session_state.summary_data or {}
    bear_bull_data  = st.session_state.bear_bull_data or {}
    dashboard_data  = st.session_state.dashboard_data
    mda_sentiment   = st.session_state.get("mda_sentiment")
    _integrity_flags = _integrity_flag_names(financial_data)
    if _integrity_flags:
        st.warning("Data integrity flags: " + ", ".join(_integrity_flags))

    # If dashboard insights are missing (old library entry or failed Call 4 in the
    # upload pipeline), generate them now from the structured data we do have.
    # filing_text is unavailable here, so we pass "" — Claude uses financials + signal.
    if dashboard_data is None:
        with st.spinner("Generating dashboard insights — this may take 15–20 seconds..."):
            _display_text = st.session_state.get("cached_filing_text") or ""
            _display_context = (
                _get_filing_context(
                    _display_text,
                    st.session_state.get("resolved_ticker") or summary_data.get("ticker"),
                    financial_data.get("period") or financial_data.get("fiscal_year"),
                )
                if _display_text
                else None
            )
            dashboard_data = analyze_dashboard_insights(
                "",
                st.session_state.summary_data,
                financial_data,
                API_KEY,
                model=get_model(),
                filing_context=_display_context,
            )
            st.session_state.dashboard_data = dashboard_data

    company  = financial_data.get("company_name") or "Untitled Document"
    period   = financial_data.get("period") or ""
    currency = financial_data.get("currency") or ""
    fy       = financial_data.get("fiscal_year") or "Current Year"
    fy_prior = financial_data.get("fiscal_year_prior") or "Prior Year"
    ticker   = st.session_state.get("resolved_ticker") or summary_data.get("ticker")

    st.subheader(company)
    _period_str = period or "Unknown period"
    st.caption(f"{_period_str}  ·  {currency}" if currency else _period_str)

    if (
        st.session_state.get("analysis_loaded_from_cache")
        and st.session_state.get("analysis_cache_is_stale")
    ):
        st.warning(
            f"⚠️ This analysis was saved with an older version of FinLens "
            f"and may display incorrect numbers or be missing fields. "
            f"Click **Re-Analyse $** above to refresh it with the current pipeline."
        )

    _fd_check = st.session_state.get("financial_data") or {}
    if _fd_check.get("currency") and _fd_check["currency"] != "USD":
        st.warning(f"⚠️ Financial data may not be normalized — currency: {_fd_check['currency']}")

    tab_stmts, tab_dash = st.tabs(["📊 Statements", "📈 Dashboard"])

    # =====================================================================
    with tab_stmts:
    # =====================================================================

        # --- Investment signal badge ---
        _BADGE_STYLE = {
            "PASS":        {"bg": "#052e16", "color": "#4ADE80", "border": "#166534"},
            "INVESTIGATE": {"bg": "#1C0F00", "color": "#FCD34D", "border": "#92400E"},
            "DECLINE":     {"bg": "#1F0000", "color": "#F87171", "border": "#991B1B"},
        }
        signal = (summary_data.get("signal") or "").upper()
        if signal in _BADGE_STYLE:
            s = _BADGE_STYLE[signal]
            st.markdown(
                f'<div style="display:inline-block;background:{s["bg"]};color:{s["color"]};'
                f'border:1px solid {s["border"]};'
                f'padding:8px 28px;border-radius:4px;font-size:18px;font-weight:700;'
                f'letter-spacing:1.5px;margin:6px 0 14px 0">{signal}</div>',
                unsafe_allow_html=True,
            )

        if st.button("Learn more about Investment Signals →", key="lm_investment_signals"):
            st.session_state["nav_mode"] = "Education"
            st.query_params["page"] = "education"

        if st.session_state.get("cache_hit"):
            st.info("📦 Using cached response (dev mode) — no API call was made.")

        if st.session_state.get("loaded_from_quick"):
            st.info("ℹ️ MD&A Sentiment not available for Quick Analysis — upload a PDF for full analysis")

        # --- Market data fetch (always visible) and display ---
        # Pre-populate the ticker input the first time results appear, or after a
        # new analysis — session state is set explicitly on analysis completion so
        # this guard is mainly a safety net for cloud cold-starts.
        if "manual_ticker" not in st.session_state:
            _auto = st.session_state.get("resolved_ticker") or (summary_data or {}).get("ticker") or ""
            if _auto:
                st.session_state["manual_ticker"] = _auto

        tk_col, btn_col = st.columns([2, 1])
        with tk_col:
            manual_ticker = st.text_input("Ticker Symbol", placeholder="e.g. MHH, AAPL", key="manual_ticker")
        with btn_col:
            st.write("")
            if st.button("Fetch Market Data", width='stretch', type="primary"):
                if manual_ticker.strip():
                    with st.spinner(f"Fetching market data for {manual_ticker.strip().upper()}..."):
                        fetched = get_market_data(manual_ticker.strip())
                        if fetched.get("current_price"):
                            st.session_state.market_data     = fetched
                            st.session_state.resolved_ticker = manual_ticker.strip().upper()
                            mc = fetched.get("market_cap") or 0.0
                            try:
                                st.session_state.excel_bytes = create_excel_file(
                                    st.session_state.financial_data,
                                    st.session_state.summary_data,
                                    mc,
                                    st.session_state.bear_bull_data,
                                )
                            except Exception as e:
                                st.error(f"Could not regenerate Excel: {e}")
                            st.rerun()
                        else:
                            st.warning(f"No market data found for '{manual_ticker.strip()}' — check the ticker and try again.")
                else:
                    st.warning("Enter a ticker symbol first.")

        if market_data.get("current_price"):
            price = market_data["current_price"]
            mc    = market_data["market_cap"]
            hi    = market_data.get("fifty_two_week_high")
            lo    = market_data.get("fifty_two_week_low")
            pe    = market_data.get("pe_ratio")

            price_str = f"${price:,.2f}"
            mc_str    = _fmt_market_cap(mc)
            range_str = f"${lo:,.2f} – ${hi:,.2f}" if (lo and hi) else "—"
            pe_str    = f"{pe:.1f}x" if pe else "—"

            st.info(
                f"**{ticker}**  ·  Price: {price_str}  ·  Mkt Cap: {mc_str}"
                f"  ·  52-week: {range_str}  ·  P/E (trailing): {pe_str}"
                f"  ·  *Data: yfinance, ~15-min delay*"
            )
            edgar_url = (
                f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                f"&CIK={ticker}&type=10-K&dateb=&owner=include&count=10"
            )
            st.markdown(
                f'<a href="{edgar_url}" target="_blank" '
                f'style="font-size:12px;color:#595959;text-decoration:none;">'
                f'&#128269; Find filings on SEC EDGAR</a>',
                unsafe_allow_html=True,
            )
        else:
            st.caption("No market data yet — enter the ticker above and click Fetch Market Data to populate live price, multiples, and Beta.")
        if st.button("Learn more about Market Data & Multiples →", key="lm_market_data"):
            st.session_state["nav_mode"] = "Education"
            st.query_params["page"] = "education"

        # --- Red Flag Analysis ---
        flag_result  = detect_flags(financial_data)
        flags        = flag_result["flags"]
        red_count    = flag_result["red_count"]
        yellow_count = flag_result["yellow_count"]
        override     = flag_result["signal_override"]

        if red_count or yellow_count:
            exp_label = f"🚩 Red Flag Analysis  —  {red_count} red · {yellow_count} yellow"
        else:
            exp_label = "🟢 Red Flag Analysis  —  Clean"

        if st.button("Learn more about Red Flag Analysis →", key="lm_red_flags"):
            st.session_state["nav_mode"] = "Education"
            st.query_params["page"] = "education"

        with st.expander(exp_label, expanded=(red_count > 0)):
            if not flags:
                st.success("No major red flags detected across all monitored thresholds.")
            else:
                if override:
                    claude_signal = (summary_data.get("signal") or "—").upper()
                    if override == claude_signal:
                        st.info(
                            f"Ratio analysis **confirms** Claude's **{claude_signal}** signal — "
                            f"{red_count} red flag(s), {yellow_count} yellow flag(s)."
                        )
                    else:
                        st.info(
                            f"**Signal override:** Ratio thresholds suggest **{override}** "
                            f"(Claude's signal: {claude_signal}) — "
                            f"{red_count} red flag(s), {yellow_count} yellow flag(s)."
                        )
                for flag in [f for f in flags if f["severity"] == "red"]:
                    st.error(f"🔴 **{flag['label']}** — {flag['detail']}")
                for flag in [f for f in flags if f["severity"] == "yellow"]:
                    st.warning(f"🟡 **{flag['label']}** — {flag['detail']}")

        # --- MD&A Sentiment ---

        if mda_sentiment and not mda_sentiment.get("error"):
            _tone = mda_sentiment.get("overall_tone") or "—"
            _scores = mda_sentiment.get("scores") or {}
            _phrases = mda_sentiment.get("key_phrases") or []
            _fo  = _scores.get("forward_outlook")
            _rld = _scores.get("risk_language_density")
            _mc  = _scores.get("management_confidence")

            _TONE_STYLE = {
                "Positive": {"bg": "#052e16", "color": "#4ADE80", "border": "#166534"},
                "Cautious":  {"bg": "#1C1200", "color": "#FCD34D", "border": "#92400E"},
                "Negative": {"bg": "#1F0000", "color": "#F87171", "border": "#991B1B"},
            }
            _ts = _TONE_STYLE.get(_tone, {"bg": "#1E2433", "color": "#94A3B8", "border": "#374B6B"})

            def _score_bar(label: str, value):
                if value is None:
                    return f'<div style="font-size:12px;color:#64748B">{label}: N/A</div>'
                filled = "■" * value
                empty  = "□" * (5 - value)
                return (
                    f'<div style="font-size:12px;color:#94A3B8;margin-bottom:4px">'
                    f'{label}: <span style="color:#378ADD;letter-spacing:2px">{filled}</span>'
                    f'<span style="color:#374B6B;letter-spacing:2px">{empty}</span>'
                    f' <span style="color:#64748B">({value}/5)</span></div>'
                )

            with st.expander("📝 MD&A Sentiment", expanded=False):
                if st.button("Learn more about MD&A Sentiment →", key="lm_mda_sentiment"):
                    st.session_state["nav_mode"] = "Education"
                    st.query_params["page"] = "education"
                tone_col, scores_col = st.columns([1, 2])

                with tone_col:
                    st.markdown(
                        f'<div style="background:{_ts["bg"]};border:1px solid {_ts["border"]};'
                        f'border-radius:8px;padding:16px 20px;text-align:center">'
                        f'<div style="font-size:11px;color:#64748B;letter-spacing:0.08em;'
                        f'text-transform:uppercase;margin-bottom:6px">Overall Tone</div>'
                        f'<div style="font-size:22px;font-weight:500;color:{_ts["color"]}">{_tone}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                with scores_col:
                    st.markdown(
                        _score_bar("Forward Outlook", _fo) +
                        _score_bar("Risk Language Density", _rld) +
                        _score_bar("Management Confidence", _mc),
                        unsafe_allow_html=True,
                    )

                if _phrases:
                    st.markdown("**Key Phrases**")
                    for phrase in _phrases:
                        st.markdown(
                            f'<blockquote style="border-left:3px solid #374B6B;'
                            f'margin:4px 0;padding:6px 12px;'
                            f'color:#94A3B8;font-size:13px;font-style:italic">'
                            f'{phrase}</blockquote>',
                            unsafe_allow_html=True,
                        )
        elif mda_sentiment and mda_sentiment.get("error"):
            st.caption(f"MD&A sentiment unavailable: {mda_sentiment['error']}")

        # --- Scenario Simulator ---
        if st.button("Learn more about Scenario Analysis →", key="lm_scenario"):
            st.session_state["nav_mode"] = "Education"
            st.query_params["page"] = "education"

        with st.expander("🔮 Scenario Simulator", expanded=False):
            _metrics = _calc_summary_metrics(financial_data)
            _base_gm = _metrics.get("gp_margin") or 50.0

            _sl1, _sl2 = st.columns(2)
            with _sl1:
                _rev_g  = st.slider("Revenue Growth (%)",        min_value=-30,   max_value=50,   value=0,   step=1,    key="ss_rev_g")
                _gm_pct = st.slider("Gross Margin (%)",          min_value=10.0,  max_value=90.0, value=round(float(_base_gm), 1), step=0.5, key="ss_gm")
            with _sl2:
                _opex_g = st.slider("OpEx Growth (%)",           min_value=-20,   max_value=30,   value=0,   step=1,    key="ss_opex_g")
                _ir_bps = st.slider("Interest Rate Change (bps)", min_value=-200,  max_value=200,  value=0,   step=25,   key="ss_ir")

            if st.button("Run Scenario $", key="ss_run", type="primary", width='stretch'):
                _sc_inputs = {
                    "revenue_growth_pct":       float(_rev_g),
                    "gross_margin_pct":         float(_gm_pct),
                    "opex_growth_pct":          float(_opex_g),
                    "interest_rate_change_bps": float(_ir_bps),
                }
                with st.spinner("Running scenario — calling Claude for narrative..."):
                    st.session_state["scenario_result"] = run_scenario(
                        financial_data, _sc_inputs, API_KEY, model=get_model()
                    )
            st.caption("~$0.01 per scenario")

            _sr = st.session_state.get("scenario_result")
            if _sr:
                if _sr.get("error"):
                    st.warning(f"Scenario failed: {_sr['error']}")
                else:
                    def _fmt_money(v):
                        if v is None:
                            return "N/A"
                        # Values are as-reported (e.g. 130497 when filing says "in millions").
                        # Scale to raw dollars before thresholding so $B/$M display correctly
                        # for large-caps (NVIDIA, Apple) and small-caps alike.
                        _cur = (financial_data.get("currency") or "").lower()
                        if "billion" in _cur:
                            _scale = 1_000_000_000
                        elif "million" in _cur:
                            _scale = 1_000_000
                        elif "thousand" in _cur:
                            _scale = 1_000
                        else:
                            _scale = 1
                        abs_v = abs(v) * _scale
                        sign  = "-" if v < 0 else ""
                        if abs_v >= 1_000_000_000_000:
                            return f"{sign}${abs_v / 1_000_000_000_000:.2f}T"
                        if abs_v >= 1_000_000_000:
                            return f"{sign}${abs_v / 1_000_000_000:.1f}B"
                        if abs_v >= 1_000_000:
                            return f"{sign}${abs_v / 1_000_000:.1f}M"
                        if abs_v >= 1_000:
                            return f"{sign}${abs_v / 1_000:.0f}K"
                        return f"{sign}${abs_v:,.0f}"

                    # Part 1 — Key Metrics
                    _sm1, _sm2, _sm3 = st.columns(3)
                    _bd   = _sr.get("base_distress_score")
                    _sd   = _sr.get("scenario_distress_score")
                    _dd   = _sr.get("distress_delta")
                    _dd_s = (f"{_dd:+.1f}" if _dd is not None else None)
                    _sm1.metric(
                        "Distress Score",
                        f"{_sd:.0f}/100" if _sd is not None else "N/A",
                        delta=_dd_s,
                        delta_color="inverse",  # lower is better, so red = higher
                    )
                    _sm2.metric("Scenario EBIT",    _fmt_money(_sr.get("scenario_ebit")))
                    _pe = _sr.get("implied_pe")
                    _sm3.metric("Implied P/E",      f"{_pe:.1f}x" if _pe else "N/A")

                    st.divider()

                    # Part 2 — Scenario vs Base comparison
                    _base_rev  = _metrics.get("rev_c")
                    _base_gp2  = _metrics.get("gp_c")
                    _base_ebit = None
                    _is_rows   = financial_data.get("income_statement", [])
                    from modules.excel_exporter import _lookup as _xlookup
                    _base_ebit = _xlookup(_is_rows, [
                        "income (loss) from operations", "income from operations",
                        "operating income", "operating profit",
                    ], "value")

                    _cmp1, _cmp2, _cmp3 = st.columns(3)
                    _s_rev  = _sr.get("scenario_revenue")
                    _s_gp   = _sr.get("scenario_gross_profit")
                    _s_ebit = _sr.get("scenario_ebit")

                    def _delta_pct(base, scenario):
                        if base and scenario:
                            return f"{((scenario - base) / abs(base) * 100):+.1f}%"
                        return None

                    _cmp1.metric("Revenue",      _fmt_money(_s_rev),  delta=_delta_pct(_base_rev,  _s_rev))
                    _cmp2.metric("Gross Profit", _fmt_money(_s_gp),   delta=_delta_pct(_base_gp2,  _s_gp))
                    _cmp3.metric("EBIT",         _fmt_money(_s_ebit), delta=_delta_pct(_base_ebit, _s_ebit))

                    # Part 3 — Claude Narrative
                    if _sr.get("narrative"):
                        st.info(_sr["narrative"])

        # --- Financial statement tables ---
        _is_fmp_source = financial_data.get("source") == "fmp"
        _has_prior_values = any(
            row.get("value_prior") is not None
            for section in ("income_statement", "balance_sheet", "cash_flow_statement")
            for row in financial_data.get(section, [])
            if row.get("row_type") != "section_header"
        )
        col_cfg = {
            "line_item":   st.column_config.TextColumn("Line Item"),
            "value_prior": st.column_config.NumberColumn(fy_prior, format="%.0f"),
            "value":       st.column_config.NumberColumn(fy,       format="%.0f"),
        }
        if _is_fmp_source and not _has_prior_values:
            col_cfg = {
                "line_item": st.column_config.TextColumn("Line Item"),
                "value":     st.column_config.TextColumn(fy),
            }
        elif _is_fmp_source:
            col_cfg = {
                "line_item":   st.column_config.TextColumn("Line Item"),
                "value_prior": st.column_config.TextColumn(fy_prior),
                "value":       st.column_config.TextColumn(fy),
            }

        def _display_rows(rows):
            if _is_fmp_source:
                def _fmt_fmp_statement_value(value):
                    if value is None:
                        return None
                    try:
                        raw_value = float(value) * (financial_data.get("scale") or 1)
                    except (TypeError, ValueError):
                        return None
                    sign = "-" if raw_value < 0 else ""
                    abs_value = abs(raw_value)
                    if abs_value >= 1_000_000_000_000:
                        return f"{sign}${abs_value / 1_000_000_000_000:,.2f}T"
                    if abs_value >= 1_000_000_000:
                        return f"{sign}${abs_value / 1_000_000_000:,.1f}B"
                    if abs_value >= 1_000_000:
                        return f"{sign}${abs_value / 1_000_000:,.1f}M"
                    return f"{sign}${abs_value:,.0f}"

                display = []
                for r in rows:
                    row = {
                        "line_item": r.get("line_item"),
                        "value": _fmt_fmp_statement_value(r.get("value")),
                    }
                    if _has_prior_values:
                        row["value_prior"] = _fmt_fmp_statement_value(r.get("value_prior"))
                    display.append(row)
                return display

            return [
                {"line_item": r.get("line_item"), "value_prior": r.get("value_prior"), "value": r.get("value")}
                for r in rows
            ]

        def _display_edgar_statement(rows):
            import html as _html

            body = ""
            for row in rows:
                line_item = _html.escape(str(row.get("line_item") or ""))
                if row.get("row_type") == "section_header":
                    body += (
                        f'<tr><td colspan="3" style="background:#1E293B;color:#F1F5F9;'
                        f'font-weight:700;text-transform:uppercase;letter-spacing:0.04em;'
                        f'padding:8px 10px;border-top:1px solid #334155;'
                        f'border-bottom:1px solid #334155">{line_item}</td></tr>'
                    )
                else:
                    prior = _fmt_edgar_value(row.get("value_prior")) or "—"
                    current = _fmt_edgar_value(row.get("value")) or "—"
                    body += (
                        f'<tr>'
                        f'<td>{line_item}</td>'
                        f'<td style="text-align:right">{prior}</td>'
                        f'<td style="text-align:right">{current}</td>'
                        f'</tr>'
                    )
            st.markdown(
                f"""
                <style>
                .edgar-statement-table {{
                    width: 100%;
                    border-collapse: collapse;
                    font-size: 13px;
                }}
                .edgar-statement-table th {{
                    color: #94A3B8;
                    font-weight: 700;
                    text-align: right;
                    border-bottom: 1px solid #2D3650;
                    padding: 7px 8px;
                }}
                .edgar-statement-table th:first-child {{
                    text-align: left;
                }}
                .edgar-statement-table td {{
                    color: #CBD5E1;
                    border-bottom: 1px solid #2D3650;
                    padding: 7px 8px;
                    vertical-align: top;
                }}
                </style>
                <table class="edgar-statement-table">
                    <thead>
                        <tr>
                            <th>Line Item</th>
                            <th>{_html.escape(str(fy_prior))}</th>
                            <th>{_html.escape(str(fy))}</th>
                        </tr>
                    </thead>
                    <tbody>{body}</tbody>
                </table>
                """,
                unsafe_allow_html=True,
            )

        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("**Income Statement**")
            rows = financial_data.get("income_statement", [])
            if rows:
                _display_edgar_statement(rows)
            else:
                st.info("Not found in document.")

        with col2:
            st.markdown("**Balance Sheet**")
            rows = financial_data.get("balance_sheet", [])
            if rows:
                _display_edgar_statement(rows)
            else:
                st.info("Not found in document.")

        with col3:
            st.markdown("**Cash Flow Statement**")
            rows = financial_data.get("cash_flow_statement", [])
            if rows:
                _display_edgar_statement(rows)
            else:
                st.info("Not found in document.")

        # --- Bull / Bear Case ---
        if st.button("Learn more about Financial Statements →", key="lm_financial_statements"):
            st.session_state["nav_mode"] = "Education"
            st.query_params["page"] = "education"

        if bear_bull_data and "error" not in bear_bull_data:
            with st.expander("Bull / Bear Case", expanded=False):
                bull_col, bear_col = st.columns(2)
                with bull_col:
                    st.markdown("**Bull Case**")
                    for pt in (bear_bull_data.get("bull_case") or [])[:3]:
                        st.markdown(f"**{pt.get('title', '')}**")
                        st.caption(pt.get("detail", ""))
                with bear_col:
                    st.markdown("**Bear Case**")
                    for pt in (bear_bull_data.get("bear_case") or [])[:3]:
                        st.markdown(f"**{pt.get('title', '')}**")
                        st.caption(pt.get("detail", ""))

        # --- Download buttons ---
        st.divider()
        filename      = f"FinLens_{company.replace(' ', '_')}_{fy}.xlsx"
        memo_filename = f"FinLens_Memo_{company.replace(' ', '_')}_{fy}.docx"

        try:
            memo_bytes = create_memo(financial_data, summary_data, bear_bull_data, market_data, flag_result)
        except Exception as e:
            memo_bytes = None
            st.warning(f"Memo generation failed: {e}")

        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            if excel_bytes:
                st.download_button(
                    label="Download FinLens Report",
                    data=excel_bytes,
                    file_name=filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width='stretch',
                    type="primary",
                )
        with dl_col2:
            if memo_bytes:
                st.download_button(
                    label="Download Investment Memo",
                    data=memo_bytes,
                    file_name=memo_filename,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    width='stretch',
                    type="secondary",
                )

        # --- Debug: Raw Extraction -----------------------------------------------
        with st.expander("🔬 Debug: Raw Extraction Output", expanded=False):
            st.caption(
                "Shows exactly what Claude extracted vs. what _calc_summary_metrics() resolved. "
                "Use this to diagnose — / N/A values in the Summary tab."
            )
            import json as _json

            _dbg_metrics = _calc_summary_metrics(financial_data)

            # Resolved metrics — what the Summary sheet actually uses
            st.markdown("**Resolved Metrics** (what the Summary tab renders)")
            _resolved_rows = [
                {"Metric": k, "Value": v}
                for k, v in _dbg_metrics.items()
            ]
            st.dataframe(_resolved_rows, width='stretch', hide_index=True)

            st.divider()

            # Raw line items — what Claude extracted from the PDF
            for _section_key, _section_label in [
                ("income_statement",    "Income Statement"),
                ("balance_sheet",       "Balance Sheet"),
                ("cash_flow_statement", "Cash Flow Statement"),
            ]:
                _rows = financial_data.get(_section_key, [])
                st.markdown(f"**{_section_label}** — {len(_rows)} line items extracted")
                if _rows:
                    st.dataframe(
                        [{"line_item": r.get("line_item"), "value": r.get("value"), "value_prior": r.get("value_prior")} for r in _rows],
                        width='stretch',
                        hide_index=True,
                    )
                else:
                    st.caption("No rows found.")
                st.write("")

    # =====================================================================
    with tab_dash:
    # =====================================================================

        metrics = _calc_summary_metrics(financial_data)
        dd = dashboard_data if dashboard_data and "error" not in dashboard_data else {}

        if dashboard_data and "error" in dashboard_data:
            st.error(
                f"Dashboard insights could not be generated: "
                f"{dashboard_data['error']}  \n"
                f"Re-analyse the filing to try again. "
                f"Ratio metrics and stress scenarios below are still available."
            )
        elif not dashboard_data:
            st.warning(
                "Dashboard insights were not generated for this filing. "
                "Re-analyse to run Call 4 (Dalio / Lynch / Marks frameworks)."
            )

        # --- Section 1: Header — Signal badge, thesis, Quality Score, Beta, MoS ---
        sig_col, qs_col, beta_col, mos_col = st.columns([3, 2, 2, 2])

        with sig_col:
            _BADGE_STYLE_D = {
                "PASS":        {"bg": "#052e16", "color": "#4ADE80", "border": "#166534"},
                "INVESTIGATE": {"bg": "#1C0F00", "color": "#FCD34D", "border": "#92400E"},
                "DECLINE":     {"bg": "#1F0000", "color": "#F87171", "border": "#991B1B"},
            }
            signal_d = (summary_data.get("signal") or "").upper()
            if signal_d in _BADGE_STYLE_D:
                s = _BADGE_STYLE_D[signal_d]
                st.markdown(
                    f'<div style="display:inline-block;background:{s["bg"]};color:{s["color"]};'
                    f'border:1px solid {s["border"]};'
                    f'padding:6px 22px;border-radius:4px;font-size:16px;font-weight:700;'
                    f'letter-spacing:1.5px;margin:4px 0 6px 0">{signal_d}</div>',
                    unsafe_allow_html=True,
                )
            thesis = summary_data.get("thesis") or ""
            if thesis:
                import html as _html
                st.markdown(
                    f'<p style="font-size:14px;color:#94A3B8;margin:4px 0 0 0;line-height:1.5">'
                    f'{_html.escape(thesis)}</p>',
                    unsafe_allow_html=True,
                )

        qs = _quality_score(metrics)
        qs_color = "#70AD47" if qs >= 70 else ("#FFC000" if qs >= 40 else "#C00000")

        with qs_col:
            st.markdown(
                f'<div style="border:1px solid #ddd;border-radius:6px;padding:12px 16px;text-align:center">'
                f'<div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px">Quality Score</div>'
                f'<div style="font-size:28px;font-weight:700;color:{qs_color}">{qs}</div>'
                f'<div style="font-size:10px;color:#aaa">/ 100</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            _learn_more("quality_score", "Quality Score")

        with beta_col:
            beta_val = market_data.get("beta")
            beta_str = f"{beta_val:.2f}" if beta_val else "—"
            st.markdown(
                f'<div style="border:1px solid #ddd;border-radius:6px;padding:12px 16px;text-align:center">'
                f'<div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px">Beta</div>'
                f'<div style="font-size:28px;font-weight:700">{beta_str}</div>'
                f'<div style="font-size:10px;color:#aaa">market sensitivity</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            _learn_more("beta", "Beta")

        with mos_col:
            _dcf_hdr = st.session_state.get("dcf_result") or {}
            _iv_hdr  = _dcf_hdr.get("intrinsic_value_per_share")
            _mos_hdr = _dcf_hdr.get("margin_of_safety_pct")
            if _iv_hdr is not None and _mos_hdr is not None:
                _mc = "#70AD47" if _mos_hdr > 20 else ("#FFC000" if _mos_hdr >= 0 else "#C00000")
                _lbl = "undervalued" if _mos_hdr > 0 else "overvalued"
                st.markdown(
                    f'<div style="border:1px solid #ddd;border-radius:6px;padding:12px 16px;text-align:center">'
                    f'<div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px">Margin of Safety</div>'
                    f'<div style="font-size:22px;font-weight:700">${_iv_hdr:,.2f}</div>'
                    f'<div style="font-size:16px;font-weight:700;color:{_mc}">{_mos_hdr:+.1f}%</div>'
                    f'<div style="font-size:10px;color:#aaa">{_lbl}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div style="border:1px solid #ddd;border-radius:6px;padding:12px 16px;text-align:center">'
                    f'<div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px">Margin of Safety</div>'
                    f'<div style="font-size:28px;font-weight:700">—</div>'
                    f'<div style="font-size:10px;color:#aaa">DCF required</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            _learn_more("margin_of_safety", "Margin of Safety")

        st.divider()

        # --- DCF Calculator ---
        st.markdown("#### DCF Calculator")
        _learn_more("dcf", "DCF Calculator")

        _dcf_c1, _dcf_c2, _dcf_c3, _dcf_c4 = st.columns([2, 2, 2, 1])
        with _dcf_c1:
            _wacc = st.number_input(
                "WACC (%)", min_value=5.0, max_value=25.0, value=10.0, step=0.5, key="dcf_wacc",
            )
        with _dcf_c2:
            _tgr = st.number_input(
                "Terminal Growth (%)", min_value=0.5, max_value=5.0, value=3.0, step=0.5, key="dcf_tgr",
            )
        with _dcf_c3:
            _rgr = st.number_input(
                "Revenue Growth (%)", min_value=-10.0, max_value=50.0, value=5.0, step=1.0, key="dcf_rgr",
            )
        with _dcf_c4:
            _fp = st.selectbox("Forecast Period", [5, 10], index=1, key="dcf_fp")

        if st.button("Calculate DCF", type="primary", key="dcf_calc_btn"):
            _md      = st.session_state.get("market_data") or {}
            _shr_raw = _md.get("shares_outstanding")
            _dcf_inp = {
                "wacc":                 _wacc,
                "terminal_growth_rate": _tgr,
                "forecast_period":      _fp,
                "revenue_growth_rate":  _rgr,
                "shares_outstanding":   _shr_raw / 1_000_000 if _shr_raw else None,
                "current_price":        _md.get("current_price"),
            }
            with st.spinner("Calculating DCF…"):
                st.session_state.dcf_result = calculate_dcf(financial_data, _dcf_inp)
            st.rerun()

        _dcf_res = st.session_state.get("dcf_result")
        if _dcf_res:
            if _dcf_res.get("error"):
                st.warning(f"DCF: {_dcf_res['error']}")
            else:
                def _fmt_dcf(v):
                    if v is None:
                        return "—"
                    av = abs(v)
                    if av >= 1_000_000_000_000:
                        return f"${v / 1_000_000_000_000:.2f}T"
                    if av >= 1_000_000_000:
                        return f"${v / 1_000_000_000:.2f}B"
                    if av >= 1_000_000:
                        return f"${v / 1_000_000:.1f}M"
                    return f"${v:,.0f}"

                _d1, _d2, _d3, _d4 = st.columns(4)
                with _d1:
                    st.metric("Base FCF", _fmt_dcf(_dcf_res["base_fcf"]))
                with _d2:
                    st.metric("PV of Forecast", _fmt_dcf(_dcf_res["pv_forecast"]))
                with _d3:
                    st.metric("PV of Terminal", _fmt_dcf(_dcf_res["pv_terminal"]))
                with _d4:
                    st.metric("Enterprise Value", _fmt_dcf(_dcf_res["enterprise_value"]))

                with st.expander("📊 Year-by-Year Forecast"):
                    _ft = _dcf_res.get("forecast_table", [])
                    if _ft:
                        st.dataframe(
                            [{"Year":           r["year"],
                              "Projected FCF":  _fmt_dcf(r["fcf"]),
                              "Discounted FCF": _fmt_dcf(r["discounted_fcf"])}
                             for r in _ft],
                            hide_index=True,
                            width='stretch',
                        )

        # --- Peer Comparison ---
        _peer_ticker = (st.session_state.get("manual_ticker") or ticker or "").strip().upper()
        if market_data.get("current_price") and _peer_ticker:
            st.markdown("#### Peer Comparison")
            _sector_options = list(peer_map.keys())
            _sector_hint = (
                financial_data.get("sector")
                or financial_data.get("sector_inferred")
                or summary_data.get("sector_inferred")
                or ""
            )
            _sector_idx = 0
            _auto_s = st.session_state.get("auto_sector")
            if _auto_s and _auto_s in _sector_options:
                _sector_idx = _sector_options.index(_auto_s)
            elif _sector_hint:
                _hint_l = _sector_hint.lower()
                for _i, _sector_name in enumerate(_sector_options):
                    if _sector_name.lower() in _hint_l or _hint_l in _sector_name.lower():
                        _sector_idx = _i
                        break

            _pc_sector_col, _pc_btn_col = st.columns([2, 1])
            with _pc_sector_col:
                _peer_sector = st.selectbox(
                    "Peer Sector",
                    _sector_options,
                    index=_sector_idx,
                    key="peer_sector",
                )
            with _pc_btn_col:
                st.write("")
                if st.button("Load Peer Comparison", width='stretch', key="peer_load_btn"):
                    with st.spinner("Fetching peer data from yfinance..."):
                        st.session_state["peer_data"] = get_peer_data(_peer_ticker, _peer_sector)

            _peer_data = st.session_state.get("peer_data")
            if _peer_data:
                if _peer_data.get("error"):
                    st.warning(_peer_data["error"])
                else:
                    import html as _html

                    _med = _peer_data.get("medians") or {}
                    _rows = [
                        {
                            "ticker": _peer_ticker,
                            "company": company,
                            "pe": market_data.get("pe_trailing") or market_data.get("pe_ratio"),
                            "ev_ebitda": market_data.get("ev_ebitda"),
                            "pb": market_data.get("pb"),
                            "ps": market_data.get("ps"),
                            "rev_growth": market_data.get("rev_growth"),
                            "gross_margin": market_data.get("gross_margin"),
                            "is_current": True,
                        }
                    ]
                    _rows.extend([{**row, "is_current": False} for row in (_peer_data.get("peers") or [])])
                    _rows.append({
                        "ticker": "Sector Median",
                        "company": "",
                        "pe": _med.get("pe"),
                        "ev_ebitda": _med.get("ev_ebitda"),
                        "pb": _med.get("pb"),
                        "ps": _med.get("ps"),
                        "rev_growth": _med.get("rev_growth"),
                        "gross_margin": _med.get("gross_margin"),
                        "is_median": True,
                    })

                    def _pc_num(v):
                        try:
                            return float(v) if v is not None else None
                        except Exception:
                            return None

                    def _pc_fmt(metric, value):
                        value = _pc_num(value)
                        if value is None:
                            return "—"
                        if metric in ("rev_growth", "gross_margin"):
                            return f"{value * 100:.1f}%"
                        return f"{value:.1f}x"

                    def _pc_cell(metric, value, is_median=False):
                        text = _pc_fmt(metric, value)
                        if is_median:
                            return f'<td style="font-weight:700;color:#F1F5F9">{text}</td>'
                        value = _pc_num(value)
                        median_value = _pc_num(_med.get(metric))
                        if value is None or median_value is None:
                            color = "#94A3B8"
                        else:
                            lower_better = metric in ("pe", "ev_ebitda", "pb", "ps")
                            better = value < median_value if lower_better else value > median_value
                            color = "#4ADE80" if better else "#F87171"
                        return f'<td style="color:{color};font-weight:600">{text}</td>'

                    _metric_cols = [
                        ("pe", "P/E"),
                        ("ev_ebitda", "EV/EBITDA"),
                        ("pb", "P/B"),
                        ("ps", "P/S"),
                        ("rev_growth", "Rev Growth %"),
                        ("gross_margin", "Gross Margin %"),
                    ]
                    _thead = (
                        "<tr><th>Ticker</th><th>Company</th>"
                        + "".join(f"<th>{label}</th>" for _, label in _metric_cols)
                        + "</tr>"
                    )
                    _tbody = ""
                    for row in _rows:
                        _is_current = row.get("is_current")
                        _is_median = row.get("is_median")
                        _row_style = (
                            "background:#10243A;border-left:3px solid #378ADD;"
                            if _is_current else
                            "background:#111827;font-weight:700;"
                            if _is_median else ""
                        )
                        _tbody += (
                            f'<tr style="{_row_style}">'
                            f'<td>{"<strong>" if _is_current or _is_median else ""}'
                            f'{_html.escape(str(row.get("ticker") or ""))}'
                            f'{"</strong>" if _is_current or _is_median else ""}</td>'
                            f'<td>{_html.escape(str(row.get("company") or ""))}</td>'
                            + "".join(_pc_cell(metric, row.get(metric), _is_median) for metric, _ in _metric_cols)
                            + "</tr>"
                        )

                    st.markdown(
                        f"""
                        <style>
                        .peer-table {{
                            width: 100%;
                            border-collapse: collapse;
                            font-size: 13px;
                        }}
                        .peer-table th {{
                            text-align: left;
                            color: #94A3B8;
                            font-weight: 700;
                            border-bottom: 1px solid #2D3650;
                            padding: 8px 10px;
                        }}
                        .peer-table td {{
                            border-bottom: 1px solid #2D3650;
                            padding: 8px 10px;
                            color: #CBD5E1;
                        }}
                        </style>
                        <table class="peer-table">
                            <thead>{_thead}</thead>
                            <tbody>{_tbody}</tbody>
                        </table>
                        """,
                        unsafe_allow_html=True,
                    )

        st.divider()

        # --- Section 2: Manager Framework Banners ---
        st.markdown("##### Framework Perspectives")
        fw_dalio, fw_lynch, fw_marks = st.columns(3)

        with fw_dalio:
            dalio_text = dd.get("dalio_view") or "Re-analyse to generate Dalio view."
            st.markdown(
                f'<div style="background:#EEEDFE;border-radius:8px;padding:16px 18px">'
                f'<div style="font-size:12px;font-weight:700;color:#5B4FCF;margin-bottom:8px;'
                f'text-transform:uppercase;letter-spacing:0.5px">Dalio — All Weather</div>'
                f'<div style="font-size:14px;color:#333;line-height:1.5">{dalio_text}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        with fw_lynch:
            lynch_cat  = dd.get("lynch_category") or ""
            lynch_text = dd.get("lynch_story") or "Re-analyse to generate Lynch view."
            cat_suffix = f" ({lynch_cat})" if lynch_cat else ""
            st.markdown(
                f'<div style="background:#E1F5EE;border-radius:8px;padding:16px 18px">'
                f'<div style="font-size:12px;font-weight:700;color:#217A4B;margin-bottom:8px;'
                f'text-transform:uppercase;letter-spacing:0.5px">Lynch — One Up{cat_suffix}</div>'
                f'<div style="font-size:14px;color:#333;line-height:1.5">{lynch_text}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        with fw_marks:
            marks_text = dd.get("marks_view") or "Re-analyse to generate Marks view."
            st.markdown(
                f'<div style="background:#FAEEDA;border-radius:8px;padding:16px 18px">'
                f'<div style="font-size:12px;font-weight:700;color:#B06000;margin-bottom:8px;'
                f'text-transform:uppercase;letter-spacing:0.5px">Marks — Second Level</div>'
                f'<div style="font-size:14px;color:#333;line-height:1.5">{marks_text}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.divider()

        # --- Section 3: Key Metrics Row ---
        st.markdown("##### Key Metrics")
        m1, m2, m3, m4, m5 = st.columns(5)

        rev_c    = metrics.get("rev_c")
        yoy_rev  = metrics.get("yoy_rev")
        gp_m     = metrics.get("gp_margin")
        ebitda_m = metrics.get("ebitda_margin")
        ni_c     = metrics.get("ni_c")
        ni_m     = metrics.get("ni_margin")
        fcf_c    = metrics.get("fcf_c")

        def _fmt_num(v):
            if v is None:
                return "—"
            if abs(v) >= 1_000_000_000_000:
                return f"{v / 1_000_000_000_000:,.2f}T"
            if abs(v) >= 1_000_000_000:
                return f"{v / 1_000_000_000:,.2f}B"
            if abs(v) >= 1_000_000:
                return f"{v / 1_000_000:,.1f}M"
            if abs(v) >= 1_000:
                return f"{v / 1_000:,.0f}K"
            return f"{v:,.0f}"

        def _fmt_pct(v):
            return f"{v:.1f}%" if v is not None else None

        with m1:
            st.metric("Revenue", _fmt_num(rev_c), _fmt_pct(yoy_rev))
        with m2:
            st.metric("Gross Margin", _fmt_pct(gp_m) or "—")
        with m3:
            st.metric("EBITDA Margin", _fmt_pct(ebitda_m) or "—")
        with m4:
            st.metric("Net Income", _fmt_num(ni_c), _fmt_pct(ni_m))
        with m5:
            st.metric("Free Cash Flow", _fmt_num(fcf_c))

        st.divider()

        # --- Section 4: Financial Health (RAG) | Capital Allocation ---
        rag_col, cap_col = st.columns(2)

        with rag_col:
            with st.container(border=True):
                st.markdown("##### Financial Health")
                rag_items = [
                    ("Liquidity",      "liquidity",  metrics.get("current_ratio")),
                    ("Leverage",       "leverage",   metrics.get("nd_ebitda")),
                    ("Revenue Growth", "rev_growth", metrics.get("rev_growth")),
                    ("FCF Conversion", "fcf_conv",   metrics.get("fcf_conv")),
                    ("Interest Cover", "int_cover",  metrics.get("int_cover")),
                ]
                for lbl, key, val in rag_items:
                    bg, rag_lbl = _dash_rag(key, val)
                    if val is None:
                        val_str = "—"
                    elif key in ("rev_growth", "fcf_conv"):
                        val_str = f"{val:.1f}%"
                    else:
                        val_str = f"{val:.2f}"
                    lbl_color = "#fff" if rag_lbl == "RED" else "#333"
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;align-items:center;'
                        f'padding:7px 4px;border-bottom:1px solid #f0f0f0">'
                        f'<span style="font-size:14px">{lbl}</span>'
                        f'<span>'
                        f'<span style="font-size:13px;margin-right:10px;color:#555">{val_str}</span>'
                        f'<span style="background:{bg};color:{lbl_color};padding:2px 10px;'
                        f'border-radius:3px;font-size:11px;font-weight:700">{rag_lbl}</span>'
                        f'</span></div>',
                        unsafe_allow_html=True,
                    )

        with cap_col:
            with st.container(border=True):
                st.markdown("##### Capital Allocation")
                cap_items = dd.get("capital_allocation") or []
                if cap_items:
                    for item in cap_items[:5]:
                        if isinstance(item, dict):
                            # prompt returns "label"/"value"; fall back to "title"/"detail" for safety
                            title  = item.get("label") or item.get("title", "")
                            detail = item.get("value") or item.get("detail", "")
                        else:
                            title, detail = str(item), ""
                        st.markdown(f"**{title}**")
                        if detail:
                            st.caption(detail)
                else:
                    st.caption("Re-analyse to generate capital allocation insights.")

        st.divider()

        # --- Section 5: Lynch Category | Lynch Story ---
        lc_col, ls_col = st.columns(2)

        with lc_col:
            with st.container(border=True):
                st.markdown("##### Lynch Category")
                _learn_more("lynch_category")
                cat = dd.get("lynch_category") or "—"
                st.markdown(f"**{cat}**")
                _LYNCH_DESCS = {
                    "Slow Grower":   "Low growth, often pays dividends. Watch for declining market share.",
                    "Stalwart":      "10–12% growers. Buy below P/E-to-growth rate; low institutional ownership.",
                    "Fast Grower":   "20–25% growers. Verify the niche, check balance sheet and P/E-to-growth.",
                    "Cyclical":      "Revenue tied to economic cycle. Buy at high P/E (trough), sell at low P/E (peak).",
                    "Turnaround":    "Depressed company with restructuring potential. Catalyst required.",
                    "Asset Play":    "Hidden balance sheet value overlooked by the market.",
                }
                desc = _LYNCH_DESCS.get(cat, "")
                if desc:
                    st.caption(desc)

        with ls_col:
            with st.container(border=True):
                st.markdown("##### Lynch Story")
                story = dd.get("lynch_story") or "Re-analyse to generate Lynch story."
                st.write(story)

        st.divider()

        # --- Section 6: Market Sentiment | Second-Level Question ---
        crowd_col, marks_col = st.columns(2)

        with crowd_col:
            with st.container(border=True):
                st.markdown("##### Market Sentiment (Marks)")
                crowd = dd.get("crowd_thinks") or "Re-analyse to generate sentiment view."
                st.write(crowd)

        with marks_col:
            with st.container(border=True):
                st.markdown("##### Second-Level Question")
                mq = dd.get("marks_question") or "Re-analyse to generate Marks question."
                st.write(mq)
                _mos_marks = (st.session_state.get("dcf_result") or {}).get("margin_of_safety_pct")
                if _mos_marks is not None:
                    _mos_mc = "#70AD47" if _mos_marks > 20 else ("#FFC000" if _mos_marks >= 0 else "#C00000")
                    st.markdown(
                        f'Margin of Safety: <span style="color:{_mos_mc};font-weight:700">'
                        f'{_mos_marks:+.1f}%</span>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.caption("Margin of Safety: — (DCF required)")

        st.divider()

        # --- Section 7: Dalio Stress Scenarios | Market Sensitivity ---
        stress_col, beta_col2 = st.columns(2)
        ic = metrics.get("int_cover")

        with stress_col:
            with st.container(border=True):
                st.markdown("##### Dalio Stress Scenarios")
                st.caption("Interest coverage (OI / Interest Expense) under stress")
                scenarios = [
                    ("EBIT –30%",             None if ic is None else ic * 0.70),
                    ("EBIT –60%",             None if ic is None else ic * 0.40),
                    ("Revenue –20% + Margin", None if ic is None else ic * 0.56),
                    ("Credit Seizure",        None if ic is None else ic * 0.50),
                ]
                for scen_name, stressed_ic in scenarios:
                    if stressed_ic is None:
                        status, bg, lbl_c = "N/A", "#D9D9D9", "#333"
                    elif stressed_ic >= 3.0:
                        status, bg, lbl_c = "SAFE", "#70AD47", "#fff"
                    elif stressed_ic >= 1.5:
                        status, bg, lbl_c = "WATCH", "#FFC000", "#333"
                    elif stressed_ic >= 1.0:
                        status, bg, lbl_c = "STRESS", "#FF8C00", "#fff"
                    else:
                        status, bg, lbl_c = "DISTRESS", "#C00000", "#fff"
                    ic_str = f"{stressed_ic:.1f}x" if stressed_ic is not None else "—"
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;align-items:center;'
                        f'padding:7px 4px;border-bottom:1px solid #f0f0f0">'
                        f'<span style="font-size:14px">{scen_name}</span>'
                        f'<span>'
                        f'<span style="font-size:13px;margin-right:10px;color:#555">{ic_str}</span>'
                        f'<span style="background:{bg};color:{lbl_c};padding:2px 10px;'
                        f'border-radius:3px;font-size:11px;font-weight:700">{status}</span>'
                        f'</span></div>',
                        unsafe_allow_html=True,
                    )

        with beta_col2:
            with st.container(border=True):
                st.markdown("##### Market Sensitivity (Beta)")
                b = market_data.get("beta")
                if b:
                    if b < 0.8:
                        interp = "Defensive — moves less than the market. Suitable for All-Weather positioning."
                    elif b < 1.2:
                        interp = "Market-neutral — tracks the index closely."
                    elif b < 1.8:
                        interp = "Cyclical — amplifies market moves. Higher upside, higher drawdown risk."
                    else:
                        interp = "High-beta — significantly more volatile than the market. Position size carefully."
                    st.metric("Beta (5Y Monthly)", f"{b:.2f}")
                    st.caption(interp)
                else:
                    st.caption("Beta not available — market data not loaded.")
                    st.caption("Fetch market data via the ticker lookup to populate this section.")

        st.divider()

        # --- Section 8: Variant Perception | Valuation Snapshot ---
        vp_col, val_col = st.columns([2, 1])

        with vp_col:
            with st.container(border=True):
                st.markdown("##### Variant Perception")
                st.caption("What does the market believe vs. what the data suggests?")
                crowd_txt = dd.get("crowd_thinks") or ""
                marks_q   = dd.get("marks_question") or ""
                if crowd_txt:
                    st.markdown(f"**Consensus view:** {crowd_txt}")
                if marks_q:
                    st.markdown(f"**What the market isn't asking:** {marks_q}")
                if not crowd_txt and not marks_q:
                    st.caption("Re-analyse to generate variant perception insights.")

        with val_col:
            with st.container(border=True):
                st.markdown("##### Valuation Snapshot")
                mc_val       = market_data.get("market_cap")
                pe_val       = market_data.get("pe_ratio")
                ebitda_c_val = metrics.get("ebitda_c")
                rev_c_val    = metrics.get("rev_c")

                ev_ebitda = None
                ev_rev    = None
                if mc_val and ebitda_c_val and ebitda_c_val > 0:
                    ev_ebitda = (mc_val * 1_000_000) / ebitda_c_val
                if mc_val and rev_c_val and rev_c_val > 0:
                    ev_rev = (mc_val * 1_000_000) / rev_c_val

                _mos_snap = (st.session_state.get("dcf_result") or {}).get("margin_of_safety_pct")
                for vname, vval in [
                    ("P/E",        f"{pe_val:.1f}x"       if pe_val      else "—"),
                    ("EV/EBITDA",  f"{ev_ebitda:.1f}x"    if ev_ebitda   else "—"),
                    ("EV/Revenue", f"{ev_rev:.2f}x"        if ev_rev      else "—"),
                    ("MoS",        f"{_mos_snap:+.1f}%"   if _mos_snap is not None else "—"),
                ]:
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;padding:5px 4px;'
                        f'border-bottom:1px solid #f0f0f0">'
                        f'<span style="font-size:14px;color:#555">{vname}</span>'
                        f'<span style="font-size:14px;font-weight:700">{vval}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

        st.divider()

        # --- Section 9: Bull / Bear with Framework Attribution ---
        st.markdown("##### Framework-Attributed Cases")
        bull_fw_col, bear_fw_col = st.columns(2)

        bull_cases = (bear_bull_data or {}).get("bull_case") or []
        bear_cases = (bear_bull_data or {}).get("bear_case") or []
        _BULL_FW = ["Lynch", "Marks", "Dalio"]
        _BEAR_FW = ["Marks", "Dalio", "Lynch"]

        with bull_fw_col:
            st.markdown("**Bull Case**")
            for i, pt in enumerate(bull_cases[:3]):
                fw     = _BULL_FW[i] if i < len(_BULL_FW) else ""
                title  = pt.get("title", "")
                detail = pt.get("detail", "")
                st.markdown(
                    f'<div style="background:#F0F7EC;border-left:4px solid #70AD47;'
                    f'padding:10px 14px;margin-bottom:8px;border-radius:0 6px 6px 0">'
                    f'<div style="font-size:11px;color:#4A7C35;font-weight:700;text-transform:uppercase;'
                    f'letter-spacing:0.5px;margin-bottom:4px">{fw}</div>'
                    f'<div style="font-size:14px;font-weight:600;margin-bottom:4px">{title}</div>'
                    f'<div style="font-size:13px;color:#555">{detail}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            if not bull_cases:
                st.caption("Re-analyse to generate bull case.")

        with bear_fw_col:
            st.markdown("**Bear Case**")
            for i, pt in enumerate(bear_cases[:3]):
                fw     = _BEAR_FW[i] if i < len(_BEAR_FW) else ""
                title  = pt.get("title", "")
                detail = pt.get("detail", "")
                st.markdown(
                    f'<div style="background:#FDF2F2;border-left:4px solid #C00000;'
                    f'padding:10px 14px;margin-bottom:8px;border-radius:0 6px 6px 0">'
                    f'<div style="font-size:11px;color:#8B0000;font-weight:700;text-transform:uppercase;'
                    f'letter-spacing:0.5px;margin-bottom:4px">{fw}</div>'
                    f'<div style="font-size:14px;font-weight:600;margin-bottom:4px">{title}</div>'
                    f'<div style="font-size:13px;color:#555">{detail}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            if not bear_cases:
                st.caption("Re-analyse to generate bear case.")

        st.caption("Powered by Dalio · Lynch · Marks frameworks")

else:
    if not uploaded_file:
        st.info("Upload a PDF above to get started.")
