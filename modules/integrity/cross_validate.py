"""
FinLens Cross-Validation Layer
==============================
Compares FinLens normalized financial figures against SEC EDGAR
company-facts (the as-filed XBRL record) for the same ticker and fiscal
period.

The integrity engine checks internal arithmetic consistency; this checks
whether FinLens numbers match the regulator-hosted record of the same
filing family.

FLAG-AND-SHOW ONLY.  Never auto-correct FinLens data to match the witness.

WITNESS HISTORY (CB-042):
    v1/v2 used FMP as the witness.  FMP was retired from the integrity
    engine after repeated phantom values (JPM FY2025 operating_cash_flow:
    FMP +100.9B vs the as-filed (147,782)MM -- CLAUDE.md "Cross-Check
    Source").  The v3 witness is EDGAR company-facts, so for EDGAR-path
    analyses the check is as-filed-vs-as-restated (near-source-identical;
    it catches restatements and tag drift), NOT an independent witness --
    the Gemini cross-extractor remains the independent-extraction check.

LEGACY KEY NAMING (deliberate, v3): record/cache keys and result attributes
named fmp_* (fmp_fetch_success, fmp_fetch_reason, fmp_value,
fmp_reported_currency) now carry the EDGAR witness.  Renaming them would
break integrity-log idempotency signatures and old-record reads;
checker_version "3" + witness_source "edgar_company_facts" disambiguate.

Usage
-----
    from modules.integrity.cross_validate import cross_validate_filing
    result = cross_validate_filing(normalized_data, ticker, fiscal_year)

Cost note
---------
    cross_validate_filing() triggers up to 2 SEC EDGAR HTTP calls (CIK
    lookup + companyfacts) -- free, no API key.  Results are cached in
    ~/.finlens/cv_cache.json keyed by ticker + fiscal year (version-stamped;
    pre-v3 FMP-era entries are ignored).  Re-display of the same filing
    does NOT re-call EDGAR.
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

CROSS_VALIDATE_VERSION = "3"
WITNESS_SOURCE_EDGAR = "edgar_company_facts"
_CV_CACHE_FILE = LIBRARY_DIR / "cv_cache.json"
FMP_FETCH_SUCCESS = "success"
NO_US_FILED_SOURCE = "no_us_filed_source"
FMP_TRANSIENT_FAILURE = "transient_failure"
# Legacy reason written by v1/v2 FMP-era records only; kept so old log
# records still classify in analyze.py. Never written by v3.
FMP_PREMIUM_BLOCKED = "fmp_premium_blocked"
FMP_REPORTED_CURRENCY_KEY = "_reported_currency"
CV_SEVERITY_ADVISORY = "advisory"
CV_ABSTAIN_CURRENCY_MISMATCH = "currency_mismatch"
CV_ABSTAIN_CURRENCY_UNKNOWN = "currency_unknown"
# The witness currency is derived from the matched facts' own unit keys
# (Stage-4 hotfix: a dual registrant can file 10-Ks with CAD-unit facts —
# the ENB trap); this constant is only the default when no fact matched
# the target year (values all None, currency moot). The v2 currency gate
# is unchanged: a filing/witness currency mismatch abstains, never converts.
_WITNESS_CURRENCY = "USD"

# Divergence thresholds (absolute percentage of the witness value)
_AGREE_THRESHOLD  = 0.02   # < 2%  -> AGREE
_MINOR_THRESHOLD  = 0.10   # 2-10% -> MINOR_DIVERGENCE
                            # >10%  -> DISAGREE

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
    """Outcome of comparing one field between FinLens and the witness."""
    field: str
    finlens_value: float | None    # raw filing currency
    fmp_value: float | None        # witness value (legacy key name -- see module docstring)
    pct_diff: float | None         # percentage, e.g. 1.5 = 1.5%; None if either value missing
    status: str                    # AGREE | MINOR_DIVERGENCE | DISAGREE | UNMATCHED
    severity: str | None = None    # advisory for witness value mismatches; omitted otherwise
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
    witness_source: str = WITNESS_SOURCE_EDGAR

    def to_dict(self) -> dict:
        """Serialize to a log-ready dict (Supabase-friendly schema)."""
        return {
            "record_type":       "cross_validation",
            "checker_version":   self.checker_version,
            "witness_source":    self.witness_source,
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


def _fetch_witness_raw(ticker: str, target_year: int) -> tuple[dict[str, Any] | None, bool, str]:
    """
    Fetch the 4 headline values for ticker + target_year from SEC EDGAR
    company-facts (the v3 witness -- CB-042).

    Concept selection reuses the CB-038/039 machinery in edgar_fetcher:
    recency-competed concept chains (the NVDA-hardened chains must never
    fork), restatement-resolved annual facts (same end -> latest filed),
    then the fact whose end YEAR equals target_year.

    Returns
    -------
    (values_dict, success_bool, reason)
        values_dict   keys: revenue, net_income, total_assets,
                      operating_cash_flow, plus _reported_currency derived
                      from the matched facts' own unit keys (USD for most
                      10-K filers; CAD for dual registrants like ENB;
                      None when matched units are mixed -- the currency
                      gate then abstains).
                      None for a field when no fact ends in target_year.
        success_bool  True when the witness was consulted and carries
                      us-gaap 10-K annual facts for this filer -- even if
                      the target year is absent (that is "period not in the
                      witness", not a failure).
        reason        success | no_us_filed_source | transient_failure
                      no_us_filed_source: the ticker resolves to no SEC CIK,
                      or its company-facts hold no us-gaap 10-K annual facts
                      for any headline concept (non-US / 40-F / 6-K filers).
                      Honest abstention -- FMP is never consulted (retired
                      from the integrity engine, CLAUDE.md Cross-Check
                      Source).
    """
    try:
        from modules.edgar_fetcher import (  # lazy: reuse session + shared concept chains
            NET_INCOME_CONCEPTS,
            OPERATING_CASH_FLOW_CONCEPTS,
            REVENUE_CONCEPTS,
            TOTAL_ASSETS_CONCEPTS,
            _competing_annual_facts,
            _get_companyfacts,
            get_cik,
        )

        cik = get_cik(ticker)
        if not cik:
            return None, False, NO_US_FILED_SOURCE

        facts = _get_companyfacts(cik)
        if not facts:
            return None, False, FMP_TRANSIENT_FAILURE

        chains = {
            "revenue":             REVENUE_CONCEPTS,
            "net_income":          NET_INCOME_CONCEPTS,
            "total_assets":        TOTAL_ASSETS_CONCEPTS,
            "operating_cash_flow": OPERATING_CASH_FLOW_CONCEPTS,
        }
        values: dict[str, Any] = {}
        any_annual_facts = False
        matched_units: set = set()
        for field_name, concepts in chains.items():
            _concept, annual = _competing_annual_facts(facts, concepts)
            if annual:
                any_annual_facts = True
            match = next(
                (item for item in annual if str(item.get("end", ""))[:4] == str(target_year)),
                None,
            )
            if match is not None:
                matched_units.add(match.get("_unit"))
            values[field_name] = match.get("val") if match else None

        if not any_annual_facts:
            return None, False, NO_US_FILED_SOURCE

        # Witness currency comes from the matched facts' own units — never
        # hardcoded (the ENB trap: CAD-unit 10-K facts). Single unit → that
        # currency; mixed units → None (the currency gate abstains as
        # currency_unknown); no matched facts → default (values all None,
        # currency moot).
        matched_units.discard(None)
        if len(matched_units) == 1:
            values[FMP_REPORTED_CURRENCY_KEY] = next(iter(matched_units))
        elif matched_units:
            values[FMP_REPORTED_CURRENCY_KEY] = None
        else:
            values[FMP_REPORTED_CURRENCY_KEY] = _WITNESS_CURRENCY

        return values, True, FMP_FETCH_SUCCESS

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
    """Keep only current-version cacheable entries.

    Pre-v3 entries (no cv_version stamp, or an older one) are FMP-era
    values and are dropped wholesale -- the v3 witness re-fetches from
    EDGAR.  Transient failures are never kept, so cross-validation retries.
    """
    if not isinstance(cache, dict):
        return {}

    repaired: dict = {}
    for key, entry in cache.items():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("cv_version") or "") != CROSS_VALIDATE_VERSION:
            continue
        if _cacheable_fmp_reason(entry.get("fmp_fetch_reason") or ""):
            repaired[key] = entry
    return repaired


def _cacheable_fmp_reason(reason: str) -> bool:
    # no_us_filed_source is a stable property of the filer (like the old
    # premium block was of the FMP tier), so it caches; transient never does.
    return reason in {FMP_FETCH_SUCCESS, NO_US_FILED_SOURCE}


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
    Compare FinLens normalized values for 4 headline fields against the
    EDGAR company-facts witness (v3, CB-042).

    Parameters
    ----------
    normalized_data   Output of normalize_financial_data() -- raw filing-currency values.
    ticker            Ticker symbol (case-insensitive, will be uppercased).
    fiscal_year       FinLens fiscal year string, e.g. "FY2025".
    filing_metadata   Optional dict.  Keys used: 'accession', 'filing_date'.

    Returns
    -------
    CrossValidationResult  Always returned -- never raises.
        fmp_fetch_reason="no_us_filed_source"  honest abstention: no SEC CIK
                                               or no us-gaap 10-K facts (non-US filers).
        fmp_fetch_success=False                if EDGAR is unreachable.
        All fields UNMATCHED                   if the witness had no usable data.

    Side effects
    ------------
    - Caches the witness result to ~/.finlens/cv_cache.json (idempotent, version-stamped).
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

    # --- Witness values (cached or fetched; legacy fmp_* naming, see module docstring) ---
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
            fmp_vals, fmp_success, fmp_reason = _fetch_witness_raw(ticker, target_year)
        fmp_reported_currency = _fmp_reported_currency(fmp_vals)
        if _cacheable_fmp_reason(fmp_reason):
            cache[ck] = {
                "cv_version": CROSS_VALIDATE_VERSION,
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
