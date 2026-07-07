"""
SEDAR statement period-column selection (CB-016, ratified 2026-07-06).

Extracted from app.py so the period picker is testable (importing app.py
executes the Streamlit script). Two consumers of the same extracted
statements used to pick period columns independently:

  - this layer (statement rows + fiscal_year label shown in the app), which
    sorted columns by (year, -index) — on a mixed-period Q4 pack the
    QUARTERLY column sorts first;
  - the canonical mapper's column picker (_mapper_source_value), which
    prefers "year ended"-labeled columns.

On CNQ FY2024 that divergence put quarterly revenue (Product sales 11,064)
in the row layer while mapping.mapped stayed annual (41,509), and picked
"Year Ended Dec 31 2024" — the SAME fiscal year — as the prior column
(the degenerate-prior shape the PLD XBRL bug had on the EDGAR path).

CB-016 ruling 1: this picker now carries the SAME annual preference as the
mapper — among "year(s) ended"/"year "-labeled columns, newest year is
current and second-newest is prior — so the row layer, mapped layer,
fiscal_year label, and analysis-cache key agree by construction. Columns
with no annual labels (balance-sheet instant dates, bare labels) keep the
original behavior unchanged. When only ONE annual column exists, prior is
None rather than a quarterly column — a mixed-period prior would be the
exact wrong-class comparison this ruling removes.
"""
from __future__ import annotations

import re


def _is_annual_period_label(label: str) -> bool:
    """Mirror of the mapper-side annual predicate (_mapper_source_value in
    scripts/build_filing_registry.py) — keep these in agreement."""
    text = str(label or "").lower()
    return (
        "year ended" in text
        or "years ended" in text
        or text.startswith("year ")
    )


def sedar_period_keys(items: list[dict]) -> tuple[str, str | None]:
    for item in items or []:
        values = item.get("values") or {}
        if isinstance(values, dict) and values:
            keys = list(values.keys())
            years = []
            for idx, key in enumerate(keys):
                match = re.search(r"(\d{4})", str(key))
                years.append((int(match.group(1)) if match else None, idx, key))
            parseable = [row for row in years if row[0] is not None]
            # CB-016: annual-labeled columns win outright, mirroring the
            # canonical mapper. Prior comes only from annual columns.
            annual = [row for row in parseable if _is_annual_period_label(row[2])]
            if annual:
                ordered = sorted(annual, key=lambda row: (row[0], -row[1]), reverse=True)
                current = ordered[0][2]
                prior = ordered[1][2] if len(ordered) > 1 else None
                return current, prior
            if parseable:
                ordered = sorted(parseable, key=lambda row: (row[0], -row[1]), reverse=True)
                current = ordered[0][2]
                prior = ordered[1][2] if len(ordered) > 1 else None
                return current, prior
            current = keys[0]
            prior = keys[1] if len(keys) > 1 else None
            return current, prior
    return "Current", None


def sedar_statement_rows(items: list[dict], current_period: str, prior_period: str | None) -> list[dict]:
    rows = []
    for item in items or []:
        values = item.get("values") or {}
        if not isinstance(values, dict):
            values = {}
        rows.append({
            "line_item": item.get("label", ""),
            "value": values.get(current_period),
            "value_prior": values.get(prior_period) if prior_period else None,
            "row_type": "data",
        })
    return rows
