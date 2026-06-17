"""
FinLens Data Integrity Engine -- Rule Definitions
=================================================
All validation rules live here as plain dicts.  The engine (engine.py)
reads this list at runtime; adding a new rule for an existing check_type
is a config edit here -- no engine changes required.

Adding a new check_type requires writing a handler function and registering
it in engine._CHECKS.

Rule schema
-----------
id                Unique string identifier; appears in logs and UI.
description       Human-readable sentence describing what is checked.
severity          "warn"  ? shown as a data-quality warning.
                  "info"  ? flagged for awareness; not a hard issue.
check_type        Key that maps to a handler in engine._CHECKS.
params            Dict passed as-is to the handler.
sector_skip       Tuple of lowercase tokens.  Rule is skipped (status
                  "sector_excluded") when the filing's sector string
                  contains any of these tokens.  Use for rules that are
                  structurally inapplicable to a sector (e.g. gross-margin
                  checks on banks that have no cost-of-revenue line).
requires_fields   Context keys that must be non-None for the rule to run.
                  If any are absent the rule is skipped (status
                  "field_unavailable") -- missing field is not a failure.
sedar_only        Boolean. If true, the rule only applies when normalized_data
                  carries a SEDAR mapping payload. Non-SEDAR filings do not
                  record a skipped check for these rules.
"""

# Tokens used to identify sector-shaped rule exceptions.
# Applied as substring matches against sector.lower().
INSURANCE_SECTOR_TOKENS = (
    "insurance",
    "property and casualty",
    "life insurer",
)

# Financial-sector tokens deliberately exclude insurance. Insurance has its
# own mapper profile and must not route through bank-shaped financial_sector.
FINANCIAL_SECTOR_TOKENS = (
    "financial",
    "bank",
    "capital markets",
    "thrift",
    "mortgage",
    "diversified financials",
)

FINANCIAL_RULE_SKIP_TOKENS = FINANCIAL_SECTOR_TOKENS + INSURANCE_SECTOR_TOKENS

RULES = [
    # ------------------------------------------------------------------
    # Gross margin: must be 0-100 % for non-financials.
    # Banks and insurers legitimately have no Cost of Revenue line; they
    # must never be flagged for a missing or zero gross margin.
    # ------------------------------------------------------------------
    {
        "id": "gross_margin_range",
        "description": "Gross margin (Gross Profit / Revenue) must be between 0 % and 100 %",
        "severity": "warn",
        "check_type": "ratio_range",
        "params": {
            "numerator": "gross_profit",
            "denominator": "revenue",
            "min": 0.0,
            "max": 1.0,
        },
        "sector_skip": FINANCIAL_RULE_SKIP_TOKENS,
        "requires_fields": ["gross_profit", "revenue"],
    },

    # ------------------------------------------------------------------
    # Net margin ceiling: above 60 % is unusual and worth reviewing.
    # Info-level only -- some software/IP-heavy companies legitimately
    # approach or exceed this in high-margin quarters.
    # ------------------------------------------------------------------
    {
        "id": "net_margin_ceiling",
        "description": "Net margin (Net Income / Revenue) above 60 % is unusual",
        "severity": "info",
        "check_type": "ratio_range",
        "params": {
            "numerator": "net_income",
            "denominator": "revenue",
            "min": None,    # no lower-bound check
            "max": 0.60,
        },
        "sector_skip": (),
        "requires_fields": ["net_income", "revenue"],
    },

    # ------------------------------------------------------------------
    # Revenue reconciliation: Revenue - Cost of Revenue ? Gross Profit.
    # Skipped for financials (no CoR) and when CoR is absent in the data.
    # ------------------------------------------------------------------
    {
        "id": "revenue_reconciliation",
        "description": "Revenue - Cost of Revenue should equal Gross Profit within 1 %",
        "severity": "warn",
        "check_type": "arithmetic_reconciliation",
        "params": {
            "a": "revenue",
            "b": "cost_of_revenue",
            "c": "gross_profit",
            "tolerance": 0.01,
        },
        "sector_skip": FINANCIAL_RULE_SKIP_TOKENS,
        "requires_fields": ["revenue", "cost_of_revenue", "gross_profit"],
    },

    # ------------------------------------------------------------------
    # Fiscal-year recency: resolved FY must be within 2 years of filing
    # date.  A lag > 2 years almost certainly means the wrong concept
    # was matched (catches the FY2010 bug before it reaches the user).
    # ------------------------------------------------------------------
    {
        "id": "fiscal_year_recency",
        "description": "Resolved fiscal year should be within 2 years of the filing date",
        "severity": "warn",
        "check_type": "year_recency",
        "params": {"max_lag": 2},
        "sector_skip": (),
        "requires_fields": ["fiscal_year_int", "filing_year_int"],
    },

    # ------------------------------------------------------------------
    # Revenue growth sanity: YoY growth outside -50 % to +100 % is
    # unusual enough to flag.  Info-level -- hyper-growth and revenue
    # restatements are real, but 289 % growth almost always indicates
    # a mapping error.
    # ------------------------------------------------------------------
    {
        "id": "revenue_growth_sanity",
        "description": "Year-over-year revenue growth outside -50 % to +100 % is unusual",
        "severity": "info",
        "check_type": "growth_range",
        "params": {
            "field": "revenue",
            "prior_field": "revenue_prior",
            "min": -0.50,
            "max": 1.00,
        },
        "sector_skip": (),
        "requires_fields": ["revenue", "revenue_prior"],
    },

    # ------------------------------------------------------------------
    # SEDAR extraction confidence: mapped fields below this confidence are
    # uncertain reads from the filing. Provisional threshold -- open tuning
    # item, calibrate during validation campaign.
    # ------------------------------------------------------------------
    {
        "id": "sedar_extraction_confidence",
        "description": "SEDAR mapped fields should meet the minimum extraction confidence",
        "severity": "warn",
        "check_type": "extraction_confidence",
        "params": {
            "min": 0.85,
        },
        "sector_skip": (),
        "requires_fields": ["mapping"],
        "sedar_only": True,
    },

    # ------------------------------------------------------------------
    # SEDAR mapping confidence: pattern matches are informational uncertain
    # mappings, distinct from extraction-confidence uncertain reads.
    # ------------------------------------------------------------------
    {
        "id": "sedar_mapping_pattern_match",
        "description": "SEDAR pattern-matched fields are informational mapping-confidence notes",
        "severity": "info",
        "check_type": "mapping_pattern_info",
        "params": {},
        "sector_skip": (),
        "requires_fields": ["mapping"],
        "sedar_only": True,
    },

    # ------------------------------------------------------------------
    # SEDAR balance-sheet identity: canonical mapped total_assets must
    # equal the filing's own combined liabilities-and-equity line. Missing
    # combined lines are logged as honest field_unavailable skips.
    # ------------------------------------------------------------------
    {
        "id": "sedar_total_assets_identity",
        "description": "SEDAR total assets should equal total liabilities and equity",
        "severity": "warn",
        "check_type": "total_assets_identity",
        "params": {
            "absolute_tolerance": 0.5,
        },
        "sector_skip": (),
        "requires_fields": ["total_assets", "total_liabilities_and_equity"],
        "sedar_only": True,
    },

    # ------------------------------------------------------------------
    # Accounting standard is informational only. The engine records it so
    # future cross-validation thresholds can become standard-aware.
    # ------------------------------------------------------------------
    {
        "id": "accounting_standard_recorded",
        "description": "Filing accounting standard is recorded for future standard-aware checks",
        "severity": "info",
        "check_type": "accounting_standard_info",
        "params": {},
        "sector_skip": (),
        "requires_fields": ["accounting_standard"],
        "sedar_only": True,
    },
]
