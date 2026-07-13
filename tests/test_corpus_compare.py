"""CB-043 pins — corpus_revenue_note (as-filed EDGAR quick figures compared
against the validated SEDAR corpus for the same filer + fiscal year).

Pinned against the REAL CI-locked registry + fixtures deliberately: the
flagship case is CNQ FY2024, where the corpus canonical revenue is the
GROSS "Product sales" 41,509M CAD (2026-06-17 ground-truth decision) and
the ifrs-full:Revenue line is the NET 35,656M — the note must say DIFFERS.
If the corpus fixture ever changes, this pin SHOULD move with it.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.integrity.corpus_compare import corpus_revenue_note


def _edgar_fd(**over):
    fd = {
        "fiscal_year": "FY2025",
        "revenue": 38_762_000_000.0,
        "fiscal_year_prior": "FY2024",
        "revenue_prior": 35_656_000_000.0,
        "currency": "CAD",
    }
    fd.update(over)
    return fd


def test_cnq_net_vs_corpus_gross_differs_on_the_prior_year():
    """CNQ: corpus year is FY2024 (gross 41,509M); EDGAR's FY2024 sits in
    the PRIOR column — the note must check every emitted year."""
    note = corpus_revenue_note("CNQ", _edgar_fd())
    assert note is not None
    assert note["status"] == "differs"
    assert note["fiscal_year"] == "FY2024"
    assert note["corpus_value_raw"] == 41_509_000_000.0
    assert note["corpus_label"] == "Product sales"
    assert note["corpus_currency"] == "CAD"


def test_matching_value_ties_within_tolerance():
    note = corpus_revenue_note(
        "CNQ", _edgar_fd(revenue_prior=41_509_000_000.0)
    )
    assert note is not None and note["status"] == "ties"


def test_currency_mismatch_is_incomparable_never_compared():
    note = corpus_revenue_note("CNQ", _edgar_fd(currency="USD"))
    assert note is not None and note["status"] == "incomparable_currency"


def test_no_corpus_mapping_returns_none():
    assert corpus_revenue_note("NVDA", _edgar_fd()) is None
    assert corpus_revenue_note("", _edgar_fd()) is None
    assert corpus_revenue_note("CNQ", None) is None


def test_no_shared_fiscal_year_returns_none():
    fd = _edgar_fd(fiscal_year="FY2030", fiscal_year_prior="FY2029")
    assert corpus_revenue_note("CNQ", fd) is None


def test_base_ticker_matches_class_suffixed_corpus_entry():
    """NYSE 'TECK' must find the corpus 'TECK.B' FY2025 entry."""
    import json
    fixture = json.loads(
        (Path(__file__).resolve().parents[1] / "tests/fixtures/TECKB_FY2025_sedar.json")
        .read_text(encoding="utf-8")
    )
    corpus_val = fixture["mapping"]["mapped"]["revenue"]["value"]
    scale = {"millions": 1e6, "thousands": 1e3}[fixture["scale"]]
    fd = _edgar_fd(
        fiscal_year="FY2025",
        revenue=corpus_val * scale,
        currency=fixture["currency"],
        fiscal_year_prior="FY2024",
        revenue_prior=None,
    )
    note = corpus_revenue_note("TECK", fd)
    assert note is not None
    assert note["corpus_ticker"] == "TECK.B"
    assert note["status"] == "ties"
