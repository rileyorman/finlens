"""
Cross-document TTM assembly for SEDAR interim filings (CB-040 Stage 3;
spec: docs/SEDAR_INTERIM_SPEC.md).

TTM_flow = FY + YTD_current − YTD_prior, where FY comes from the library's
STORED ANNUAL extraction and both YTD values come from the interim's own
columns (IAS 34 mandates the comparative prior-year YTD). This mirrors the
CB-039 construction on the EDGAR path — evidence-forced there because cash
flow is YTD-only in interims; label text replaces XBRL date arithmetic here.

STRICT GATES (ratified decision 4) — any failure → honest N/A, never a
conversion or a guess:
- CURRENCY equality between the two documents (code token compare; no FX).
- SCALE equality (annual-in-millions vs interim-in-thousands is the live
  trap named at ratification; we gate, we never rescale).
- YEAR CHAIN: the interim's YTD year must be the annual's fiscal year + 1.
  The annual document is trusted as ANNUAL by provenance (it is the
  classed, mapped, stored annual — its column keys may be bare years like
  TOU's "2025"/"2024"); the WINDOW semantics come from the interim's own
  column text via parse_period_window (fp/labels never trusted beyond
  their own text — CB-039 discipline).
- Per field, the YTD pair must be the SAME window class one year apart
  (the CB-040 pairing rule), taken from the LARGEST YTD window printed
  (9M > H1 > Q): at Q2/Q3 the discrete-quarter column is the row-layer
  display, but TTM needs the year-to-date column.

Receipts are composite and cite both documents. Values are as-presented
(signs ride with the filer's own presentation, consistent within one
filer's documents; the receipt makes the composition auditable).
"""
from __future__ import annotations

import re

from modules.sedar_periods import parse_period_window, select_period_pair

# Headline flow fields (income + cash-flow) — balance items are instants
# and have no TTM. Derived metrics (FCF etc.) belong to consumers, not here.
TTM_FIELDS = ("revenue", "net_income", "operating_cash_flow", "capex")

# Statements that can hold TTM-able flow rows. Balance-sheet rows carry
# instant column keys (no window words), so they can never produce a YTD
# pair — but scoping the search keeps a same-label balance row from even
# being considered.
_FLOW_STATEMENTS = ("income_statement", "cash_flow")

# Largest YTD window first: at Q2/Q3 the year-to-date column is the TTM
# component, not the discrete quarter the row layer displays.
_YTD_PREFERENCE = ("9M", "H1", "Q")


def _currency_code(value) -> str:
    return str(value or "").split(",")[0].strip().upper()


def interim_window(financial_data: dict) -> dict | None:
    """The analysis's window parse ({window, year}) when its fiscal_year
    label declares a non-FY window — the same document-driven test the
    header's "unaudited interim" caption uses. None for annual (or
    non-SEDAR) analyses, so an annual can never look like an interim."""
    window = parse_period_window((financial_data or {}).get("fiscal_year"))
    if window and window.get("window") != "FY":
        return window
    return None


def find_stored_annual_for_interim(interim_fd: dict, entries: list) -> dict | None:
    """The library's stored annual EXTRACTION for a loaded interim
    analysis: same issuer (ticker match when both sides carry one, else
    exact company-name match), a SEDAR extraction present, fiscal year ==
    the interim's year − 1, and not itself an interim. Returns the
    annual's extraction dict (statements + mapping) or None — the TTM
    panel simply does not render without one (honest absence)."""
    window = interim_window(interim_fd)
    if not window:
        return None
    target_year = window["year"] - 1
    ticker_i = str((interim_fd or {}).get("ticker") or "").strip().upper()
    company_i = str((interim_fd or {}).get("company_name") or "").strip().lower()
    for entry in entries or []:
        fd = (entry or {}).get("financial_data") or {}
        extraction = fd.get("sedar_extraction")
        if not isinstance(extraction, dict):
            continue
        if interim_window(fd):
            continue  # another interim can never serve as the annual side
        ticker_e = str(fd.get("ticker") or "").strip().upper()
        company_e = str(fd.get("company_name") or "").strip().lower()
        if ticker_i and ticker_e:
            if ticker_i != ticker_e:
                continue
        elif not company_i or company_i != company_e:
            continue
        if _annual_fiscal_year(extraction) != target_year:
            continue
        return extraction
    return None


def _year_of(text) -> int | None:
    match = re.search(r"(\d{4})", str(text or ""))
    return int(match.group(1)) if match else None


def _annual_fiscal_year(annual: dict) -> int | None:
    """The stored annual's fiscal year, from its own current income column
    (select_period_pair handles both 'Year Ended Dec 31 2025' and TOU's
    bare '2025' key shapes)."""
    statements = annual.get("statements") or {}
    for item in statements.get("income_statement") or []:
        values = item.get("values") or {}
        if isinstance(values, dict) and values:
            current, _prior = select_period_pair(values)
            return _year_of(current)
    return None


def _ytd_pair(values: dict, interim_year: int) -> tuple[str, str] | None:
    """The interim row's (YTD_current_key, YTD_prior_key): same window
    class, current year and current year − 1, preferring the largest YTD
    window printed. None when no class yields the strict pair."""
    if not isinstance(values, dict):
        return None
    by_class: dict[str, dict[int, str]] = {}
    for key in values:
        window = parse_period_window(key)
        if not window:
            continue
        by_class.setdefault(window["window"], {})[window["year"]] = key
    for cls in _YTD_PREFERENCE:
        years = by_class.get(cls) or {}
        if interim_year in years and (interim_year - 1) in years:
            return years[interim_year], years[interim_year - 1]
    return None


def _interim_flow_row(interim: dict, source_label: str) -> dict | None:
    """The unique flow-statement row carrying the mapped source label.
    Zero or multiple candidates → None (ambiguity is honest absence)."""
    statements = interim.get("statements") or {}
    candidates = []
    for statement_key in _FLOW_STATEMENTS:
        for item in statements.get(statement_key) or []:
            if isinstance(item, dict) and str(item.get("label") or "").strip() == source_label:
                candidates.append(item)
    return candidates[0] if len(candidates) == 1 else None


def build_ttm_from_interim(interim: dict, annual: dict) -> dict:
    """Assemble TTM headline flows from an interim extraction plus the
    stored annual extraction. Returns:

        {"status": "ok" | "gates_failed",
         "gates": {name: {"pass": bool, "detail": str}},
         "annual_year": int | None, "interim_year": int | None,
         "fields": {name: {"value": number, "receipt": str}},
         "unavailable": {name: reason}}

    A gate failure empties fields (honest N/A across the board); a
    per-field chain failure lands that field in unavailable with its
    reason. Never raises.
    """
    gates: dict[str, dict] = {}
    fields: dict[str, dict] = {}
    unavailable: dict[str, str] = {}

    interim = interim or {}
    annual = annual or {}

    cur_i, cur_a = _currency_code(interim.get("currency")), _currency_code(annual.get("currency"))
    gates["currency"] = {
        "pass": bool(cur_i) and cur_i == cur_a,
        "detail": f"interim {cur_i or '?'} vs annual {cur_a or '?'}",
    }
    scale_i = str(interim.get("scale") or "").strip().lower()
    scale_a = str(annual.get("scale") or "").strip().lower()
    gates["scale"] = {
        "pass": bool(scale_i) and scale_i == scale_a,
        "detail": f"interim {scale_i or '?'} vs annual {scale_a or '?'}",
    }

    annual_year = _annual_fiscal_year(annual)
    # The interim's year comes from its own income-statement current key —
    # the same window-class selection the row layer uses.
    interim_year = None
    for item in (interim.get("statements") or {}).get("income_statement") or []:
        values = item.get("values") or {}
        if isinstance(values, dict) and values:
            current, _prior = select_period_pair(values)
            window = parse_period_window(current)
            interim_year = window["year"] if window else _year_of(current)
            break
    gates["year_chain"] = {
        "pass": annual_year is not None and interim_year is not None
        and interim_year == annual_year + 1,
        "detail": f"interim year {interim_year} vs annual FY {annual_year}",
    }

    result = {
        "status": "gates_failed",
        "gates": gates,
        "annual_year": annual_year,
        "interim_year": interim_year,
        "fields": fields,
        "unavailable": unavailable,
    }
    if not all(gate["pass"] for gate in gates.values()):
        return result

    annual_mapped = (annual.get("mapping") or {}).get("mapped") or {}
    interim_mapped = (interim.get("mapping") or {}).get("mapped") or {}

    for name in TTM_FIELDS:
        annual_entry = annual_mapped.get(name) or {}
        annual_value = annual_entry.get("value")
        if annual_value is None:
            unavailable[name] = "annual_field_unmapped"
            continue
        interim_entry = interim_mapped.get(name) or {}
        source_label = str(interim_entry.get("source_label") or "").strip()
        if not source_label:
            unavailable[name] = "interim_field_unmapped"
            continue
        row = _interim_flow_row(interim, source_label)
        if row is None:
            unavailable[name] = "interim_row_ambiguous_or_missing"
            continue
        pair = _ytd_pair(row.get("values") or {}, interim_year)
        if pair is None:
            unavailable[name] = "no_ytd_pair"
            continue
        ytd_key, ytd_prior_key = pair
        values = row.get("values") or {}
        ytd_value, ytd_prior_value = values.get(ytd_key), values.get(ytd_prior_key)
        if not isinstance(ytd_value, (int, float)) or not isinstance(ytd_prior_value, (int, float)):
            unavailable[name] = "ytd_value_missing"
            continue
        if not isinstance(annual_value, (int, float)):
            unavailable[name] = "annual_value_not_numeric"
            continue
        ttm = annual_value + ytd_value - ytd_prior_value
        fields[name] = {
            "value": ttm,
            "receipt": (
                f"TTM = FY{annual_year} “{annual_entry.get('source_label')}” "
                f"({annual_value:,}) [stored annual] + “{ytd_key}” ({ytd_value:,}) "
                f"− “{ytd_prior_key}” ({ytd_prior_value:,}) "
                f"[interim: “{source_label}”]"
            ),
        }

    result["status"] = "ok"
    return result
