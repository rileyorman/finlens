"""Pins for sector_quote_note (2026-07-13) — the tracker's sector quote-basis
disclosure, grounded in the docs/research/ coverage-gap reports: the number
the market quotes per sector is a company-defined non-GAAP measure outside
the statements. Notes DISCLOSE the basis; they never serve values (Arc 3,
CB-036-gated). Classification is conservative: unknown → None, never a guess.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.stock_tracker import sector_quote_note


def test_og_upstream_notes_funds_flow_not_fcf():
    note = sector_quote_note("Energy", "Oil & Gas E&P")
    assert note is not None
    assert "EV/DACF" in note["valuation"]
    assert "FUNDS FLOW" in note["cashflow"]
    # Integrated majors get the same upstream basis
    assert sector_quote_note("Energy", "Oil & Gas Integrated") is note


def test_og_midstream_notes_dcf_payout():
    note = sector_quote_note("Energy", "Oil & Gas Midstream")
    assert note is not None
    assert "distributable-cash-flow" in note["valuation"]


def test_reit_notes_p_ffo_and_definitional_variance():
    note = sector_quote_note("Real Estate", "REIT - Retail")
    assert note is not None
    assert "P/FFO" in note["valuation"]
    assert "NAREIT" in note["valuation"]


def test_bank_notes_no_ev_and_no_cashflow_note():
    note = sector_quote_note("Financial Services", "Banks - Diversified")
    assert note is not None
    assert "ROE/ROTE" in note["valuation"]
    assert note["cashflow"] is None


def test_miner_notes_aisc_with_cost_basis_variance():
    note = sector_quote_note("Basic Materials", "Gold")
    assert note is not None
    assert "AISC" in note["valuation"]
    assert "by-product" in note["valuation"]


def test_unrecognized_sectors_get_no_note_never_a_guess():
    assert sector_quote_note("Technology", "Semiconductors") is None
    assert sector_quote_note(None, None) is None
    assert sector_quote_note("Basic Materials", "Specialty Chemicals") is None
    # Insurance deliberately not covered yet (research did not ground it)
    assert sector_quote_note("Financial Services", "Insurance - Property & Casualty") is None
