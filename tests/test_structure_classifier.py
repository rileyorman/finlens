"""Structural-subtotal classifier — Stage 0 pins
(design: docs/STRUCTURAL_SUBTOTAL_SPEC.md, ratified 2026-07-12).

The centerpiece is the REAL Peyto FY2025 balance-sheet shape (values in
filing thousands, transcribed from the ground-truthed cold-load analysis):
every genuine subtotal must classify, the grand totals must classify as
totals, and the extractor-invented "Total liabilities" on the non-current
block (CB-033) must surface as a label-vs-structure CONTRADICTION — while
the legitimate "Total equity" block subtotal stays clean.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.integrity.structure import (
    STRUCTURE_DATA,
    STRUCTURE_SUBTOTAL,
    STRUCTURE_TOTAL,
    classify_statement_structure,
)


def _row(label, value, prior=None):
    values = {"2025": value}
    if prior is not None:
        values["2024"] = prior
    return {"label": label, "values": values}


PEYTO_BALANCE_SHEET = [
    _row("Cash", 51_057),
    _row("Accounts receivable (Note 11)", 163_870),
    _row("Prepaid and other", 33_688),
    _row("Derivative financial instruments (Note 13)", 111_682),
    _row("Current assets", 360_297),                     # unlabeled in print; block subtotal
    _row("Long-term derivative financial instruments (Note 13)", 11_969),
    _row("Property, plant and equipment, net (Note 3)", 5_087_126),
    _row("Total non-current assets", 5_099_095),         # qualified label; block subtotal
    _row("Total assets", 5_459_392),                     # grand total of 2 subtotals
    _row("Accounts payable and accrued liabilities", 192_810),
    _row("Deferred other income", 4_731),
    _row("Dividends payable (Note 6)", 22_368),
    _row("Income tax payable (Note 12)", 32_010),
    _row("Current portion of lease obligation", 991),
    _row("Current portion of decommissioning provision (Note 5)", 13_000),
    _row("Current portion of long-term debt (Note 4)", 100_000),
    _row("Current liabilities", 365_910),                # block subtotal
    _row("Long-term debt (Note 4)", 1_074_273),
    _row("Decommissioning provision (Note 5)", 299_483),
    _row("Lease obligation", 6_572),
    _row("Deferred income taxes (Note 12)", 861_420),
    _row("Total liabilities", 2_241_748),                # CB-033: invented label, NON-current block only
    _row("Shareholders' capital (Note 6)", 2_067_782),
    _row("Contributed surplus (Note 10)", 26_170),
    _row("Retained earnings", 660_918),
    _row("Accumulated other comprehensive income", 96_864),
    _row("Total equity", 2_851_734),                     # legitimate block subtotal
    _row("Total liabilities and equity", 5_459_392),     # grand total of 3 subtotals
]


def _by_label(rows, annotations):
    return {row["label"]: ann for row, ann in zip(rows, annotations)}


def test_peyto_shape_every_real_subtotal_and_total_classifies():
    ann = _by_label(PEYTO_BALANCE_SHEET,
                    classify_statement_structure(PEYTO_BALANCE_SHEET))
    assert ann["Current assets"]["structure"] == STRUCTURE_SUBTOTAL
    assert ann["Total non-current assets"]["structure"] == STRUCTURE_SUBTOTAL
    assert ann["Total assets"]["structure"] == STRUCTURE_TOTAL
    assert ann["Current liabilities"]["structure"] == STRUCTURE_SUBTOTAL
    assert ann["Total equity"]["structure"] == STRUCTURE_SUBTOTAL
    assert ann["Total liabilities and equity"]["structure"] == STRUCTURE_TOTAL
    # Plain data rows stay data.
    assert ann["Cash"]["structure"] == STRUCTURE_DATA
    assert ann["Long-term debt (Note 4)"]["structure"] == STRUCTURE_DATA


def test_peyto_cb033_invented_total_liabilities_is_a_contradiction():
    ann = _by_label(PEYTO_BALANCE_SHEET,
                    classify_statement_structure(PEYTO_BALANCE_SHEET))
    tl = ann["Total liabilities"]
    assert tl["structure"] == STRUCTURE_SUBTOTAL      # arithmetic: non-current block only
    assert tl["structure_conflict"] is True           # label claims the grand total
    assert "liabilities" in tl["conflict_note"]
    # The legitimate unqualified block totals stay clean.
    assert ann["Total equity"]["structure_conflict"] is False
    assert ann["Total non-current assets"]["structure_conflict"] is False


def test_true_grand_total_liabilities_is_clean():
    """A filer that PRINTS current + non-current subtotals and a true grand
    total: 'Total liabilities' ties as the sum of subtotals -> TOTAL, no
    conflict (the honest counterpart to the Peyto case)."""
    rows = [
        _row("Accounts payable", 100),
        _row("Short-term debt", 200),
        _row("Total current liabilities", 300),
        _row("Long-term debt", 400),
        _row("Deferred taxes", 500),
        _row("Total non-current liabilities", 900),
        _row("Total liabilities", 1_200),
    ]
    ann = _by_label(rows, classify_statement_structure(rows))
    assert ann["Total liabilities"]["structure"] == STRUCTURE_TOTAL
    assert ann["Total liabilities"]["structure_conflict"] is False


def test_memo_line_degrades_to_honest_non_classification():
    """A memo row inside the block breaks the tie -> the subtotal stays
    'data' (recall bias: never a wrong classification)."""
    rows = [
        _row("Trade receivables", 100),
        _row("Other receivables", 200),
        _row("of which: past due", 5),   # memo line, outside the printed sum
        _row("Total receivables", 300),
    ]
    ann = _by_label(rows, classify_statement_structure(rows))
    assert ann["Total receivables"]["structure"] == STRUCTURE_DATA


def test_rounding_tolerance_ties():
    rows = [
        _row("Segment A", 100.2),
        _row("Segment B", 200.3),
        _row("Total segments", 300.4),   # off by 0.1, within tolerance
    ]
    ann = _by_label(rows, classify_statement_structure(rows))
    assert ann["Total segments"]["structure"] == STRUCTURE_SUBTOTAL


def test_multi_period_disagreement_degrades_to_data():
    """Ties in 2025 but not 2024 -> honest 'data' (multi-period agreement
    required; a single-column coincidence must not classify)."""
    rows = [
        _row("A", 100, prior=100),
        _row("B", 200, prior=200),
        _row("Coincidence", 300, prior=999),
    ]
    ann = _by_label(rows, classify_statement_structure(rows))
    assert ann["Coincidence"]["structure"] == STRUCTURE_DATA


def test_multi_period_agreement_classifies():
    rows = [
        _row("A", 100, prior=110),
        _row("B", 200, prior=220),
        _row("Total", 300, prior=330),
    ]
    ann = _by_label(rows, classify_statement_structure(rows))
    assert ann["Total"]["structure"] == STRUCTURE_SUBTOTAL


def test_rows_without_numeric_values_stay_data():
    rows = [
        _row("Header", None),
        _row("A", 100),
        _row("B", 200),
        _row("Total", 300),
    ]
    ann = classify_statement_structure(rows)
    assert ann[0]["structure"] == STRUCTURE_DATA
    assert ann[3]["structure"] == STRUCTURE_SUBTOTAL


# ---------------------------------------------------------------------------
# Stage 1 wiring — attach_mapping annotation + the integrity rule
# ---------------------------------------------------------------------------

def test_attach_mapping_annotates_rows_and_line_items():
    from sedar_extractor import attach_mapping

    extraction = {
        "accounting_standard": "IFRS",
        "sector_inferred": "Upstream Oil & Gas",
        "statements": {
            "balance_sheet": [
                {"label": "Cash", "values": {"2025": 100}, "confidence": 0.9},
                {"label": "Receivables", "values": {"2025": 200}, "confidence": 0.9},
                {"label": "Current assets", "values": {"2025": 300}, "confidence": 0.9},
            ],
            "income_statement": [],
            "cash_flow": [],
        },
    }
    enriched = attach_mapping(extraction)
    rows = enriched["statements"]["balance_sheet"]
    assert rows[2]["structure"] == STRUCTURE_SUBTOTAL
    assert rows[0]["structure"] == STRUCTURE_DATA
    # The input extraction is never mutated (new row dicts).
    assert "structure" not in extraction["statements"]["balance_sheet"][0]


def _normalized_row(label, value, prior=None):
    return {"line_item": label, "value": value, "value_prior": prior,
            "row_type": "data"}


PEYTO_NORMALIZED_LIABILITIES = [
    _normalized_row("Accounts payable and accrued liabilities", 192_810_000),
    _normalized_row("Dividends payable", 22_368_000),
    _normalized_row("Income tax payable", 32_010_000),
    _normalized_row("Current portion of lease obligation", 991_000),
    _normalized_row("Current portion of decommissioning provision", 13_000_000),
    _normalized_row("Current portion of long-term debt", 100_000_000),
    _normalized_row("Deferred other income", 4_731_000),
    _normalized_row("Current liabilities", 365_910_000),
    _normalized_row("Long-term debt", 1_074_273_000),
    _normalized_row("Decommissioning provision", 299_483_000),
    _normalized_row("Lease obligation", 6_572_000),
    _normalized_row("Deferred income taxes", 861_420_000),
    _normalized_row("Total liabilities", 2_241_748_000),  # CB-033 invented label
]


def test_integrity_rule_warns_on_peyto_shape():
    from modules.integrity.engine import validate_filing

    data = {
        "income_statement": [], "cash_flow_statement": [],
        "balance_sheet": PEYTO_NORMALIZED_LIABILITIES,
        "mapping": {"mapped": {}, "meta": {}},
    }
    result = validate_filing(data, "PEY.TO", "Energy")
    check = {c.rule_id: c for c in result.checks}["structure_label_contradiction"]
    assert not check.skipped
    assert check.passed is False
    assert "Total liabilities" in check.message


def test_integrity_rule_passes_on_clean_statements():
    from modules.integrity.engine import validate_filing

    data = {
        "income_statement": [], "cash_flow_statement": [],
        "balance_sheet": [
            _normalized_row("Accounts payable", 100),
            _normalized_row("Short-term debt", 200),
            _normalized_row("Total current liabilities", 300),
            _normalized_row("Long-term debt", 400),
            _normalized_row("Deferred taxes", 500),
            _normalized_row("Total non-current liabilities", 900),
            _normalized_row("Total liabilities", 1_200),
        ],
        "mapping": {"mapped": {}, "meta": {}},
    }
    result = validate_filing(data, "CLEAN", "Energy")
    check = {c.rule_id: c for c in result.checks}["structure_label_contradiction"]
    assert not check.skipped
    assert check.passed is True


def test_integrity_rule_skips_without_statements():
    from modules.integrity.engine import validate_filing

    result = validate_filing({"mapping": {"mapped": {}, "meta": {}}}, "X", None)
    check = {c.rule_id: c for c in result.checks}["structure_label_contradiction"]
    assert check.skipped
    assert check.skip_reason == "field_unavailable"
