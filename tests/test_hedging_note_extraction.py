"""Hedging-book note extraction — stage-1 pins (design: docs/HEDGING_BOOK_SPEC.md).

Locator pins run against the REAL Peyto/TOU/CNQ PDFs on Riley's machine and
skip honestly on CI (no PDFs there). The normalization and figure-presence
pins are pure functions over transcribed real table rows — they run
everywhere and double as schema documentation.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sedar_extractor import (
    _hedging_figure_presence,
    _locate_derivative_note_pages_from_texts,
    _normalize_hedging_payload,
    locate_derivative_note_pages,
)

PEYTO_PDF = Path(r"C:\Users\riley\.finlens\pdfs\_cache\PEY_TO_2025.pdf")
TOU_PDF = Path(r"C:\Users\riley\.finlens\pdfs\TOU_FY2025.pdf")
CNQ_PDF = Path(r"C:\Users\riley\.finlens\pdfs\CNQ_FY2024.pdf")


# ---------------------------------------------------------------------------
# Locator — real-PDF pins (skip when the canonical PDFs are absent, e.g. CI)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not PEYTO_PDF.exists(), reason="canonical Peyto PDF not on this machine")
def test_locator_finds_peyto_note_pages_exactly():
    # Peyto FY2025 Note 13 spans pages 24-26 (ground-truthed 2026-07-11).
    assert locate_derivative_note_pages(str(PEYTO_PDF)) == [24, 25, 26]


@pytest.mark.skipif(not TOU_PDF.exists(), reason="canonical TOU PDF not on this machine")
def test_locator_finds_tou_note_pages_exactly():
    # TOU FY2025 derivative note spans PDF pages 64-65 (bank research + ground-truth).
    assert locate_derivative_note_pages(str(TOU_PDF)) == [64, 65]


@pytest.mark.skipif(not CNQ_PDF.exists(), reason="canonical CNQ PDF not on this machine")
def test_locator_finds_cnq_financial_instruments_note():
    # CNQ FY2024 "16. FINANCIAL INSTRUMENTS" is PDF page 17.
    assert 17 in locate_derivative_note_pages(str(CNQ_PDF))


def test_locator_pure_function_negative_and_positive():
    # Prose page with derivative vocabulary but no table signals: no hit.
    prose = ("The Company uses swaps and collars to manage derivative exposure. "
             "Notional amounts are reviewed quarterly. " + "1 2 3 4 5 6 7 8 9 10 11")
    # Table page: vocabulary + volume/price signal + numbers.
    table = ("Fixed Price swaps collars derivative\n"
             "Period Hedged Type Daily Volume (GJ) (CAD/GJ)\n"
             "Q1 2026 Fixed Price 240,000 $4.17\n"
             "Q2 2026 Fixed Price 217,500 $3.29\n"
             "Q3 2026 Fixed Price 217,500 $3.29\n"
             "Q4 2026 Fixed Price 214,185 $3.44\n")
    assert _locate_derivative_note_pages_from_texts([prose, table]) == [1]


# ---------------------------------------------------------------------------
# Schema normalization — transcribed real rows (both geometries)
# ---------------------------------------------------------------------------

def test_normalize_peyto_style_fixed_price_row():
    payload = {
        "as_of": "December 31, 2025",
        "commodity_positions": [{
            "commodity": "natural_gas", "index": "AECO 7A Monthly",
            "instrument": "fixed_price_swap", "period_label": "Q1 2026",
            "period_start_year": 2026, "volume": "240,000", "volume_unit": "GJ/d",
            "price": "$4.17", "price_floor": None, "price_ceiling": None,
            "price_unit": "CAD/GJ", "fair_value": None, "source_page": 24,
            "verbatim_notes": None,
        }],
        "extraction_confidence": 0.95,
    }
    book = _normalize_hedging_payload(payload)
    pos = book["commodity_positions"][0]
    assert pos["volume"] == 240_000          # comma-string parsed
    assert pos["price"] == 4.17              # $ stripped
    assert pos["index"] == "AECO 7A Monthly" # verbatim preserved
    assert book["as_of"] == "December 31, 2025"
    assert book["extraction_confidence"] == 0.95


def test_normalize_tou_style_year_column_row_with_fair_value():
    payload = {
        "fair_value_total": "223,703",
        "fair_value_scale": "thousands",
        "commodity_positions": [{
            "commodity": "natural_gas", "index": "NYMEX",
            "instrument": "swap", "period_label": "2026",
            "period_start_year": 2026, "volume": "60,000", "volume_unit": "mmbtu/d",
            "price": "4.14", "price_unit": "USD/MMBtu",
            "fair_value": "17,379", "source_page": 64,
        }],
    }
    book = _normalize_hedging_payload(payload)
    assert book["fair_value_total"] == 223_703
    assert book["commodity_positions"][0]["fair_value"] == 17_379


def test_normalize_collar_keeps_floor_and_ceiling():
    payload = {
        "commodity_positions": [{
            "commodity": "oil", "index": "WTI CAD", "instrument": "collar",
            "period_label": "Q1 2026", "period_start_year": 2026,
            "volume": 500, "volume_unit": "bbls/d",
            "price": None, "price_floor": "$85.00", "price_ceiling": "$100.00",
            "price_unit": "CAD/bbl", "source_page": 25,
        }],
    }
    pos = _normalize_hedging_payload(payload)["commodity_positions"][0]
    assert pos["price"] is None
    assert pos["price_floor"] == 85.0
    assert pos["price_ceiling"] == 100.0


def test_normalize_negative_fair_value_parenthesized():
    # TOU NYMEX financial call options: fair value $(8,261) thousands.
    payload = {
        "commodity_positions": [{
            "commodity": "natural_gas", "index": "NYMEX", "instrument": "call_option",
            "period_label": "2026", "volume": 74_932, "volume_unit": "mmbtu/d",
            "price": 8.07, "price_unit": "USD/MMBtu",
            "fair_value": "(8,261)", "source_page": 64,
        }],
    }
    assert _normalize_hedging_payload(payload)["commodity_positions"][0]["fair_value"] == -8_261


def test_normalize_empty_payload_is_honest():
    book = _normalize_hedging_payload({})
    assert book["commodity_positions"] == []
    assert book["fair_value_total"] is None
    assert book["extraction_confidence"] == 0.0


# ---------------------------------------------------------------------------
# Figure-presence guard — fabricated values must be counted, never silent
# ---------------------------------------------------------------------------

NOTE_TEXT = ("Q1 2026 Fixed Price 240,000 $4.17\n"
             "Had these contracts closed on December 31, 2025, Peyto would have "
             "realized a gain in the amount of $123.3 million.")


def test_figure_presence_all_found():
    book = _normalize_hedging_payload({
        "commodity_positions": [{"volume": 240_000, "price": 4.17, "source_page": 24}],
        "mtm_disclosures": [{"scope": "commodity", "amount": 123.3, "verbatim": "...", "source_page": 24}],
    })
    fp = _hedging_figure_presence(book, NOTE_TEXT)
    assert fp["checked"] == 3
    assert fp["missing_count"] == 0


def test_figure_presence_flags_fabricated_value():
    book = _normalize_hedging_payload({
        "commodity_positions": [{"volume": 999_999, "price": 4.17, "source_page": 24}],
    })
    fp = _hedging_figure_presence(book, NOTE_TEXT)
    assert fp["missing_count"] == 1
    assert "999999" in fp["missing"][0]
