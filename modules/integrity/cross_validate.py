"""
FinLens Cross-Validation Layer
==============================
Compares FinLens normalized financial figures against FMP (Financial
Modeling Prep) for the same ticker and fiscal period.

This is a SECOND, independent check.  The integrity engine checks internal
arithmetic consistency; this checks whether FinLens numbers are plausible
against an independent external source.

FLAG-AND-SHOW ONLY.  Never auto-correct FinLens data to match FMP.
FMP is a second opinion and is sometimes itself wrong.

Usage
-----
    from modules.integrity.cross_validate import cross_validate_filing
    result = cross_validate_filing(normalized_data, ticker, fiscal_year)

Cost note
---------
    cross_validate_filing() triggers up to 3 FMP HTTP calls (income,
    balance-sheet, cash-flow).  Results are cached in
    ~/.finlens/cv_cache.json keyed by ticker + fiscal year.
    Re-display of the same filing does NOT re-call FMP.
    Mark any UI action that calls this function with a $ indicator.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from config import LIBRARY_DIR

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CROSS_VALIDATE_VERSION = "2"
_CV_CACHE_FILE = LIBRARY_DIR / "cv_cache.json"
FMP_FETCH_SUCCESS = "success"
FMP_PREMIUM_BLOCKED = "fmp_premium_blocked"
FMP_TRANSIENT_FAILURE = "transient_failure"
FMP_REPORTED_CURRENCY_KEY = "_reported_currency"
CV_SEVERITY_ADVISORY = "advisory"
CV_ABSTAIN_CURRENCY_MISMATCH = "currency_mismatch"
CV_ABSTAIN_CURRENCY_UNKNOWN = "currency_unknown"

# Divergence thresholds (absolute percentage of FMP value)
_AGREE_THRESHOLD  = 0.02   # < 2%  -> AGREE
_MINOR_THRESHOLD  = 0.10   # 2-10% -> MINOR_DIVERGENCE
                            # >10%  -> DISAGREE

# 4 headline fields: (field_name, FinLens line-item labels, FMP raw JSON key)
# FinLens uses different labels depending on source (EDGAR vs FMP-sourced data).
_FIELDS: list[tuple[str, list[str], str]] = [
    (
        "revenue",
        ["Revenues", "Revenue"],
        "revenue",
    ),
    (
        "net_income",
        ["Net Income"],
        "netIncome",
    ),
    (
        "total_assets",
        ["Assets", "Total Assets"],
        "totalAssets",
    ),
    (
        "operating_cash_flow",
        [
            "Net Cash Provided by Operating Activities",  # EDGAR label
            "Net Cash from Operating Activities",         # FMP-sourced label
        ],
        "operatingCashFlow",
    ),
]

# FMP endpoint per FinLens statement key
_FMP_ENDPOINTS: dict[str, str] = {
    "revenue":             "income-statement",
    "net_income":          "income-statement",
    "total_assets":        "balance-sheet-statement",
    "operating_cash_flow": "cash-flow-statement",
}

# Raw JSON key per field in the FMP response
_FMP_RAW_KEYS: dict[str, str] = {
    "revenue":             "revenue",
    "net_income":          "netIncome",
    "total_assets":        "totalAssets",
    "operating_cash_flow": "operatingCashFlow",
}

# FinLens statement dict key per field
_FINLENS_STATEMENT: dict[str, str] = {
    "revenue":             "income_statement",
    "net_income":          "income_statement",
    "total_assets":        "balance_sheet",
    "operating_cash_flow": "cash_flow_statement",
}

# Line-item labels per field (EDGAR label first, FMP-sourced label second)
_FINLENS_LABELS: dict[str, list[str]] = {
    "revenue":             ["Revenues", "Revenue"],
    "net_income":          ["Net Income"],
    "total_assets":        ["Assets", "Total Assets"],
    "operating_cash_flow": [
        "Net Cash Provided by Operating Activities",
        "Net Cash from Operating Activities",
    ],
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class FieldResult:
    """Outcome of comparing one field between FinLens and FMP."""
    field: str
    finlens_value: float | None    # raw filing currency
    fmp_value: float | None        # raw FMP reported currency
    pct_diff: float | None         # percentage, e.g. 1.5 = 1.5%; None if either value missing
    status: str                    # AGREE | MINOR_DIVERGENCE | DISAGREE | UNMATCHED
    severity: str | None = None    # advisory for FMP value mismatches; omitted otherwise
    abstention_reason: str | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        if self.severity is None:
            data.pop("severity")
        if self.abstention_reason is None:
            data.pop("abstention_reason")
        return data


@dataclass
class CrossValidationResult:
    """Full cross-validation outcome for one filing."""
    overall_status: str            # all_agree | minor_divergence | disagreement | partial_unmatched
    fields: list[FieldResult]
    timestamp: str                 # ISO 8601
    ticker: str
    fiscal_year: str
    filing_accession: str | None
    fmp_fetch_success: bool
    fmp_fetch_reason: str
    filing_currency: str | None = None
    fmp_reported_currency: str | None = None
    abstention_reason: str | None = None
    checker_version: str = CROSS_VALIDATE_VERSION

    def to_dict(self) -> dict:
        """Serialize to a log-ready dict (Supabase-friendly schema)."""
        return {
            "record_type":       "cross_validation",
            "checker_version":   self.checker_version,
            "timestamp":         self.timestamp,
            "ticker":            self.ticker,
            "fiscal_year":       self.fiscal_year,
            "filing_accession":  self.filing_accession,
            "overall_status":    self.overall_status,
            "fmp_fetch_success": self.fmp_fetch_success,
            "fmp_fetch_reason":  self.fmp_fetch_reason,
            "filing_currency":   self.filing_currency,
            "fmp_reported_currency": self.fmp_reported_currency,
            "abstention_reason": self.abstention_reason,
            "cv_fields":         [f.to_dict() for f in self.fields],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_year(s: Any) -> int | None:
    """Extract a 4-digit calendar year from strings like 'FY2025', '2025', or int 2025."""
    if s is None:
        return None
    m = re.search(r"(\d{4})", str(s))
    return int(m.group(1)) if m else None


def _currency_code(text: Any) -> str | None:
    """Extract a 3-letter filing/reporting currency code from a label."""
    if not text:
        return None
    m = re.search(r"\b[A-Z]{3}\b", str(text).upper())
    return m.group(0) if m else None


def _line_item_value(rows: list[dict], *labels: str) -> float | None:
    """Return the value of the first row whose line_item matches any of the given labels."""
    for row in rows:
        if row.get("line_item") in labels:
            v = row.get("value")
            return float(v) if v is not None else None
    return None


def _top_level_value(data: dict, field: str) -> float | None:
    """Return a canonical top-level value, if present."""
    v = data.get(field)
    return float(v) if v is not None else None


def _extract_finlens_values(normalized_data: dict) -> dict[str, float | None]:
    """
    Pull the 4 headline values out of FinLens normalized_data.
    All values returned are in raw filing currency (normalize_financial_data()
    has already scaled them to raw units, not FX-converted them).
    """
    income   = normalized_data.get("income_statement",    [])
    balance  = normalized_data.get("balance_sheet",        [])
    cashflow = normalized_data.get("cash_flow_statement",  [])
    revenue = _line_item_value(income, *_FINLENS_LABELS["revenue"])
    net_income = _line_item_value(income, *_FINLENS_LABELS["net_income"])
    total_assets = _line_item_value(balance, *_FINLENS_LABELS["total_assets"])
    operating_cash_flow = _line_item_value(cashflow, *_FINLENS_LABELS["operating_cash_flow"])
    return {
        "revenue":             revenue if revenue is not None else _top_level_value(normalized_data, "revenue"),
        "net_income":          net_income if net_income is not None else _top_level_value(normalized_data, "net_income"),
        "total_assets":        total_assets if total_assets is not None else _top_level_value(normalized_data, "total_assets"),
        "operating_cash_flow": (
            operating_cash_flow
            if operating_cash_flow is not None
            else _top_level_value(normalized_data, "operating_cash_flow")
        ),
    }


def _find_year_entry(data: list[dict], target_year: int) -> dict | None:
    """Return the first entry from an FMP statement list whose fiscalYear matches target_year."""
    for entry in data:
        if isinstance(entry, dict) and _parse_year(entry.get("fiscalYear")) == target_year:
            return entry
    return None


def _common_reported_currency(*entries: dict | None) -> str | None:
    """Return a single FMP reportedCurrency code, or None when unknown/conflicting."""
    codes: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry:
            continue
        code = _currency_code(entry.get("reportedCurrency"))
        if code is None:
            return None
        codes.append(code)
    if not codes:
        return None
    unique_codes = set(codes)
    return codes[0] if len(unique_codes) == 1 else None


def _fetch_fmp_raw(ticker: str, target_year: int) -> tuple[dict[str, Any] | None, bool, str]:
    """
    Call FMP for the 4 headline values for ticker + target_year.

    Returns
    -------
    (values_dict, success_bool, reason)
        values_dict   keys: revenue, net_income, total_assets, operating_cash_flow,
                      plus _reported_currency when FMP reports one consistently.
                      Values are raw FMP reported-currency values.
                      None for a field if FMP has no matching entry.
        success_bool  False only if FMP is unreachable or returns a non-200 response.
                      True even if the period is not found -- that is "not in FMP",
                      not an API failure.
        reason        success | fmp_premium_blocked | transient_failure
    """
    try:
        from modules.fmp import (
            FMP_FETCH_SUCCESS as FMP_FETCH_SUCCESS_REASON,
            FMP_PREMIUM_BLOCKED as FMP_PREMIUM_BLOCKED_REASON,
            _get_statement_list_with_reason,
        )  # reuse session + SSL setup

        income_list, income_reason = _get_statement_list_with_reason(
            "income-statement", ticker, "annual", 3
        )
        balance_list, balance_reason = _get_statement_list_with_reason(
            "balance-sheet-statement", ticker, "annual", 3
        )
        cashflow_list, cashflow_reason = _get_statement_list_with_reason(
            "cash-flow-statement", ticker, "annual", 3
        )

        reasons = (income_reason, balance_reason, cashflow_reason)
        if FMP_PREMIUM_BLOCKED_REASON in reasons:
            return None, False, FMP_PREMIUM_BLOCKED
        if any(reason != FMP_FETCH_SUCCESS_REASON for reason in reasons):
            return None, False, FMP_TRANSIENT_FAILURE

        income_entry   = _find_year_entry(income_list,         target_year)
        balance_entry  = _find_year_entry(balance_list  or [], target_year) or {}
        cashflow_entry = _find_year_entry(cashflow_list or [], target_year) or {}

        # Period not in FMP -- successful fetch but matching year absent
        if income_entry is None:
            return None, True, FMP_FETCH_SUCCESS

        fmp_reported_currency = _common_reported_currency(
            income_entry,
            balance_entry,
            cashflow_entry,
        )

        return {
            FMP_REPORTED_CURRENCY_KEY: fmp_reported_currency,
            "revenue":             income_entry.get("revenue"),
            "net_income":          income_entry.get("netIncome"),
            "total_assets":        balance_entry.get("totalAssets"),
            "operating_cash_flow": cashflow_entry.get("operatingCashFlow"),
        }, True, FMP_FETCH_SUCCESS

    except Exception:
        return None, False, FMP_TRANSIENT_FAILURE


# ---------------------------------------------------------------------------
# Comparison logic
# ---------------------------------------------------------------------------

def _pct_diff_raw(finlens: float | None, fmp: float | None) -> float | None:
    """Return absolute relative difference as a fraction (0.015 = 1.5%).  None if either value missing."""
    if finlens is None or fmp is None:
        return None
    if fmp == 0:
        return None
    return abs(finlens - fmp) / abs(fmp)


def _field_status(pct_raw: float | None) -> str:
    if pct_raw is None:
        return "UNMATCHED"
    if pct_raw <= _AGREE_THRESHOLD:
        return "AGREE"
    if pct_raw <= _MINOR_THRESHOLD:
        return "MINOR_DIVERGENCE"
    return "DISAGREE"


def _field_severity(status: str) -> str | None:
    """FMP mismatches are advisory only: triage-needed, never FinLens-wrong."""
    if status in {"MINOR_DIVERGENCE", "DISAGREE"}:
        return CV_SEVERITY_ADVISORY
    return None


def _overall_status(field_results: list[FieldResult], fmp_success: bool) -> str:
    if not fmp_success:
        return "partial_unmatched"
    statuses = {f.status for f in field_results}
    if "DISAGREE"         in statuses:
        return "disagreement"
    if "UNMATCHED"        in statuses:
        return "partial_unmatched"
    if "MINOR_DIVERGENCE" in statuses:
        return "minor_divergence"
    return "all_agree"


def _fmp_reported_currency(fmp_vals: dict | None, cached_entry: dict | None = None) -> str | None:
    if isinstance(cached_entry, dict):
        cached_currency = _currency_code(cached_entry.get("fmp_reported_currency"))
        if cached_currency:
            return cached_currency
    if isinstance(fmp_vals, dict):
        return _currency_code(fmp_vals.get(FMP_REPORTED_CURRENCY_KEY))
    return None


def _currency_abstention_reason(
    filing_currency: str | None,
    fmp_reported_currency: str | None,
    fmp_vals: dict | None,
    fmp_success: bool,
) -> str | None:
    """Return a currency-gate abstention reason before any value comparison."""
    if not fmp_success or not fmp_vals:
        return None
    if not filing_currency or not fmp_reported_currency:
        return CV_ABSTAIN_CURRENCY_UNKNOWN
    if filing_currency != fmp_reported_currency:
        return CV_ABSTAIN_CURRENCY_MISMATCH
    return None


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_key(ticker: str, fiscal_year: str) -> str:
    yr = _parse_year(fiscal_year) or fiscal_year
    return f"{ticker.upper()}|{yr}"


def _load_cv_cache() -> dict:
    try:
        if _CV_CACHE_FILE.exists():
            cache = json.loads(_CV_CACHE_FILE.read_text(encoding="utf-8"))
            repaired = _repair_cv_cache(cache)
            if repaired != cache:
                _save_cv_cache(repaired)
            return repaired
    except Exception:
        pass
    return {}


def _save_cv_cache(cache: dict) -> None:
    try:
        _CV_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CV_CACHE_FILE.write_text(
            json.dumps(cache, indent=2, default=str), encoding="utf-8"
        )
    except Exception:
        pass


def _repair_cv_cache(cache: dict) -> dict:
    """Drop legacy or transient failed FMP fetches so cross-validation retries."""
    if not isinstance(cache, dict):
        return {}

    repaired: dict = {}
    for key, entry in cache.items():
        if not isinstance(entry, dict):
            continue
        reason = entry.get("fmp_fetch_reason")
        success = bool(entry.get("fmp_fetch_success"))
        if success:
            entry.setdefault("fmp_fetch_reason", FMP_FETCH_SUCCESS)
            vals = entry.get("fmp_vals")
            if vals is None:
                repaired[key] = entry
                continue
            if "fmp_reported_currency" in entry:
                reported_currency = _fmp_reported_currency(vals, entry)
                if reported_currency and isinstance(vals, dict):
                    vals[FMP_REPORTED_CURRENCY_KEY] = reported_currency
                repaired[key] = entry
                continue
            reported_currency = _fmp_reported_currency(vals, entry)
            if not reported_currency:
                continue
            entry["fmp_reported_currency"] = reported_currency
            if isinstance(vals, dict):
                vals[FMP_REPORTED_CURRENCY_KEY] = reported_currency
            repaired[key] = entry
        elif reason == FMP_PREMIUM_BLOCKED:
            repaired[key] = entry
        elif reason == FMP_TRANSIENT_FAILURE or reason is None:
            continue
    return repaired


def _cacheable_fmp_reason(reason: str) -> bool:
    return reason in {FMP_FETCH_SUCCESS, FMP_PREMIUM_BLOCKED}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def cross_validate_filing(
    normalized_data: dict,
    ticker: str,
    fiscal_year: str,
    filing_metadata: dict | None = None,
) -> CrossValidationResult:
    """
    Compare FinLens normalized values for 4 headline fields against FMP.

    Parameters
    ----------
    normalized_data   Output of normalize_financial_data() -- raw filing-currency values.
    ticker            Ticker symbol (case-insensitive, will be uppercased).
    fiscal_year       FinLens fiscal year string, e.g. "FY2025".
    filing_metadata   Optional dict.  Keys used: 'accession', 'filing_date'.

    Returns
    -------
    CrossValidationResult  Always returned -- never raises.
        fmp_fetch_success=False  if FMP is unreachable or key missing.
        All fields UNMATCHED     if FMP returned no usable data.

    Side effects
    ------------
    - Caches FMP result to ~/.finlens/cv_cache.json (idempotent).
    - Appends a cross_validation record to the integrity log (idempotent).
    """
    if filing_metadata is None:
        filing_metadata = {}

    ticker    = (ticker or "").strip().upper()
    timestamp = datetime.now(timezone.utc).isoformat()
    filing_accession = filing_metadata.get("accession")
    target_year = _parse_year(fiscal_year)

    # --- FinLens values (always available, no network call) ---
    finlens_vals = _extract_finlens_values(normalized_data)

    # --- FMP values (cached or fetched) ---
    ck    = _cache_key(ticker, fiscal_year)
    cache = _load_cv_cache()
    fmp_reported_currency = None

    if ck in cache:
        cached       = cache[ck]
        fmp_vals     = cached.get("fmp_vals")
        fmp_success  = cached.get("fmp_fetch_success", False)
        fmp_reason   = cached.get("fmp_fetch_reason") or (
            FMP_FETCH_SUCCESS if fmp_success else FMP_TRANSIENT_FAILURE
        )
        fmp_reported_currency = _fmp_reported_currency(fmp_vals, cached)
    else:
        if target_year is None:
            fmp_vals, fmp_success, fmp_reason = None, False, FMP_TRANSIENT_FAILURE
        else:
            fmp_vals, fmp_success, fmp_reason = _fetch_fmp_raw(ticker, target_year)
        fmp_reported_currency = _fmp_reported_currency(fmp_vals)
        if _cacheable_fmp_reason(fmp_reason):
            cache[ck] = {
                "fmp_vals": fmp_vals,
                "fmp_fetch_success": fmp_success,
                "fmp_fetch_reason": fmp_reason,
                "fmp_reported_currency": fmp_reported_currency,
            }
            _save_cv_cache(cache)

    filing_currency = _currency_code(
        normalized_data.get("currency")
        or filing_metadata.get("currency")
        or filing_metadata.get("reported_currency")
    )
    abstention_reason = _currency_abstention_reason(
        filing_currency,
        fmp_reported_currency,
        fmp_vals,
        bool(fmp_success),
    )

    # --- Build per-field results ---
    field_results: list[FieldResult] = []
    for field_name in ("revenue", "net_income", "total_assets", "operating_cash_flow"):
        fl_val  = finlens_vals.get(field_name)
        fmp_val = (fmp_vals or {}).get(field_name) if fmp_vals else None
        if abstention_reason:
            pct_raw = None
            status = "UNMATCHED"
            severity = None
            field_abstention_reason = abstention_reason
        else:
            pct_raw = _pct_diff_raw(fl_val, fmp_val)
            status  = _field_status(pct_raw)
            severity = _field_severity(status)
            field_abstention_reason = None
        field_results.append(FieldResult(
            field=field_name,
            finlens_value=fl_val,
            fmp_value=fmp_val,
            pct_diff=round(pct_raw * 100, 2) if pct_raw is not None else None,
            status=status,
            severity=severity,
            abstention_reason=field_abstention_reason,
        ))

    result = CrossValidationResult(
        overall_status   =_overall_status(field_results, fmp_success),
        fields           =field_results,
        timestamp        =timestamp,
        ticker           =ticker,
        fiscal_year      =fiscal_year,
        filing_accession =filing_accession,
        fmp_fetch_success=fmp_success,
        fmp_fetch_reason =fmp_reason,
        filing_currency=filing_currency,
        fmp_reported_currency=fmp_reported_currency,
        abstention_reason=abstention_reason,
    )

    # --- Append to integrity log (idempotent) ---
    try:
        from .log import append_cv_to_log
        append_cv_to_log(result)
    except Exception:
        pass

    return result
