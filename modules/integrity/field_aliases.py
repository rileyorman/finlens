"""
FinLens shared headline-field alias table.

Single source of truth for the five v1 canonical headline fields and
their as-filed label aliases.  Both the prior-column continuity checker
(modules/integrity/prior_column.py) and the candidate review runner
(scripts/review_candidates.py) import from here.

Why here?  Two independent copies drifted immediately: prior_column.py
had three capex aliases that review_candidates.py was missing.  One
table prevents that class of divergence.

Alias evidence notes
--------------------
Labels marked "IFRS: IMO FY2025" come from the Imperial Oil FY2025
annual-report extraction (bundle ingest/IMO-FY2025, guard PASS,
ratio=1.0, 63/63 figures verified).  Only labels with direct filing
evidence are listed; no speculative aliases.
"""
from __future__ import annotations

# v1 canonical fields in output order
HEADLINE_FIELDS: list[str] = [
    "revenue",
    "net_income",
    "total_assets",
    "operating_cash_flow",
    "capex",
]

# Statement key that holds each canonical field
FIELD_STATEMENT: dict[str, str] = {
    "revenue":             "income_statement",
    "net_income":          "income_statement",
    "total_assets":        "balance_sheet",
    "operating_cash_flow": "cash_flow_statement",
    "capex":               "cash_flow_statement",
}

# Alias lists for as-filed label resolution (statement-row scan fallback).
# Rules:
#   - Add ONLY labels we have direct filing evidence for.
#   - Do NOT add speculative aliases.
#   - Annotate new aliases with the evidence source.
FIELD_ALIASES: dict[str, list[str]] = {
    "revenue": [
        "Revenues",
        "Revenue",
    ],
    "net_income": [
        "Net Income",
        "Net income",
        "Net income (loss)",                              # IFRS: IMO FY2025
    ],
    "total_assets": [
        "Assets",
        "Total Assets",
        "Total assets",
    ],
    "operating_cash_flow": [
        "Net Cash Provided by Operating Activities",
        "Net Cash from Operating Activities",
        "Cash flows from (used in) operating activities",  # IFRS: IMO FY2025
    ],
    "capex": [
        "Capital Expenditures",
        "Purchases of Property, Plant and Equipment",
        "Purchase of property and equipment",
        "Additions to property, plant and equipment",     # IFRS: IMO FY2025 (also prior_column.py v1)
        "Capital expenditures",
    ],
}
