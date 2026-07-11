"""CB-034 pins — derivative-gains concentration flag + hedging fair-value tie.

Values are the real Peyto FY2025 / TOU FY2025 figures (cold-load drill +
hedging-book design session, 2026-07-11), so the pins double as concept
documentation.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.integrity.engine import (
    _check_hedging_fair_value_tie,
    _hedging_bs_derivative_net_raw,
    _hedging_note_fair_value_raw,
)
from modules.red_flag_detector import detect_flags


# ---------------------------------------------------------------------------
# Red flag: derivative-gains concentration (yellow >= 25%, red >= 50%)
# ---------------------------------------------------------------------------

def _flag_ids(result: dict) -> list[str]:
    return [f["label"] for f in result["flags"]]


def test_peyto_46_percent_concentration_fires_yellow():
    fd = {"realized_derivative_gains": 248_737, "pretax_income": 535_822,
          "income_statement": []}
    result = detect_flags(fd)
    hits = [f for f in result["flags"] if "derivative" in f["label"].lower()]
    assert len(hits) == 1
    assert hits[0]["severity"] == "yellow"
    assert "46%" in hits[0]["detail"]


def test_majority_derivative_earnings_fires_red():
    fd = {"realized_derivative_gains": 300, "pretax_income": 500,
          "income_statement": []}
    result = detect_flags(fd)
    hits = [f for f in result["flags"] if "derivative" in f["label"].lower()]
    assert hits and hits[0]["severity"] == "red"


def test_concentration_skips_honestly_when_unmapped():
    # Field absent (non-resource filer, or line not aliased) — no flag, no crash.
    result = detect_flags({"pretax_income": 535_822, "income_statement": []})
    assert not [f for f in result["flags"] if "derivative" in f["label"].lower()]


def test_concentration_skips_on_pretax_loss():
    # Ratio against a loss denominator is meaningless — honest skip.
    fd = {"realized_derivative_gains": 100, "pretax_income": -50,
          "income_statement": []}
    result = detect_flags(fd)
    assert not [f for f in result["flags"] if "derivative" in f["label"].lower()]


# ---------------------------------------------------------------------------
# Integrity tie: note fair value vs balance-sheet derivative rows
# ---------------------------------------------------------------------------

PEYTO_BOOK = {
    "status": "extracted",
    "fair_value_total": None,
    "fair_value_scale": None,
    "mtm_disclosures": [
        {"scope": "commodity", "amount": 123.3, "amount_unit": "CAD millions"},
        {"scope": "fx", "amount": 0.7, "amount_unit": "CAD millions"},
        {"scope": "interest_rate", "amount": -0.3, "amount_unit": "CAD millions"},
    ],
}

PEYTO_BS_ROWS = [
    # Rows are raw dollars at engine time (scaled at the boundary).
    {"line_item": "Derivative financial instruments (Note 13)", "value": 111_682_000},
    {"line_item": "Long-term derivative financial instruments (Note 13)", "value": 11_969_000},
    {"line_item": "Accounts receivable (Note 11)", "value": 163_870_000},
]


def test_peyto_note_fair_value_sums_mtm_in_raw_dollars():
    assert _hedging_note_fair_value_raw(PEYTO_BOOK) == 123_700_000  # 123.3+0.7-0.3 M


def test_tou_printed_total_preferred_over_mtm():
    book = {"status": "extracted", "fair_value_total": 223_703,
            "fair_value_scale": "thousands", "mtm_disclosures": []}
    assert _hedging_note_fair_value_raw(book) == 223_703_000


def test_unparseable_unit_returns_none_never_guesses():
    book = {"status": "extracted", "fair_value_total": 223_703,
            "fair_value_scale": None, "mtm_disclosures": []}
    assert _hedging_note_fair_value_raw(book) is None


def test_bs_net_matches_peyto_asset_only_shape():
    assert _hedging_bs_derivative_net_raw(PEYTO_BS_ROWS) == 123_651_000


def test_bs_liability_labeled_rows_subtract():
    rows = [
        {"line_item": "Risk management assets", "value": 100},
        {"line_item": "Risk management liabilities", "value": 30},
    ]
    assert _hedging_bs_derivative_net_raw(rows) == 70


def test_bs_ambiguous_tou_labels_do_not_match():
    # TOU's four identical "Fair value of financial instruments" rows carry
    # neither 'derivative' nor 'risk management' — honest None, rule skips.
    rows = [{"line_item": "Fair value of financial instruments", "value": v}
            for v in (181_352, 502_106, 45_676, 17_088)]
    assert _hedging_bs_derivative_net_raw(rows) is None


def test_tie_check_passes_on_peyto_values():
    rule = {"params": {"relative_tolerance": 0.05}}
    ctx = {"hedging_note_fair_value_raw": 123_700_000,
           "hedging_bs_derivative_net_raw": 123_651_000}
    observed, threshold, passed, message = _check_hedging_fair_value_tie(rule, ctx)
    assert passed
    assert observed < 0.001  # 0.04% gap


def test_tie_check_fails_on_large_gap():
    rule = {"params": {"relative_tolerance": 0.05}}
    ctx = {"hedging_note_fair_value_raw": 200_000_000,
           "hedging_bs_derivative_net_raw": 100_000_000}
    observed, threshold, passed, message = _check_hedging_fair_value_tie(rule, ctx)
    assert not passed
