"""
FinLens Data Integrity Engine -- Prior-Column Continuity Checker
================================================================
Filing N's comparative (prior-year) column must tie to filing N-1's
as-filed current-year figures.  A number that contradicts the previous
filing is a restatement (analytical signal) or an extraction defect --
either way a human should look.

Motivating case: the 2026-07-03 fabricated NVDA extraction presented
real-FY2024 values as its comparative column.  A stored FY2025 filing
would have exposed the mismatch instantly and deterministically, with
zero API cost.

SCOPE NOTE: v1 fields only: revenue, net_income, total_assets,
operating_cash_flow, capex.  Same-year duplicate-copy divergence is a
distinct check outside v1 scope.

Usage
-----
    from modules.integrity.prior_column import check_prior_column
    record = check_prior_column(payload, analysis_dir=some_path, log_path=some_path)

Programmatic -- entry point
    check_prior_column(payload, analysis_dir, log_path) -> dict
    Returns the log record dict.  Never raises; returns UNCHECKED on any
    lookup or currency failure.  Appends to the integrity log unless the
    append itself fails (logged and swallowed).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHECKER_VERSION = "1"
RECORD_TYPE = "prior_column_continuity"
DISPOSITION_RECORD_TYPE = "prior_column_disposition"

# Relative tolerance for MATCH: |a - b| / max(|a|, |b|) <= TOLERANCE
TOLERANCE = 0.005  # 0.5%, per spec

# v1 canonical fields in output order
V1_FIELDS = ["revenue", "net_income", "total_assets", "operating_cash_flow", "capex"]

# Statement key that holds each canonical field
_STATEMENT_MAP: dict[str, str] = {
    "revenue":             "income_statement",
    "net_income":          "income_statement",
    "total_assets":        "balance_sheet",
    "operating_cash_flow": "cash_flow_statement",
    "capex":               "cash_flow_statement",
}

# Alias lists for fallback label-scan resolution.
# Mirrors the label sets used by cross_validate.py and excel_exporter summary
# metrics; capex aliases include as-filed variants present in existing caches.
_ALIASES: dict[str, list[str]] = {
    "revenue": [
        "Revenues",
        "Revenue",
    ],
    "net_income": [
        "Net Income",
        "Net income",
    ],
    "total_assets": [
        "Assets",
        "Total Assets",
        "Total assets",
    ],
    "operating_cash_flow": [
        "Net Cash Provided by Operating Activities",
        "Net Cash from Operating Activities",
    ],
    "capex": [
        "Capital Expenditures",
        "Purchases of Property, Plant and Equipment",
        "Purchase of property and equipment",
        "Additions to property, plant and equipment",
        "Capital expenditures",
    ],
}

# Valid disposition values for prior_column_disposition records
PRIOR_COLUMN_DISPOSITION_VALUES = {
    "restatement",
    "extraction_error",
    "checker_error",
    "other",
}

# ---------------------------------------------------------------------------
# Value resolution helpers
# ---------------------------------------------------------------------------

def _mapped_entry(financial_data: dict, canonical: str) -> dict | None:
    """Return the mapping.mapped entry for a canonical field, or None."""
    mapping = financial_data.get("mapping") or {}
    mapped = mapping.get("mapped") or {}
    entry = mapped.get(canonical)
    return entry if isinstance(entry, dict) else None


def _resolve_current(financial_data: dict, canonical: str) -> float | None:
    """Resolve the current-year value for a canonical field.

    Priority:
    1. mapping.mapped[canonical].value  (SEDAR analyses)
    2. Statement row label scan, row["value"]
    """
    entry = _mapped_entry(financial_data, canonical)
    if entry is not None:
        v = entry.get("value")
        return float(v) if v is not None else None

    stmt_key = _STATEMENT_MAP.get(canonical)
    if not stmt_key:
        return None
    aliases = _ALIASES.get(canonical) or []
    for row in financial_data.get(stmt_key) or []:
        if row.get("line_item") in aliases:
            v = row.get("value")
            return float(v) if v is not None else None
    return None


def _resolve_prior(financial_data: dict, canonical: str) -> float | None:
    """Resolve the comparative (prior-year) column value for a canonical field.

    Priority:
    1. mapping.mapped[canonical].value_prior  (SEDAR when available)
    2. Statement row label scan, row["value_prior"]

    Falls through to the statement scan when the mapped entry lacks value_prior
    (SEDAR mapper does not always populate it).
    """
    entry = _mapped_entry(financial_data, canonical)
    if entry is not None:
        vp = entry.get("value_prior")
        if vp is not None:
            return float(vp)
        # Fall through: SEDAR mapper may omit value_prior; try statement rows.

    stmt_key = _STATEMENT_MAP.get(canonical)
    if not stmt_key:
        return None
    aliases = _ALIASES.get(canonical) or []
    for row in financial_data.get(stmt_key) or []:
        if row.get("line_item") in aliases:
            vp = row.get("value_prior")
            return float(vp) if vp is not None else None
    return None


# ---------------------------------------------------------------------------
# Prior-filing lookup
# ---------------------------------------------------------------------------

def _parse_ticker(payload: dict) -> str:
    """Extract ticker from payload, uppercased."""
    return str(payload.get("ticker") or "").strip().upper()


def _parse_fiscal_year(financial_data: dict) -> str | None:
    """Extract fiscal_year string from financial_data."""
    v = financial_data.get("fiscal_year")
    return str(v).strip() if v else None


def _parse_fiscal_year_prior(financial_data: dict) -> str | None:
    """Extract fiscal_year_prior string from financial_data."""
    v = financial_data.get("fiscal_year_prior")
    return str(v).strip() if v else None


def _parse_currency(financial_data: dict) -> str | None:
    """Extract currency code from financial_data, uppercased."""
    v = financial_data.get("currency")
    return str(v).strip().upper() if v else None


def _find_prior_filing(
    ticker: str,
    fiscal_year_prior: str,
    analysis_dir: Path,
) -> tuple[dict | None, str | None]:
    """Scan analysis_dir for a payload whose ticker matches and
    financial_data.fiscal_year == fiscal_year_prior.

    When multiple candidates match, prefers the most recent timestamp
    (later-corrected extractions win).

    Returns (payload_dict, basename) or (None, None).
    Corrupt/unreadable files are skipped; they do not count as candidates.
    """
    if not analysis_dir.exists():
        return None, None

    # (timestamp_str, payload_dict, basename)
    candidates: list[tuple[str, dict, str]] = []

    for path in analysis_dir.glob("*.json"):
        try:
            with open(path, encoding="utf-8") as fh:
                candidate = json.load(fh)
            if not isinstance(candidate, dict):
                continue
            c_ticker = str(candidate.get("ticker") or "").strip().upper()
            if c_ticker != ticker:
                continue
            # Resolve fiscal_year from financial_data when available;
            # fall back to the top-level 'period' key for payloads whose
            # financial_data is malformed (caller handles reader_error).
            fd = candidate.get("financial_data")
            if isinstance(fd, dict):
                c_fy = _parse_fiscal_year(fd)
            else:
                c_fy = str(candidate.get("period") or "").strip() or None
            if c_fy == fiscal_year_prior:
                ts = str(candidate.get("timestamp") or "")
                candidates.append((ts, candidate, path.name))
        except Exception:
            continue  # truly unreadable (bad JSON, I/O error); skip to next file

    if not candidates:
        return None, None

    # Most recent timestamp wins.
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, best_payload, best_basename = candidates[0]
    return best_payload, best_basename


# ---------------------------------------------------------------------------
# Field comparison
# ---------------------------------------------------------------------------

def _pct_diff(a: float, b: float) -> float:
    """Absolute relative difference as a fraction, e.g. 0.015 = 1.5%.
    Returns 0.0 when both values are zero."""
    denom = max(abs(a), abs(b))
    if denom == 0:
        return 0.0
    return abs(a - b) / denom


def _compare_field(
    canonical: str,
    value_prior_n: float | None,
    value_n1: float | None,
) -> dict:
    """Build a per-field comparison record.

    Parameters
    ----------
    canonical      Canonical field name.
    value_prior_n  Filing N's comparative column (what N says the prior year was).
    value_n1       Filing N-1's current-year value (what the prior filing reported).
    """
    if value_prior_n is None or value_n1 is None:
        return {
            "canonical_field": canonical,
            "value_prior_n": value_prior_n,
            "value_prior_filing": value_n1,
            "pct_diff": None,
            "status": "FIELD_MISSING",
        }

    diff = _pct_diff(value_prior_n, value_n1)
    status = "MATCH" if diff <= TOLERANCE else "CONFLICT"
    return {
        "canonical_field": canonical,
        "value_prior_n": value_prior_n,
        "value_prior_filing": value_n1,
        "pct_diff": round(diff * 100, 4),
        "status": status,
    }


def _filing_state(field_records: list[dict]) -> str:
    """Compute the filing-level state from per-field results.

    FLAGGED   -- at least one CONFLICT
    VERIFIED  -- at least one MATCH, no CONFLICT, no FIELD_MISSING
    PARTIAL   -- no CONFLICT, at least one MATCH, some FIELD_MISSING
    UNCHECKED -- no comparisons ran (all fields FIELD_MISSING)
    """
    statuses = [r["status"] for r in field_records]
    if "CONFLICT" in statuses:
        return "FLAGGED"
    n_match = sum(1 for s in statuses if s == "MATCH")
    if n_match == 0:
        return "UNCHECKED"
    n_missing = sum(1 for s in statuses if s == "FIELD_MISSING")
    if n_missing > 0:
        return "PARTIAL"
    return "VERIFIED"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def check_prior_column(
    payload: dict,
    analysis_dir: Path | str | None = None,
    log_path: Path | str | None = None,
) -> dict:
    """Run the prior-column continuity check for one analysis-cache payload.

    Parameters
    ----------
    payload       Loaded analysis-cache JSON dict (shape written to
                  ~/.finlens/analysis/ by modules/analysis_cache.py).
    analysis_dir  Directory scanned for the prior filing.  None uses the
                  production ANALYSIS_CACHE_DIR from config.  Pass a
                  tmp_path in tests.
    log_path      Integrity log path.  None uses the production default.
                  Pass a tmp_path for tests to avoid writing real logs.

    Returns
    -------
    The log record dict (record_type="prior_column_continuity").
    Never raises; always returns a dict.
    """
    from .log import append_prior_column_to_log

    if analysis_dir is None:
        try:
            from config import ANALYSIS_CACHE_DIR
            analysis_dir = ANALYSIS_CACHE_DIR
        except Exception:
            analysis_dir = Path.home() / ".finlens" / "analysis"
    analysis_dir = Path(analysis_dir)

    if log_path is None:
        try:
            from config import LIBRARY_DIR
            log_path = LIBRARY_DIR / "integrity_log.jsonl"
        except Exception:
            log_path = Path.home() / ".finlens" / "integrity_log.jsonl"
    log_path = Path(log_path)

    timestamp = datetime.now(timezone.utc).isoformat()

    # --- Extract payload fields ---
    financial_data = payload.get("financial_data")
    if not isinstance(financial_data, dict):
        record = _unchecked_record(
            timestamp=timestamp,
            ticker=_parse_ticker(payload),
            fiscal_year=None,
            reason="no_financial_data",
        )
        _safe_append(record, log_path, append_prior_column_to_log)
        return record

    ticker = _parse_ticker(payload)
    fiscal_year = _parse_fiscal_year(financial_data)
    fiscal_year_prior = _parse_fiscal_year_prior(financial_data)
    currency_n = _parse_currency(financial_data)
    schema_n = payload.get("schema_version")

    # --- Guard: must have a prior year to look for ---
    if not fiscal_year_prior:
        record = _unchecked_record(
            timestamp=timestamp,
            ticker=ticker,
            fiscal_year=fiscal_year,
            reason="no_prior_fiscal_year",
        )
        _safe_append(record, log_path, append_prior_column_to_log)
        return record

    # --- Locate prior filing ---
    prior_payload, prior_basename = _find_prior_filing(
        ticker, fiscal_year_prior, analysis_dir
    )

    if prior_payload is None:
        record = _unchecked_record(
            timestamp=timestamp,
            ticker=ticker,
            fiscal_year=fiscal_year,
            prior_fiscal_year=fiscal_year_prior,
            reason="no_prior_filing",
        )
        _safe_append(record, log_path, append_prior_column_to_log)
        return record

    # --- Prior filing must have a readable financial_data dict (fail-closed) ---
    prior_fd = prior_payload.get("financial_data")
    if not isinstance(prior_fd, dict):
        record = _unchecked_record(
            timestamp=timestamp,
            ticker=ticker,
            fiscal_year=fiscal_year,
            prior_fiscal_year=fiscal_year_prior,
            prior_source_file=prior_basename,
            reason="reader_error",
        )
        _safe_append(record, log_path, append_prior_column_to_log)
        return record

    # --- Currency gate (mirrors cross_validate v2: no FX conversion, ever) ---
    currency_prior = _parse_currency(prior_fd)
    schema_prior = prior_payload.get("schema_version")

    if not currency_n or not currency_prior:
        record = _unchecked_record(
            timestamp=timestamp,
            ticker=ticker,
            fiscal_year=fiscal_year,
            prior_fiscal_year=fiscal_year_prior,
            prior_source_file=prior_basename,
            schema_version_n=schema_n,
            schema_version_prior=schema_prior,
            currency_n=currency_n,
            currency_prior=currency_prior,
            reason="currency_unknown",
        )
        _safe_append(record, log_path, append_prior_column_to_log)
        return record

    if currency_n != currency_prior:
        record = _unchecked_record(
            timestamp=timestamp,
            ticker=ticker,
            fiscal_year=fiscal_year,
            prior_fiscal_year=fiscal_year_prior,
            prior_source_file=prior_basename,
            schema_version_n=schema_n,
            schema_version_prior=schema_prior,
            currency_n=currency_n,
            currency_prior=currency_prior,
            reason="currency_mismatch",
        )
        _safe_append(record, log_path, append_prior_column_to_log)
        return record

    # --- Field comparisons ---
    field_records: list[dict] = []
    for canonical in V1_FIELDS:
        value_prior_n = _resolve_prior(financial_data, canonical)
        value_n1 = _resolve_current(prior_fd, canonical)
        field_records.append(_compare_field(canonical, value_prior_n, value_n1))

    state = _filing_state(field_records)

    record = {
        "record_type": RECORD_TYPE,
        "checker_version": CHECKER_VERSION,
        "timestamp": timestamp,
        "ticker": ticker,
        "fiscal_year": fiscal_year,
        "prior_fiscal_year": fiscal_year_prior,
        "prior_source_file": prior_basename,
        "schema_version_n": schema_n,
        "schema_version_prior": schema_prior,
        "currency_n": currency_n,
        "currency_prior": currency_prior,
        "state": state,
        "fields": field_records,
    }

    _safe_append(record, log_path, append_prior_column_to_log)
    return record


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _unchecked_record(
    *,
    timestamp: str,
    ticker: str,
    fiscal_year: str | None = None,
    prior_fiscal_year: str | None = None,
    prior_source_file: str | None = None,
    schema_version_n: object = None,
    schema_version_prior: object = None,
    currency_n: str | None = None,
    currency_prior: str | None = None,
    reason: str,
) -> dict:
    """Build a minimal UNCHECKED record dict."""
    return {
        "record_type": RECORD_TYPE,
        "checker_version": CHECKER_VERSION,
        "timestamp": timestamp,
        "ticker": ticker,
        "fiscal_year": fiscal_year,
        "prior_fiscal_year": prior_fiscal_year,
        "prior_source_file": prior_source_file,
        "schema_version_n": schema_version_n,
        "schema_version_prior": schema_version_prior,
        "currency_n": currency_n,
        "currency_prior": currency_prior,
        "state": "UNCHECKED",
        "reason": reason,
        "fields": [],
    }


def _safe_append(record: dict, log_path: Path, append_fn) -> None:
    """Append a log record, swallowing any error silently."""
    try:
        append_fn(record, log_path=log_path)
    except Exception:
        _log.exception("prior_column log append failed")
