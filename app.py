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

# streamlit-cookies-manager still decorates a helper with the deprecated
# st.cache at import time, which paints a deprecation banner into the app on
# every boot. Point st.cache at st.cache_data (ignoring legacy kwargs) before
# the import runs. The decorated helper lives in EncryptedCookieManager,
# which FinLens does not use.
def _quiet_cache(func=None, **_legacy_kwargs):
    if func is None:
        return st.cache_data
    return st.cache_data(func)

st.cache = _quiet_cache
from streamlit_cookies_manager import CookieManager

from modules.pdf_extractor import extract_text_from_pdf
from modules.document_converter import convert_to_markdown
from sedar_extractor import (
    SedarExtractionError,
    attach_mapping,
    extract_hedging_note,
    extract_mda_metrics,
    extract_sedar_filing,
)
from modules.claude_analyzer import (
    FabricatedExtractionError,
    analyze_financials,
    analyze_summary,
    analyze_bear_bull,
    analyze_dashboard_insights,
    analyze_mda_sentiment,
    build_filing_context,
    is_legacy_scaled_financial_data_stale,
    is_truncated_excerpt,
    is_per_share_line_item,
    normalize_financial_data,
    normalize_and_validate,
)
from modules.integrity import cross_validate_filing
from modules.integrity.sedar_mapper import mapper_version, sedar_mapping_is_stale
from modules.integrity.receipts import (
    integrity_receipt_rows,
    integrity_status_badge,
    mapping_receipt_rows,
)
from modules.integrity.document_class import (
    DOC_CLASS_EXTRACTION_EMPTY,
    DOC_CLASS_MDA,
    DOC_CLASS_NO_STATEMENTS,
    DOC_CLASS_STATEMENTS_UNAUDITED,
    classify_document_text,
    mda_refusal_message,
    refusal_message,
    unaudited_warning_message,
)
from modules.filing_comparison import compare_filings
from modules.scenario_simulator import run_scenario
from modules.excel_exporter import create_excel_file, _calc_summary_metrics, two_year_statement_pairs
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
from modules.peer_comparison import get_peer_data, peer_map, suggest_sector
from modules.dcf_calculator import calculate_dcf
from modules.economics.resource_display import build_commodity_display_text
from modules.economics.resource_economics import build_resource_economics_snapshot
from modules.agent_fetch import (
    FetchedUpload,
    build_provenance,
    cache_fetched_pdf,
    fetch_pdf_bytes,
    gateway_config,
    request_filing_url,
    safe_fetch_filename,
)
from modules.campaign_pdf import resolve_campaign_pdf
from modules.cache import get_cache_key, load_cache, save_cache, clear_cache, cache_count
from modules.analysis_cache import CURRENT_SCHEMA_VERSION, load_analysis, save_analysis
from modules.analysis.munger_inversion import generate_inversion
from modules.analysis.inversion_store import inversion_exists, load_inversion, save_inversion
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
from config import (
    EXTRACTION_MODEL,
    ANALYSIS_MODEL,
    MAX_FILING_CHARS,
    ANALYSIS_CACHE_DIR,
    CACHE_DIR,
    EDGAR_TEXT_DIR,
    LIBRARY_DIR,
    LIBRARY_PDF_CACHE_DIR,
    LIBRARY_PDFS_DIR,
    FILING_LIBRARY_PATH,
    YFINANCE_CACHE_DIR,
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

MODEL_OPTIONS = {
    "Haiku 4.5": "claude-haiku-4-5-20251001",
    "Sonnet 5": "claude-sonnet-5",
    "Opus 4.8": "claude-opus-4-8",
    "Fable 5": "claude-fable-5",
}
DEFAULT_MODEL_LABEL = next(
    (label for label, model in MODEL_OPTIONS.items() if model == ANALYSIS_MODEL),
    "Sonnet 5",
)


def _get_filing_context(filing_text: str, ticker: str | None, period: str | None) -> list:
    ticker_key = (ticker or "unknown").strip().upper() or "unknown"
    period_key = re.sub(r"\s+", "_", (period or "unknown").strip()) or "unknown"
    # Text length in the key keeps contexts built from different text for the
    # same filing apart — without it, a context built from empty or truncated
    # text earlier in the session would be silently reused by Re-Analyse (and
    # its blocks are exactly what Call 1's figure-presence guard checks).
    cache_key = f"filing_context::{ticker_key}::{period_key}::{len(filing_text or '')}"
    if cache_key not in st.session_state:
        st.session_state[cache_key] = build_filing_context(filing_text)
    return st.session_state[cache_key]


def get_model():
    selected_label = st.session_state.get("analysis_model_label", DEFAULT_MODEL_LABEL)
    return MODEL_OPTIONS.get(selected_label, ANALYSIS_MODEL)


def get_model_label():
    selected_label = st.session_state.get("analysis_model_label", DEFAULT_MODEL_LABEL)
    if selected_label in MODEL_OPTIONS:
        return selected_label
    return DEFAULT_MODEL_LABEL


def _selected_model_cache_part() -> str:
    return re.sub(r"[^\w\-]", "_", get_model())


def get_mda_model():
    return EXTRACTION_MODEL


def _gate_document_class(raw_text: str | None, *, warn_only: bool = False) -> dict:
    """CB-015 ingest gate: classify extracted document text BEFORE any Claude
    spend. no_statements_detected / extraction_empty -> honest refusal
    (st.error + st.stop) on analysis flows — analyzing a statements-less
    document guarantees a confident wrong-class analysis. statements_unaudited
    -> warn banner and proceed (interim packs are sanctioned: CNQ FY2024 is a
    corpus fixture). warn_only=True (Filing Comparison) downgrades the refusal
    to a warning. Returns the classification dict for attachment to
    financial_data["document_class"]."""
    result = classify_document_text(raw_text)
    doc_class = result["document_class"]
    signals = result["signals"]

    if doc_class == DOC_CLASS_EXTRACTION_EMPTY:
        if warn_only:
            st.warning("Very little text was extracted from this document — the comparison may be unreliable.")
        else:
            st.error(
                "Very little text was extracted — the file may be scanned/image-based or empty. "
                "Try a text-based PDF or a Word document with readable text content."
            )
            st.stop()
    elif doc_class == DOC_CLASS_NO_STATEMENTS:
        if warn_only:
            st.warning(refusal_message(signals))
        else:
            st.error(refusal_message(signals))
            st.stop()
    elif doc_class == DOC_CLASS_MDA:
        # A standalone MD&A is still refused for STATEMENT analysis — the
        # class exists so the MD&A-metrics lane can accept it separately
        # (docs/MDA_FETCHER_SPEC.md Stage 0).
        if warn_only:
            st.warning(mda_refusal_message(signals))
        else:
            st.error(mda_refusal_message(signals))
            st.stop()
    elif doc_class == DOC_CLASS_STATEMENTS_UNAUDITED:
        st.warning(unaudited_warning_message(signals))
    return result


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

    # When ticker resolution fails, log under the company name so the entry
    # is identifiable. The engine still runs every rule whose required fields
    # are present — field_unavailable skips remain honest for missing data.
    ticker_unresolved = not bool(ticker_value)
    log_identity = ticker_value
    if ticker_unresolved:
        log_identity = (
            (summary_data or {}).get("company_name")
            or (summary_data or {}).get("company")
            or financial_data.get("company_name")
            or financial_data.get("company")
            or "Unknown"
        )

    filing_metadata = {
        "source": source,
        "filing_date": filing_date,
        "accession": accession,
        "ticker_unresolved": ticker_unresolved,
    }

    try:
        normalize_and_validate(financial_data, log_identity, sector_value, filing_metadata)
    except Exception:
        logger.exception("Integrity validation failed for %s", log_identity)

    if ticker_unresolved and isinstance(financial_data.get("_integrity"), dict):
        st.info(
            "Integrity check validated under company name — ticker could not be "
            "resolved, so external cross-validation was skipped."
        )

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
LIBRARY_PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
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


def _ensure_yfinance_cache_location():
    try:
        YFINANCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        yf.set_tz_cache_location(str(YFINANCE_CACHE_DIR))
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


def _escape_md_dollars(text: str) -> str:
    """Escape bare $ in model-generated text so Streamlit doesn't render it as LaTeX math."""
    return (text or "").replace("$", r"\$")


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


def _quality_score(m: dict) -> tuple[int | None, int]:
    """(score, metrics_available): 0–100 quality score over the AVAILABLE
    RAG health metrics only (Green=20, Amber=10, Red=0, rescaled to the
    available maximum). Missing data is not poor quality — a sparse
    extraction must not score like a distressed company. Returns (None, 0)
    when no metrics are available."""
    def pts(metric, value):
        if metric == "liquidity":  return 20 if value >= 2.0 else (10 if value >= 1.0 else 0)
        if metric == "leverage":   return 20 if value <= 1.5 else (10 if value <= 3.0 else 0)
        if metric == "rev_growth": return 20 if value >= 5.0 else (10 if value >= 0.0 else 0)
        if metric == "fcf_conv":   return 20 if value >= 100.0 else (10 if value >= 50.0 else 0)
        if metric == "int_cover":  return 20 if value >= 3.0 else (10 if value >= 1.5 else 0)
        if metric == "debt_equity": return 20 if value <= 1.0 else (10 if value <= 2.0 else 0)
        return 0

    checks = [
        ("liquidity",  m.get("current_ratio")),
        ("leverage",   m.get("nd_ebitda")),
        ("debt_equity", m.get("de_ratio")),
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
        return None, 0
    return round(earned / (available * 20) * 100), available


def _dash_rag(metric: str, value) -> tuple:
    """Return (bg_hex, label) for dashboard RAG cells — mirrors excel_exporter thresholds."""
    if value is None:
        return "rgba(148,163,184,0.25)", "N/A"
    if metric == "liquidity":  c = "G" if value >= 2.0 else ("A" if value >= 1.0 else "R")
    elif metric == "leverage": c = "G" if value <= 1.5 else ("A" if value <= 3.0 else "R")
    elif metric == "rev_growth": c = "G" if value >= 5.0 else ("A" if value >= 0.0 else "R")
    elif metric == "fcf_conv": c = "G" if value >= 100.0 else ("A" if value >= 50.0 else "R")
    elif metric == "int_cover": c = "G" if value >= 3.0 else ("A" if value >= 1.5 else "R")
    elif metric == "debt_equity": c = "G" if value <= 1.0 else ("A" if value <= 2.0 else "R")
    else: return "#D9D9D9", "N/A"
    return {"G": ("#70AD47", "GREEN"), "A": ("#FFC000", "AMBER"), "R": ("#C00000", "RED")}[c]


def _pdf_cache_path(ticker: str | None, period: str | None) -> str | None:
    """Return disk cache path for a filing PDF, or None if ticker/period unavailable."""
    if not ticker or not period:
        return None
    safe = re.sub(r"[^\w\-]", "_", f"{ticker}_{period}")
    return str(LIBRARY_PDF_CACHE_DIR / f"{safe}.pdf")


def _library_pdf_cache_path(entry: dict) -> str | None:
    ticker = entry.get("ticker")
    if ticker == "—":
        ticker = None
    period = entry.get("fiscal_year") or entry.get("period", "")
    return _pdf_cache_path(ticker, period)


def _reanalyse_pdf_path_for_entry(entry: dict) -> str | None:
    """On-disk PDF path for a paid Re-Analyse of a SEDAR entry, or None.

    Chain: the per-entry PDF cache (pdfs/_cache/), then — for registry-loaded
    entries, which store no bytes by design — the canonical campaign PDF
    resolved by its recorded filename in ~/.finlens/pdfs
    (modules/campaign_pdf.py, per docs/CAMPAIGN_PDF_RESOLVER_SPEC.md).

    Closes the registry-entry Re-Analyse dead-end (queued 2026-07-02, hit
    live on ARX 2026-07-10): the honest "SEDAR+ PDF is no longer cached"
    error fired even though the canonical PDF sat on disk one directory up.
    """
    cached = _library_pdf_cache_path(entry)
    if cached and Path(cached).exists():
        return cached
    entry_id = str(entry.get("id", ""))
    if entry_id.startswith("registry::"):
        for filing in _load_filing_registry().get("filings") or []:
            if _registry_entry_id(filing) == entry_id:
                resolved = resolve_campaign_pdf(filing)
                if resolved is not None:
                    return str(resolved)
                break
    return None


def _hedging_pdf_path_for_current(ticker: str | None, financial_data: dict | None) -> str | None:
    """On-disk PDF for the currently loaded SEDAR filing (hedging-note pass).

    Chain: the per-filing PDF cache (upload flow caches there), then the
    canonical campaign PDF via the registry (registry loads store no bytes;
    matched by ticker root + fiscal year digits since the entry id isn't in
    scope at render time). Same resolution family as
    _reanalyse_pdf_path_for_entry.
    """
    fd = financial_data or {}
    period = fd.get("fiscal_year") or fd.get("period") or ""
    cached = _pdf_cache_path(ticker, period)
    if cached and Path(cached).exists():
        return cached
    root = (ticker or "").split(".")[0].upper()
    year_match = re.search(r"(\d{4})", str(period))
    year = year_match.group(1) if year_match else None
    if not root or not year:
        return None
    for filing in _load_filing_registry().get("filings") or []:
        f_ticker = str(filing.get("ticker") or "").split(".")[0].upper()
        f_year = re.search(r"(\d{4})", str(filing.get("fiscal_year") or ""))
        if f_ticker == root and f_year and f_year.group(1) == year:
            resolved = resolve_campaign_pdf(filing)
            if resolved is not None:
                return str(resolved)
    return None


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


def _reanalyse_text_for_entry(entry: dict) -> str | None:
    """Full-document text for Re-Analyse, or None when only a truncated excerpt exists.

    Extraction (Call 1) needs the full document — its input windows and the
    figure-presence guard assume the financial statements are present, and an
    80K analysis excerpt usually ends before them. Returning None routes the
    caller to PDF re-extraction or an honest error instead of a doomed
    extraction call (fabrication fix (b), reference: NVDA FY2026 incident).
    """
    text = _library_text_for_entry(entry)
    if is_truncated_excerpt(text):
        return None
    return text


def _dashboard_or_none(dashboard_data):
    """Treat a persisted Call 4 failure as missing dashboard insights.

    Six corpus library entries stored {"error": "Call 4 failed..."} dicts from
    the pre-2026-07-11 max_tokens=1200 truncation bug. A stored error-dict is
    not None, so the load-time regeneration (the `if dashboard_data is None`
    branch on the dashboard) never fired and the error banner persisted
    forever. Returning None here lets that regeneration heal the entry on its
    next load — one cheap Call 4, no full Re-Analyse needed.
    """
    if isinstance(dashboard_data, dict) and dashboard_data.get("error"):
        return None
    return dashboard_data


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

    # Derived metrics are deliberately NOT stored: every consumer recomputes
    # _calc_summary_metrics(financial_data) at render time, so a stored copy
    # can only drift from the live derivation (a pre-1cc9fd9 snapshot would
    # still carry the OCF-mislabelled-as-FCF value). financial_data is the
    # stored source of truth; derivations stay live.

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
    if not ticker or not period:
        return False
    return save_analysis(ticker, f"{period}_{_selected_model_cache_part()}", payload)


def _legacy_scaled_stale(financial_data: dict | None, schema_version: object) -> bool:
    return is_legacy_scaled_financial_data_stale(
        financial_data or {},
        schema_version,
        CURRENT_SCHEMA_VERSION,
    )


def _fetch_market_data_for_filing(ticker: str | None, financial_data: dict | None) -> dict:
    """Load-time market fetch through the wrong-issuer guard (free yfinance
    call, no Claude spend). Library/registry entries store the analysis-time
    market snapshot, which is stale by construction (prices move) and, for
    entries that never fetched, empty — leaving Beta/valuation dark and
    steering users to the unguarded manual lookup (the ARX/Accelerant path).
    Returns {} when no ticker is available or the fetch fails."""
    if not ticker or ticker == "—":
        return {}
    try:
        fd = financial_data or {}
        return get_market_data(
            ticker,
            company_name=fd.get("company_name"),
            prefer_canadian=fd.get("source") == "sedar_pdf",
        )
    except Exception:
        return {}


def _restore_analysis_cache(cached: dict, entry: dict | None = None) -> bool:
    financial_data = cached.get("financial_data")
    if not isinstance(financial_data, dict):
        return False
    if _legacy_scaled_stale(financial_data, cached.get("schema_version")):
        return False
    financial_data = normalize_financial_data(_heal_sedar_mapping(financial_data))

    summary_data = cached.get("summary_data") or cached.get("summary")
    bear_bull_data = cached.get("bear_bull_data") or cached.get("bear_bull")
    dashboard_data = _dashboard_or_none(
        cached.get("dashboard_data") or cached.get("dashboard_insights")
    )
    market_data = cached.get("market_data") or {}
    if not market_data and cached.get("market_cap") is not None:
        market_data = {"market_cap": cached.get("market_cap")}
    if not market_data.get("current_price"):
        # Stored snapshot is empty/priceless — fetch fresh through the guard.
        _live_md = _fetch_market_data_for_filing(
            cached.get("ticker") or (entry or {}).get("ticker"), financial_data
        )
        if _live_md.get("current_price"):
            market_data = _live_md

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


# CB-016: period-column selection extracted to modules/sedar_periods.py so
# it is testable and carries the same annual preference as the canonical
# mapper (the mixed-period drift fix).
from modules.sedar_periods import (  # noqa: E402
    parse_period_window as _parse_period_window,
    sedar_period_keys as _sedar_period_keys,
    sedar_statement_rows as _sedar_statement_rows,
)


def _sedar_currency_label(extraction_result: dict) -> str:
    return str(extraction_result.get("currency") or "").strip()


def _prettify_currency_label(currency: str) -> str:
    """Display-only polish for the header's currency label.

    Extraction labels echo the filing's scale wording ("CAD, in actual",
    "CAD, in ones") which reads awkwardly in the header. Only the display
    changes — the stored label stays verbatim because downstream consumers
    (resource_economics currency guard) parse the raw form.
    """
    label = str(currency or "").strip()
    lowered = label.lower()
    for suffix in (", in actual", ", in ones", ", in units"):
        if lowered.endswith(suffix):
            return f"{label[: -len(suffix)]}, actual dollars"
    return label


def _sedar_extraction_to_financial_data(
    extraction_result: dict,
    file_name: str,
    company_name: str | None = None,
    ticker: str | None = None,
) -> dict:
    statements = extraction_result.get("statements") or {}
    mapping = extraction_result.get("mapping") or {}
    income_current, income_prior = _sedar_period_keys(statements.get("income_statement", []))
    balance_current, balance_prior = _sedar_period_keys(statements.get("balance_sheet", []))
    cash_flow_current, cash_flow_prior = _sedar_period_keys(statements.get("cash_flow", []))

    financial_data = {
        "source": "sedar_pdf",
        "ticker": ticker,
        "company_name": company_name or extraction_result.get("company_name") or file_name,
        "company": company_name or extraction_result.get("company_name") or file_name,
        "period": extraction_result.get("fiscal_year_end") or income_current,
        "currency": _sedar_currency_label(extraction_result),
        "scale": extraction_result.get("scale"),
        "fiscal_year": income_current,
        "fiscal_year_prior": income_prior or "Prior",
        "accounting_standard": extraction_result.get("accounting_standard"),
        # Boundary normalization: the filing's inferred sector must ride at the
        # top level so consumers (peer comparison, inversion panel, library
        # views) never have to dig into sedar_extraction for it.
        "sector_inferred": extraction_result.get("sector_inferred"),
        "extraction_confidence": extraction_result.get("extraction_confidence"),
        "pages_used": extraction_result.get("pages_used"),
        "mapping": mapping,
        "sedar_extraction": extraction_result,
        "sedar_filing_date": extraction_result.get("filing_date"),
        "income_statement": _sedar_statement_rows(
            statements.get("income_statement", []),
            income_current,
            income_prior,
        ),
        "balance_sheet": _sedar_statement_rows(
            statements.get("balance_sheet", []),
            balance_current,
            balance_prior,
        ),
        "cash_flow_statement": _sedar_statement_rows(
            statements.get("cash_flow", []),
            cash_flow_current,
            cash_flow_prior,
        ),
    }

    for field, mapped in (mapping.get("mapped") or {}).items():
        if isinstance(mapped, dict):
            financial_data[field] = mapped.get("value")

    # Stamp the mapper version so a later load can tell whether this analysis's
    # mapping predates a mapper/alias improvement and heal it for free.
    financial_data["_mapper_version"] = mapper_version()

    return financial_data


def _heal_sedar_mapping(financial_data: dict) -> dict:
    """Re-map a stored SEDAR analysis with the CURRENT mapper when its cached
    mapping predates a mapper/alias improvement.

    Deterministic and FREE — no Claude call — because the full extraction (with
    statements) rides along in financial_data['sedar_extraction']. Rebuilds
    financial_data exactly as a fresh extraction would (un-normalized), so the
    caller's normalize_financial_data scales it on the same basis. Returns the
    input unchanged when it is not a stale, re-mappable SEDAR analysis, and never
    raises — a heal failure must never break a load.
    """
    if not sedar_mapping_is_stale(financial_data, mapper_version()):
        return financial_data
    try:
        healed_extraction = attach_mapping(financial_data["sedar_extraction"])
        healed = _sedar_extraction_to_financial_data(
            healed_extraction,
            file_name=financial_data.get("company_name") or "",
            company_name=financial_data.get("company_name"),
            ticker=financial_data.get("ticker"),
        )
        # The hedging book and MD&A metrics are separate PAID extractions
        # stored top-level — a free re-map must never drop them (CB-034
        # precedent; MDA_FETCHER_SPEC Stage 2; sibling-path check).
        if isinstance(financial_data.get("hedging_book"), dict):
            healed["hedging_book"] = financial_data["hedging_book"]
        if isinstance(financial_data.get("mda_metrics"), dict):
            healed["mda_metrics"] = financial_data["mda_metrics"]
        return healed
    except Exception:
        return financial_data


# --- Registry-backed library load -------------------------------------------
# NOTE: The filing library is currently a single SHARED session — there is no
# per-user (Supabase) isolation yet. This registry-load surface is for Riley's
# own use right now. Before it becomes a signup pre-seed feature, per-user
# library isolation must be sorted (tracked in pre-commercial priorities). Do
# not treat loaded registry filings as user-scoped until that lands.
#
# Loading a registry filing is FREE and INSTANT: it reads the committed fixture
# JSON and registers it as a library entry. NO Claude API call, NO pipeline
# re-run, NO integrity-log write — each fixture already carries validated
# financials + mapping. The registry file itself is READ-ONLY from the
# library's perspective: library load/delete never modifies it.
_REGISTRY_PATH = Path(__file__).resolve().parent / "tests" / "fixtures" / "filing_registry.json"


def _load_filing_registry() -> dict:
    """Read the committed master filing registry (read-only catalog).

    Cached in session state so the file is not re-read on every Streamlit
    rerun. The registry is the source catalog that library entries are loaded
    *from* — it is never written by library operations.
    """
    cached = st.session_state.get("filing_registry_cache")
    if cached is not None:
        return cached
    try:
        with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
            registry = json.load(f)
    except Exception as e:
        logger.warning(f"Could not read filing registry: {e}")
        registry = {"filings": [], "registry_notes": []}
    st.session_state["filing_registry_cache"] = registry
    return registry


def _registry_entry_id(filing: dict) -> str:
    """Stable, deterministic library id for a registry filing.

    Derived from the fixture filename so re-loading the same registry filing
    updates in place (lib_add is keyed on id) instead of duplicating, and so
    'already loaded' detection is reliable.
    """
    stem = Path(filing.get("fixture_path", "")).stem
    if not stem:
        stem = f"{filing.get('ticker', 'NA')}_{filing.get('fiscal_year', '')}"
    return f"registry::{stem}"


def _load_registry_filing_into_library(filing: dict) -> tuple[bool, str]:
    """Read a registry filing's fixture and register it as a library entry.

    Free + instant + deterministic. Converts the committed fixture JSON to
    financial_data via the same SEDAR converter the upload path uses, then
    stores it via lib_add. No AI analysis is attached (thesis/Dalio/Lynch/
    Marks) — running analysis is a separate, paid action.

    Returns (loaded, message). loaded=False means it was skipped (already in
    the library, or the fixture is missing/unreadable).
    """
    fixture_rel = filing.get("fixture_path", "")
    # Registry fixture_paths are repo-relative; resolve against app.py's dir
    # (the repo root). The registry's source_pdf_paths are Riley's local
    # absolute paths and are intentionally NOT used for loading.
    fixture_abs = Path(__file__).resolve().parent / fixture_rel
    if not fixture_rel or not fixture_abs.exists():
        return False, f"fixture missing: {fixture_rel or '(no path)'}"

    entry_id = _registry_entry_id(filing)
    if any(e.get("id") == entry_id for e in lib_get()):
        return False, "already loaded"

    try:
        with open(fixture_abs, "r", encoding="utf-8") as f:
            extraction_result = json.load(f)
    except Exception as e:
        return False, f"could not read fixture: {e}"

    ticker = filing.get("ticker")
    company_name = filing.get("company_name")
    file_name = Path(fixture_rel).name

    financial_data = _sedar_extraction_to_financial_data(
        extraction_result,
        file_name,
        company_name=company_name,
        ticker=ticker,
    )
    # Pin the period label to the registry's authoritative fiscal_year so the
    # library row matches the catalog (the converter infers it from the
    # statement period keys, which can differ in formatting).
    if filing.get("fiscal_year"):
        financial_data["fiscal_year"] = filing["fiscal_year"]

    # Minimal summary_data carries only the ticker so the library row groups
    # correctly. No investment signal / thesis — this is a financials-only
    # load by design.
    summary_data = {"ticker": ticker} if ticker and ticker != "—" else None

    try:
        lib_add(
            entry_id,
            file_name,
            0,  # no PDF bytes — loaded from a committed fixture, not a file
            financial_data,
            summary_data,
            None,   # bear_bull_data — no AI analysis on a free load
            None,   # dashboard_data — no AI analysis on a free load
            raw_text=None,
            mda_sentiment=None,
            source="sedar",
            file_type="pdf",
        )
    except Exception as e:
        return False, f"load failed: {e}"
    return True, "loaded"


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
        "Commodities",
        "commodities",
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="6 3 18 3 22 9 12 21 2 9 6 3"/><path d="M2 9h20"/><path d="M12 21 8 9l3-6"/><path d="m12 21 4-12-3-6"/></svg>',
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
            <p style="color:#94A3B8;margin-bottom:2rem;">Source-Traced Fundamental Analysis</p>
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
            margin: 1.5rem auto 0;
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
        [class*="st-key-onboarding_card_"] div[data-testid="stButton"] {
            height: 100%;
        }
        [class*="st-key-onboarding_card_"] button {
            width: 100%;
            min-height: 210px;
            height: 210px;
            display: flex;
            align-items: flex-start;
            justify-content: flex-start;
            text-align: left;
            white-space: normal;
            background: linear-gradient(135deg, #252D40 0%, #1E2840 100%);
            border: 0.5px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 1.75rem;
            box-shadow: 0 4px 24px rgba(0, 0, 0, 0.3), 0 1px 0 rgba(255, 255, 255, 0.04) inset;
            transition: all 0.25s ease;
            overflow: hidden;
        }
        [class*="st-key-onboarding_card_"] button > div,
        [class*="st-key-onboarding_card_"] button div[data-testid="stMarkdownContainer"] {
            width: 100%;
            display: flex;
            flex-direction: column;
            justify-content: flex-start;
            align-items: flex-start;
            text-align: left;
        }
        [class*="st-key-onboarding_card_"] button:hover {
            border-color: rgba(255, 255, 255, 0.16);
            box-shadow: 0 8px 40px rgba(0, 0, 0, 0.45), 0 1px 0 rgba(255, 255, 255, 0.06) inset;
            transform: translateY(-2px);
        }
        [class*="st-key-onboarding_card_"] button p {
            color: #CBD5E1;
            font-size: 14px;
            line-height: 1.55;
            text-align: left;
            white-space: normal;
            margin: 0;
        }
        [class*="st-key-onboarding_card_"] button strong {
            display: block;
            color: #F1F5F9;
            font-size: 15px;
            font-weight: 600;
            letter-spacing: 0;
            margin-bottom: 0.75rem;
        }
        .onboarding-trust {
            display: flex;
            justify-content: center;
            flex-wrap: wrap;
            gap: 1.5rem;
            margin: -0.5rem auto 2.5rem;
            color: #94A3B8;
            font-size: 13px;
            letter-spacing: 0.04em;
        }
        .onboarding-trust span { white-space: nowrap; }
        .onboarding-trust span::before { content: '◆ '; color: #FFB454; font-size: 9px; vertical-align: middle; }
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
            <div class="onboarding-tagline">Source-Traced Fundamental Analysis</div>
            <div class="onboarding-copy">
                FinLens traces every financial figure back to its source filing, with a full audit trail — SEC EDGAR and SEDAR+, US GAAP and IFRS. Built on value-investing fundamentals: downside first, margin of safety, intrinsic value versus price.
            </div>
            <div class="onboarding-trust">
              <span>Every figure traced to source</span>
              <span>Audit trail on every load</span>
              <span>SEC EDGAR + SEDAR+</span>
              <span>US GAAP + IFRS</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    feature_rows = [
        [
            (
                "Single Analysis",
                "Fetch from SEC EDGAR, or upload SEDAR+ filings as PDF. Every figure traced back to the filing, then analysed for red flags, downside risk, and margin of safety.",
                "single",
            ),
            (
                "Filing Comparison",
                "Compare two filings year-over-year to surface language shifts, sentiment changes, and quiet restatements between reporting periods.",
                "comparison",
            ),
        ],
        [
            (
                "Stock Tracker",
                "Live price, momentum, short interest, RSI, and moving averages for any ticker.",
                "stocks",
            ),
            (
                "Portfolio Manager",
                "Score every holding for distress and momentum, then roll up to a portfolio-level view of concentration and risk.",
                "portfolio",
            ),
        ],
    ]

    for row_index, row in enumerate(feature_rows):
        _, left, right, _ = st.columns([1, 2, 2, 1])
        for col, (title, copy, slug) in zip((left, right), row):
            with col:
                if st.button(f"**{title}**\n\n{copy}", key=f"onboarding_card_{slug}", width='stretch'):
                    st.session_state["nav_mode"] = title
                    st.query_params["page"] = slug
                    st.session_state["onboarding_complete"] = True
                    st.rerun()
        if row_index < len(feature_rows) - 1:
            st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

    _, start_col, _ = st.columns([1, 2, 1])
    with start_col:
        if st.button("Get Started →", type="primary", width='stretch'):
            st.session_state["onboarding_complete"] = True
            st.rerun()
    st.stop()

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
            Source-Traced Fundamental Analysis
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


def _looks_like_filename(name: str) -> bool:
    """True when a stored company name is really an uploaded filename,
    e.g. 'RIOCAN_FY2025_ANNUAL_FINANCIALS.PDF.PDF' or 'SU_FY2025.PDF'."""
    return bool(re.search(r"(?i)\.(pdf|docx?)\b", name)) or "_" in name


def _clean_filename_label(name: str) -> str:
    """Make a filename presentable: strip (repeated) extensions, turn
    underscores into spaces. Last-resort label when no company name exists."""
    base = re.sub(r"(?i)(\.(pdf|docx?))+$", "", name.strip())
    return re.sub(r"[_\s]+", " ", base).strip()


def _library_company_header(ticker: str, entries: list[dict]) -> str:
    raw_name = ""
    for entry in entries:
        raw_name = str(entry.get("company_name") or "").strip()
        if raw_name:
            break

    company_name = raw_name
    raw_is_filename = _looks_like_filename(raw_name) if raw_name else False

    # A filename is not a company name: prefer a yfinance lookup, and only
    # fall back to the cleaned-up filename when the lookup finds nothing.
    if (not company_name or raw_is_filename) and ticker and ticker != "N/A":
        cache_key = f"company_name_{ticker}"
        if cache_key not in st.session_state:
            try:
                _ensure_yfinance_cache_location()
                st.session_state[cache_key] = (
                    yf.Ticker(ticker).info or {}
                ).get("longName", "") or ""
            except Exception:
                st.session_state[cache_key] = ""
        looked_up = str(st.session_state.get(cache_key) or "").strip()
        if looked_up:
            company_name = looked_up
        elif raw_is_filename:
            company_name = _clean_filename_label(raw_name)
    elif raw_is_filename:
        company_name = _clean_filename_label(raw_name)

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
            <div class="finlens-sidebar-tagline">SOURCE-TRACED FUNDAMENTAL ANALYSIS</div>
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
                        "<hr style='margin:4px 0;border:none;border-top:0.5px solid rgba(255,255,255,0.08)'>",
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
                                # Wrong-issuer receipt (2026-07-12): name the
                                # resolved listing so a bare-ticker collision
                                # (ARX = Accelerant, not ARC) is VISIBLE at
                                # add time instead of silently poisoning the
                                # portfolio's market data.
                                st.session_state.pm_ticker_added_receipt = (
                                    f"{t_up} — {vmd.get('resolved_name') or 'listing name unavailable'}"
                                )
                                st.rerun()
                            else:
                                st.warning(f"{t_up} already in portfolio.")
                        else:
                            st.session_state.pm_ticker_not_found = t_up
                    else:
                        st.warning("Enter a ticker symbol.")

                if st.session_state.get("pm_ticker_added_receipt"):
                    st.info(
                        f"Added {st.session_state.pm_ticker_added_receipt}. "
                        "Not the company you meant? Remove it and use the "
                        "exchange suffix (e.g. ARX.TO for the TSX listing)."
                    )
                    st.session_state.pm_ticker_added_receipt = None

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
                    "<hr style='margin:4px 0;border:none;border-top:0.5px solid rgba(255,255,255,0.08)'>",
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
                "<hr style='margin:6px 0;border:none;border-top:0.5px solid rgba(255,255,255,0.08)'>",
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
                    f"No full source document stored for **{st.session_state.al_no_text_warning}** "
                    "(no cached PDF, and any stored text is only a truncated excerpt) — "
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
                                _entry_text = _reanalyse_text_for_entry(entry)
                                _entry_pdf_path = _reanalyse_pdf_path_for_entry(entry) if entry.get("source") == "sedar" else None
                                if _entry_text:
                                    st.session_state.pending_reanalyse = {
                                        "raw_text":     _entry_text,  # full document — extraction needs the statements; analyzer calls apply their own caps
                                        "company_name": entry.get("company_name") or entry.get("file_name") or "Unknown",
                                        "entry_id":     eid,
                                        "file_name":    entry.get("file_name", ""),
                                        "file_size":    entry.get("file_size_bytes", 0),
                                        "ticker":       entry.get("ticker"),
                                        "period":       entry.get("fiscal_year") or entry.get("period", ""),
                                        "source":       entry.get("source", "pdf"),
                                        "file_path":    entry.get("file_path"),
                                        "pdf_path":     _entry_pdf_path,
                                        "file_type":    entry.get("file_type", "pdf"),
                                    }
                                else:
                                    _period = entry.get("fiscal_year") or entry.get("period", "")
                                    _pdf_bytes = None
                                    # Resolved Re-Analyse pdf_path first (covers
                                    # registry entries via the canonical campaign
                                    # PDF) — sibling of the library-flow probe.
                                    try:
                                        if _entry_pdf_path and Path(_entry_pdf_path).exists():
                                            _pdf_bytes = Path(_entry_pdf_path).read_bytes()
                                    except Exception:
                                        _pdf_bytes = None
                                    if _pdf_bytes is None:
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
                                                "raw_text":     _extracted_text,  # full re-extracted document — do not pre-truncate extraction input
                                                "company_name": entry.get("company_name") or entry.get("file_name") or "Unknown",
                                                "entry_id":     eid,
                                                "file_name":    entry.get("file_name", ""),
                                                "file_size":    entry.get("file_size_bytes", 0),
                                                "ticker":       entry.get("ticker"),
                                                "period":       entry.get("fiscal_year") or entry.get("period", ""),
                                                "source":       entry.get("source", "pdf"),
                                                "file_path":    entry.get("file_path"),
                                                "pdf_path":     _entry_pdf_path,
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
                        "<hr style='margin:2px 0;border:none;border-top:0.5px solid rgba(255,255,255,0.08)'>",
                        unsafe_allow_html=True,
                    )

        st.divider()

    # Dev tooling only: model override + raw model IDs stay out of the
    # user-facing sidebar (get_model falls back to the config default).
    if os.getenv("FINLENS_DEBUG") == "1":
        _default_model_index = list(MODEL_OPTIONS).index(DEFAULT_MODEL_LABEL)
        st.sidebar.selectbox(
            "Dev mode model",
            list(MODEL_OPTIONS),
            index=_default_model_index,
            key="analysis_model_label",
        )
        st.sidebar.caption(f"{get_model_label()} — {get_model()}")

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

        # --- Load from Registry (pre-validated SEDAR catalog) --------------
        # Free, instant pre-seed: loads committed fixtures into the library
        # with no AI call. See _load_registry_filing_into_library for the
        # shared-session / per-user-isolation caveat.
        _registry = _load_filing_registry()
        _registry_filings = _registry.get("filings", [])
        if _registry_filings:
            _lib_ids = {e.get("id") for e in lib_get()}
            _reg_loaded = sum(1 for f in _registry_filings if _registry_entry_id(f) in _lib_ids)
            with st.expander(
                f"📥 Load from Registry ({_reg_loaded}/{len(_registry_filings)} loaded)",
                expanded=False,
            ):
                st.caption(
                    "Pre-validated SEDAR filings. Loading is free and instant "
                    "(no AI call) — financials + mapping only. Run analysis "
                    "separately for thesis and insights."
                )
                if st.button("Load all", key="registry_load_all",
                             width='stretch', type="primary"):
                    _added = 0
                    for _f in _registry_filings:
                        _ok, _ = _load_registry_filing_into_library(_f)
                        if _ok:
                            _added += 1
                    st.session_state["filing_library"] = lib_get()
                    st.success(
                        f"Loaded {_added} filing(s); "
                        f"{len(_registry_filings) - _added} already present."
                    )
                    st.rerun()

                for _f in _registry_filings:
                    _rid       = _registry_entry_id(_f)
                    _already   = _rid in _lib_ids
                    _r_ticker  = _f.get("ticker") or "—"
                    _r_company = _f.get("company_name") or _r_ticker
                    _r_sector  = (_f.get("sector") or "—").replace("_sector", "")
                    _r_fy      = _f.get("fiscal_year", "")
                    _r_stored  = _f.get("stored_field_count")
                    _r_resolved = _f.get("resolved_field_count")
                    _is_stale  = _f.get("validation_status") == "stale_mapping_pending_reextract"
                    # Integrity-first: show stale status visibly, never hide it.
                    _status_txt = "⚠️ stale fixture" if _is_stale else "✓ validated"
                    _status_col = "#c0392b" if _is_stale else "#27ae60"
                    st.markdown(
                        f"<div style='font-size:11px;line-height:1.45;margin-top:6px'>"
                        f"<b>{_r_ticker}</b> · {_r_fy} "
                        f"<span style='color:#888'>· {_r_sector}</span><br>"
                        f"<span style='color:#888'>{_r_company}</span><br>"
                        f"<span style='color:{_status_col};font-weight:600'>{_status_txt}</span> "
                        f"<span style='color:#888'>· stored {_r_stored} · resolved {_r_resolved}</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    if _already:
                        st.caption("✓ in library")
                    elif st.button("Load", key=f"registry_load_{_rid}", width='stretch'):
                        _ok, _msg = _load_registry_filing_into_library(_f)
                        st.session_state["filing_library"] = lib_get()
                        if _ok:
                            st.success(f"Loaded {_r_ticker}.")
                        else:
                            st.info(f"{_r_ticker}: {_msg}.")
                        st.rerun()

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
                        elif entry.get("source") == "fmp":
                            # Aggregator-sourced quick analysis — never claim a
                            # document class it doesn't have (was falling
                            # through to "· PDF").
                            row_period = f"{row_period} · FMP (unvalidated)"
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
                                    # Toast fires after the rerun (a toast shown
                                    # now would be discarded by st.rerun).
                                    st.session_state["_just_loaded_label"] = (
                                        f"{_library_company_header(ticker, [entry])}"
                                        f"{' — ' + _entry_period if _entry_period else ''}"
                                    )
                                    # Load path: excerpt-sized text is fine here — it only feeds
                                    # analysis-sized calls (dashboard regen), never extraction.
                                    _entry_text = _library_text_for_entry(entry)
                                    st.session_state.cached_filing_text = _entry_text
                                    _cached_analysis = (
                                        load_analysis(_entry_ticker, f"{_entry_period}_{_selected_model_cache_part()}")
                                        if _entry_ticker and _entry_period
                                        else None
                                    )
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

                                    if _legacy_scaled_stale(entry.get("financial_data"), entry.get("schema_version")):
                                        # Route to the Re-Analyse confirmation instead of loading. The
                                        # stale message is rendered in that confirmation block below —
                                        # NOT here, because st.rerun() discards any st.warning shown now.
                                        st.session_state.confirm_reanalyse = eid
                                        st.session_state.confirm_delete = None
                                        st.rerun()

                                    fd = normalize_financial_data(_heal_sedar_mapping(entry["financial_data"]))
                                    sd = entry.get("summary_data")
                                    bb = entry.get("bear_bull_data")
                                    st.session_state.financial_data      = fd
                                    st.session_state.summary_data        = sd
                                    st.session_state.bear_bull_data      = bb
                                    st.session_state.dashboard_data      = _dashboard_or_none(entry.get("dashboard_data"))
                                    st.session_state.mda_sentiment       = entry.get("mda_sentiment")
                                    # Direct-entry loads never stored market data — fetch
                                    # fresh through the wrong-issuer guard at load time.
                                    st.session_state.market_data = _fetch_market_data_for_filing(
                                        ticker if ticker != "—" else None, fd
                                    )
                                    try:
                                        _load_mc = st.session_state.market_data.get("market_cap") or 0.0
                                        st.session_state.excel_bytes = create_excel_file(fd, sd, _load_mc, bb)
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
                            # Recompute staleness at render time (entry is in scope) so the
                            # message survives the rerun that routed us here — whether the
                            # prompt came from a stale Load or a direct Re-Analyse click.
                            if _legacy_scaled_stale(entry.get("financial_data"), entry.get("schema_version")):
                                st.warning(
                                    "This stored analysis was saved with an older normalization schema, so its "
                                    "figures may be mis-scaled. Re-analyse to refresh it before loading."
                                )
                            st.caption(
                                f"Re-analyse **{entry.get('company_name') or entry.get('file_name') or 'Unknown'}**? This will run 4 Claude API calls "
                                f"(~$0.10–0.15 cost) and overwrite the existing result."
                            )
                            yes_col, no_col = st.columns(2)
                            with yes_col:
                                if st.button("Yes, re-analyse", key=f"lib_ra_yes_{eid}",
                                             width='stretch', type="primary"):
                                    st.session_state.confirm_reanalyse = None
                                    _entry_text = _reanalyse_text_for_entry(entry)
                                    _entry_pdf_path = _reanalyse_pdf_path_for_entry(entry) if entry.get("source") == "sedar" else None
                                    if _entry_text:
                                        st.session_state.pending_reanalyse = {
                                            "raw_text":     _entry_text,  # full document — extraction needs the statements; analyzer calls apply their own caps
                                            "company_name": entry.get("company_name") or entry.get("file_name") or "Unknown",
                                            "entry_id":     eid,
                                            "file_name":    entry.get("file_name", ""),
                                            "file_size":    entry.get("file_size_bytes", 0),
                                            "ticker":       entry.get("ticker"),
                                            "period":       entry.get("fiscal_year") or entry.get("period", ""),
                                            "source":       entry.get("source", "pdf"),
                                            "file_path":    entry.get("file_path"),
                                            "pdf_path":     _entry_pdf_path,
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
                                            "pdf_path":     _entry_pdf_path,
                                            "file_type":    entry.get("file_type", "pdf"),
                                        }
                                        st.session_state.uploader_key += 1
                                    st.rerun()
                            with no_col:
                                if st.button("Cancel", key=f"lib_ra_no_{eid}",
                                             width='stretch'):
                                    st.session_state.confirm_reanalyse = None
                                    st.rerun()
        # Response-cache plumbing is dev tooling — hidden from end users.
        if os.getenv("FINLENS_DEBUG") == "1":
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
        # CB-015: gate before the Claude calls — sibling path of fresh upload.
        _ra_doc_class = _gate_document_class(_ra_text)
        _ra_context = _get_filing_context(
            _ra_text,
            ra.get("ticker") or ra.get("company_name"),
            ra.get("period") or ra.get("file_name"),
        )
        if ra.get("source") == "sedar":
            _sedar_pdf_path = ra.get("pdf_path")
            if not _sedar_pdf_path or not Path(_sedar_pdf_path).exists():
                st.error(
                    "The original SEDAR+ PDF is no longer cached. Re-upload the filing "
                    "with the Canadian filing (SEDAR+ / IFRS) toggle enabled to re-analyse it."
                )
                st.session_state.pending_reanalyse = None
                st.stop()
            with st.spinner("Call 1: Extracting SEDAR+ financial statements..."):
                try:
                    _sedar_result = extract_sedar_filing(_sedar_pdf_path)
                except SedarExtractionError as e:
                    st.error(f"SEDAR+ extraction failed: {e}")
                    st.stop()
                except Exception as e:
                    # pending_reanalyse stays set so a rerun retries —
                    # transient API errors (e.g. 529 Overloaded) usually succeed on retry.
                    st.error(f"SEDAR+ extraction failed: {e} — click Re-Analyse again to retry.")
                    st.stop()
                _ra_fd = _sedar_extraction_to_financial_data(
                    _sedar_result,
                    ra.get("file_name", ""),
                    company_name=ra.get("company_name"),
                    ticker=ra.get("ticker"),
                )
        else:
            with st.spinner(f"Call 1: Extracting financials ({get_model_label()})..."):
                try:
                    _ra_fd = analyze_financials(_ra_text, API_KEY, model=get_model(), filing_context=_ra_context)
                except FabricatedExtractionError as _fab_err:
                    st.error(f"🛑 {_fab_err}")
                    st.stop()
        if isinstance(_ra_fd, dict):
            _ra_fd["document_class"] = _ra_doc_class["document_class"]
            _ra_fd["document_class_signals"] = _ra_doc_class["signals"]
        with st.spinner("Call 2: Generating investment signal..."):
            _ra_sd = analyze_summary(_ra_text, _ra_fd, API_KEY, model=get_model(), filing_context=_ra_context)
        with st.spinner("Call 3: Generating bull/bear case..."):
            _ra_bb = analyze_bear_bull(_ra_text, API_KEY, model=get_model(), filing_context=_ra_context)
        with st.spinner("Call 4: Generating dashboard insights..."):
            _ra_dd = analyze_dashboard_insights(_ra_text, _ra_sd, _ra_fd, API_KEY, model=get_model(), filing_context=_ra_context)
        with st.spinner(f"Call 5: Scoring MD&A sentiment ({get_mda_model()})..."):
            _ra_mda = analyze_mda_sentiment(_ra_text, API_KEY, model=get_mda_model(), filing_context=_ra_context)
        _ra_fd = _run_integrity_checks(
            _ra_fd,
            _ra_sd,
            (ra.get("ticker") or (_ra_sd or {}).get("ticker")),
            ra.get("source", "pdf"),
            filing_date=(ra.get("sec_filing_date") or (ra.get("summary_data") or {}).get("sec_filing_date") or _ra_fd.get("sedar_filing_date")),
            accession=ra.get("accession"),
        )
        if _ra_fd and _ra_fd.get("_integrity") is None:
            st.warning("Data integrity check could not run for this filing. Details were written to logs/service_stderr.log.")
        if ra.get("source") == "edgar" and ra.get("file_path"):
            try:
                # _ra_text is the full document here (truncated excerpts are
                # routed away before extraction), so this write heals any legacy
                # cache an older re-analyse truncated. Never write excerpts here.
                safe_write_text(ra["file_path"], _ra_text)
            except Exception:
                pass
        try:
            # Library JSON stores an analysis-sized excerpt (matches fresh
            # upload); the full document lives in the on-disk text/PDF caches.
            lib_add(ra["entry_id"], ra["file_name"], ra["file_size"],
                    _ra_fd, _ra_sd, _ra_bb, _ra_dd,
                    raw_text=_ra_text[:MAX_FILING_CHARS],
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
            raw_text=_ra_text[:MAX_FILING_CHARS],
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
    _qs_vals = [r["quality_score"] for r in analysed if r["quality_score"] is not None]
    avg_qs   = (sum(_qs_vals) / len(_qs_vals)) if _qs_vals else None

    # --- Section 1: Portfolio Summary ---
    st.markdown("##### Portfolio Summary")
    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("Holdings", len(tickers))
    s2.metric("🟢 PASS", pass_n)
    s3.metric("🟡 INVESTIGATE", inv_n)
    s4.metric("🔴 DECLINE", dec_n)
    qs_color = "#4ADE80" if (avg_qs or 0) >= 70 else ("#FCD34D" if (avg_qs or 0) >= 40 else "#F87171")
    with s5:
        qs_str = f"{avg_qs:.0f}" if avg_qs is not None else "—"
        st.markdown(
            f'<div style="background:linear-gradient(135deg,#252D40 0%,#1E2840 100%);'
            f'border:0.5px solid rgba(255,255,255,0.08);border-radius:12px;'
            f'padding:8px 12px;text-align:center;margin-top:4px">'
            f'<div style="font-size:11px;color:#64748B">Avg Quality</div>'
            f'<div style="font-size:22px;font-weight:700;color:{qs_color}">{qs_str}</div>'
            f'<div style="font-size:10px;color:#64748B">/ 100</div>'
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
                st.plotly_chart(fig1, width='stretch', config={"displayModeBar": False})

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
                st.plotly_chart(fig2, width='stretch', config={"displayModeBar": False})

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
                st.plotly_chart(fig3, width='stretch', config={"displayModeBar": False})

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
    # Scores stay in a scannable table; the Dalio/Marks narratives are
    # Claude-written analysis and render in full below (never truncated
    # into table cells — see CLAUDE.md truncation principle).
    st.markdown("##### Framework Scores")
    st.dataframe(
        [
            {
                "Ticker":        r["ticker"],
                "Company":       r["company_name"],
                "Quality Score": r["quality_score"],
            }
            for r in analysed
        ],
        width='stretch',
        hide_index=True,
        column_config={
            "Quality Score": st.column_config.ProgressColumn(
                "Quality Score", min_value=0, max_value=100, format="%d",
            ),
        },
    )
    for r in analysed:
        if not (r["dalio_view"] or r["marks_view"]):
            continue
        with st.expander(f"{r['ticker']} — Dalio & Marks framework views"):
            if r["dalio_view"]:
                st.markdown("**Dalio — cycle view**")
                st.markdown(_escape_md_dollars(r["dalio_view"]))
            if r["marks_view"]:
                st.markdown("**Marks — second-level view**")
                st.markdown(_escape_md_dollars(r["marks_view"]))

    st.stop()


# --- Filing Comparison page --------------------------------------------
if page == "Filing Comparison":

    if not API_KEY:
        st.error("ANTHROPIC_API_KEY not found — the app was started without secrets injected. There is no .env anymore (SOPS migration 2026-07-08): relaunch with .\run.bat, or run Import-Secrets in PowerShell before streamlit run app.py.")
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
            _comparison_cache_key = f"comparison_{_sorted_id_1}_{_sorted_id_2}_{_selected_model_cache_part()}"
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

        # CB-015: warn-only on the comparison flow (comparison of prose
        # documents is a legitimate use; a wrong class still deserves a flag).
        _gate_document_class(_text1, warn_only=True)
        _gate_document_class(_text2, warn_only=True)

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


# --- Commodities page ---------------------------------------------------
if page == "Commodities":
    from modules.economics.resource_economics import (
        COMMODITY_PROXIES,
        _fetch_proxy_data,
        infer_commodity,
    )
    from modules.economics.resource_display import PROXY_UNITS

    st.markdown("## Commodities")
    st.caption(
        "Oil & gas and minerals — spot prices, relative performance, and "
        "one-year trends. Same free yfinance proxy feeds that power the "
        "Economics tab; ETF-proxied commodities are labeled as such."
    )

    # One identity color per commodity, used everywhere on this page
    # (colorblind-validated as a set on the dark surface).
    _CMD_ORDER = ["gold", "silver", "copper", "crude oil", "natural gas", "uranium"]
    _CMD_LABEL = {
        "gold": "Gold", "silver": "Silver", "copper": "Copper",
        "crude oil": "WTI Crude", "natural gas": "Natural Gas",
        "uranium": "Uranium (ETF proxy)",
    }
    _CMD_COLOR = {
        "gold": "#B8821F", "silver": "#3574C6", "copper": "#C2554F",
        "crude oil": "#26A69A", "natural gas": "#8B5CF6", "uranium": "#B565A8",
    }

    @st.cache_data(ttl=900, show_spinner=False)
    def _cmd_fetch(symbol: str) -> dict:
        return _fetch_proxy_data(symbol)

    def _cmd_load(commodity_key: str) -> dict:
        cfg = COMMODITY_PROXIES[commodity_key]
        for role in ("primary", "fallback"):
            data = _cmd_fetch(cfg[role])
            if data.get("spot_price") is not None or data.get("trend"):
                return {"symbol": cfg[role], "role": role, **data}
        return {"symbol": cfg["primary"], "role": "primary",
                "spot_price": None, "trend": []}

    with st.spinner("Fetching commodity data…"):
        _cmd = {key: _cmd_load(key) for key in _CMD_ORDER}

    def _cmd_pct(new_value, old_value):
        if not new_value or not old_value:
            return None
        return (new_value / old_value - 1) * 100

    def _cmd_pill(pct_value, label):
        if pct_value is None:
            return (f'<span style="color:#64748B;font-size:11px;'
                    f'margin-right:8px">{label} —</span>')
        color = "#4ADE80" if pct_value >= 0 else "#F87171"
        return (f'<span style="color:{color};font-size:11px;font-weight:650;'
                f'margin-right:8px">{label} {pct_value:+.1f}%</span>')

    # --- Spot cards -----------------------------------------------------
    _cmd_cols = st.columns(3)
    for _i, _key in enumerate(_CMD_ORDER):
        _d = _cmd[_key]
        _trend = _d.get("trend") or []
        _spot = _d.get("spot_price")
        _day = _cmd_pct(_trend[-1]["close"], _trend[-2]["close"]) if len(_trend) >= 2 else None
        _year = _cmd_pct(_trend[-1]["close"], _trend[0]["close"]) if len(_trend) >= 2 else None
        _unit = PROXY_UNITS.get(_d["symbol"], "US$")
        _spot_str = f"${_spot:,.2f}" if _spot is not None else "—"
        with _cmd_cols[_i % 3]:
            st.markdown(
                f'<div style="background:linear-gradient(135deg,#252D40 0%,#1E2840 100%);'
                f'border:0.5px solid rgba(255,255,255,0.08);border-radius:12px;'
                f'padding:14px 16px;margin-bottom:12px">'
                f'<div style="font-size:11px;font-weight:700;letter-spacing:0.08em;'
                f'text-transform:uppercase;color:#64748B">'
                f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
                f'background:{_CMD_COLOR[_key]};margin-right:7px"></span>{_CMD_LABEL[_key]}</div>'
                f'<div style="font-size:26px;font-weight:650;color:#F1F5F9;margin:4px 0 2px">'
                f'{_spot_str} <span style="font-size:11px;color:#64748B;font-weight:400">{_unit}</span></div>'
                f'<div>{_cmd_pill(_day, "1d")}{_cmd_pill(_year, "1y")}'
                f'<span style="color:#64748B;font-size:10px">via {_d["symbol"]}</span></div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # --- Classic ratios ---------------------------------------------------
    _gold_spot = _cmd["gold"].get("spot_price")
    _silver_spot = _cmd["silver"].get("spot_price")
    _wti_spot = _cmd["crude oil"].get("spot_price")
    _gas_spot = _cmd["natural gas"].get("spot_price")
    _r1, _r2 = st.columns(2)
    with _r1:
        _gs = (_gold_spot / _silver_spot) if (_gold_spot and _silver_spot) else None
        st.markdown(
            f'<div style="background:linear-gradient(135deg,#252D40 0%,#1E2840 100%);'
            f'border:0.5px solid rgba(255,255,255,0.08);border-radius:12px;padding:14px 16px">'
            f'<div style="font-size:11px;font-weight:700;letter-spacing:0.08em;'
            f'text-transform:uppercase;color:#64748B">Gold / Silver ratio</div>'
            f'<div style="font-size:26px;font-weight:650;color:#F1F5F9;margin:4px 0 2px">'
            f'{f"{_gs:,.1f}" if _gs else "—"}</div>'
            f'<div style="font-size:11px;color:#64748B">ounces of silver per ounce of gold — '
            f'higher means silver is cheap relative to gold</div></div>',
            unsafe_allow_html=True,
        )
    with _r2:
        _og = (_wti_spot / _gas_spot) if (_wti_spot and _gas_spot) else None
        st.markdown(
            f'<div style="background:linear-gradient(135deg,#252D40 0%,#1E2840 100%);'
            f'border:0.5px solid rgba(255,255,255,0.08);border-radius:12px;padding:14px 16px">'
            f'<div style="font-size:11px;font-weight:700;letter-spacing:0.08em;'
            f'text-transform:uppercase;color:#64748B">Oil / Gas ratio</div>'
            f'<div style="font-size:26px;font-weight:650;color:#F1F5F9;margin:4px 0 2px">'
            f'{f"{_og:,.1f}" if _og else "—"}</div>'
            f'<div style="font-size:11px;color:#64748B">WTI $/bbl ÷ Henry Hub $/MMBtu — '
            f'energy-equivalent parity is ≈ 6; higher favors gas-weighted producers</div></div>',
            unsafe_allow_html=True,
        )

    st.divider()

    # --- Relative performance (indexed) -----------------------------------
    st.markdown("##### Relative Performance — indexed to 100, last 1 year")
    st.caption("Pick commodities to compare. Each series is rebased to 100 at the start of its window.")
    _picked = st.multiselect(
        "Commodities to compare",
        [_CMD_LABEL[k] for k in _CMD_ORDER],
        default=["Gold", "WTI Crude", "Copper"],
        label_visibility="collapsed",
    )
    _label_to_key = {v: k for k, v in _CMD_LABEL.items()}

    def _cmd_parse_date(value):
        try:
            return datetime.fromisoformat(str(value))
        except (ValueError, TypeError):
            return None

    _idx_fig = go.Figure()
    for _label in _picked:
        _key = _label_to_key[_label]
        _points = _cmd[_key].get("trend") or []
        if len(_points) < 2 or not _points[0]["close"]:
            continue
        _base = _points[0]["close"]
        _xs = [_cmd_parse_date(p["date"]) for p in _points]
        if any(x is None for x in _xs):
            _xs = [p["date"] for p in _points]
        _ys = [p["close"] / _base * 100 for p in _points]
        _idx_fig.add_trace(go.Scatter(
            x=_xs, y=_ys, mode='lines', name=_label,
            line=dict(color=_CMD_COLOR[_key], width=2),
            hovertemplate=_label + " · %{x|%b %d}: %{y:.0f}<extra></extra>",
        ))
        _idx_fig.add_annotation(
            x=_xs[-1], y=_ys[-1], text=f"{_ys[-1]:.0f}",
            showarrow=False, xanchor='left',
            font=dict(color=_CMD_COLOR[_key], size=10),
        )
    if _idx_fig.data:
        _idx_fig.add_hline(y=100, line_dash='dot', line_color='rgba(148,163,184,0.4)')
        _idx_fig.update_layout(
            paper_bgcolor='#1E2433', plot_bgcolor='#1E2433',
            font=dict(color='#94A3B8', size=11),
            margin=dict(l=40, r=40, t=20, b=40), height=320,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        )
        _idx_fig.update_xaxes(gridcolor='rgba(255,255,255,0.06)', zerolinecolor='rgba(255,255,255,0.1)')
        _idx_fig.update_yaxes(gridcolor='rgba(255,255,255,0.06)', zerolinecolor='rgba(255,255,255,0.1)', title_text='Indexed (start = 100)')
        st.plotly_chart(_idx_fig, width='stretch', config={"displayModeBar": False})
    else:
        st.caption("No trend data available for the selected commodities.")

    st.divider()

    # --- Small multiples: one-year trend per commodity ---------------------
    st.markdown("##### One-Year Trends")
    _sm_cols = st.columns(3)
    for _i, _key in enumerate(_CMD_ORDER):
        _points = _cmd[_key].get("trend") or []
        with _sm_cols[_i % 3]:
            st.markdown(
                f'<div style="font-size:11px;font-weight:700;letter-spacing:0.06em;'
                f'text-transform:uppercase;color:#94A3B8;margin:4px 0 2px">'
                f'{_CMD_LABEL[_key]} <span style="color:#64748B;font-weight:400">'
                f'{PROXY_UNITS.get(_cmd[_key]["symbol"], "US$")}</span></div>',
                unsafe_allow_html=True,
            )
            if len(_points) < 2:
                st.caption("No data.")
                continue
            _xs = [_cmd_parse_date(p["date"]) for p in _points]
            if any(x is None for x in _xs):
                _xs = [p["date"] for p in _points]
            _ys = [p["close"] for p in _points]
            _sm_fig = go.Figure(go.Scatter(
                x=_xs, y=_ys, mode='lines',
                line=dict(color=_CMD_COLOR[_key], width=1.8),
                hovertemplate="%{x|%b %d}: %{y:,.2f}<extra></extra>",
            ))
            _sm_fig.add_annotation(
                x=_xs[-1], y=_ys[-1], text=f"{_ys[-1]:,.2f}",
                showarrow=False, xanchor='left',
                font=dict(color=_CMD_COLOR[_key], size=10),
            )
            _sm_fig.update_layout(
                paper_bgcolor='#1E2433', plot_bgcolor='#1E2433',
                font=dict(color='#64748B', size=10),
                margin=dict(l=35, r=35, t=8, b=25), height=150,
                showlegend=False,
            )
            _sm_fig.update_xaxes(gridcolor='rgba(255,255,255,0.05)', zerolinecolor='rgba(255,255,255,0.08)')
            _sm_fig.update_yaxes(gridcolor='rgba(255,255,255,0.05)', zerolinecolor='rgba(255,255,255,0.08)')
            st.plotly_chart(_sm_fig, width='stretch', config={"displayModeBar": False})

    st.divider()

    # --- Your resource filers ---------------------------------------------
    st.markdown("##### Your Resource Filers")
    _resource_profiles = {"mining_sector", "resource_sector", "mining_exploration_sector"}
    _res_rows = []
    for _entry in lib_get():
        _efd = _entry.get("financial_data") or {}
        _emeta = ((_efd.get("mapping") or {}).get("meta") or {})
        if _emeta.get("sector_profile") not in _resource_profiles:
            continue
        _sector_text = (
            _efd.get("sector_inferred")
            or (_entry.get("summary_data") or {}).get("sector_inferred")
            or ""
        )
        _linked = infer_commodity(_sector_text)
        _res_rows.append({
            "Company": _library_company_header(_library_ticker(_entry), [_entry]),
            "Sector": _sector_text or "—",
            "Linked Commodity": _CMD_LABEL.get(_linked, (_linked or "—").title()),
            "Period": _library_period_label(_entry) or "—",
        })
    if _res_rows:
        st.dataframe(_res_rows, width='stretch', hide_index=True)
        st.caption(
            "Load any of these in Single Analysis for the full Economics tab — "
            "commodity linkage (r/β), the indexed company-vs-commodity chart, "
            "and the cost-structure waterfall."
        )
    else:
        st.caption(
            "No resource-sector filings in your library yet. Load a miner or "
            "oil & gas producer (e.g. AEM, CNQ, SU from the registry) to link "
            "filings to these commodities."
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

    # Helper: coloured pill badge (dark-theme tints, same palette as the
    # PASS / INVESTIGATE / DECLINE signal badges)
    def _pill(label, ok):
        if ok is None:
            color, bg, sym = "#94A3B8", "rgba(148,163,184,0.12)", "—"
        elif ok:
            color, bg, sym = "#4ADE80", "rgba(74,222,128,0.12)", "✓"
        else:
            color, bg, sym = "#F87171", "rgba(248,113,113,0.12)", "✗"
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
            label, color, bg = "Beat", "#4ADE80", "rgba(74,222,128,0.12)"
        elif actual < estimated:
            label, color, bg = "Miss", "#F87171", "rgba(248,113,113,0.12)"
        else:
            label, color, bg = "In Line", "#FCD34D", "rgba(252,211,77,0.12)"
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
            return ("—", "#94A3B8", "rgba(148,163,184,0.12)")
        short_pct = float(short_pct)
        if short_pct < 0.05:
            return ("LOW", "#4ADE80", "rgba(74,222,128,0.12)")
        if short_pct <= 0.15:
            return ("ELEVATED", "#FCD34D", "rgba(252,211,77,0.12)")
        return ("HIGH", "#F87171", "rgba(248,113,113,0.12)")

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
            st.markdown(_escape_md_dollars(short_desc))
            if len(desc) > 200:
                with st.expander("Read more"):
                    st.markdown(_escape_md_dollars(desc))
    with header_analyst_col:
        analyst = sd["analyst"]
        rec = (analyst["recommendation"] or "").upper()
        target = analyst["target_price"]
        upside = analyst["upside_pct"]
        num_an = analyst["num_analysts"]

        if rec in ("BUY", "STRONG_BUY", "STRONG BUY"):
            rec_color, rec_bg = "#4ADE80", "rgba(74,222,128,0.15)"
        elif rec in ("SELL", "STRONG_SELL", "STRONG SELL", "UNDERPERFORM"):
            rec_color, rec_bg = "#F87171", "rgba(248,113,113,0.15)"
        else:
            rec_color, rec_bg = "#FCD34D", "rgba(252,211,77,0.15)"

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
                f'<div style="background:rgba(255,255,255,0.10);border-radius:6px;height:10px;position:relative">'
                f'<div style="position:absolute;left:{fill_left:.0f}%;width:{fill_width:.0f}%;'
                f'height:100%;background:rgba(77,159,255,0.45);border-radius:6px"></div>'
                f'<div style="position:absolute;left:{c_pct:.0f}%;transform:translateX(-50%);'
                f'width:3px;height:100%;background:#F1F5F9;border-radius:2px" title="Current"></div>'
                f'<div style="position:absolute;left:{t_pct:.0f}%;transform:translateX(-50%);'
                f'width:3px;height:100%;background:#4ADE80;border-radius:2px" title="Target"></div>'
                f'</div>'
                f'<div style="font-size:11px;color:#64748B;margin-top:4px">'
                f'<span style="color:#F1F5F9">&#9632;</span> Current: ${cur:,.2f} &nbsp;&nbsp; '
                f'<span style="color:#4ADE80">&#9632;</span> Target: ${target:,.2f}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.divider()

    price_metrics_col, price_chart_col = st.columns([1, 1])
    with price_metrics_col:
        st.markdown("#### Price & Momentum")
        # 2x2 grid: this block lives in a half-width column, and four
        # metrics across were so narrow that prices wrapped mid-number.
        c1, c2 = st.columns(2)
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
        c3, c4 = st.columns(2)
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
                rsi_label, rsi_color = "Oversold", "#4ADE80"
                rsi_bg = "rgba(74,222,128,0.12)"
            elif rsi < 70:
                rsi_label, rsi_color = "Neutral", "#94A3B8"
                rsi_bg = "rgba(148,163,184,0.12)"
            else:
                rsi_label, rsi_color = "Overbought", "#F87171"
                rsi_bg = "rgba(248,113,113,0.12)"
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
            st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})

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
                st.plotly_chart(vol_fig, width='stretch', config={"displayModeBar": False})

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
                s_color = "#4ADE80" if surp >= 0 else "#F87171"
                s_bg = "rgba(74,222,128,0.12)" if surp >= 0 else "rgba(248,113,113,0.12)"
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
            st.caption("Source: Financial Modeling Prep — unvalidated aggregator data, not part of the verified corpus")

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
            st.caption("Source: Financial Modeling Prep — unvalidated aggregator data, not part of the verified corpus")

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
    st.error("ANTHROPIC_API_KEY not found — the app was started without secrets injected. There is no .env anymore (SOPS migration 2026-07-08): relaunch with .\run.bat, or run Import-Secrets in PowerShell before streamlit run app.py.")
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
    LIBRARY_PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)

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
                            # Wrong-issuer guard (2026-07-12): EDGAR knows the
                            # filer's name authoritatively — arm the check.
                            _edgar_md = get_market_data(_tk, company_name=_company_name)
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
        st.warning("⚠️ Canadian companies are not on SEC EDGAR (and FMP premium-blocks TSX tickers). Use the SEDAR+ agent fetch or PDF upload instead — that path is the verified corpus.")

    if st.button("Fetch Financials", width='stretch', key="quick_fetch_btn", disabled=_quick_is_canadian):
        _quick_ticker = quick_ticker.strip().upper()
        if not _quick_ticker:
            st.warning("Enter a ticker symbol first.")
        else:
            # CB-038: the ANNUAL options fetch as-filed XBRL from SEC
            # company-facts (per-figure receipts). CB-039 (Phase 2): the
            # Quarter/TTM options route to the quarterly builders (YTD
            # differencing / TTM = FY + YTD − prior YTD under the strict
            # date-chain gate) — FMP is retired from the Quick tab entirely.
            if _quick_period == "annual":
                with st.spinner(f"Fetching as-filed SEC data for {_quick_ticker}..."):
                    from modules.edgar_fetcher import build_financial_data_from_edgar_facts
                    _quick_fd = build_financial_data_from_edgar_facts(_quick_ticker, limit=_quick_limit)
                if not _quick_fd:
                    st.error(
                        f"Could not fetch as-filed SEC data for {_quick_ticker} — "
                        "check the ticker symbol (US filers only). Quick Financials "
                        "no longer falls back to aggregator data for annual figures."
                    )
                    st.stop()
            else:
                _quick_mode = "ttm" if _quick_limit == 4 else "quarter"
                with st.spinner(f"Deriving as-filed {'TTM' if _quick_mode == 'ttm' else 'quarterly'} figures for {_quick_ticker}..."):
                    from modules.edgar_fetcher import build_quarterly_financial_data_from_edgar_facts
                    _quick_fd = build_quarterly_financial_data_from_edgar_facts(_quick_ticker, mode=_quick_mode)
                if not _quick_fd:
                    st.error(
                        f"Could not derive as-filed {'TTM' if _quick_mode == 'ttm' else 'quarterly'} "
                        f"figures for {_quick_ticker} — check the ticker symbol (US filers only). "
                        "Values that fail the strict period date-chain are withheld rather than "
                        "approximated; Quick Financials never falls back to aggregator data."
                    )
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
            if _quick_fd_preview.get("source") == "edgar":
                st.success(f"Fetched {_quick_year} for {_quick_company} — trailing-twelve-month figures derived from as-filed facts.")
            else:
                st.success(f"Fetched last 4 quarters for {_quick_company}. Analysis will use TTM (trailing twelve months) totals.")
        elif selected_period == "Latest Quarter":
            st.success(f"Fetched {_quick_year} data for {_quick_company}.")
        elif selected_period == "Latest Annual":
            st.success(f"Fetched {_quick_year} data for {_quick_company}.")
        elif selected_period == "Last 2 Years (Annual)":
            st.success(f"Fetched 2 years of data for {_quick_company}.")
        else:
            st.success(f"Fetched 4 years of data for {_quick_company}.")
        # Multi-column history only when the data actually carries multiple
        # periods (as-filed TTM/quarter dicts are single-period; CB-039).
        if len(_quick_fd_preview.get("period_history") or []) > 1:
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
        if _quick_fd_preview.get("source") == "edgar":
            # Source-accurate form note: annual options read 10-Ks only;
            # Quarter/TTM read 10-Q/10-Q/A + 10-K/10-K/A (CB-039).
            _quick_form_note = (
                "10-K and 10-Q filings (amendments included)"
                if _quick_fd_preview.get("fmp_period") == "quarter"
                else "10-Ks"
            )
            st.caption(
                "Source: **as filed with the SEC** — us-gaap XBRL company "
                "facts, selected restatement-aware from the filer's own "
                f"{_quick_form_note}. Every figure carries a receipt below."
            )
            _quick_receipts = _quick_fd_preview.get("receipts") or {}
            if _quick_receipts:
                with st.expander(f"Per-figure receipts ({len(_quick_receipts)})", expanded=False):
                    for _r_name, _r_text in _quick_receipts.items():
                        st.caption(f"**{_r_name}**: {_r_text}")
        else:
            st.caption(
                "Source: Financial Modeling Prep — unvalidated aggregator data. "
                "Analyses built from it are badged on the dashboard and library, "
                "and are not part of the verified corpus."
            )
        if selected_period == "Last 4 Quarters (TTM)":
            if _quick_fd_preview.get("source") == "edgar":
                st.caption(
                    "TTM = latest fiscal year + current year-to-date − prior-year "
                    "year-to-date, from as-filed facts (composite receipts above). "
                    "With no post-FY quarter on file yet, TTM equals FY exactly."
                )
            else:
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
                    # Wrong-issuer guard (2026-07-12): the FMP profile's
                    # company name arms the name-agreement check so the
                    # market data can never belong to a different issuer
                    # than the statements on screen.
                    _quick_market_data = get_market_data(
                        _quick_ticker,
                        company_name=_quick_fd.get("company_name") or _quick_fd.get("company"),
                    )
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
            # CB-038: the source rides the data — annual quick analyses are
            # as-filed EDGAR (the "· EDGAR" library tag, no unvalidated
            # warning); Quarter/TTM remain FMP-badged.
            _quick_source = _quick_fd.get("source") or "fmp"
            _quick_entry_id = f"{_quick_source}_{_quick_ticker}_{_quick_period_label}"
            _save_analysis_cache(
                _quick_ticker,
                _quick_period_label,
                _quick_source,
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
                    source=_quick_source,
                )
                st.session_state["filing_library"] = lib_get()
                st.success("✓ Analysis saved to library")
            except Exception as _e:
                st.warning(f"Could not save to library: {_e}")
            st.info("ℹ️ MD&A Sentiment not available for Quick Analysis — upload a PDF for full analysis")
            st.rerun()

# Once an analysis is on screen the upload zone collapses out of the way,
# so the loaded company — not the intake plumbing — owns the page. A
# collapsed expander still renders its widgets, so upload state survives.
_has_loaded_analysis = bool(st.session_state.get("financial_data"))
with st.expander(
    "📄 Upload Financial Statements (PDF or Word)",
    expanded=not _has_loaded_analysis,
):
    uploaded_file = st.file_uploader(
        "Upload Financial Statements (PDF or Word)",
        type=["pdf", "docx"],
        help="Annual reports, 10-K filings, or standalone financial statement PDFs work best. Word (.docx) documents are also accepted.",
        key=f"pdf_uploader_{st.session_state.uploader_key}",
        label_visibility="collapsed",
    )
    canadian_filing = st.checkbox(
        "Canadian filing (SEDAR+ / IFRS)",
        value=False,
        help="Routes the PDF through the SEDAR+ IFRS extraction pipeline. Use for Canadian filings downloaded from SEDAR+.",
        key="canadian_sedar_upload",
    )

    # --- CB-028: search-triggered agent fetch (the flywheel front door) ---
    # The agent finds the issuer-hosted direct-PDF URL; the app re-fetches
    # the bytes ITSELF (provenance receipt) and converges them on the same
    # uploaded_file variable below, so every gate fires unchanged (R5).
    st.markdown("---")
    st.markdown(
        "**Or fetch from the web** — name the company and filing; the agent "
        "finds the issuer-hosted PDF and loads it here. Best for Canadian "
        "filings. Takes 1–3 minutes; the page waits while it runs."
    )
    _af_config = gateway_config()
    if _af_config is None:
        st.caption(
            "Agent fetch not configured on this machine — set "
            "OPENCLAW_GATEWAY_URL, OPENCLAW_GATEWAY_TOKEN and "
            "OPENCLAW_GATEWAY_SESSION_KEY in the secrets store to enable it."
        )
    else:
        _af_c1, _af_c2 = st.columns(2)
        with _af_c1:
            _af_company = st.text_input(
                "Company", key="agent_fetch_company",
                placeholder="e.g. Tourmaline Oil",
            )
        with _af_c2:
            _af_filing = st.text_input(
                "Filing", key="agent_fetch_filing",
                placeholder="e.g. FY2025 annual financial statements",
            )
        _af_canadian = st.checkbox(
            "Canadian filing (SEDAR+ / IFRS)",
            value=True,
            key="agent_fetch_canadian_flag",
            help="Routes the FETCHED PDF through the SEDAR+ IFRS pipeline — "
                 "independent of the manual-upload checkbox above.",
        )
        if st.button(
            "🔎 Fetch via agent",
            key="agent_fetch_go",
            disabled=not (_af_company or "").strip() or not (_af_filing or "").strip(),
            help="Runs one agent turn (1–3 minutes). Fetching only LOADS the "
                 "file — analysis stays your click, and its cost stays with it.",
        ):
            with st.status("Agent fetch in progress…", expanded=True) as _af_status:
                st.write("① Agent searching the issuer's investor-relations site…")
                _af_reply = request_filing_url(
                    _af_company, _af_filing, _af_canadian, _af_config
                )
                _af_manual_fallback = (
                    "Fallback: download the PDF in your browser and drop it "
                    "in the uploader above — same pipeline, same gates."
                )
                if _af_reply["status"] != "found":
                    _af_msgs = {
                        "not_found": "The agent could not locate that filing with confidence (it never guesses a URL).",
                        "blocked": "The issuer's site refused automated access (Cloudflare-class block).",
                        "gateway_error": "The agent channel is unreachable.",
                        "agent_reply_unparseable": "The agent's reply did not match the expected contract.",
                    }
                    st.error(
                        f"{_af_msgs.get(_af_reply['status'], 'Fetch failed.')} "
                        f"({_af_reply['status']}: {_af_reply.get('notes') or '—'}) "
                        f"{_af_manual_fallback}"
                    )
                    _af_status.update(label="Agent fetch failed — see message", state="error")
                else:
                    st.write("② Agent returned a URL — verifying and fetching the bytes ourselves…")
                    _af_result = fetch_pdf_bytes(_af_reply["url"])
                    if not _af_result["ok"]:
                        st.error(
                            f"Could not verify the fetched document "
                            f"({_af_result['reason']}: {_af_result['detail']}). "
                            f"{_af_manual_fallback}"
                        )
                        _af_status.update(label="Agent fetch failed — see message", state="error")
                    else:
                        _af_name = safe_fetch_filename(_af_company, _af_filing)
                        _af_provenance = build_provenance(
                            _af_reply["url"], _af_result["sha256"], _af_result["byte_size"]
                        )
                        _af_disk = cache_fetched_pdf(_af_result["data"], _af_name)
                        if _af_disk:
                            _af_provenance["cached_pdf_path"] = _af_disk
                        st.session_state["agent_fetched_upload"] = FetchedUpload(
                            _af_result["data"], _af_name
                        )
                        st.session_state["agent_fetched_canadian"] = _af_canadian
                        st.session_state["agent_fetch_provenance"] = _af_provenance
                        st.write(
                            f"③ Loaded {_af_name} "
                            f"({_af_result['byte_size']:,} bytes, "
                            f"sha256 {_af_result['sha256'][:16]}…)"
                        )
                        _af_status.update(label="✓ Fetched and loaded — ready to analyze", state="complete")
                        st.rerun()
        if (
            st.session_state.get("agent_fetched_upload") is not None
            and uploaded_file is None
        ):
            _af_loaded = st.session_state["agent_fetched_upload"]
            _af_prov = st.session_state.get("agent_fetch_provenance") or {}
            st.success(
                f"Agent-fetched file loaded: **{_af_loaded.name}** "
                f"(sha256 {str(_af_prov.get('sha256', ''))[:16]}…) — "
                f"it analyzes exactly like a manual upload."
            )
            if st.button("Clear fetched file", key="agent_fetch_clear"):
                st.session_state.pop("agent_fetched_upload", None)
                st.session_state.pop("agent_fetched_canadian", None)
                st.session_state.pop("agent_fetch_provenance", None)
                st.rerun()
# Clear stored results when the uploaded file changes.
# When data was loaded from the Filing Library there is no uploaded file,
# so we must NOT reset — library results should persist until the user
# explicitly uploads a different file.
if st.session_state.get("reanalyse_no_text"):
    _pdf_info = st.session_state.get("reanalyse_pdf_info") or {}
    if _pdf_info.get("source") == "edgar":
        _restored_text = _read_text_cache(_pdf_info.get("file_path"))
        if _restored_text and is_truncated_excerpt(_restored_text):
            # Legacy corrupted cache: an earlier re-analyse wrote the 80K
            # excerpt back over the full EDGAR text. Extraction would fail
            # its figure-presence guard — fail honestly with the remedy.
            st.info(
                f"Cached EDGAR text for **{st.session_state.reanalyse_no_text}** is a truncated "
                f"excerpt (the financial statements are missing). Load the filing from EDGAR "
                f"again to re-fetch the full document, then re-analyse."
            )
            st.session_state.reanalyse_no_text = None
            st.session_state.reanalyse_pdf_info = None
            st.stop()
        if _restored_text:
            st.session_state.pending_reanalyse = {
                "raw_text":     _restored_text,  # full document — extraction needs the statements
                "company_name": _pdf_info.get("company_name", st.session_state.reanalyse_no_text),
                "entry_id":     _pdf_info.get("entry_id"),
                "file_name":    _pdf_info.get("file_name", ""),
                "file_size":    _pdf_info.get("file_size", 0),
                "ticker":       _pdf_info.get("ticker"),
                "period":       _pdf_info.get("period"),
                "source":       "edgar",
                "file_path":    _pdf_info.get("file_path"),
                "pdf_path":     _pdf_info.get("pdf_path"),
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
        # The resolved Re-Analyse pdf_path (per-entry cache, or the canonical
        # campaign PDF for registry-loaded entries) is the authoritative
        # source — without this probe, registry entries dead-ended at
        # "Re-upload the PDF" while the canonical PDF sat on disk.
        try:
            _rp = _pdf_info.get("pdf_path")
            if _rp and Path(_rp).exists():
                _cached_bytes = Path(_rp).read_bytes()
        except Exception:
            _cached_bytes = None
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
                "raw_text":     _restored_text,  # full re-extracted document — do not pre-truncate extraction input
                "company_name": _pdf_info.get("company_name", st.session_state.reanalyse_no_text),
                "entry_id":     _pdf_info.get("entry_id"),
                "file_name":    _pdf_info.get("file_name", ""),
                "file_size":    _pdf_info.get("file_size", 0),
                "ticker":       _pdf_info.get("ticker"),
                "period":       _pdf_info.get("period"),
                "source":       _pdf_info.get("source", "pdf"),
                "file_path":    _pdf_info.get("file_path"),
                "pdf_path":     _pdf_info.get("pdf_path"),
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

# CB-028 R5: an agent-fetched filing converges on the SAME uploaded_file
# variable, so the entire downstream chain — 20MB guard, docx branch, cache
# key, CB-015 document-class gate, extraction, mapper, engine, moat log,
# library — fires unchanged BY CONSTRUCTION (no second path to drift).
# A manual upload always wins and clears the fetched file.
_agent_fetched = st.session_state.get("agent_fetched_upload")
if uploaded_file is not None and _agent_fetched is not None:
    st.session_state.pop("agent_fetched_upload", None)
    st.session_state.pop("agent_fetched_canadian", None)
    st.session_state.pop("agent_fetch_provenance", None)
    _agent_fetched = None
if uploaded_file is None and _agent_fetched is not None:
    _agent_fetched.seek(0)  # BytesIO position survives reruns; rewind before reuse
    uploaded_file = _agent_fetched
    canadian_filing = bool(st.session_state.get("agent_fetched_canadian")) or canadian_filing

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
    "Consumer Staples", "Industrials", "Metals & Mining",
    "Real Estate", "Other",
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


# yfinance industry keywords that indicate a metals/mining company. yfinance
# reports these under the broad "Basic Materials" sector alongside chemicals,
# so we route on industry to avoid lumping miners in with Industrials/chemicals.
_MINING_INDUSTRY_KW = (
    "gold", "silver", "copper", "platinum", "palladium",
    "precious metals", "metals & mining", "mining", "aluminum", "steel",
)


def _map_sector_to_option(raw_sector, raw_industry=None):
    if not raw_sector and not raw_industry:
        return None
    # Resource/mining companies: route to a dedicated option so both the
    # valuation sector label and the peer set reflect mining, not Industrials.
    industry_lower = str(raw_industry or "").lower()
    if industry_lower and any(kw in industry_lower for kw in _MINING_INDUSTRY_KW):
        return "Metals & Mining"
    raw_sector = str(raw_sector or "").strip()
    if not raw_sector:
        return None
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


def _lookup_yfinance_sector(ticker, return_industry=False):
    """Look up (sector, industry) from yfinance, cached in session state.

    Returns just the sector string by default; pass return_industry=True to get
    a (sector, industry) tuple. Industry is needed to tell miners apart from
    chemicals within yfinance's broad "Basic Materials" sector.
    """
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return (None, None) if return_industry else None
    cache_key = f"yf_class_{ticker}"
    if cache_key not in st.session_state:
        try:
            _ensure_yfinance_cache_location()
            _info = yf.Ticker(ticker).info or {}
            st.session_state[cache_key] = (_info.get("sector"), _info.get("industry"))
        except Exception:
            st.session_state[cache_key] = (None, None)
    _sector, _industry = st.session_state.get(cache_key) or (None, None)
    return (_sector, _industry) if return_industry else _sector


_sector_ticker = (
    st.session_state.get("resolved_ticker")
    or st.session_state.get("ticker")
    or st.session_state.get("manual_ticker")
    or (st.session_state.get("quick_financial_data") or {}).get("ticker")
)
_quick_financial_data = st.session_state.get("quick_financial_data") or {}
_yf_sector, _yf_industry = _lookup_yfinance_sector(_sector_ticker, return_industry=True)
# market_data now carries the NAME-VALIDATED listing's classification
# (wrong-issuer guard, 2026-07-10 ARX/Accelerant collision), so it outranks
# the raw bare-ticker yfinance lookup.
_raw_sector = (
    _quick_financial_data.get("sector")
    or (st.session_state.get("market_data") or {}).get("sector")
    or _yf_sector
)
_raw_industry = (
    _quick_financial_data.get("industry")
    or (st.session_state.get("market_data") or {}).get("industry")
    or _yf_industry
)
_auto_sector = _map_sector_to_option(_raw_sector, _raw_industry)
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
    # CB-015: gate before the Claude calls — sibling path of fresh upload.
    _ra_doc_class = _gate_document_class(_ra_text)
    _ra_context = _get_filing_context(
        _ra_text,
        ra.get("ticker") or ra.get("company_name"),
        ra.get("period") or ra.get("file_name"),
    )

    if ra.get("source") == "sedar":
        _sedar_pdf_path = ra.get("pdf_path")
        if not _sedar_pdf_path or not Path(_sedar_pdf_path).exists():
            st.error(
                "The original SEDAR+ PDF is no longer cached. Re-upload the filing "
                "with the Canadian filing (SEDAR+ / IFRS) toggle enabled to re-analyse it."
            )
            st.session_state.pending_reanalyse = None
            st.stop()
        with st.spinner("Call 1: Extracting SEDAR+ financial statements..."):
            try:
                _sedar_result = extract_sedar_filing(_sedar_pdf_path)
            except SedarExtractionError as e:
                st.error(f"SEDAR+ extraction failed: {e}")
                st.stop()
            except Exception as e:
                # pending_reanalyse stays set so a rerun retries —
                # transient API errors (e.g. 529 Overloaded) usually succeed on retry.
                st.error(f"SEDAR+ extraction failed: {e} — click Re-Analyse again to retry.")
                st.stop()
            _ra_fd = _sedar_extraction_to_financial_data(
                _sedar_result,
                ra.get("file_name", ""),
                company_name=ra.get("company_name"),
                ticker=ra.get("ticker"),
            )
    else:
        with st.spinner(f"Call 1: Extracting financials ({get_model_label()})..."):
            try:
                _ra_fd = analyze_financials(_ra_text, API_KEY, model=get_model(), filing_context=_ra_context)
            except FabricatedExtractionError as _fab_err:
                st.error(f"🛑 {_fab_err}")
                st.stop()

    if isinstance(_ra_fd, dict):
        _ra_fd["document_class"] = _ra_doc_class["document_class"]
        _ra_fd["document_class_signals"] = _ra_doc_class["signals"]

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
    with st.spinner(f"Call 5: Scoring MD&A sentiment ({get_mda_model()})..."):
        _ra_mda = analyze_mda_sentiment(_ra_text, API_KEY, model=get_mda_model(), filing_context=_ra_context)

    _ra_fd = _run_integrity_checks(
        _ra_fd,
        _ra_sd,
        (ra.get("ticker") or (_ra_sd or {}).get("ticker")),
        ra.get("source", "pdf"),
        filing_date=(ra.get("sec_filing_date") or (ra.get("summary_data") or {}).get("sec_filing_date")),
        accession=ra.get("accession"),
    )
    if _ra_fd and _ra_fd.get("_integrity") is None:
        st.warning("Data integrity check could not run for this filing. Details were written to logs/service_stderr.log.")

    if ra.get("source") == "edgar" and ra.get("file_path"):
        try:
            # _ra_text is the full document here (truncated excerpts are routed
            # away before extraction), so this write heals any legacy cache an
            # older re-analyse truncated. Never write excerpts to this cache.
            safe_write_text(ra["file_path"], _ra_text)
        except Exception:
            pass

    try:
        # Library JSON stores an analysis-sized excerpt (matches fresh upload);
        # the full document lives in the on-disk text/PDF caches.
        lib_add(ra["entry_id"], ra["file_name"], ra["file_size"],
                _ra_fd, _ra_sd, _ra_bb, _ra_dd,
                raw_text=_ra_text[:MAX_FILING_CHARS],
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
        raw_text=_ra_text[:MAX_FILING_CHARS],
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
        _is_docx  = uploaded_file.name.lower().endswith(".docx")
        _use_sedar_pipeline = bool(canadian_filing)
        if _use_sedar_pipeline and _is_docx:
            st.error("Canadian filing (SEDAR+ / IFRS) extraction is PDF-only. Upload a SEDAR+ PDF or turn the Canadian filing toggle off for Word documents.")
            st.stop()

        cache_key_base = get_cache_key(pdf_bytes)
        cache_key = (
            f"{cache_key_base}_sedar_{_selected_model_cache_part()}"
            if _use_sedar_pipeline
            else f"{cache_key_base}_{_selected_model_cache_part()}"
        )
        cached    = load_cache(cache_key)
        raw_text  = None  # populated in non-cached path; stored in library for future re-analysis
        if cached and _legacy_scaled_stale(cached.get("financial_data"), cached.get("schema_version")):
            st.warning(
                "Cached analysis was saved with an older normalization schema and will be refreshed."
            )
            cached = None

        if cached:
            # Heal a stale mapping (mapper/alias improved since this was cached)
            # for free from the stored extraction, BEFORE normalize scales it.
            _healed_stale = sedar_mapping_is_stale(cached.get("financial_data"), mapper_version())
            financial_data = normalize_financial_data(_heal_sedar_mapping(cached["financial_data"]))
            summary_data   = cached.get("summary_data")
            bear_bull_data = cached.get("bear_bull_data")
            dashboard_data = _dashboard_or_none(cached.get("dashboard_data"))
            mda_sentiment  = cached.get("mda_sentiment")
            if _healed_stale:
                # Persist the free re-map so future loads are instant and the
                # stored artifact carries the improved mapping (delivery, not
                # just display). Best-effort — a save failure must not block.
                try:
                    save_cache(
                        cache_key,
                        uploaded_file.name,
                        financial_data,
                        summary_data,
                        bear_bull_data,
                        dashboard_data,
                        mda_sentiment=mda_sentiment,
                    )
                except Exception:
                    pass
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

            # CB-015: classify the document BEFORE any Claude spend — refuses
            # honestly when no financial statements are detected.
            _doc_class_result = _gate_document_class(raw_text)

            _upload_context = _get_filing_context(raw_text, uploaded_file.name, cache_key)

            # Step 2 — Call 1: extract structured financials
            if _use_sedar_pipeline:
                with st.spinner("Extracting SEDAR+ financial statements with Claude..."):
                    _tmp_path = None
                    try:
                        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as _tmp:
                            _tmp.write(pdf_bytes)
                            _tmp_path = _tmp.name
                        _sedar_result = extract_sedar_filing(_tmp_path)
                        if not any((_sedar_result.get("pages_used") or {}).values()):
                            st.error("SEDAR+ extraction failed: no financial statement pages were found in this PDF.")
                            st.stop()
                        _sedar_company = st.session_state.get("sedar_company") or {}
                        financial_data = _sedar_extraction_to_financial_data(
                            _sedar_result,
                            uploaded_file.name,
                            company_name=_sedar_company.get("company_name"),
                            ticker=_sedar_company.get("ticker"),
                        )
                    except SedarExtractionError as e:
                        st.error(f"SEDAR+ extraction failed: {e}")
                        st.stop()
                    except Exception as e:
                        st.error(f"SEDAR+ extraction failed: {e}")
                        st.stop()
                    finally:
                        if _tmp_path:
                            try:
                                os.unlink(_tmp_path)
                            except Exception:
                                pass
            else:
                with st.spinner("Analyzing with Claude (this can take 30–60 seconds for large documents)..."):
                    try:
                        financial_data = analyze_financials(raw_text, API_KEY, model=get_model(), filing_context=_upload_context)
                    except Exception as e:
                        st.error(f"Claude analysis failed: {e}")
                        st.stop()

            # CB-015: record the ingest document class on the analysis so the
            # integrity engine logs it (document_class_recorded rule).
            if isinstance(financial_data, dict):
                financial_data["document_class"] = _doc_class_result["document_class"]
                financial_data["document_class_signals"] = _doc_class_result["signals"]

            # CB-028 R4: the agent-fetch receipt (url + sha256) rides inside
            # financial_data BEFORE save_cache, so the analysis cache, the
            # library entry, and the Supabase copy all carry it additively.
            if (
                isinstance(financial_data, dict)
                and st.session_state.get("agent_fetched_upload") is uploaded_file
                and st.session_state.get("agent_fetch_provenance")
            ):
                financial_data["agent_fetch_provenance"] = st.session_state["agent_fetch_provenance"]

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
            with st.spinner(f"Scoring MD&A sentiment ({get_mda_model()})..."):
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
                # company_name arms the wrong-issuer guard (bare 'ARX' on
                # yfinance is Accelerant Holdings, not ARC Resources);
                # prefer_canadian makes SEDAR filers try .TO/.V first.
                market_data = get_market_data(
                    resolved_ticker,
                    company_name=financial_data.get("company_name"),
                    prefer_canadian=_use_sedar_pipeline,
                )
                if not market_data.get("current_price"):
                    _res_note = market_data.get("resolution_note")
                    if _res_note:
                        st.warning(
                            f"Market data withheld for '{resolved_ticker}': {_res_note}"
                        )
                    else:
                        st.warning(f"Could not fetch market data for '{resolved_ticker}'.")

        market_cap = market_data.get("market_cap") or 0.0
        _upload_source = "sedar" if _use_sedar_pipeline else _upload_analysis_source(resolved_ticker)
        financial_data = _run_integrity_checks(
            financial_data,
            summary_data,
            resolved_ticker,
            _upload_source,
            filing_date=((summary_data or {}).get("sec_filing_date") or financial_data.get("sedar_filing_date")),
        )
        if financial_data and financial_data.get("_integrity") is None:
            st.warning("Data integrity check could not run for this filing. Details were written to logs/service_stderr.log.")

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
    st.caption("~$0.10–0.15 per analysis" if canadian_filing else "~$0.08 per analysis")

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
    _integrity_badge = integrity_status_badge(financial_data.get("_integrity"))
    if _integrity_flags or _integrity_badge:
        # Chip row, not a warning slab: flags are the audit trail (the
        # product's moat), not an error state. The overall verdict pill
        # renders whenever a validation ran — a visible CLEAN is part of
        # the trust surface, not just the failures.
        _verdict_pill = ""
        if _integrity_badge:
            _b_label, _b_rgb, _b_hex = _integrity_badge
            _verdict_pill = (
                f'<span style="background:rgba({_b_rgb},0.12);color:{_b_hex};'
                f'border:1px solid rgba({_b_rgb},0.35);padding:2px 10px;'
                f'border-radius:999px;font-size:11px;font-weight:700;'
                f'letter-spacing:0.5px;margin-right:6px">{escape(_b_label)}</span>'
            )
        _flag_pills = "".join(
            f'<span style="background:rgba(252,211,77,0.12);color:#FCD34D;'
            f'border:1px solid rgba(252,211,77,0.30);padding:2px 10px;'
            f'border-radius:999px;font-size:11px;font-weight:600;'
            f'margin-right:6px">⚑ {escape(str(f))}</span>'
            for f in _integrity_flags
        )
        st.markdown(
            f'<div style="margin:2px 0 8px"><span style="color:#64748B;'
            f'font-size:11px;margin-right:8px">INTEGRITY</span>'
            f'{_verdict_pill}{_flag_pills}</div>',
            unsafe_allow_html=True,
        )

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

    period   = financial_data.get("period") or ""
    currency = financial_data.get("currency") or ""
    fy       = financial_data.get("fiscal_year") or "Current Year"
    fy_prior = financial_data.get("fiscal_year_prior") or "Prior Year"
    ticker   = st.session_state.get("resolved_ticker") or summary_data.get("ticker")

    company = financial_data.get("company_name") or "Untitled Document"
    if _looks_like_filename(company):
        # Uploaded-file analyses store the raw filename (SU_FY2025.pdf) as
        # company_name. Show a real name instead — same resolution as the
        # library sidebar: yfinance longName, else the cleaned filename.
        company = _library_company_header(
            _library_ticker({"ticker": ticker}),
            [{"company_name": company}],
        )

    # Toast confirming what just loaded (set by the library Load handler
    # before its rerun — a toast shown pre-rerun would be discarded).
    _just_loaded = st.session_state.pop("_just_loaded_label", None)
    if _just_loaded:
        st.toast(f"Loaded {_just_loaded}", icon="📂")

    # Company logo beside the name when a ticker is known (Allied dry-run
    # credibility finding #2). fiscal.ai returns None quietly for names the
    # plan doesn't cover — TSX logos are plan-gated on the free tier
    # (verified 2026-07-07), so SEDAR filers render name-only for now and
    # light up automatically if the plan changes. Cache key matches Stock
    # Tracker's so the two pages share one fetch per session.
    _logo_bytes = None
    if ticker:
        from modules.fiscal_ai import get_company_logo as _hdr_logo
        from modules.stock_tracker import (
            _fiscal_ai_exchange_for_ticker as _hdr_exchange_for,
        )
        _logo_cache_key = f"fiscal_get_company_logo_{ticker}"
        if _logo_cache_key not in st.session_state:
            st.session_state[_logo_cache_key] = _hdr_logo(
                ticker, _hdr_exchange_for(str(ticker))
            )
        _logo_bytes = st.session_state[_logo_cache_key]
    if _logo_bytes:
        _logo_col, _name_col = st.columns([1, 12])
        with _logo_col:
            st.image(io.BytesIO(_logo_bytes), width=44)
        with _name_col:
            st.subheader(company)
    else:
        st.subheader(company)
    _period_str = period or "Unknown period"
    # Header year fallback (2026-07-12 dashboard-review minor (d)): some
    # filers print their fiscal year end without the year ("December 31" —
    # TOU), and the extraction honestly stores it that way. The authoritative
    # fiscal_year (registry pin / extraction) carries the year — append it
    # for display only; stored period and cache keys are untouched.
    if _period_str != "Unknown period" and not re.search(r"\d{4}", _period_str):
        _fy_year_match = re.search(r"(\d{4})", str(financial_data.get("fiscal_year") or ""))
        if _fy_year_match:
            _period_str = f"{_period_str}, {_fy_year_match.group(1)}"
    # Fiscal period and reporting currency, promoted from a buried caption
    # to the header proper (Allied dry-run credibility finding #3): a
    # skeptical reader's first two questions are "as of when?" and "in
    # what currency?" — they should never have to hunt for the answers.
    _currency_display = _prettify_currency_label(currency)
    # CB-040: an interim analysis never renders without its audit-status
    # caption. The window is parsed from the fiscal_year label's own text
    # ("Three/Six/Nine Months Ended ..."), so the caption is document-driven
    # — an annual pack can never trip it.
    _header_window = _parse_period_window(financial_data.get("fiscal_year"))
    _header_is_interim = bool(_header_window and _header_window.get("window") != "FY")
    st.markdown(
        f'<div style="color:#CBD5E1;font-size:15px;font-weight:600;'
        f'margin:-6px 0 12px">{escape(_period_str)}'
        + (
            f' <span style="color:#64748B;font-weight:400">·</span> '
            f'<span style="color:#94A3B8">{escape(_currency_display)}</span>'
            if _currency_display else ""
        )
        + (
            ' <span style="color:#64748B;font-weight:400">·</span> '
            '<span style="color:#FCD34D">unaudited interim</span>'
            if _header_is_interim else ""
        )
        + '</div>',
        unsafe_allow_html=True,
    )

    # --- Verdict hero strip -------------------------------------------
    # The moment of arrival: signal, quality, and the thesis in one
    # signal-colored banner, so the verdict greets you before the tabs.
    _hero_signal = (summary_data.get("signal") or "").upper()
    _hero_thesis = summary_data.get("thesis") or ""
    if _hero_signal or _hero_thesis:
        _HERO_RGB = {
            "PASS":        ("74,222,128", "#4ADE80"),
            "INVESTIGATE": ("252,211,77", "#FCD34D"),
            "DECLINE":     ("248,113,113", "#F87171"),
        }
        _hero_rgb, _hero_hex = _HERO_RGB.get(_hero_signal, ("148,163,184", "#94A3B8"))
        _hero_qs, _hero_qs_n = _quality_score(_calc_summary_metrics(financial_data))
        _hero_qs_chip = (
            f'<span title="Scored from the six Financial Health checks (Dashboard tab): '
            f'Liquidity · Leverage · Debt/equity · Revenue growth · FCF conversion · Interest coverage" '
            f'style="background:rgba(255,255,255,0.06);color:#F1F5F9;cursor:help;'
            f'padding:5px 14px;border-radius:6px;font-size:13px;font-weight:600">'
            f'Quality {_hero_qs} <span style="color:#64748B;font-weight:400">'
            f'/ 100 · {_hero_qs_n} of 6 metrics</span></span>'
            if _hero_qs is not None else ""
        )
        _hero_badge = (
            f'<span style="background:rgba({_hero_rgb},0.15);color:{_hero_hex};'
            f'border:1px solid rgba({_hero_rgb},0.45);padding:5px 16px;'
            f'border-radius:6px;font-size:14px;font-weight:700;'
            f'letter-spacing:1.2px">{escape(_hero_signal)}</span>'
            if _hero_signal else ""
        )
        st.markdown(
            f'<div style="border-radius:14px;padding:16px 20px;margin:2px 0 14px;'
            f'background:linear-gradient(135deg,rgba({_hero_rgb},0.10) 0%,#1E2840 60%);'
            f'border:1px solid rgba({_hero_rgb},0.30);'
            f'box-shadow:0 0 30px rgba({_hero_rgb},0.12), 0 4px 24px rgba(0,0,0,0.3)">'
            f'<div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;'
            f'margin-bottom:{"10px" if _hero_thesis else "0"}">'
            f'{_hero_badge}'
            f'{_hero_qs_chip}'
            f'</div>'
            + (
                f'<div style="color:#CBD5E1;font-size:14px;line-height:1.55">'
                f'{escape(_hero_thesis)}</div>'
                if _hero_thesis else ""
            )
            + '</div>',
            unsafe_allow_html=True,
        )
        # Cross-page hop: hand the ticker to Stock Tracker already tracked.
        if ticker:
            _hero_track_col, _ = st.columns([1, 4])
            with _hero_track_col:
                if st.button("📈 Track live in Stock Tracker", key="hero_track_btn"):
                    from modules.stock_tracker import get_stock_data as _hero_gsd
                    with st.spinner(f"Fetching live data for {ticker}…"):
                        st.session_state.stock_data = _hero_gsd(ticker)
                        st.session_state.st_current_ticker = str(ticker).upper()
                    st.session_state["nav_mode"] = "Stock Tracker"
                    st.query_params["page"] = "stocks"
                    st.rerun()

    if (
        st.session_state.get("analysis_loaded_from_cache")
        and st.session_state.get("analysis_cache_is_stale")
    ):
        st.warning(
            "⚠️ This analysis was saved with an older version of FinLens "
            "and may display incorrect numbers or be missing fields. "
            "Click **Re-Analyse $** above to refresh it with the current pipeline."
        )

    _fd_check = st.session_state.get("financial_data") or {}
    if _fd_check and _fd_check.get("_normalized") is not True:
        st.warning("⚠️ Financial data may not be normalized to raw reporting units.")

    tab_stmts, tab_dash, tab_econ = st.tabs(["📊 Statements", "📈 Dashboard", "🪨 Economics"])

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

        # Trust badge: FMP-sourced analyses render through the same dashboard
        # as validated filings but carry NO receipts to an as-filed document.
        # Keyed on financial_data.source (not the session flag) so library
        # re-loads of FMP entries stay badged too. FMP is an unreliable
        # witness (CLAUDE.md; JPM phantom-OCF proof case) — say so on-screen.
        if isinstance(financial_data, dict) and financial_data.get("source") == "fmp":
            st.warning(
                "⚠️ **Unvalidated aggregator data (FMP).** These figures come from "
                "a third-party feed, not an as-filed document, and are not part of "
                "FinLens's verified corpus — no per-figure receipts exist for them. "
                "Treat this as a quick look; for verified numbers, analyse the "
                "company's actual filing (SEDAR+/EDGAR or PDF upload)."
            )

        _mapping = financial_data.get("mapping") if isinstance(financial_data, dict) else None
        if isinstance(_mapping, dict):
            _mapping_meta = _mapping.get("meta") or {}
            # Compact chip instead of a full-width info slab — the mapping
            # census is provenance, not a problem to fix.
            st.markdown(
                f'<div style="margin:2px 0 8px">'
                f'<span style="background:rgba(148,163,184,0.10);color:#94A3B8;'
                f'border:1px solid rgba(148,163,184,0.25);padding:2px 10px;'
                f'border-radius:999px;font-size:11px;font-weight:600">'
                f'SEDAR+ mapping · {_mapping_meta.get("mapped_count", 0)} of '
                f'{_mapping_meta.get("total", 0)} lines mapped to canonical fields'
                f'</span></div>',
                unsafe_allow_html=True,
            )
            # The receipt: every mapped canonical field with its verbatim
            # source label and as-filed value, so each number can be tied
            # back to the printed filing line-by-line. This is the mapped
            # counterpart to the unmapped list below — before this, only
            # what FAILED to map was inspectable.
            with st.expander("SEDAR+ mapped fields — the receipt", expanded=False):
                _receipt_rows = mapping_receipt_rows(_mapping)
                if _receipt_rows:
                    st.dataframe(_receipt_rows, width='stretch', hide_index=True)
                    st.caption(
                        "Values shown as filed (the filing's own scale and sign) "
                        "so each row ties directly to the source PDF. Derived "
                        "rows are computed from the printed lines listed in Notes."
                    )
                else:
                    st.caption("No line items mapped to canonical fields.")
            with st.expander("SEDAR+ unmapped line items", expanded=False):
                _unmapped = _mapping.get("unmapped") or []
                if _unmapped:
                    st.dataframe(
                        [{"label": item.get("label"), "value": item.get("value")} for item in _unmapped],
                        width='stretch',
                        hide_index=True,
                    )
                else:
                    st.caption("No unmapped line items.")

        # Per-rule integrity receipt — rendered for any analysis that carries
        # an engine validation (SEDAR and EDGAR alike), not only SEDAR
        # mappings. Honest skips are listed with their reasons: an engine
        # that says "couldn't check this" is evidence, not noise.
        _integrity_rows = integrity_receipt_rows(financial_data.get("_integrity"))
        if _integrity_rows:
            with st.expander("Integrity checks — every rule the engine ran", expanded=False):
                st.dataframe(_integrity_rows, width='stretch', hide_index=True)

        # --- Market data fetch (always visible) and display ---
        # Pre-populate the ticker input the first time results appear, or after a
        # new analysis — session state is set explicitly on analysis completion so
        # this guard is mainly a safety net for cloud cold-starts.
        if "manual_ticker" not in st.session_state:
            _auto = st.session_state.get("resolved_ticker") or (summary_data or {}).get("ticker") or ""
            if _auto:
                st.session_state["manual_ticker"] = _auto

        # --- Find a ticker by company name OR symbol -----------------------
        # yfinance Search resolves names to the correct symbol, including the
        # ".TO" suffix for TSX-listed names (e.g. "Tourmaline" -> "TOU.TO"),
        # so the user does not need to know the exact exchange symbol. This is
        # placed above the Ticker Symbol input so a selected match flows
        # straight into the existing Fetch Market Data button.
        with st.expander("🔍 Search by company name or ticker", expanded=False):
            _sr_col, _sr_btn = st.columns([3, 1])
            with _sr_col:
                _ticker_query = st.text_input(
                    "Company name or ticker",
                    placeholder="e.g. Tourmaline, Agnico Eagle, or TOU.TO",
                    key="ticker_search_query",
                    label_visibility="collapsed",
                )
            with _sr_btn:
                if st.button("Search", width='stretch', key="ticker_search_btn"):
                    _q = (_ticker_query or "").strip()
                    st.session_state["ticker_search_results"] = (
                        search_ticker_details(_q, max_results=8) if _q else []
                    )

            _results = st.session_state.get("ticker_search_results")
            if _results is not None:
                if not _results:
                    st.caption("No matches — try the full company name or the exact ticker.")
                else:
                    def _search_label(_qt):
                        _sym = (_qt.get("symbol") or "?").strip()
                        _nm = _qt.get("longname") or _qt.get("shortname") or ""
                        _exch = _qt.get("exchDisp") or _qt.get("exchange") or ""
                        _tail = f"  ·  {_exch}" if _exch else ""
                        return f"{_nm}  —  {_sym}{_tail}" if _nm else f"{_sym}{_tail}"

                    _choice = st.radio(
                        "Select a match",
                        options=list(range(len(_results))),
                        format_func=lambda i: _search_label(_results[i]),
                        key="ticker_search_choice",
                    )
                    if st.button("Use this ticker", type="primary", key="ticker_search_use"):
                        _picked = (_results[_choice].get("symbol") or "").strip().upper()
                        if _picked:
                            # Set before the Ticker Symbol widget below renders.
                            st.session_state["manual_ticker"] = _picked
                            st.session_state.pop("ticker_search_results", None)
                            st.success(f"Selected {_picked} — click Fetch Market Data below.")

        tk_col, btn_col = st.columns([2, 1])
        with tk_col:
            manual_ticker = st.text_input("Ticker Symbol", placeholder="e.g. MHH, AAPL", key="manual_ticker")
        with btn_col:
            st.write("")
            if st.button("Fetch Market Data", width='stretch', type="primary"):
                if manual_ticker.strip():
                    with st.spinner(f"Fetching market data for {manual_ticker.strip().upper()}..."):
                        # Session market data feeds THIS filing's valuation, so
                        # the wrong-issuer guard applies here too — the ticker
                        # box is auto-prefilled from the filing, and bare TSX
                        # tickers collide with US listings (ARX = Accelerant).
                        _loaded_fd = st.session_state.get("financial_data") or {}
                        fetched = get_market_data(
                            manual_ticker.strip(),
                            company_name=_loaded_fd.get("company_name"),
                            prefer_canadian=_loaded_fd.get("source") == "sedar_pdf",
                        )
                        if fetched.get("current_price"):
                            st.session_state.market_data     = fetched
                            st.session_state.resolved_ticker = (
                                fetched.get("resolved_symbol")
                                or manual_ticker.strip().upper()
                            )
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
                            _fetch_note = fetched.get("resolution_note")
                            if _fetch_note:
                                st.warning(f"Market data withheld: {_fetch_note}")
                            else:
                                st.warning(f"No market data found for '{manual_ticker.strip()}' — check the ticker and try again.")
                else:
                    st.warning("Enter a ticker symbol first.")

        if market_data.get("current_price"):
            # Per-figure legibility: name the listing these numbers came from.
            if market_data.get("resolved_symbol") and market_data.get("resolved_name"):
                st.caption(
                    f"Market data: {market_data['resolved_symbol']} — "
                    f"{market_data['resolved_name']}"
                )
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

        # CB-019: suppressed flags are visible, never silent — the count
        # rides the panel label so "Clean" never hides a sector adjustment.
        _suppressed_flags = flag_result.get("suppressed") or []
        if red_count or yellow_count:
            exp_label = f"🚩 Red Flag Analysis  —  {red_count} red · {yellow_count} yellow"
        else:
            exp_label = "🟢 Red Flag Analysis  —  Clean"
        if _suppressed_flags:
            exp_label += f"  ·  {len(_suppressed_flags)} sector-adjusted"

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

            # CB-019 sector-adjusted strip (R7): flags that FIRED but are
            # suppressed for this sector render as a deliberate, visible
            # absence — each with the value, the threshold it breached, and
            # the sector rationale. Nothing suppressed → nothing rendered.
            if _suppressed_flags:
                st.caption(
                    f"Sector-adjusted flags ({len(_suppressed_flags)}) — "
                    f"evaluated and breached, suppressed for this sector, "
                    f"not counted toward the signal:"
                )
                for s in _suppressed_flags:
                    _s_val = s.get("metric_value")
                    _s_val_txt = (
                        f"{_s_val:,.2f}" if isinstance(_s_val, float) and not float(_s_val).is_integer()
                        else f"{_s_val:,.0f}" if isinstance(_s_val, (int, float))
                        else str(_s_val)
                    )
                    st.markdown(
                        f'<div style="color:#94A3B8;font-size:13px;margin:2px 0 6px">'
                        f'⚪ <b>{escape(str(s.get("check", "")).replace("_", " "))}</b> '
                        f'(would be {escape(str(s.get("severity_suppressed", "")))}) — '
                        f'value {escape(_s_val_txt)} breached {escape(str(s.get("threshold", "")))}. '
                        f'{escape(str(s.get("rationale") or ""))}</div>',
                        unsafe_allow_html=True,
                    )

        # --- Munger Inversion (value-investing pre-mortem) ---
        # PAID Claude call. Pay-once guard: a saved inversion loads free from disk;
        # only the explicit Run / Re-run buttons (marked with $) spend money. The
        # engine + decoupled store are committed in modules/analysis/ (994c090);
        # this panel only wires the UI. Runs off fundamentals, so it works for any
        # filing with financial_data — including financials-only registry loads.
        _inv_ticker = ticker or company
        _inv_period = (
            financial_data.get("fiscal_year")
            or financial_data.get("period")
            or period
            or ""
        )
        _inv_sector = (
            financial_data.get("sector_inferred")
            or financial_data.get("sector")
            or (summary_data.get("sector") if isinstance(summary_data, dict) else None)
        )
        _inv_key = f"munger_inv_{_inv_ticker}_{_inv_period}"

        # Hydrate the session cache from disk once so tab switches and reruns don't
        # re-read the file every time. A None value means "checked, nothing saved".
        if _inv_key not in st.session_state:
            if _inv_period and inversion_exists(_inv_ticker, _inv_period):
                st.session_state[_inv_key] = load_inversion(_inv_ticker, _inv_period)
            else:
                st.session_state[_inv_key] = None

        def _run_and_save_inversion():
            """Run the paid inversion, persist on success, never save an error payload."""
            with st.spinner("Running Munger inversion — value-investing pre-mortem (~10–20s)..."):
                _res = generate_inversion(financial_data, _inv_ticker, _inv_sector, _mapping or {})
            if isinstance(_res, dict) and "error" not in _res:
                _res["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                save_inversion(_inv_ticker, _inv_period, _res)
                st.session_state[_inv_key] = _res
                st.rerun()
            else:
                _msg = _res.get("error") if isinstance(_res, dict) else "unknown error"
                st.caption(f"Inversion unavailable: {_msg}")

        _SEVERITY_STYLE = {
            "high":   {"bg": "#1F0000", "color": "#F87171", "border": "#991B1B", "label": "HIGH"},
            "medium": {"bg": "#1C0F00", "color": "#FCD34D", "border": "#92400E", "label": "MEDIUM"},
            "low":    {"bg": "#1E2433", "color": "#94A3B8", "border": "#374B6B", "label": "LOW"},
        }

        def _render_inversion(inv: dict):
            # Thesis Killers — the one-glance headline (2–3 things most likely to break the thesis).
            _killers = [k for k in (inv.get("thesis_killers") or []) if k]
            if _killers:
                st.markdown(
                    '<div style="font-size:11px;color:#64748B;letter-spacing:0.08em;'
                    'text-transform:uppercase;margin:4px 0 8px 0">Thesis Killers</div>',
                    unsafe_allow_html=True,
                )
                _cards = "".join(
                    f'<div style="flex:1;min-width:180px;background:#1F0000;'
                    f'border:1px solid #991B1B;border-left:4px solid #F87171;'
                    f'border-radius:8px;padding:12px 16px">'
                    f'<span style="color:#FCA5A5;font-size:14px;font-weight:600">'
                    f'{escape(str(k))}</span></div>'
                    for k in _killers
                )
                st.markdown(
                    f'<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px">{_cards}</div>',
                    unsafe_allow_html=True,
                )

            # Pre-Mortem narrative — full prose, never truncated.
            _narr = inv.get("premortem_narrative")
            if _narr:
                st.markdown("**Pre-Mortem**")
                st.markdown(_escape_md_dollars(str(_narr)))

            # Failure Modes — severity badge + the real metric that makes each plausible.
            _modes = [m for m in (inv.get("failure_modes") or []) if isinstance(m, dict)]
            if _modes:
                st.markdown("**Failure Modes**")
                for m in _modes:
                    _sev = str(m.get("severity") or "low").lower()
                    _ss = _SEVERITY_STYLE.get(_sev, _SEVERITY_STYLE["low"])
                    _mode_txt = escape(str(m.get("mode") or "—"))
                    _ground = escape(str(m.get("grounding") or ""))
                    st.markdown(
                        f'<div style="background:#141A24;border:1px solid #243044;'
                        f'border-radius:8px;padding:12px 16px;margin-bottom:8px">'
                        f'<span style="display:inline-block;background:{_ss["bg"]};'
                        f'color:{_ss["color"]};border:1px solid {_ss["border"]};'
                        f'border-radius:4px;padding:2px 10px;font-size:11px;'
                        f'font-weight:700;letter-spacing:0.06em;margin-right:10px">'
                        f'{_ss["label"]}</span>'
                        f'<span style="color:#E2E8F0;font-size:14px;font-weight:600">'
                        f'{_mode_txt}</span>'
                        f'<div style="color:#94A3B8;font-size:13px;margin-top:6px">'
                        f'{_ground}</div></div>',
                        unsafe_allow_html=True,
                    )

            # Margin of Safety — value-investor framing.
            _mos = inv.get("margin_of_safety_note")
            if _mos:
                st.markdown("**Margin of Safety**")
                st.markdown(_escape_md_dollars(str(_mos)))

        _saved_inv = st.session_state.get(_inv_key)

        with st.expander("🔄 Munger Inversion — Pre-Mortem", expanded=bool(_saved_inv)):
            st.caption(
                "Charlie Munger's inversion: assume the investment has failed badly "
                "in 3–5 years, then work backward from the real reported numbers to "
                "find what most plausibly killed it."
            )

            if _saved_inv:
                _gen = _saved_inv.get("generated_at")
                _note = f"✓ saved inversion · generated {_gen}" if _gen else "✓ saved inversion"
                st.markdown(
                    f'<div style="color:#4ADE80;font-size:12px;margin-bottom:10px">'
                    f'{escape(_note)}</div>',
                    unsafe_allow_html=True,
                )
                _render_inversion(_saved_inv)
                st.divider()
                st.caption("Re-run only if the filing or your thesis changed — this spends another Claude call.")
                if st.button("↻ Re-run inversion ($)", key=f"inv_rerun_{_inv_key}"):
                    _run_and_save_inversion()
            else:
                st.markdown(
                    "Run a one-time pre-mortem on this filing. This is a **paid Claude "
                    "call**; once generated it's saved to disk and free to view forever after."
                )
                if st.button("🔍 Run Munger Inversion ($)", key=f"inv_run_{_inv_key}", type="primary"):
                    _run_and_save_inversion()

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
                            f'{escape(phrase)}</blockquote>',
                            unsafe_allow_html=True,
                        )
        elif mda_sentiment and mda_sentiment.get("error"):
            st.caption(f"MD&A sentiment unavailable: {mda_sentiment['error']}")
        elif not st.session_state.get("loaded_from_quick"):
            # mda_sentiment is None for registry/library/SEDAR financials-only
            # loads (the fixture carries statements + mapping, no MD&A prose).
            # Explain the absence instead of rendering nothing, so the feature
            # doesn't look missing. Quick Analysis has its own note (above), so
            # exclude it here to avoid a double message.
            st.caption(
                "ℹ️ MD&A Sentiment not available — this filing contains financial "
                "statements only (no MD&A prose). Upload a full annual report PDF "
                "or load via EDGAR for MD&A analysis."
            )

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
                        st.info(_escape_md_dollars(_sr["narrative"]))

        # --- Financial statement tables ---
        def _display_edgar_statement(rows):
            import html as _html

            def _fmt_per_share(v):
                # Per-share values are raw dollars-per-share: show 2 decimals,
                # never K/M/B abbreviation or unit scaling.
                try:
                    if v is None:
                        return "—"
                    return f"${float(v):,.2f}"
                except (TypeError, ValueError):
                    return "—"

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
                    if is_per_share_line_item(row.get("line_item")):
                        prior = _fmt_per_share(row.get("value_prior"))
                        current = _fmt_per_share(row.get("value"))
                    else:
                        prior = _fmt_edgar_value(row.get("value_prior")) or "—"
                        current = _fmt_edgar_value(row.get("value")) or "—"
                    # Current year left, prior right — matching how filings
                    # present their columns (NGEx dry-run finding #2: the
                    # reversed order forced a skeptic to reconcile).
                    body += (
                        f'<tr>'
                        f'<td>{line_item}</td>'
                        f'<td style="text-align:right">{current}</td>'
                        f'<td style="text-align:right">{prior}</td>'
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
                            <th>{_html.escape(str(fy))}</th>
                            <th>{_html.escape(str(fy_prior))}</th>
                        </tr>
                    </thead>
                    <tbody>{body}</tbody>
                </table>
                """,
                unsafe_allow_html=True,
            )

        # Full-width statement tabs. Three side-by-side columns forced long
        # line items ("Selling, General and Administrative Expense") to wrap
        # over four lines; one statement at full width reads like a filing.
        _stmt_is, _stmt_bs, _stmt_cf = st.tabs(
            ["Income Statement", "Balance Sheet", "Cash Flow Statement"]
        )

        with _stmt_is:
            rows = financial_data.get("income_statement", [])
            if rows:
                _display_edgar_statement(rows)
            else:
                st.info("Not found in document.")

        with _stmt_bs:
            rows = financial_data.get("balance_sheet", [])
            if rows:
                _display_edgar_statement(rows)
            else:
                st.info("Not found in document.")

        with _stmt_cf:
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
                        st.markdown(f"**{_escape_md_dollars(pt.get('title', ''))}**")
                        st.caption(_escape_md_dollars(pt.get("detail", "")))
                with bear_col:
                    st.markdown("**Bear Case**")
                    for pt in (bear_bull_data.get("bear_case") or [])[:3]:
                        st.markdown(f"**{_escape_md_dollars(pt.get('title', ''))}**")
                        st.caption(_escape_md_dollars(pt.get("detail", "")))

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
        # Dev-only diagnostic: hidden unless FINLENS_DEBUG=1 is set in .env,
        # so end users never see internal extraction plumbing.
        if os.getenv("FINLENS_DEBUG") == "1":
            with st.expander("🔬 Debug: Raw Extraction Output", expanded=False):
                st.caption(
                    "Shows exactly what Claude extracted vs. what _calc_summary_metrics() resolved. "
                    "Use this to diagnose — / N/A values in the Summary tab."
                )

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

        # --- Section 1: Header — Quality Score, Beta, MoS ---
        # (The signal badge + thesis moved to the verdict hero strip above
        # the tabs; the old in-tab copy was redundant.)
        qs_col, beta_col, mos_col = st.columns(3)

        qs, qs_n = _quality_score(metrics)
        if qs is None:
            qs_color = "#94A3B8"
        else:
            qs_color = "#4ADE80" if qs >= 70 else ("#FCD34D" if qs >= 40 else "#F87171")

        # Shared dark-card shell for the three header stat cards.
        _stat_card_style = (
            "background:linear-gradient(135deg,#252D40 0%,#1E2840 100%);"
            "border:0.5px solid rgba(255,255,255,0.08);border-radius:12px;"
            "padding:12px 16px;text-align:center"
        )

        with qs_col:
            st.markdown(
                f'<div style="{_stat_card_style}">'
                f'<div style="font-size:11px;color:#64748B;text-transform:uppercase;letter-spacing:1px">Quality Score</div>'
                f'<div style="font-size:28px;font-weight:700;color:{qs_color}">{qs if qs is not None else "—"}</div>'
                f'<div style="font-size:10px;color:#64748B">'
                f'{f"/ 100 · {qs_n} of 6 Financial Health checks below" if qs is not None else "no health metrics available"}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            _learn_more("quality_score", "Quality Score")

        with beta_col:
            beta_val = market_data.get("beta")
            beta_str = f"{beta_val:.2f}" if beta_val else "—"
            st.markdown(
                f'<div style="{_stat_card_style}">'
                f'<div style="font-size:11px;color:#64748B;text-transform:uppercase;letter-spacing:1px">Beta</div>'
                f'<div style="font-size:28px;font-weight:700;color:#F1F5F9">{beta_str}</div>'
                f'<div style="font-size:10px;color:#64748B">market sensitivity</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            _learn_more("beta", "Beta")

        with mos_col:
            _dcf_hdr = st.session_state.get("dcf_result") or {}
            _iv_hdr  = _dcf_hdr.get("intrinsic_value_per_share")
            _mos_hdr = _dcf_hdr.get("margin_of_safety_pct")
            if _iv_hdr is not None and _mos_hdr is not None:
                _mc = "#4ADE80" if _mos_hdr > 20 else ("#FCD34D" if _mos_hdr >= 0 else "#F87171")
                _lbl = "undervalued" if _mos_hdr > 0 else "overvalued"
                st.markdown(
                    f'<div style="{_stat_card_style}">'
                    f'<div style="font-size:11px;color:#64748B;text-transform:uppercase;letter-spacing:1px">Margin of Safety</div>'
                    f'<div style="font-size:22px;font-weight:700;color:#F1F5F9">${_iv_hdr:,.2f}</div>'
                    f'<div style="font-size:16px;font-weight:700;color:{_mc}">{_mos_hdr:+.1f}%</div>'
                    f'<div style="font-size:10px;color:#64748B">{_lbl}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div style="{_stat_card_style}">'
                    '<div style="font-size:11px;color:#64748B;text-transform:uppercase;letter-spacing:1px">Margin of Safety</div>'
                    '<div style="font-size:28px;font-weight:700;color:#F1F5F9">—</div>'
                    '<div style="font-size:10px;color:#64748B">DCF required</div>'
                    '</div>',
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
            _auto_pick_note = None
            _auto_choice = None
            _auto_s = st.session_state.get("auto_sector")
            # SEDAR filers get the Canadian peer variant where one exists —
            # a WCSB gas producer's comparables are Canadian issuers, not
            # US supermajors.
            _is_sedar = financial_data.get("source") == "sedar_pdf"
            _suggested = suggest_sector(_sector_hint, canadian=_is_sedar)
            # The filing's own sector is ground truth and wins; the
            # yfinance-derived session auto_sector is only a fallback — it can
            # be stale from a previously viewed company, or wrong when the
            # bare ticker resolves to a different listing.
            if _suggested:
                _sector_idx = _sector_options.index(_suggested)
                _auto_choice = _suggested
                _auto_pick_note = (
                    f'Auto-picked from the filing sector "{_sector_hint}" — '
                    f'change it if wrong.'
                )
            elif _auto_s and _auto_s in _sector_options:
                _sector_idx = _sector_options.index(_auto_s)
                _auto_choice = _auto_s
                _auto_pick_note = (
                    "Auto-picked from market data (no sector in the filing) — "
                    "change it if wrong."
                )

            _pc_sector_col, _pc_btn_col = st.columns([2, 1])
            with _pc_sector_col:
                _peer_sector = st.selectbox(
                    "Peer Sector",
                    _sector_options,
                    index=_sector_idx,
                    key="peer_sector",
                )
                if _auto_pick_note and _peer_sector == _auto_choice:
                    st.caption(_auto_pick_note)
                elif _auto_choice is None:
                    # Nothing matched — never let the index-0 default look
                    # deliberate (a gas producer silently benchmarked against
                    # Big Tech was the reference incident, 2026-07-10).
                    if _sector_hint:
                        st.caption(
                            f'No peer bucket matched the filing sector "{_sector_hint}" — '
                            f'pick one, or edit the ticker list below.'
                        )
                    else:
                        st.caption(
                            "No sector hint available for this filing — pick the "
                            "right bucket, or edit the ticker list below."
                        )
            # Self-peer exclusion (2026-07-12 dashboard-review minor (c)): the
            # subject's own listing is dropped from the DEFAULT list (TOU.TO
            # while analyzing TOU invited confusion) — same ticker-root
            # semantics as the compute-time dedup, which remains the backstop
            # if the user types it back.
            _subject_root = str(_peer_ticker or "").split(".")[0].upper()
            _default_peers = ", ".join(
                t for t in peer_map.get(_peer_sector, [])
                if not _subject_root or str(t).split(".")[0].upper() != _subject_root
            )
            _peer_tickers_text = st.text_input(
                "Peer tickers (comma-separated — edit to compare against your own set)",
                value=_default_peers,
                key=f"peer_tickers_{_peer_sector}",
            )
            with _pc_btn_col:
                st.write("")
                if st.button("Load Peer Comparison", width='stretch', key="peer_load_btn"):
                    _peer_list = [t.strip() for t in _peer_tickers_text.split(",") if t.strip()]
                    with st.spinner("Fetching peer data from yfinance..."):
                        st.session_state["peer_data"] = get_peer_data(
                            _peer_ticker, _peer_sector, tickers=_peer_list
                        )

            _peer_data = st.session_state.get("peer_data")
            if _peer_data:
                if _peer_data.get("error"):
                    st.warning(_peer_data["error"])
                else:
                    import html as _html

                    _med = _peer_data.get("medians") or {}

                    # Subject Net Debt / OCF from the filing's own canonical
                    # fields (same normalization basis, so the ratio is
                    # scale-invariant); honest None when the inputs aren't
                    # mapped. Peers get the yfinance approximation.
                    def _filing_net_debt_cf():
                        try:
                            _ocf = financial_data.get("operating_cash_flow")
                            _ltd = financial_data.get("long_term_debt")
                            if _ocf is None or float(_ocf) <= 0 or _ltd is None:
                                return None
                            _debt = float(_ltd) + float(financial_data.get("short_term_debt") or 0)
                            _cash = float(financial_data.get("cash") or 0)
                            return (_debt - _cash) / float(_ocf)
                        except Exception:
                            return None

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
                            "net_debt_cf": _filing_net_debt_cf(),
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
                        "net_debt_cf": _med.get("net_debt_cf"),
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
                        # Neutral band: within ±10% of the median stays gray.
                        # A P/E a hair under the median is not meaningfully
                        # "better" — binary red/green overstated precision.
                        if value is None or median_value is None or (
                            median_value != 0
                            and abs(value - median_value) <= 0.10 * abs(median_value)
                        ):
                            color = "#94A3B8"
                        else:
                            lower_better = metric in ("pe", "ev_ebitda", "pb", "ps", "net_debt_cf")
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
                        ("net_debt_cf", "Net Debt/CF"),
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
                    st.caption(
                        "Peer figures are trailing-twelve-month market data via "
                        "yfinance; your company's row uses the same market data, "
                        "not filing-period figures. Gray = within 10% of the "
                        "sector median."
                    )

        st.divider()

        # --- Section 2: Manager Framework Banners ---
        st.markdown("##### Framework Perspectives")
        fw_dalio, fw_lynch, fw_marks = st.columns(3)

        with fw_dalio:
            # HTML container: html-escape only (no \$-escaping — see thesis note above).
            dalio_text = escape(dd.get("dalio_view") or "Re-analyse to generate Dalio view.")
            st.markdown(
                f'<div style="background:rgba(139,127,232,0.10);border:0.5px solid rgba(139,127,232,0.30);'
                f'border-radius:12px;padding:16px 18px">'
                f'<div style="font-size:12px;font-weight:700;color:#A79DF5;margin-bottom:8px;'
                f'text-transform:uppercase;letter-spacing:0.5px">Dalio — All Weather</div>'
                f'<div style="font-size:14px;color:#CBD5E1;line-height:1.5">{dalio_text}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        with fw_lynch:
            lynch_cat  = dd.get("lynch_category") or ""
            lynch_text = escape(dd.get("lynch_story") or "Re-analyse to generate Lynch view.")
            cat_suffix = f" ({escape(lynch_cat)})" if lynch_cat else ""
            st.markdown(
                f'<div style="background:rgba(78,206,139,0.08);border:0.5px solid rgba(78,206,139,0.28);'
                f'border-radius:12px;padding:16px 18px">'
                f'<div style="font-size:12px;font-weight:700;color:#5FD69A;margin-bottom:8px;'
                f'text-transform:uppercase;letter-spacing:0.5px">Lynch — One Up{cat_suffix}</div>'
                f'<div style="font-size:14px;color:#CBD5E1;line-height:1.5">{lynch_text}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        with fw_marks:
            marks_text = escape(dd.get("marks_view") or "Re-analyse to generate Marks view.")
            st.markdown(
                f'<div style="background:rgba(255,180,84,0.08);border:0.5px solid rgba(255,180,84,0.28);'
                f'border-radius:12px;padding:16px 18px">'
                f'<div style="font-size:12px;font-weight:700;color:#FFB454;margin-bottom:8px;'
                f'text-transform:uppercase;letter-spacing:0.5px">Marks — Second Level</div>'
                f'<div style="font-size:14px;color:#CBD5E1;line-height:1.5">{marks_text}</div>'
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

        # CB-021: a small calculation caption under each card shows the formula
        # + inputs behind the number (receipts principle applied to ratios).
        _calcs = metrics.get("calcs") or {}
        with m1:
            st.metric("Revenue", _fmt_num(rev_c), _fmt_pct(yoy_rev))
            if _calcs.get("rev"):
                st.caption(_calcs["rev"])
        with m2:
            # CB-024: sector-aware — O&G producers have no cost-of-goods line, so
            # the card shows the operating Netback Margin (the O&G analog) instead
            # of a faked Gross Margin. Non-resource filers keep Gross Margin.
            _nb_m = metrics.get("netback_margin")
            if _nb_m is not None:
                st.metric("Netback Margin", _fmt_pct(_nb_m))
                if _calcs.get("netback_margin"):
                    st.caption(_calcs["netback_margin"])
            elif metrics.get("netback_expected"):
                # Resource filer (royalties map) whose netback inputs are
                # unmapped: name the RIGHT metric honestly rather than showing
                # a Gross Margin dash that reads as a missing-COGS problem.
                st.metric("Netback Margin", "—")
                st.caption("netback inputs (operating / transportation) unmapped for this filer")
            else:
                st.metric("Gross Margin", _fmt_pct(gp_m) or "—")
                if _calcs.get("gp_margin"):
                    st.caption(_calcs["gp_margin"])
        with m3:
            st.metric("EBITDA Margin", _fmt_pct(ebitda_m) or "—")
            if _calcs.get("ebitda_margin"):
                st.caption(_calcs["ebitda_margin"])
        with m4:
            st.metric("Net Income", _fmt_num(ni_c), _fmt_pct(ni_m))
            if _calcs.get("ni_margin"):
                st.caption(_calcs["ni_margin"])
        with m5:
            st.metric("Free Cash Flow", _fmt_num(fcf_c))
            if _calcs.get("fcf"):
                st.caption(_calcs["fcf"])

        st.divider()

        # --- Section 3b: Two-Year Performance charts ---
        # The statements carry two fiscal years side by side; these charts
        # make the comparison visible instead of leaving it as table rows.
        _pairs = two_year_statement_pairs(financial_data)

        def _chart_dark(fig, height=300, **extra):
            """Shared dark theme for dashboard charts."""
            fig.update_layout(
                paper_bgcolor="#1E2433",
                plot_bgcolor="#1E2433",
                font=dict(color="#94A3B8", size=11),
                margin=dict(l=40, r=20, t=30, b=40),
                height=height,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                **extra,
            )
            fig.update_xaxes(gridcolor="rgba(255,255,255,0.06)",
                             zerolinecolor="rgba(255,255,255,0.1)")
            fig.update_yaxes(gridcolor="rgba(255,255,255,0.06)",
                             zerolinecolor="rgba(255,255,255,0.1)")
            return fig

        # Colorblind-validated pair (dataviz six-checks, dark surface):
        # prior year teal, current year blue.
        _PRIOR_COLOR, _CURRENT_COLOR = "#26A69A", "#3574C6"
        _fy_prior_name = str(fy_prior or "Prior year")
        _fy_name = str(fy or "Current year")

        _UNIT_WORDS = {"T": "trillions", "B": "billions", "M": "millions",
                       "K": "thousands", "": ""}

        def _money_scale(values):
            """Pick one divisor + unit for a chart so all bars share a scale."""
            peak = max((abs(v) for v in values if v is not None), default=0)
            if peak >= 1_000_000_000_000:
                return 1_000_000_000_000, "T"
            if peak >= 1_000_000_000:
                return 1_000_000_000, "B"
            if peak >= 1_000_000:
                return 1_000_000, "M"
            if peak >= 1_000:
                return 1_000, "K"
            return 1, ""

        _bar_items = [
            name for name in ("Revenue", "Gross Profit", "Operating Income",
                              "Net Income", "Operating Cash Flow")
            if _pairs[name]["current"] is not None
            and _pairs[name]["prior"] is not None
        ]
        if len(_bar_items) >= 2:
            st.markdown("##### Two-Year Performance")
            perf_col, margin_col = st.columns([3, 2])

            with perf_col:
                _cur_vals = [_pairs[n]["current"] for n in _bar_items]
                _pri_vals = [_pairs[n]["prior"] for n in _bar_items]
                _div, _sfx = _money_scale(_cur_vals + _pri_vals)
                fig_perf = go.Figure()
                fig_perf.add_trace(go.Bar(
                    name=_fy_prior_name, x=_bar_items,
                    y=[v / _div for v in _pri_vals],
                    marker_color=_PRIOR_COLOR,
                    customdata=[_fmt_num(v) for v in _pri_vals],
                    hovertemplate="%{x} · " + _fy_prior_name + ": %{customdata}<extra></extra>",
                ))
                fig_perf.add_trace(go.Bar(
                    name=_fy_name, x=_bar_items,
                    y=[v / _div for v in _cur_vals],
                    marker_color=_CURRENT_COLOR,
                    text=[_fmt_num(v) for v in _cur_vals],
                    textposition="outside",
                    textfont=dict(size=10, color="#CBD5E1"),
                    cliponaxis=False,
                    customdata=[_fmt_num(v) for v in _cur_vals],
                    hovertemplate="%{x} · " + _fy_name + ": %{customdata}<extra></extra>",
                ))
                _chart_dark(fig_perf, barmode="group", bargap=0.3, bargroupgap=0.08)
                fig_perf.update_yaxes(title_text=_UNIT_WORDS[_sfx] or None)
                st.plotly_chart(fig_perf, width='stretch',
                                config={"displayModeBar": False})

            with margin_col:
                _rev_cur = _pairs["Revenue"]["current"]
                _rev_pri = _pairs["Revenue"]["prior"]
                _margin_rows = []
                for _name, _label in (("Gross Profit", "Gross"),
                                      ("Operating Income", "Operating"),
                                      ("Net Income", "Net")):
                    _c = _pairs[_name]["current"]
                    _p = _pairs[_name]["prior"]
                    if None not in (_c, _p) and _rev_cur and _rev_pri:
                        _margin_rows.append(
                            (_label, _p / _rev_pri * 100, _c / _rev_cur * 100)
                        )
                if _margin_rows:
                    fig_marg = go.Figure()
                    fig_marg.add_trace(go.Bar(
                        name=_fy_prior_name,
                        x=[r[0] for r in _margin_rows],
                        y=[r[1] for r in _margin_rows],
                        marker_color=_PRIOR_COLOR,
                        hovertemplate="%{x} margin · " + _fy_prior_name + ": %{y:.1f}%<extra></extra>",
                    ))
                    fig_marg.add_trace(go.Bar(
                        name=_fy_name,
                        x=[r[0] for r in _margin_rows],
                        y=[r[2] for r in _margin_rows],
                        marker_color=_CURRENT_COLOR,
                        text=[f"{r[2]:.1f}%" for r in _margin_rows],
                        textposition="outside",
                        textfont=dict(size=10, color="#CBD5E1"),
                        cliponaxis=False,
                        hovertemplate="%{x} margin · " + _fy_name + ": %{y:.1f}%<extra></extra>",
                    ))
                    _chart_dark(fig_marg, barmode="group", bargap=0.3, bargroupgap=0.08)
                    fig_marg.update_yaxes(ticksuffix="%", title_text="margin")
                    st.plotly_chart(fig_marg, width='stretch',
                                    config={"displayModeBar": False})

        # Cash flow waterfall. Preferred: where operating cash flow went
        # (capex / buybacks / dividends). If the extraction lacks those
        # detail lines, or they are immaterial next to OCF, fall back to the
        # always-present section totals: Operating -> Investing -> Financing
        # -> Net Change (this closes exactly for any filing).
        _ocf_cur = _pairs["Operating Cash Flow"]["current"]
        _detail_flows = []
        for _name in ("Capital Expenditures", "Buybacks", "Dividends"):
            _v = _pairs[_name]["current"]
            if _v is not None and _v != 0:
                _detail_flows.append((_name, -abs(_v)))
        _detail_total = sum(abs(f[1]) for f in _detail_flows)
        _icf_cur = _pairs["Investing Cash Flow"]["current"]
        _fin_cur = _pairs["Financing Cash Flow"]["current"]

        _wf_steps = None  # (title, caption, [(label, value)...], end_label)
        if (_ocf_cur is not None and len(_detail_flows) >= 2
                and _detail_total >= 0.10 * abs(_ocf_cur)):
            _wf_steps = (
                "Cash Flow Allocation",
                f"Where {_fy_name} operating cash flow went — the remainder "
                f"stays on the balance sheet.",
                _detail_flows,
                "Retained Cash",
            )
        elif _ocf_cur is not None and _icf_cur is not None and _fin_cur is not None:
            _wf_steps = (
                "Cash Flow Bridge",
                f"{_fy_name} cash movement by statement section — operating, "
                f"investing, and financing activities.",
                [("Investing Activities", _icf_cur),
                 ("Financing Activities", _fin_cur)],
                "Net Change in Cash",
            )

        if _wf_steps:
            _wf_title, _wf_caption, _wf_flows, _wf_end = _wf_steps
            st.markdown(f"##### {_wf_title}")
            st.caption(_wf_caption)
            _wf_total = _ocf_cur + sum(f[1] for f in _wf_flows)
            _div_wf, _ = _money_scale([_ocf_cur] + [f[1] for f in _wf_flows])
            fig_wf = go.Figure(go.Waterfall(
                x=(["Operating Cash Flow"] + [f[0] for f in _wf_flows]
                   + [_wf_end]),
                y=([_ocf_cur / _div_wf] + [f[1] / _div_wf for f in _wf_flows]
                   + [0]),
                measure=(["absolute"] + ["relative"] * len(_wf_flows)
                         + ["total"]),
                decreasing=dict(marker=dict(color="#F87171")),
                increasing=dict(marker=dict(color="#4ADE80")),
                totals=dict(marker=dict(color="#3574C6")),
                connector=dict(line=dict(color="rgba(255,255,255,0.2)", width=1)),
                text=([_fmt_num(_ocf_cur)] + [_fmt_num(f[1]) for f in _wf_flows]
                      + [_fmt_num(_wf_total)]),
                textposition="outside",
                textfont=dict(size=10, color="#CBD5E1"),
                cliponaxis=False,
                hoverinfo="skip",
            ))
            _chart_dark(fig_wf, height=320, showlegend=False)
            st.plotly_chart(fig_wf, width='stretch',
                            config={"displayModeBar": False})

        st.divider()

        # --- Section 4: Financial Health (RAG) | Capital Allocation ---
        rag_col, cap_col = st.columns(2)

        with rag_col:
            with st.container(border=True):
                st.markdown("##### Financial Health")
                rag_items = [
                    ("Liquidity",      "liquidity",  metrics.get("current_ratio")),
                    ("Leverage",       "leverage",   metrics.get("nd_ebitda")),
                    ("Debt / Equity",  "debt_equity", metrics.get("de_ratio")),
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
                    if rag_lbl == "RED":
                        lbl_color = "#fff"
                    elif rag_lbl == "N/A":
                        lbl_color = "#CBD5E1"
                    else:
                        lbl_color = "#333"
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;align-items:center;'
                        f'padding:7px 4px;border-bottom:1px solid rgba(255,255,255,0.06)">'
                        f'<span style="font-size:14px;color:#CBD5E1">{lbl}</span>'
                        f'<span>'
                        f'<span style="font-size:13px;margin-right:10px;color:#94A3B8">{val_str}</span>'
                        f'<span style="background:{bg};color:{lbl_color};padding:2px 10px;'
                        f'border-radius:3px;font-size:11px;font-weight:700">{rag_lbl}</span>'
                        f'</span></div>',
                        unsafe_allow_html=True,
                    )
                # CB-022/CB-023: disclose the composition of the derived
                # leverage/coverage ratios (receipts principle) — Debt/Equity,
                # Interest Cover (EBIT ÷ interest), and the EBIT add-back when
                # EBIT was derived rather than lifted from a printed line.
                _fh_calcs = metrics.get("calcs") or {}
                for _ck in ("debt_equity", "int_cover", "ebit"):
                    if _fh_calcs.get(_ck):
                        st.caption(_fh_calcs[_ck])

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
                        st.markdown(f"**{_escape_md_dollars(title)}**")
                        if detail:
                            # Claude-written analysis: render at readable size,
                            # not st.caption's faint 11px gray.
                            st.markdown(
                                f'<p style="font-size:13px;color:#94A3B8;'
                                f'margin:0 0 10px 0;line-height:1.55">{escape(detail)}</p>',
                                unsafe_allow_html=True,
                            )
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
                st.write(_escape_md_dollars(story))

        st.divider()

        # --- Section 6: Market Sentiment | Second-Level Question ---
        crowd_col, marks_col = st.columns(2)

        with crowd_col:
            with st.container(border=True):
                st.markdown("##### Market Sentiment (Marks)")
                crowd = dd.get("crowd_thinks") or "Re-analyse to generate sentiment view."
                st.write(_escape_md_dollars(crowd))

        with marks_col:
            with st.container(border=True):
                st.markdown("##### Second-Level Question")
                mq = dd.get("marks_question") or "Re-analyse to generate Marks question."
                st.write(_escape_md_dollars(mq))
                _mos_marks = (st.session_state.get("dcf_result") or {}).get("margin_of_safety_pct")
                if _mos_marks is not None:
                    _mos_mc = "#4ADE80" if _mos_marks > 20 else ("#FCD34D" if _mos_marks >= 0 else "#F87171")
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
                        status, bg, lbl_c = "N/A", "rgba(148,163,184,0.25)", "#CBD5E1"
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
                        f'padding:7px 4px;border-bottom:1px solid rgba(255,255,255,0.06)">'
                        f'<span style="font-size:14px;color:#CBD5E1">{scen_name}</span>'
                        f'<span>'
                        f'<span style="font-size:13px;margin-right:10px;color:#94A3B8">{ic_str}</span>'
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
                    st.markdown(f"**Consensus view:** {_escape_md_dollars(crowd_txt)}")
                if marks_q:
                    st.markdown(f"**What the market isn't asking:** {_escape_md_dollars(marks_q)}")
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
                        f'border-bottom:1px solid rgba(255,255,255,0.06)">'
                        f'<span style="font-size:14px;color:#94A3B8">{vname}</span>'
                        f'<span style="font-size:14px;font-weight:700;color:#F1F5F9">{vval}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                # Trust-Is-Page-Level receipt: this card mixes bases. P/E is
                # yfinance's trailing market ratio, NOT market cap ÷ filing
                # net income (TOU 2026-07-12: 33.0x TTM vs ~84x on the
                # impairment-year filing earnings — a silent 2.5x gap). The
                # EV multiples use market cap WITHOUT net debt (proxy).
                st.caption(
                    "P/E: yfinance trailing (market TTM basis — can differ "
                    "materially from filing-year earnings, e.g. impairment "
                    "years). EV/EBITDA & EV/Revenue: market cap used as the "
                    "EV proxy (net debt not added); EBITDA and revenue from "
                    "the filing. MoS: from the DCF inputs above."
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
                # HTML cards: html-escape only (no \$-escaping — markdown never runs in raw HTML).
                title  = escape(pt.get("title", ""))
                detail = escape(pt.get("detail", ""))
                st.markdown(
                    f'<div style="background:rgba(112,173,71,0.10);border-left:4px solid #70AD47;'
                    f'padding:10px 14px;margin-bottom:8px;border-radius:0 6px 6px 0">'
                    f'<div style="font-size:11px;color:#8FCE6B;font-weight:700;text-transform:uppercase;'
                    f'letter-spacing:0.5px;margin-bottom:4px">{fw}</div>'
                    f'<div style="font-size:14px;font-weight:600;color:#F1F5F9;margin-bottom:4px">{title}</div>'
                    f'<div style="font-size:13px;color:#94A3B8">{detail}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            if not bull_cases:
                st.caption("Re-analyse to generate bull case.")

        with bear_fw_col:
            st.markdown("**Bear Case**")
            for i, pt in enumerate(bear_cases[:3]):
                fw     = _BEAR_FW[i] if i < len(_BEAR_FW) else ""
                title  = escape(pt.get("title", ""))
                detail = escape(pt.get("detail", ""))
                st.markdown(
                    f'<div style="background:rgba(217,83,79,0.10);border-left:4px solid #D9534F;'
                    f'padding:10px 14px;margin-bottom:8px;border-radius:0 6px 6px 0">'
                    f'<div style="font-size:11px;color:#F08A8A;font-weight:700;text-transform:uppercase;'
                    f'letter-spacing:0.5px;margin-bottom:4px">{fw}</div>'
                    f'<div style="font-size:14px;font-weight:600;color:#F1F5F9;margin-bottom:4px">{title}</div>'
                    f'<div style="font-size:13px;color:#94A3B8">{detail}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            if not bear_cases:
                st.caption("Re-analyse to generate bear case.")

        st.caption("Powered by Dalio · Lynch · Marks frameworks")

    # =====================================================================
    with tab_econ:
    # =====================================================================
    # Resource Economics Snapshot — Tier 1
    # Spec: docs/RESOURCE_ECONOMICS_SNAPSHOT_SPEC.md (sections 2, 3-Tier1, 4).
    # Brains: modules/economics/resource_economics.py. This tab is UI only.
    # Gate: visible only when the SEDAR mapper resolved a resource sector profile.

        _econ_mapping = financial_data.get("mapping") if isinstance(financial_data, dict) else None
        _econ_meta = (_econ_mapping.get("meta") or {}) if isinstance(_econ_mapping, dict) else {}
        _econ_sector_profile = _econ_meta.get("sector_profile")
        _is_resource = _econ_sector_profile in ("mining_sector", "resource_sector")

        if not _is_resource:
            st.info(
                "📊 **Economics Snapshot** is available for resource-sector filings "
                "(mining or oil & gas). The mapper resolved this filing's sector profile "
                f"as `{_econ_sector_profile or 'None'}`. Load Agnico Eagle (AEM) or "
                "Canadian Natural Resources (CNQ) to see the panel."
            )
        else:
            # Build fundamentals dict the module's _extract_field / _extract_text understand.
            _sedar_extraction = financial_data.get("sedar_extraction") or {}
            _econ_sector_inferred = (
                _sedar_extraction.get("sector_inferred")
                or summary_data.get("sector_inferred")
                or financial_data.get("sector_inferred")
            )
            _econ_fundamentals = {
                "mapping": _econ_mapping,
                "sector_inferred": _econ_sector_inferred,
                "currency": financial_data.get("currency"),
                "scale": financial_data.get("scale") or _sedar_extraction.get("scale"),
                "fiscal_year_end": (
                    _sedar_extraction.get("fiscal_year_end")
                    or financial_data.get("fiscal_year")
                ),
            }
            # Session-state cache — module accepts a plain dict; spec section 3 calls for it.
            st.session_state.setdefault("economics_cache", {})
            _econ_cache = st.session_state["economics_cache"]

            try:
                _econ_snapshot = build_resource_economics_snapshot(
                    _econ_fundamentals,
                    ticker or "",
                    cache=_econ_cache,
                )
            except Exception as _econ_exc:
                st.error(f"Economics snapshot failed: {_econ_exc}")
                _econ_snapshot = None

            if _econ_snapshot:
                _econ_metrics = _econ_snapshot["metrics"]
                _econ_metadata = _econ_snapshot["metadata"]
                _econ_reasons = _econ_metadata.get("none_reasons") or {}
                _econ_company_mkt = _econ_snapshot["market_data"]["company"]
                _econ_cmdt_mkt = _econ_snapshot["market_data"]["commodity"]
                _econ_spot = _econ_snapshot["commodity_spot_price"]
                _econ_trend = _econ_snapshot["commodity_trend"]
                _econ_cheap = _econ_snapshot["cheap_company_or_cheap_sector"]
                _econ_fetch_errs = _econ_metadata.get("fetch_errors") or {}

                # --- Header line ---
                _econ_cmdt_key = _econ_cmdt_mkt.get("commodity")
                _econ_proxy_symbol = _econ_cmdt_mkt.get("proxy_used")
                _econ_proxy = _econ_proxy_symbol or "—"
                _econ_proxy_role = _econ_cmdt_mkt.get("proxy_role") or "—"
                _econ_cmdt_display = build_commodity_display_text(
                    _econ_cmdt_key,
                    _econ_proxy_symbol,
                )
                _econ_cmdt_header_label = _econ_cmdt_display["header_label"]
                _econ_cmdt_spot_title = _econ_cmdt_display["spot_title"]
                _econ_cmdt_caveat = _econ_cmdt_display["crude_caveat"]
                # CB-027: many producers sell several commodities at once and
                # the sector string cannot reveal the revenue weighting — the
                # header records EVERY family evidenced (incl. record-only
                # families with no free-tier proxy) and claims NO primary;
                # a benchmark block renders below for each proxied family.
                _econ_all_commodities = _econ_metadata.get("commodities") or []
                _econ_benchmarks = _econ_snapshot.get("commodity_benchmarks") or []
                if len(_econ_all_commodities) > 1:
                    _cmdt_names = []
                    for _c in _econ_all_commodities:
                        _cname = str(_c.get("name") or "").title()
                        if not _c.get("proxy_available"):
                            _cname += " (recorded — no free-tier benchmark proxy)"
                        _cmdt_names.append(_cname)
                    _econ_cmdt_line = (
                        f'Commodities: {escape(", ".join(_cmdt_names))} — from the sector '
                        f'description; <b>no revenue weighting claimed</b>. A benchmark '
                        f'block renders below for each proxied commodity.'
                    )
                else:
                    _econ_cmdt_line = (
                        f'Commodity: {escape(_econ_cmdt_header_label)}; '
                        f'proxy: <code>{escape(_econ_proxy)}</code> ({escape(_econ_proxy_role)}).'
                    )
                st.markdown(
                    f'<div style="font-size:20px;font-weight:700;color:#F1F5F9;margin:0 0 4px 0">'
                    f'Resource Economics Snapshot — Tier 1</div>'
                    f'<div style="font-size:12px;color:#64748B;margin:0 0 16px 0">'
                    f'Filing fundamentals × yfinance commodity overlay. '
                    f'{_econ_cmdt_line} Free tier (yfinance only); no API cost.'
                    f'{"<br>" + escape(_econ_cmdt_caveat) if _econ_cmdt_caveat else ""}</div>',
                    unsafe_allow_html=True,
                )

                # Currency guard — the module suppresses market-cap ratios when the
                # filing currency and the listing currency differ or can't be
                # determined (honest skip beats a wrong cross-currency number).
                # Code-generated text, no dollars — safe for the markdown pipeline.
                _econ_guard = _econ_metadata.get("currency_guard") or {}
                if _econ_guard.get("suppressed") and _econ_guard.get("note"):
                    st.warning(_econ_guard["note"])

                # --- Helpers (local; reused across cards) ---
                def _econ_fmt_pct(v):
                    return f"{v*100:.1f}%" if isinstance(v, (int, float)) else "—"
                def _econ_fmt_mult(v):
                    return f"{v:.2f}×" if isinstance(v, (int, float)) else "—"
                def _econ_fmt_price(v):
                    return f"${v:,.2f}" if isinstance(v, (int, float)) else "—"

                _econ_card_style = (
                    "background:linear-gradient(135deg,#252D40 0%,#1E2840 100%);"
                    "border:0.5px solid rgba(255,255,255,0.08);border-radius:12px;"
                    "box-shadow:0 4px 24px rgba(0,0,0,0.3),0 1px 0 rgba(255,255,255,0.04) inset;"
                    "padding:0.85rem 1rem;margin:0 0 0.5rem 0;"
                )
                _econ_label_style = (
                    "font-size:10px;font-weight:600;letter-spacing:0.08em;"
                    "text-transform:uppercase;color:#64748B;"
                )
                _econ_value_style = (
                    "font-size:28px;font-weight:600;color:#F1F5F9;letter-spacing:-0.02em;"
                )
                _econ_reason_style = (
                    "font-size:11px;color:#94A3B8;margin-top:6px;font-style:italic;"
                )

                def _econ_metric_card(label, value, reason=None, extra_html=""):
                    # The currency-guard note renders once in the banner above;
                    # cards affected by it carry a short pointer instead of
                    # repeating the full sentence.
                    if reason and reason == _econ_guard.get("note"):
                        reason = "Suppressed — see currency note above."
                    body = (
                        f'<div style="{_econ_label_style}">{escape(label)}</div>'
                        f'<div style="{_econ_value_style}">{escape(value)}</div>'
                    )
                    if reason:
                        body += f'<div style="{_econ_reason_style}">{escape(reason)}</div>'
                    body += extra_html
                    st.markdown(
                        f'<div style="{_econ_card_style}">{body}</div>',
                        unsafe_allow_html=True,
                    )

                # --- Row 1: three metric cards ---
                # resource_sector canonical revenue is GROSS of royalties (product
                # sales / gross revenues per the 2026-06-17 ground-truth decision) —
                # label it so a user reconciling against the filing's net "Revenue"
                # line isn't hit by an unexplained discrepancy.
                _econ_is_gross_revenue = _econ_sector_profile == "resource_sector"
                _econ_revenue_label = (
                    "Revenue (gross of royalties) / Market Cap"
                    if _econ_is_gross_revenue
                    else "Revenue / Market Cap"
                )
                _ec1, _ec2, _ec3 = st.columns(3)
                with _ec1:
                    _econ_metric_card(
                        "Earnings Yield",
                        _econ_fmt_pct(_econ_metrics.get("earnings_yield")),
                        _econ_reasons.get("earnings_yield"),
                    )
                with _ec2:
                    _econ_metric_card(
                        _econ_revenue_label,
                        _econ_fmt_mult(_econ_metrics.get("revenue_to_market_cap")),
                        _econ_reasons.get("revenue_to_market_cap"),
                    )
                with _ec3:
                    _econ_metric_card(
                        "Net Margin",
                        _econ_fmt_pct(_econ_metrics.get("net_margin")),
                        _econ_reasons.get("net_margin"),
                    )
                if _econ_is_gross_revenue:
                    st.caption(
                        "Revenue basis: gross of royalties — the canonical resource-sector "
                        "top line (e.g. product sales / gross revenues), before royalty "
                        "deductions. Net margin uses the same gross revenue denominator."
                    )

                # --- Row 2: spot + commodity linkage + cheap flag ---
                _ecA, _ecB, _ecC = st.columns(3)
                with _ecA:
                    _spot_reason = _econ_spot.get("reason") or (
                        f"via {_econ_proxy} ({_econ_proxy_role})"
                        if _econ_cmdt_mkt.get("proxy_used") else None
                    )
                    _econ_metric_card(
                        _econ_cmdt_spot_title,
                        _econ_fmt_price(_econ_spot.get("value")),
                        _spot_reason,
                    )
                with _ecB:
                    # Is the equity a commodity proxy or an operating story?
                    _econ_corr = _econ_snapshot.get("commodity_correlation") or {}
                    _corr_val = _econ_corr.get("correlation")
                    _corr_beta = _econ_corr.get("beta")
                    if _corr_val is not None and _corr_beta is not None:
                        _corr_value_text = f"r = {_corr_val:.2f}"
                        _corr_reason = (
                            f"β {_corr_beta:.2f}× vs {_econ_corr.get('proxy_used') or 'proxy'} "
                            f"daily moves · {_econ_corr.get('points_used')} trading days"
                        )
                    else:
                        _corr_value_text = "—"
                        _corr_reason = _econ_corr.get("reason")
                    _econ_metric_card(
                        "Commodity Linkage (1y daily returns)",
                        _corr_value_text,
                        _corr_reason,
                    )
                with _ecC:
                    _flag = _econ_cheap.get("company_flag")
                    _flag_label_map = {
                        "high_earnings_yield": "Cheap company signal",
                        "not_high_earnings_yield": "Not flagged cheap",
                    }
                    _flag_label = _flag_label_map.get(_flag, "Insufficient data")
                    _flag_reason = _econ_cheap.get("reason") or (
                        f"Earnings yield {_econ_fmt_pct(_econ_metrics.get('earnings_yield'))} "
                        f"vs 8% threshold. See trend below for sector context."
                        if _flag else None
                    )
                    # Show the verdict as a position on a scale, not just a
                    # phrase: bar = earnings yield on a 0-16% scale, with the
                    # 8% threshold as the amber mid-tick.
                    _flag_bar = ""
                    _ey_val = _econ_metrics.get("earnings_yield")
                    if isinstance(_ey_val, (int, float)):
                        _ey_fill = max(0.0, min(_ey_val / 0.16, 1.0)) * 100
                        _ey_color = "#4ADE80" if _ey_val >= 0.08 else "#94A3B8"
                        _flag_bar = (
                            f'<div style="margin-top:8px;background:rgba(255,255,255,0.10);'
                            f'border-radius:4px;height:8px;position:relative">'
                            f'<div style="width:{_ey_fill:.0f}%;height:100%;'
                            f'background:{_ey_color};border-radius:4px"></div>'
                            f'<div style="position:absolute;left:50%;top:-2px;width:2px;'
                            f'height:12px;background:#FCD34D" title="8% threshold"></div>'
                            f'</div>'
                            f'<div style="font-size:10px;color:#64748B;margin-top:3px">'
                            f'earnings yield on a 0–16% scale · amber tick = 8% threshold</div>'
                        )
                    _econ_metric_card(
                        "Cheap company / cheap sector?",
                        _flag_label,
                        _flag_reason,
                        extra_html=_flag_bar,
                    )

                # --- Commodity price trend chart ---
                # Trend dates arrive as ISO strings; parse to datetime so the
                # x-axis is a true date axis. Shared by the trend chart and the
                # indexed company-vs-commodity chart below.
                def _econ_parse_date(value):
                    try:
                        return datetime.fromisoformat(str(value))
                    except (ValueError, TypeError):
                        return None

                def _econ_render_trend_chart(trend_points, proxy_symbol, unit_label,
                                             commodity_label=None):
                    # CB-027: shared by benchmark #1 and every additional
                    # commodity benchmark block (multi-commodity filers).
                    _title = "Commodity Price Trend — last 1 year"
                    if commodity_label:
                        _title = f"{commodity_label} Price Trend — last 1 year"
                    if not trend_points:
                        st.caption("Commodity price trend unavailable — proxy returned no points.")
                        return
                    st.markdown(
                        f'<div style="font-size:13px;font-weight:700;color:#F1F5F9;margin:18px 0 4px 0">'
                        f'{escape(_title)}</div>'
                        f'<div style="font-size:11px;color:#64748B;margin:0 0 8px 0">'
                        f'Source proxy: <code>{escape(proxy_symbol or "—")}</code>. '
                        f'Filing fiscal year end overlaid in dotted gray.</div>',
                        unsafe_allow_html=True,
                    )
                    # Fall back to raw strings only if any point fails to
                    # parse (so the x list never mixes types).
                    _raw_xs = [p["date"] for p in trend_points]
                    _parsed_xs = [_econ_parse_date(x) for x in _raw_xs]
                    _trend_xs = _parsed_xs if all(d is not None for d in _parsed_xs) else _raw_xs
                    _trend_ys = [p["close"] for p in trend_points]
                    _trend_fig = go.Figure()
                    _trend_fig.add_trace(go.Scatter(
                        x=_trend_xs, y=_trend_ys,
                        mode='lines',
                        line=dict(color='#F4B942', width=2),
                        fill='tozeroy',
                        fillcolor='rgba(244,185,66,0.08)',
                        name=proxy_symbol or "Commodity",
                    ))
                    # Overlay the filing's fiscal-year-end as a dotted vertical line.
                    # NOTE: plotly 6.7.0's add_vline crashes on datetime/string x
                    # (TypeError in its annotation math), so we draw the line with
                    # add_shape + add_annotation instead. Skip the overlay entirely
                    # when fiscal_year_end is missing or unparseable (e.g. CSU/REI.UN
                    # with null filing dates) — render the chart without it, no crash.
                    _fye = _econ_metadata.get("fiscal_year_end")
                    _fye_dt = _econ_parse_date(_fye) if _fye else None
                    if _fye_dt is not None:
                        _trend_fig.add_shape(
                            type='line',
                            x0=_fye_dt, x1=_fye_dt,
                            yref='paper', y0=0, y1=1,
                            line=dict(dash='dot', color='rgba(148,163,184,0.6)'),
                        )
                        _trend_fig.add_annotation(
                            x=_fye_dt, yref='paper', y=1,
                            text=f'FYE {_fye}',
                            showarrow=False,
                            font=dict(color='#94A3B8', size=10),
                            yanchor='bottom',
                        )
                    _trend_fig.update_layout(
                        paper_bgcolor='#1E2433',
                        plot_bgcolor='#1E2433',
                        font=dict(color='#94A3B8', size=11),
                        margin=dict(l=40, r=20, t=20, b=40),
                        showlegend=False,
                        height=280,
                    )
                    # Mark the latest close so the spot card above ties
                    # visually to the end of the line.
                    _trend_fig.add_trace(go.Scatter(
                        x=[_trend_xs[-1]], y=[_trend_ys[-1]],
                        mode='markers',
                        marker=dict(size=8, color='#F4B942'),
                        showlegend=False, hoverinfo='skip',
                    ))
                    _trend_fig.add_annotation(
                        x=_trend_xs[-1], y=_trend_ys[-1],
                        text=f"${_trend_ys[-1]:,.2f}",
                        showarrow=False, xanchor='left', xshift=6,
                        font=dict(color='#F4B942', size=10),
                    )
                    _trend_fig.update_xaxes(gridcolor='rgba(255,255,255,0.06)', zerolinecolor='rgba(255,255,255,0.1)')
                    _trend_fig.update_yaxes(
                        gridcolor='rgba(255,255,255,0.06)',
                        zerolinecolor='rgba(255,255,255,0.1)',
                        title_text=unit_label or "US$",
                    )
                    st.plotly_chart(_trend_fig, width='stretch', config={"displayModeBar": False})

                _trend_points = _econ_trend.get("points") or []
                _econ_render_trend_chart(
                    _trend_points,
                    _econ_trend.get("proxy_used"),
                    _econ_cmdt_display.get("unit_label"),
                )

                # --- Company vs commodity — indexed relative performance ---
                # Both series rebased to 100 one year back, on ONE axis: shows
                # whether the equity tracked the commodity or diverged from it.
                _company_trend = _econ_snapshot.get("company_trend") or {}
                _company_points = _company_trend.get("points") or []
                _company_symbol = _company_trend.get("ticker_used") or "Company"

                def _econ_render_indexed_chart(trend_points, proxy_name,
                                               commodity_label=None):
                    # CB-027: shared by benchmark #1 and every additional
                    # commodity benchmark block (multi-commodity filers).
                    if not (_company_points and trend_points):
                        return

                    def _econ_indexed(points):
                        base = points[0]["close"]
                        if not base:
                            return None, None
                        xs = [_econ_parse_date(p["date"]) for p in points]
                        if any(x is None for x in xs):
                            xs = [p["date"] for p in points]
                        ys = [p["close"] / base * 100 for p in points]
                        return xs, ys

                    _cmd_xs, _cmd_ys = _econ_indexed(trend_points)
                    _cmp_xs, _cmp_ys = _econ_indexed(_company_points)
                    if _cmd_ys and _cmp_ys:
                        _cmd_name = proxy_name or "Commodity"
                        _vs_label = commodity_label or "Commodity"
                        st.markdown(
                            f'<div style="font-size:13px;font-weight:700;color:#F1F5F9;margin:18px 0 4px 0">'
                            f'Company vs {escape(_vs_label)} — indexed to 100, last 1 year</div>'
                            f'<div style="font-size:11px;color:#64748B;margin:0 0 8px 0">'
                            f'Is the equity tracking the commodity or diverging from it? '
                            f'Both series rebased to 100 at the start of the window.</div>',
                            unsafe_allow_html=True,
                        )
                        # Colorblind-validated pair on the dark surface:
                        # commodity amber #B8821F, company blue #3574C6.
                        _idx_fig = go.Figure()
                        _idx_fig.add_trace(go.Scatter(
                            x=_cmd_xs, y=_cmd_ys, mode='lines',
                            name=_cmd_name,
                            line=dict(color='#B8821F', width=2),
                            hovertemplate=_cmd_name + " · %{x|%b %d}: %{y:.0f}<extra></extra>",
                        ))
                        _idx_fig.add_trace(go.Scatter(
                            x=_cmp_xs, y=_cmp_ys, mode='lines',
                            name=_company_symbol,
                            line=dict(color='#3574C6', width=2),
                            hovertemplate=_company_symbol + " · %{x|%b %d}: %{y:.0f}<extra></extra>",
                        ))
                        _idx_fig.add_hline(
                            y=100, line_dash='dot',
                            line_color='rgba(148,163,184,0.4)',
                        )
                        # Direct labels at the line ends: final index values.
                        for _xs, _ys, _color in (
                            (_cmd_xs, _cmd_ys, '#B8821F'),
                            (_cmp_xs, _cmp_ys, '#3574C6'),
                        ):
                            _idx_fig.add_annotation(
                                x=_xs[-1], y=_ys[-1],
                                text=f"{_ys[-1]:.0f}",
                                showarrow=False, xanchor='left',
                                font=dict(color=_color, size=10),
                            )
                        _idx_fig.update_layout(
                            paper_bgcolor='#1E2433',
                            plot_bgcolor='#1E2433',
                            font=dict(color='#94A3B8', size=11),
                            margin=dict(l=40, r=40, t=20, b=40),
                            height=280,
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                        )
                        _idx_fig.update_xaxes(gridcolor='rgba(255,255,255,0.06)', zerolinecolor='rgba(255,255,255,0.1)')
                        _idx_fig.update_yaxes(gridcolor='rgba(255,255,255,0.06)', zerolinecolor='rgba(255,255,255,0.1)', title_text='Indexed (start = 100)')
                        st.plotly_chart(_idx_fig, width='stretch', config={"displayModeBar": False})

                _econ_render_indexed_chart(
                    _trend_points,
                    _econ_trend.get("proxy_used"),
                    _econ_cmdt_display["commodity_label"] if len(_econ_benchmarks) > 1 else None,
                )

                # --- CB-027: additional commodity benchmarks (no primary) ---
                # Multi-commodity filers (e.g. "Upstream Oil & Gas" — CNQ, TOU,
                # ARX) get a full benchmark block per proxied commodity: spot,
                # linkage, trend, and indexed chart. The first family rendered
                # above is NOT a primary — the header says so.
                for _bm in _econ_benchmarks[1:]:
                    _bm_display = build_commodity_display_text(
                        _bm.get("commodity"), _bm.get("proxy_used")
                    )
                    _bm_label = _bm_display["commodity_label"]
                    st.markdown(
                        f'<div style="font-size:16px;font-weight:700;color:#F1F5F9;margin:22px 0 4px 0">'
                        f'{escape(_bm_label)} benchmark</div>'
                        f'<div style="font-size:11px;color:#64748B;margin:0 0 10px 0">'
                        f'Additional commodity this filer produces — no revenue '
                        f'weighting claimed between benchmarks. Proxy: '
                        f'<code>{escape(_bm.get("proxy_used") or "—")}</code> '
                        f'({escape(_bm.get("proxy_role") or "—")}).'
                        f'{"<br>" + escape(_bm_display["crude_caveat"]) if _bm_display["crude_caveat"] else ""}</div>',
                        unsafe_allow_html=True,
                    )
                    _bm1, _bm2, _bm3 = st.columns(3)
                    with _bm1:
                        _bm_spot_reason = (
                            f'via {_bm.get("proxy_used")} ({_bm.get("proxy_role") or "—"})'
                            if _bm.get("proxy_used")
                            else (_bm.get("error") or "proxy unavailable")
                        )
                        _econ_metric_card(
                            _bm_display["spot_title"],
                            _econ_fmt_price(_bm.get("spot_price")),
                            _bm_spot_reason,
                        )
                    with _bm2:
                        _bm_corr = _bm.get("correlation") or {}
                        _bm_corr_val = _bm_corr.get("correlation")
                        _bm_corr_beta = _bm_corr.get("beta")
                        if _bm_corr_val is not None and _bm_corr_beta is not None:
                            _bm_corr_text = f"r = {_bm_corr_val:.2f}"
                            _bm_corr_reason = (
                                f"β {_bm_corr_beta:.2f}× vs {_bm_corr.get('proxy_used') or 'proxy'} "
                                f"daily moves · {_bm_corr.get('points_used')} trading days"
                            )
                        else:
                            _bm_corr_text = "—"
                            _bm_corr_reason = _bm_corr.get("reason")
                        _econ_metric_card(
                            "Commodity Linkage (1y daily returns)",
                            _bm_corr_text,
                            _bm_corr_reason,
                        )
                    _econ_render_trend_chart(
                        _bm.get("trend") or [],
                        _bm.get("proxy_used"),
                        _bm_display.get("unit_label"),
                        _bm_label,
                    )
                    _econ_render_indexed_chart(
                        _bm.get("trend") or [],
                        _bm.get("proxy_used"),
                        _bm_label,
                    )

                # --- Cost structure waterfall (statement-level) ---
                # Where the top line goes, using the sector profile's mapped
                # cost fields. Ends in "margin after these costs" — G&A,
                # finance, and other items are deliberately out of scope, so
                # the end bar is NOT the filer's printed operating income.
                _cs = _econ_snapshot.get("cost_structure") or {}
                _cs_rev = _cs.get("revenue")
                _CS_ITEMS = [
                    ("royalties", "Royalties"),
                    ("production_costs", "Production Costs"),
                    ("operating_expense", "Operating Expense"),
                    ("exploration_expense", "Exploration"),
                    ("mine_development_amortization", "Mine D&A"),
                    ("depletion_depreciation_amortization", "DD&A"),
                ]
                # -abs() normalizes both storage conventions: royalties are
                # stored negative (as-presented deduction), most costs positive.
                _cs_flows = [
                    (label, -abs(_cs[key]))
                    for key, label in _CS_ITEMS
                    if _cs.get(key)
                ]
                if _cs_rev and _cs_flows:
                    st.markdown(
                        '<div style="font-size:13px;font-weight:700;color:#F1F5F9;margin:18px 0 4px 0">'
                        'Cost Structure — where the top line goes</div>'
                        '<div style="font-size:11px;color:#64748B;margin:0 0 8px 0">'
                        'Statement-level costs from the sector profile\'s mapped fields '
                        'only. The end bar is the margin after these costs — before '
                        'G&amp;A, finance, and other items, so it will not equal the '
                        'filer\'s printed operating income.</div>',
                        unsafe_allow_html=True,
                    )
                    _cs_margin = _cs_rev + sum(f[1] for f in _cs_flows)
                    _cs_div, _ = _money_scale([_cs_rev] + [f[1] for f in _cs_flows])
                    _cs_fig = go.Figure(go.Waterfall(
                        x=(["Revenue"] + [f[0] for f in _cs_flows]
                           + ["Margin After These Costs"]),
                        y=([_cs_rev / _cs_div] + [f[1] / _cs_div for f in _cs_flows]
                           + [0]),
                        measure=(["absolute"] + ["relative"] * len(_cs_flows)
                                 + ["total"]),
                        decreasing=dict(marker=dict(color="#F87171")),
                        increasing=dict(marker=dict(color="#4ADE80")),
                        totals=dict(marker=dict(color="#3574C6")),
                        connector=dict(line=dict(color="rgba(255,255,255,0.2)", width=1)),
                        text=([_fmt_num(_cs_rev)] + [_fmt_num(f[1]) for f in _cs_flows]
                              + [_fmt_num(_cs_margin)]),
                        textposition="outside",
                        textfont=dict(size=10, color="#CBD5E1"),
                        cliponaxis=False,
                        hoverinfo="skip",
                    ))
                    _cs_fig.update_layout(
                        paper_bgcolor='#1E2433',
                        plot_bgcolor='#1E2433',
                        font=dict(color='#94A3B8', size=11),
                        margin=dict(l=40, r=20, t=30, b=40),
                        height=300,
                        showlegend=False,
                    )
                    _cs_fig.update_xaxes(gridcolor='rgba(255,255,255,0.06)', zerolinecolor='rgba(255,255,255,0.1)')
                    _cs_fig.update_yaxes(gridcolor='rgba(255,255,255,0.06)', zerolinecolor='rgba(255,255,255,0.1)')
                    st.plotly_chart(_cs_fig, width='stretch', config={"displayModeBar": False})
                    _cs_margin_pct = _cs_margin / _cs_rev * 100 if _cs_rev else None
                    if _cs_margin_pct is not None:
                        # Royalty burden — the O&G-specific number: what share
                        # of the GROSS top line the crown/royalty holders took
                        # (canonical resource revenue is gross of royalties).
                        _royalty_note = ""
                        _cs_royalties = _cs.get("royalties")
                        if _cs_royalties and _cs_rev:
                            _royalty_pct = abs(_cs_royalties) / _cs_rev * 100
                            _royalty_note = (
                                f" Royalties took {_royalty_pct:.1f}% of the "
                                f"gross top line."
                            )
                        st.caption(
                            f"Margin after these costs: {_cs_margin_pct:.1f}% "
                            f"of the top line.{_royalty_note}"
                        )

                # --- Tier 2 placeholder slot (clearly upcoming, no fake data) ---
                _econ_tier2_style = (
                    "background:rgba(30,36,51,0.5);"
                    "border:0.5px dashed rgba(244,185,66,0.35);border-radius:12px;"
                    "padding:1rem 1.2rem;margin:18px 0 0 0;"
                )
                st.markdown(
                    f'<div style="{_econ_tier2_style}">'
                    f'<div style="font-size:11px;font-weight:700;letter-spacing:0.12em;'
                    f'text-transform:uppercase;color:#F4B942;margin-bottom:4px">'
                    f'TIER 2 · PARTIALLY LIVE</div>'
                    f'<div style="font-size:15px;font-weight:600;color:#F1F5F9;margin-bottom:6px">'
                    f'AISC vs Spot · Netback vs Price</div>'
                    f'<div style="font-size:12px;color:#94A3B8;line-height:1.5">'
                    f'The flagship margin-of-safety metric — All-In Sustaining Cost vs commodity '
                    f'spot (mining) or netback vs commodity price (oil &amp; gas). These figures '
                    f'live in the MD&amp;A, not the consolidated income statement. The O&amp;G '
                    f'inputs ($/boe netback, production volumes) are now extractable via the '
                    f'MD&amp;A Operational Metrics panel below; the vs-price overlay chart and '
                    f'the mining AISC pack land next. See '
                    f'<code>docs/MDA_FETCHER_SPEC.md</code> and '
                    f'<code>docs/RESOURCE_ECONOMICS_SNAPSHOT_SPEC.md</code> §3 Tier 2.</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                # --- Honest provenance + coverage footer ---
                with st.expander("Data provenance & coverage", expanded=False):
                    st.markdown(f"**Ticker resolved:** `{_econ_metadata.get('ticker_used') or '—'}`")
                    st.markdown(
                        f"**Sector inferred:** `{_econ_sector_inferred or '—'}` "
                        f"→ profile: `{_econ_sector_profile}`"
                    )
                    st.markdown(
                        f"**Commodity:** `{_econ_metadata.get('commodity') or '—'}` "
                        f"via `{_econ_metadata.get('proxy_used') or '—'}`"
                    )
                    st.markdown(
                        f"**Scale applied:** `{_econ_metadata.get('scale') or '—'}` "
                        f"(factor ×{_econ_metadata.get('scale_factor_applied')})"
                    )
                    _missing = _econ_metadata.get("missing_inputs") or []
                    if _missing:
                        st.markdown(f"**Missing inputs:** {', '.join(_missing)}")
                    if _econ_fetch_errs.get("company"):
                        st.warning(f"Company fetch error: {_econ_fetch_errs['company']}")
                    if _econ_fetch_errs.get("commodity"):
                        st.warning(f"Commodity fetch error: {_econ_fetch_errs['commodity']}")

            # =============================================================
            # Hedging Book — as disclosed in the statement notes (CB-034,
            # design: docs/HEDGING_BOOK_SPEC.md). On-demand extraction
            # (Riley's ratified trigger): analysis stays your click.
            # =============================================================
            st.divider()
            _hb = financial_data.get("hedging_book") if isinstance(financial_data, dict) else None

            if not isinstance(_hb, dict):
                st.markdown("#### 🔒 Hedging Book")
                _hb_pdf = _hedging_pdf_path_for_current(ticker, financial_data)
                if not _hb_pdf:
                    st.caption(
                        "Extracts the derivative/hedging note (volumes, prices, tenor, "
                        "fair values) from the filed statements. The source PDF is not "
                        "cached for this filing — re-load or re-upload it to enable."
                    )
                else:
                    st.caption(
                        "Extract the derivative/hedging note — positions, prices, tenor, "
                        "fair values, as disclosed. One targeted Claude pass (~$0.05–0.15)."
                    )
                    if st.button("🔒 Extract Hedging Book $", key="hedging_extract_go"):
                        with st.spinner("Extracting the derivative note (30–90 seconds)..."):
                            try:
                                _hb_book = extract_hedging_note(_hb_pdf)
                            except SedarExtractionError as _hb_exc:
                                st.error(f"Hedging-note extraction failed: {_hb_exc}")
                                _hb_book = None
                            except Exception as _hb_exc:
                                st.error(f"Hedging-note extraction failed: {_hb_exc} — try again.")
                                _hb_book = None
                        if _hb_book is not None:
                            financial_data["hedging_book"] = _hb_book
                            # Re-run integrity so the CB-034 fair-value tie rule
                            # arms with the new data (fresh moat-log record).
                            _hb_fd = _run_integrity_checks(
                                financial_data,
                                st.session_state.get("summary_data"),
                                ticker,
                                financial_data.get("source", "sedar"),
                                filing_date=financial_data.get("sedar_filing_date"),
                            )
                            if isinstance(_hb_fd, dict):
                                st.session_state.financial_data = _hb_fd
                            _save_analysis_cache(
                                ticker,
                                financial_data.get("fiscal_year") or financial_data.get("period"),
                                financial_data.get("source", "sedar"),
                            )
                            st.rerun()
            elif _hb.get("status") == "no_note_detected":
                st.markdown("#### 🔒 Hedging Book")
                st.info(
                    "No derivative/hedging note was detected in this filing — "
                    "itself a finding: the filer discloses no hedge positions in "
                    "the pages scanned."
                )
            else:
                st.markdown("#### 🔒 Hedging Book — as disclosed")
                _hb_fp = _hb.get("figure_presence") or {}
                _hb_positions = _hb.get("commodity_positions") or []
                _hb_fx = _hb.get("fx_positions") or []
                _hb_ir = _hb.get("interest_rate_positions") or []
                _hb_subs = _hb.get("subsequent_event_positions") or []

                # Summary strip
                _hb_c1, _hb_c2, _hb_c3 = st.columns(3)
                with _hb_c1:
                    _hb_fv = _hb.get("fair_value_total")
                    if _hb_fv is not None:
                        st.metric("Net fair value (as printed)",
                                  f"{_hb_fv:,.0f} {_hb.get('fair_value_scale') or ''}")
                    else:
                        _hb_mtms = _hb.get("mtm_disclosures") or []
                        _hb_mtm_sum = sum(m.get("amount") or 0 for m in _hb_mtms
                                          if isinstance(m.get("amount"), (int, float)))
                        st.metric("MTM disclosures (sum)",
                                  f"{_hb_mtm_sum:,.1f}" if _hb_mtms else "—")
                with _hb_c2:
                    st.metric("Positions", f"{len(_hb_positions)} commodity · "
                                           f"{len(_hb_fx)} FX · {len(_hb_ir)} IR")
                with _hb_c3:
                    if _hb_fp.get("missing_count", 0) == 0 and _hb_fp.get("checked"):
                        st.metric("Figure presence", f"{_hb_fp['checked']}/{_hb_fp['checked']} ✓")
                    else:
                        st.metric("Figure presence",
                                  f"{_hb_fp.get('missing_count', '?')} UNVERIFIED")
                if _hb_fp.get("missing_count"):
                    st.warning(
                        f"⚠️ {_hb_fp['missing_count']} extracted value(s) were NOT found "
                        "verbatim in the note text — treat those figures as unverified "
                        "and check the source pages."
                    )

                # Roll-off view: hedged volume by start year per commodity+unit.
                _hb_rolloff: dict = {}
                for _pos in _hb_positions:
                    _yr = _pos.get("period_start_year")
                    _vol = _pos.get("volume")
                    if not isinstance(_yr, (int, float)) or not isinstance(_vol, (int, float)):
                        continue
                    _rk = (_pos.get("commodity") or "?", _pos.get("volume_unit") or "")
                    _hb_rolloff.setdefault(_rk, {})
                    _hb_rolloff[_rk][int(_yr)] = _hb_rolloff[_rk].get(int(_yr), 0) + _vol
                if _hb_rolloff:
                    st.caption(
                        "Hedged volume by start year (sum of disclosed position rows — "
                        "quarterly rows sum within a year; the roll-off cliff is the story):"
                    )
                    _hb_years = sorted({y for row in _hb_rolloff.values() for y in row})
                    _hb_table = [
                        {"Commodity / unit": f"{ck} ({cu})",
                         **{str(y): f"{row.get(y, 0):,.0f}" for y in _hb_years}}
                        for (ck, cu), row in sorted(_hb_rolloff.items())
                    ]
                    st.dataframe(_hb_table, hide_index=True, width='stretch')

                with st.expander(
                    f"All positions — the receipt ({len(_hb_positions) + len(_hb_fx) + len(_hb_ir)} "
                    f"current + {len(_hb_subs)} subsequent)", expanded=False,
                ):
                    if _hb_positions:
                        st.markdown("**Commodity contracts** (as disclosed)")
                        st.dataframe([
                            {"Index": p.get("index"), "Period": p.get("period_label"),
                             "Type": p.get("instrument"), "Volume": p.get("volume"),
                             "Unit": p.get("volume_unit"), "Price": p.get("price"),
                             "Floor": p.get("price_floor"), "Ceiling": p.get("price_ceiling"),
                             "Price unit": p.get("price_unit"), "Fair value": p.get("fair_value"),
                             "Page": p.get("source_page")}
                            for p in _hb_positions
                        ], hide_index=True, width='stretch')
                    if _hb_fx:
                        st.markdown("**FX contracts**")
                        st.dataframe([
                            {"Type": p.get("instrument"), "Direction": p.get("direction"),
                             "Period": p.get("period_label"), "Amount": p.get("amount"),
                             "Unit": p.get("amount_unit"), "Rate": p.get("rate"),
                             "Floor": p.get("rate_floor"), "Ceiling": p.get("rate_ceiling"),
                             "Page": p.get("source_page")}
                            for p in _hb_fx
                        ], hide_index=True, width='stretch')
                    if _hb_ir:
                        st.markdown("**Interest-rate contracts**")
                        st.dataframe([
                            {"Term": p.get("term_label"), "Notional": p.get("notional"),
                             "Unit": p.get("notional_unit"), "Fixed %": p.get("fixed_rate_pct"),
                             "Floating": p.get("floating_benchmark"), "Page": p.get("source_page")}
                            for p in _hb_ir
                        ], hide_index=True, width='stretch')
                    if _hb_subs:
                        st.markdown("**Entered AFTER period end** (subsequent events)")
                        st.dataframe([
                            {"Index": p.get("index") or p.get("direction") or p.get("term_label"),
                             "Period": p.get("period_label"), "Type": p.get("instrument"),
                             "Volume/Amount": p.get("volume") if p.get("volume") is not None else p.get("amount"),
                             "Unit": p.get("volume_unit") or p.get("amount_unit"),
                             "Price/Rate": p.get("price") if p.get("price") is not None else p.get("rate"),
                             "Floor": p.get("price_floor") or p.get("rate_floor"),
                             "Ceiling": p.get("price_ceiling") or p.get("rate_ceiling"),
                             "Page": p.get("source_page")}
                            for p in _hb_subs
                        ], hide_index=True, width='stretch')
                    for _mtm in _hb.get("mtm_disclosures") or []:
                        st.caption(f"MTM ({_mtm.get('scope')}): {_mtm.get('verbatim') or _mtm.get('amount')}")
                    for _sens in _hb.get("sensitivities") or []:
                        st.caption(f"Sensitivity: {_sens.get('verbatim')}")

                _hb_pages = ", ".join(str(p) for p in _hb.get("source_pages") or [])
                st.caption(
                    f"Extracted from note pages {_hb_pages} of the filed statements; "
                    f"volumes, prices and periods as disclosed (extraction confidence "
                    f"{_hb.get('extraction_confidence', 0):.2f}). Hedge coverage % and "
                    "hedge-price-vs-strip need production volumes / futures data — "
                    "MD&A-fetcher era, planned."
                )

            # =============================================================
            # MD&A Operational Metrics — O&G upstream pack (Stage 2,
            # design: docs/MDA_FETCHER_SPEC.md). On-demand extraction
            # (Riley's ratified trigger): analysis stays your click.
            # Every figure is issuer-defined non-GAAP — receipts + the
            # definition string render with the data (ratified trust
            # policy: receipt + permanent caption).
            # =============================================================
            st.divider()
            _mm = financial_data.get("mda_metrics") if isinstance(financial_data, dict) else None

            if not isinstance(_mm, dict):
                st.markdown("#### 📄 MD&A Operational Metrics")
                _mm_pdf = _hedging_pdf_path_for_current(ticker, financial_data)
                if not _mm_pdf:
                    st.caption(
                        "Extracts production volumes, the per-boe operating netback, "
                        "funds flow, and realized prices from the filing's MD&A pages. "
                        "The source PDF is not cached for this filing — re-load or "
                        "re-upload it to enable."
                    )
                else:
                    st.caption(
                        "Extract production volumes, per-boe netback, funds flow, and "
                        "realized prices from the MD&A pages — issuer-defined non-GAAP "
                        "measures with their definitions, as printed. One targeted "
                        "Claude pass (~$0.05–0.15)."
                    )
                    if st.button("📄 Extract MD&A Metrics $", key="mda_extract_go"):
                        with st.spinner("Extracting MD&A operational metrics (30–90 seconds)..."):
                            try:
                                _mm_result = extract_mda_metrics(_mm_pdf)
                            except SedarExtractionError as _mm_exc:
                                st.error(f"MD&A-metrics extraction failed: {_mm_exc}")
                                _mm_result = None
                            except Exception as _mm_exc:
                                st.error(f"MD&A-metrics extraction failed: {_mm_exc} — try again.")
                                _mm_result = None
                        if _mm_result is not None:
                            financial_data["mda_metrics"] = _mm_result
                            # Re-run integrity so the Stage 3 tie rules arm
                            # with the new data (netback internal tie + FFO
                            # anchor tie; fresh moat-log record).
                            _mm_fd = _run_integrity_checks(
                                financial_data,
                                st.session_state.get("summary_data"),
                                ticker,
                                financial_data.get("source", "sedar"),
                                filing_date=financial_data.get("sedar_filing_date"),
                            )
                            if isinstance(_mm_fd, dict):
                                st.session_state.financial_data = _mm_fd
                            else:
                                st.session_state.financial_data = financial_data
                            _save_analysis_cache(
                                ticker,
                                financial_data.get("fiscal_year") or financial_data.get("period"),
                                financial_data.get("source", "sedar"),
                            )
                            st.rerun()
            elif _mm.get("status") == "no_mda_detected":
                st.markdown("#### 📄 MD&A Operational Metrics")
                st.info(
                    "No MD&A operational section was detected in this PDF — this "
                    "looks like a statements-only pack (the MD&A is filed as a "
                    "separate document). Fetching the standalone MD&A is planned "
                    "(MDA_FETCHER_SPEC Stage 4)."
                )
            else:
                st.markdown("#### 📄 MD&A Operational Metrics — as disclosed")
                _mm_fp = _mm.get("figure_presence") or {}
                _mm_nb_rows = _mm.get("netback_rows") or []
                _mm_vols = _mm.get("production_volumes") or []

                def _mm_latest_year(rows, period_key="period_label"):
                    """Pick the row for the most recent period among candidates."""
                    def _year_of(row):
                        m = re.search(r"(\d{4})", str(row.get(period_key) or ""))
                        return int(m.group(1)) if m else 0
                    return max(rows, key=_year_of) if rows else None

                # Summary strip: annual per-boe netback, total production, guard.
                _mm_c1, _mm_c2, _mm_c3 = st.columns(3)
                with _mm_c1:
                    _mm_boe_totals = [
                        r for r in _mm_nb_rows
                        if r.get("is_total") and isinstance(r.get("value"), (int, float))
                        and "boe" in str(r.get("unit") or "").lower()
                        and "year" in str(r.get("period_label") or "").lower()
                    ]
                    _mm_headline = _mm_latest_year(_mm_boe_totals)
                    if _mm_headline is not None:
                        st.metric(
                            "Operating netback (annual)",
                            f"${_mm_headline['value']:,.2f}/boe",
                        )
                        st.caption(_mm_headline.get("period_label") or "")
                    else:
                        st.metric("Operating netback (annual)", "—")
                with _mm_c2:
                    _mm_boe_vols = [
                        v for v in _mm_vols
                        if v.get("product") == "total_boe"
                        and isinstance(v.get("volume"), (int, float))
                    ]
                    # Prefer the annual row (same rule as the netback
                    # headline) — TOU's Q4 and FY rows share the year, and
                    # max() alone picked the quarterly 659,204 over the
                    # annual 638,196 (found live 2026-07-12).
                    _mm_annual_vols = [
                        v for v in _mm_boe_vols
                        if "year" in str(v.get("period_label") or "").lower()
                    ]
                    _mm_vol_headline = _mm_latest_year(_mm_annual_vols or _mm_boe_vols)
                    if _mm_vol_headline is not None:
                        st.metric(
                            "Total production",
                            f"{_mm_vol_headline['volume']:,.0f} {_mm_vol_headline.get('volume_unit') or ''}",
                        )
                        st.caption(_mm_vol_headline.get("period_label") or "")
                    else:
                        st.metric("Total production", "—")
                with _mm_c3:
                    if _mm_fp.get("missing_count", 0) == 0 and _mm_fp.get("checked"):
                        st.metric("Figure presence", f"{_mm_fp['checked']}/{_mm_fp['checked']} ✓")
                    else:
                        st.metric("Figure presence",
                                  f"{_mm_fp.get('missing_count', '?')} UNVERIFIED")
                if _mm_fp.get("missing_count"):
                    st.warning(
                        f"⚠️ {_mm_fp['missing_count']} extracted value(s) were NOT found "
                        "verbatim in the MD&A page text — treat those figures as "
                        "unverified and check the source pages."
                    )

                # The ratified trust policy: the issuer's own definition renders
                # with the data, permanently. Variant differences are the trap.
                _mm_nb_def = _mm.get("netback_definition_verbatim")
                _mm_hedge_flag = _mm.get("netback_includes_hedging")
                if _mm_nb_def or _mm_hedge_flag is not None:
                    _mm_variant = (
                        "includes realized hedging" if _mm_hedge_flag
                        else ("excludes realized hedging" if _mm_hedge_flag is False
                              else "hedging treatment unclear")
                    )
                    st.caption(
                        f"**Issuer-defined non-GAAP** ({_mm_variant} — netback variants "
                        f"differ by issuer and may not be comparable). Definition as "
                        f"printed: _{_mm_nb_def or 'not stated in the extracted pages'}_"
                    )

                def _mm_pivot(rows, value_key, label_key="label"):
                    """Pivot flat (label, period, value) records into one table row
                    per label with a column per period, first-seen order."""
                    periods, labels, cells = [], [], {}
                    for r in rows:
                        lbl, per = r.get(label_key), r.get("period_label") or "—"
                        if lbl is None:
                            continue
                        if per not in periods:
                            periods.append(per)
                        if lbl not in labels:
                            labels.append(lbl)
                        cells[(lbl, per)] = r.get(value_key)
                    return [
                        {"": lbl, **{
                            per: (f"{cells[(lbl, per)]:,g}" if isinstance(cells.get((lbl, per)), (int, float)) else "—")
                            for per in periods
                        }}
                        for lbl in labels
                    ]

                # Netback tables, one per unit (filers print $ and $/boe forms).
                _mm_nb_units = []
                for r in _mm_nb_rows:
                    u = r.get("unit") or "—"
                    if u not in _mm_nb_units:
                        _mm_nb_units.append(u)
                for _u in _mm_nb_units:
                    _u_rows = [r for r in _mm_nb_rows if (r.get("unit") or "—") == _u]
                    st.markdown(f"**Netback ({_u})**")
                    st.dataframe(_mm_pivot(_u_rows, "value"), hide_index=True, width='stretch')

                if _mm_vols:
                    st.markdown("**Production volumes**")
                    st.dataframe(_mm_pivot(_mm_vols, "volume"), hide_index=True, width='stretch')

                with st.expander("Funds flow, realized prices, guidance — the receipt", expanded=False):
                    _mm_ff = _mm.get("funds_flow_rows") or []
                    if _mm_ff:
                        st.markdown("**Funds flow reconciliation** (as printed)")
                        _mm_ff_def = _mm.get("funds_flow_definition_verbatim")
                        if _mm_ff_def:
                            st.caption(f"Issuer definition: _{_mm_ff_def}_")
                        st.dataframe([
                            {"Row": r.get("label"), "Period": r.get("period_label"),
                             "Value": r.get("value"), "Scale": r.get("unit_scale"),
                             "Per share": bool(r.get("per_share")), "Page": r.get("source_page")}
                            for r in _mm_ff
                        ], hide_index=True, width='stretch')
                    _mm_rp = _mm.get("realized_prices") or []
                    if _mm_rp:
                        st.markdown("**Average realized prices**")
                        st.dataframe([
                            {"Product": r.get("label"), "Period": r.get("period_label"),
                             "Value": r.get("value"), "Unit": r.get("unit"),
                             "Page": r.get("source_page")}
                            for r in _mm_rp
                        ], hide_index=True, width='stretch')
                    for _g in _mm.get("guidance_disclosures") or []:
                        st.caption(f"Guidance ({_g.get('topic')}): {_g.get('verbatim')} (p{_g.get('source_page')})")
                    _mm_mix = _mm.get("commodity_mix") or {}
                    if _mm_mix.get("verbatim"):
                        st.caption(f"Commodity mix: {_mm_mix['verbatim']} (p{_mm_mix.get('source_page')})")

                _mm_pages = ", ".join(str(p) for p in _mm.get("source_pages") or [])
                _mm_dropped = _mm.get("dropped_pages") or []
                _mm_dropped_note = (
                    f" {len(_mm_dropped)} lower-signal page(s) were not sent to "
                    f"extraction (disclosed, not silent)." if _mm_dropped else ""
                )
                st.caption(
                    f"Extracted from MD&A pages {_mm_pages}; values, labels and periods "
                    f"as disclosed (extraction confidence "
                    f"{_mm.get('extraction_confidence', 0):.2f}).{_mm_dropped_note} "
                    "Netback-vs-commodity-price overlay and $/boe cross-filer "
                    "comparison land with the Stage 3 integrity rules."
                )

else:
    if not uploaded_file:
        st.info("Upload a PDF above to get started.")
