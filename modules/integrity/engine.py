"""
FinLens Data Integrity Engine -- Validation Engine
==================================================
Public API
    validate_filing(normalized_data, ticker, sector, filing_metadata)
        -> ValidationResult

Design principles
    - Flag-and-warn only.  validate_filing() never mutates normalized_data.
    - No external API calls.  All checks are pure arithmetic on the data dict.
    - Adding a new check_type: write a handler, add it to _CHECKS.
    - Adding a new rule for an existing type: edit rules.py only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .rules import RULES


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    rule_id: str
    severity: str
    passed: bool
    skipped: bool
    skip_reason: str | None    # "sector_excluded" | "field_unavailable" | "check_error" | None
    observed_value: float | None
    threshold: dict[str, Any]
    message: str

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "passed": self.passed,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "observed_value": self.observed_value,
            "threshold": self.threshold,
            "message": self.message,
        }


@dataclass
class ValidationResult:
    overall_status: str           # "clean" | "warnings" | "info_only" | "unknown"
    checks: list[CheckResult]
    timestamp: str                # ISO 8601
    ticker: str
    sector: str | None
    sector_was_unknown: bool
    fiscal_year: str
    filing_accession: str | None
    filing_source: str | None
    accounting_standard: str | None
    rules_run: int
    rules_passed: int
    rules_failed: int
    rules_skipped: int
    gross_profit_derived: bool = False
    ticker_unresolved: bool = False

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "ticker": self.ticker,
            "sector": self.sector,
            "sector_was_unknown": self.sector_was_unknown,
            "fiscal_year": self.fiscal_year,
            "overall_status": self.overall_status,
            "filing_accession": self.filing_accession,
            "filing_source": self.filing_source,
            "accounting_standard": self.accounting_standard,
            "rules_run": self.rules_run,
            "rules_passed": self.rules_passed,
            "rules_failed": self.rules_failed,
            "rules_skipped": self.rules_skipped,
            "gross_profit_derived": self.gross_profit_derived,
            "ticker_unresolved": self.ticker_unresolved,
            "checks": [c.to_dict() for c in self.checks],
        }


# ---------------------------------------------------------------------------
# Context extraction
# Builds a flat dict of named financial values from normalized_data so
# check handlers can reference fields by name without knowing the schema.
# ---------------------------------------------------------------------------

_LINE_ITEM_ALIASES = {
    "revenue": (
        "Revenues",
        "Revenue",
        "Total Revenues",
        "Total Revenue",
        "Net Revenues",
        "Net Revenue",
        "Total Net Revenues",
        "Operating Revenues",
        "Total Operating Revenues",
    ),
    "cost_of_revenue": (
        "Cost of Revenue",
        "Cost of Revenues",
        "Cost of revenue",
        "Cost of Goods Sold",
        "Cost of Goods and Services Sold",
        "Cost of Sales",
        "Total Cost of Revenue",
    ),
    "gross_profit": (
        "Gross Profit",
        "Gross profit",
        "Gross Margin",
    ),
    "net_income": (
        "Net Income",
        "Net income",
        "Net Income to Common Shareholders",
        "Net income attributable to common stockholders",
        "Net Income Attributable to Common Stockholders",
    ),
}

_TOTAL_LIABILITIES_AND_EQUITY_LABELS = (
    "Total liabilities and equity",
    "Total liabilities and shareholders' equity",
    "Total liabilities and unitholders' equity",
)


def _normalized_label(label: str) -> str:
    """Normalize statement labels for case-insensitive alias matching."""
    return re.sub(r"[^a-z0-9]+", " ", str(label or "").lower()).strip()


def _aliases_for(label: str) -> tuple[str, ...]:
    return _LINE_ITEM_ALIASES.get(label, (label,))


def _coerce_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _line_item(rows: list[dict], label: str) -> float | None:
    aliases = {_normalized_label(alias) for alias in _aliases_for(label)}
    for row in rows:
        if _normalized_label(row.get("line_item")) in aliases:
            value = _coerce_number(row.get("value"))
            if value is not None:
                return value
    return None


def _line_item_from_labels(rows: list[dict], labels: tuple[str, ...]) -> float | None:
    aliases = {_normalized_label(alias) for alias in labels}
    for row in rows:
        if _normalized_label(row.get("line_item")) in aliases:
            value = _coerce_number(row.get("value"))
            if value is not None:
                return value
    return None


def _mapped_value(mapping: dict | None, field: str) -> float | None:
    if not isinstance(mapping, dict):
        return None
    mapped = mapping.get("mapped")
    if not isinstance(mapped, dict):
        return None
    item = mapped.get(field)
    if not isinstance(item, dict):
        return None
    return _coerce_number(item.get("value"))


def _line_item_prior(rows: list[dict], label: str) -> float | None:
    aliases = {_normalized_label(alias) for alias in _aliases_for(label)}
    for row in rows:
        if _normalized_label(row.get("line_item")) in aliases:
            value = _coerce_number(row.get("value_prior"))
            if value is not None:
                return value
    return None


def _parse_fy_year(fy: str) -> int | None:
    """Return the integer year from a string like 'FY2025' or '2025'."""
    m = re.search(r"(\d{4})", str(fy or ""))
    return int(m.group(1)) if m else None


def _parse_iso_year(date_str: str) -> int | None:
    """Return the year from an ISO date string like '2025-07-30'."""
    m = re.match(r"^(\d{4})-", str(date_str or ""))
    return int(m.group(1)) if m else None


def _build_context(normalized_data: dict, filing_metadata: dict) -> dict[str, Any]:
    income = normalized_data.get("income_statement", [])
    balance = normalized_data.get("balance_sheet", [])
    mapping = normalized_data.get("mapping")
    revenue = _line_item(income, "revenue")
    cost_of_revenue = _line_item(income, "cost_of_revenue")
    gross_profit = _line_item(income, "gross_profit")
    total_assets = _coerce_number(normalized_data.get("total_assets"))
    if total_assets is None:
        total_assets = _mapped_value(mapping, "total_assets")
    # CB-013 canonical balance-sheet components -- same top-level-then-mapped
    # resolution as total_assets (app.py promotes mapped fields to top level
    # for SEDAR filings; the mapped fallback covers direct engine callers).
    total_liabilities = _coerce_number(normalized_data.get("total_liabilities"))
    if total_liabilities is None:
        total_liabilities = _mapped_value(mapping, "total_liabilities")
    total_equity = _coerce_number(normalized_data.get("total_equity"))
    if total_equity is None:
        total_equity = _mapped_value(mapping, "total_equity")
    gross_profit_derived = False
    cost_of_revenue_excludes_da = False

    # Use mapper-derived gross_profit when raw label lookup fails (e.g. IFRS retail filers
    # whose cost label is non-standard like "Cost of sales, excluding D&A").
    if mapping and isinstance(mapping, dict) and gross_profit is None:
        mapper_gp = (mapping.get("mapped") or {}).get("gross_profit")
        if isinstance(mapper_gp, dict) and mapper_gp.get("derived"):
            gp_val = _coerce_number(mapper_gp.get("value"))
            if gp_val is not None:
                gross_profit = gp_val
                gross_profit_derived = True
                cost_of_revenue_excludes_da = bool(mapper_gp.get("excludes_da"))

    # Fallback: derive from raw income statement rows when both values are available.
    if gross_profit is None and revenue is not None and cost_of_revenue is not None:
        gross_profit = revenue - cost_of_revenue
        gross_profit_derived = True

    return {
        "revenue":                    revenue,
        "revenue_prior":              _line_item_prior(income, "revenue"),
        "cost_of_revenue":            cost_of_revenue,
        "gross_profit":               gross_profit,
        "gross_profit_derived":       gross_profit_derived,
        "cost_of_revenue_excludes_da": cost_of_revenue_excludes_da,
        "net_income":                 _line_item(income, "net_income"),
        "total_assets":               total_assets,
        "total_liabilities":          total_liabilities,
        "total_equity":               total_equity,
        "total_liabilities_and_equity": _line_item_from_labels(
            balance,
            _TOTAL_LIABILITIES_AND_EQUITY_LABELS,
        ),
        "mapping":                    mapping,
        "has_mapping":                "mapping" in normalized_data,
        "accounting_standard":        normalized_data.get("accounting_standard"),
        "fiscal_year":                normalized_data.get("fiscal_year", ""),
        "fiscal_year_int":            _parse_fy_year(normalized_data.get("fiscal_year", "")),
        "filing_year_int":            _parse_iso_year(filing_metadata.get("filing_date", "")),
    }


# ---------------------------------------------------------------------------
# Sector helpers
# ---------------------------------------------------------------------------

def _sector_skip_matches(sector: str | None, sector_skip: tuple | list) -> bool:
    """Return True if any token in sector_skip appears in the lowercased sector string."""
    if not sector or not sector_skip:
        return False
    s = sector.lower()
    return any(token in s for token in sector_skip)


# ---------------------------------------------------------------------------
# Check handlers
# Each receives (rule: dict, ctx: dict) and returns
#     (observed_value: float|None, threshold: dict, passed: bool, message: str)
# Handlers must not raise -- callers wrap in try/except for safety.
# ---------------------------------------------------------------------------

def _check_ratio_range(rule: dict, ctx: dict) -> tuple:
    p = rule["params"]
    num = ctx.get(p["numerator"])
    den = ctx.get(p["denominator"])
    min_v: float | None = p.get("min")
    max_v: float | None = p.get("max")

    if den is None or den == 0:
        return None, {}, False, f"denominator '{p['denominator']}' is zero or unavailable"
    if num is None:
        return None, {}, False, f"numerator '{p['numerator']}' is unavailable"

    ratio = num / den
    passed = True
    if min_v is not None and ratio < min_v:
        passed = False
    if max_v is not None and ratio > max_v:
        passed = False

    threshold = {k: v for k, v in {"min": min_v, "max": max_v}.items() if v is not None}
    lo = f"{min_v * 100:.0f}%" if min_v is not None else "-inf"
    hi = f"{max_v * 100:.0f}%" if max_v is not None else "+inf"
    direction = "within" if passed else "outside"
    msg = (
        f"{p['numerator'].replace('_', ' ').title()} / "
        f"{p['denominator'].replace('_', ' ').title()} = "
        f"{ratio * 100:.1f}% -- {direction} [{lo}, {hi}]"
    )
    if ctx.get("cost_of_revenue_excludes_da") and "gross_profit" in {
        p.get("numerator"), p.get("denominator")
    }:
        msg += (
            " [NOTE: cost_of_revenue excludes D&A"
            " -- derived margin not comparable to COGS-inclusive benchmarks]"
        )
    return round(ratio, 4), threshold, passed, msg


def _check_reconciliation(rule: dict, ctx: dict) -> tuple:
    p = rule["params"]
    a, b, c, tol = ctx.get(p["a"]), ctx.get(p["b"]), ctx.get(p["c"]), p["tolerance"]

    if any(v is None for v in (a, b, c)):
        missing = [k for k, v in {p["a"]: a, p["b"]: b, p["c"]: c}.items() if v is None]
        return None, {"tolerance": tol}, False, f"fields unavailable: {missing}"
    if a == 0:
        return None, {"tolerance": tol}, False, f"'{p['a']}' is zero -- cannot compute relative error"

    diff_pct = abs((a - b - c) / a)
    passed = diff_pct <= tol
    verdict = "<=" if passed else ">"
    msg = (
        f"{p['a']} (${a / 1e9:.2f}B) - {p['b']} (${b / 1e9:.2f}B) "
        f"= ${(a - b) / 1e9:.2f}B vs {p['c']} (${c / 1e9:.2f}B) -- "
        f"diff {diff_pct * 100:.2f}% ({verdict} {tol * 100:.0f}% tolerance)"
    )
    if ctx.get("cost_of_revenue_excludes_da") and "gross_profit" in {
        p.get("a"), p.get("b"), p.get("c")
    }:
        msg += (
            " [NOTE: cost_of_revenue excludes D&A"
            " -- gross profit derived from non-COGS cost base]"
        )
    return round(diff_pct, 6), {"tolerance": tol}, passed, msg


def _check_year_recency(rule: dict, ctx: dict) -> tuple:
    fy_year = ctx.get("fiscal_year_int")
    filing_year = ctx.get("filing_year_int")
    max_lag = rule["params"]["max_lag"]
    threshold = {"max_lag": max_lag}

    if fy_year is None or filing_year is None:
        return None, threshold, False, "could not parse fiscal year or filing date"

    lag = filing_year - fy_year
    passed = lag <= max_lag
    fy_label = ctx.get("fiscal_year", str(fy_year))
    direction = "within" if passed else "exceeds"
    msg = (
        f"Fiscal year {fy_label} filed in {filing_year} -- "
        f"lag {lag} year(s), {direction} max {max_lag}"
    )
    return lag, threshold, passed, msg


def _check_growth_range(rule: dict, ctx: dict) -> tuple:
    p = rule["params"]
    current = ctx.get(p["field"])
    prior = ctx.get(p["prior_field"])
    threshold = {"min": p["min"], "max": p["max"]}

    if current is None or prior is None:
        return None, threshold, False, f"'{p['field']}' or '{p['prior_field']}' unavailable"
    if prior == 0:
        return None, threshold, False, f"'{p['prior_field']}' is zero -- cannot compute growth rate"

    growth = (current - prior) / abs(prior)
    passed = p["min"] <= growth <= p["max"]
    direction = "within" if passed else "outside"
    msg = (
        f"YoY {p['field']} growth {growth * 100:.1f}% -- "
        f"{direction} [{p['min'] * 100:.0f}%, {p['max'] * 100:.0f}%]"
    )
    return round(growth, 4), threshold, passed, msg


def _mapped_fields(mapping: dict | None) -> dict:
    if not isinstance(mapping, dict):
        return {}
    mapped = mapping.get("mapped")
    return mapped if isinstance(mapped, dict) else {}


def _check_extraction_confidence(rule: dict, ctx: dict) -> tuple:
    min_confidence = rule["params"]["min"]
    threshold = {"min": min_confidence}
    low_confidence = []

    for field, item in _mapped_fields(ctx.get("mapping")).items():
        if not isinstance(item, dict):
            continue
        confidence = _coerce_number(item.get("confidence"))
        if confidence is not None and confidence < min_confidence:
            low_confidence.append((field, item.get("source_label"), confidence))

    if not low_confidence:
        return None, threshold, True, (
            f"All mapped SEDAR fields meet extraction confidence >= {min_confidence:.2f}"
        )

    observed = min(confidence for _, _, confidence in low_confidence)
    details = ", ".join(
        f"{field} from '{label}' ({confidence:.2f})"
        for field, label, confidence in low_confidence
    )
    return round(observed, 4), threshold, False, (
        "Uncertain read: mapped SEDAR field extraction confidence below "
        f"{min_confidence:.2f}: {details}"
    )


def _check_mapping_pattern_info(rule: dict, ctx: dict) -> tuple:
    pattern_matches = []
    for field, item in _mapped_fields(ctx.get("mapping")).items():
        if isinstance(item, dict) and item.get("match_type") == "pattern":
            pattern_matches.append((field, item.get("source_label")))

    if not pattern_matches:
        return None, {}, True, "No SEDAR pattern-matched fields"

    details = ", ".join(f"{field} from '{label}'" for field, label in pattern_matches)
    return float(len(pattern_matches)), {}, False, (
        f"Uncertain mapping: SEDAR pattern match used for {details}"
    )


def _check_accounting_standard_info(rule: dict, ctx: dict) -> tuple:
    standard = ctx.get("accounting_standard")
    return None, {}, True, f"Accounting standard recorded: {standard or 'unknown'}"


def _check_total_assets_identity(rule: dict, ctx: dict) -> tuple:
    total_assets = ctx.get("total_assets")
    combined = ctx.get("total_liabilities_and_equity")
    absolute_tolerance = rule["params"].get("absolute_tolerance", 0.5)

    diff = abs(total_assets - combined)
    passed = diff <= absolute_tolerance
    direction = "<=" if passed else ">"
    return round(diff, 6), {"absolute_tolerance": absolute_tolerance}, passed, (
        "SEDAR total_assets vs Total liabilities and equity: "
        f"{total_assets} vs {combined}; absolute difference {diff} "
        f"({direction} {absolute_tolerance})"
    )


def _check_balance_sheet_identity(rule: dict, ctx: dict) -> tuple:
    """CB-013: total_assets == total_liabilities + total_equity from the
    canonical mapped components. A wrong-concept equity pick (NCI-excluding
    subtotal, attributable-only line) fails this by exactly the excluded
    amount, converting the silent-error class into a flagged conflict."""
    total_assets = ctx.get("total_assets")
    total_liabilities = ctx.get("total_liabilities")
    total_equity = ctx.get("total_equity")
    absolute_tolerance = rule["params"].get("absolute_tolerance", 0.5)

    combined = total_liabilities + total_equity
    diff = abs(total_assets - combined)
    passed = diff <= absolute_tolerance
    direction = "<=" if passed else ">"
    return round(diff, 6), {"absolute_tolerance": absolute_tolerance}, passed, (
        "SEDAR total_assets vs total_liabilities + total_equity: "
        f"{total_assets} vs {total_liabilities} + {total_equity} = {combined}; "
        f"absolute difference {diff} ({direction} {absolute_tolerance})"
    )


# Registry: check_type ? handler
_CHECKS = {
    "ratio_range":               _check_ratio_range,
    "arithmetic_reconciliation": _check_reconciliation,
    "year_recency":              _check_year_recency,
    "growth_range":              _check_growth_range,
    "extraction_confidence":     _check_extraction_confidence,
    "mapping_pattern_info":      _check_mapping_pattern_info,
    "accounting_standard_info":  _check_accounting_standard_info,
    "total_assets_identity":     _check_total_assets_identity,
    "balance_sheet_identity":    _check_balance_sheet_identity,
}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def validate_filing(
    normalized_data: dict,
    ticker: str,
    sector: str | None,
    filing_metadata: dict | None = None,
) -> ValidationResult:
    """
    Run all applicable integrity rules against normalized_data.

    Parameters
    ----------
    normalized_data  Output of get_financial_data() or normalize_financial_data().
                     Not mutated -- validation result is returned, not attached.
    ticker           Ticker symbol (used in the log record; not in check logic).
    sector           Company sector string, e.g. "Technology" or "Financial Services".
                     Pass None if unknown -- rules that need sector classification will
                     run anyway, and sector_was_unknown is flagged in the result.
    filing_metadata  Dict with optional keys:
                       filing_date  ISO date string, e.g. "2025-07-30"
                       accession    SEC accession number
                       source       "edgar" | "pdf" | ...
    """
    if filing_metadata is None:
        filing_metadata = {}

    timestamp = datetime.now(timezone.utc).isoformat()
    ctx = _build_context(normalized_data, filing_metadata)
    sector_was_unknown = sector is None

    checks: list[CheckResult] = []
    rules_run = rules_passed = rules_failed = rules_skipped = 0

    for rule in RULES:
        rule_id = rule["id"]
        severity = rule["severity"]
        handler = _CHECKS.get(rule["check_type"])

        if rule.get("sedar_only") and not ctx.get("has_mapping"):
            continue

        # Unknown check_type -- config references a type with no handler
        if handler is None:
            checks.append(CheckResult(
                rule_id=rule_id, severity=severity,
                passed=False, skipped=True,
                skip_reason=f"unknown check_type: {rule['check_type']}",
                observed_value=None, threshold={},
                message=f"No handler registered for check_type '{rule['check_type']}'",
            ))
            rules_skipped += 1
            continue

        # Sector-skip: rule is structurally inapplicable to this sector
        if _sector_skip_matches(sector, rule.get("sector_skip", ())):
            checks.append(CheckResult(
                rule_id=rule_id, severity=severity,
                passed=True, skipped=True,
                skip_reason="sector_excluded",
                observed_value=None, threshold={},
                message=f"Rule not applicable to sector '{sector}'",
            ))
            rules_skipped += 1
            continue

        # Required-fields: silently skip rather than fail when data is absent
        missing = [f for f in rule.get("requires_fields", []) if ctx.get(f) is None]
        if missing:
            checks.append(CheckResult(
                rule_id=rule_id, severity=severity,
                passed=True, skipped=True,
                skip_reason="field_unavailable",
                observed_value=None, threshold={},
                message=f"Skipped -- required fields unavailable: {missing}",
            ))
            rules_skipped += 1
            continue

        # Run the check
        try:
            observed, threshold, passed, message = handler(rule, ctx)
        except Exception as exc:
            checks.append(CheckResult(
                rule_id=rule_id, severity=severity,
                passed=False, skipped=True,
                skip_reason="check_error",
                observed_value=None, threshold={},
                message=f"Check raised an exception: {exc}",
            ))
            rules_skipped += 1
            continue

        checks.append(CheckResult(
            rule_id=rule_id, severity=severity,
            passed=passed, skipped=False,
            skip_reason=None,
            observed_value=observed,
            threshold=threshold,
            message=message,
        ))
        rules_run += 1
        if passed:
            rules_passed += 1
        else:
            rules_failed += 1

    # Overall status -- severity-aware
    failed = [c for c in checks if not c.passed and not c.skipped]
    warn_failures = [c for c in failed if c.severity == "warn"]
    info_failures = [c for c in failed if c.severity == "info"]

    if warn_failures:
        overall_status = "warnings"
    elif info_failures:
        overall_status = "info_only"
    elif ctx.get("revenue") is None and ctx.get("net_income") is None:
        overall_status = "unknown"
    else:
        overall_status = "clean"

    return ValidationResult(
        overall_status=overall_status,
        checks=checks,
        timestamp=timestamp,
        ticker=ticker,
        sector=sector,
        sector_was_unknown=sector_was_unknown,
        fiscal_year=normalized_data.get("fiscal_year", ""),
        filing_accession=filing_metadata.get("accession"),
        filing_source=filing_metadata.get("source", "edgar"),
        accounting_standard=normalized_data.get("accounting_standard"),
        rules_run=rules_run,
        rules_passed=rules_passed,
        rules_failed=rules_failed,
        rules_skipped=rules_skipped,
        gross_profit_derived=bool(ctx.get("gross_profit_derived")),
        ticker_unresolved=bool(filing_metadata.get("ticker_unresolved", False)),
    )
