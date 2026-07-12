"""MD&A operational-metrics locator — Stage 1 pins (design: docs/MDA_FETCHER_SPEC.md).

Locator pins run against the REAL O&G corpus PDFs on Riley's machine and skip
honestly on CI (no PDFs there). The pure-function pins encode the predicate's
load-bearing behaviors — above all the DOCUMENT-LEVEL ANCHOR GATE: a document
with no dense netback page has no O&G MD&A section and must yield ZERO pages
(honest no_mda_detected → the fetch-fallback lane), even when its statement
notes are signal-rich (WCP's capital-management note says "funds flow" 8x;
hedge notes carry volume units). Empirically tuned 2026-07-12 on five PDFs:
TOU (combined pack), ARX (full annual report), CNQ/Peyto/WCP (statements-only).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sedar_extractor import (
    MAX_MDA_PAGES,
    _locate_mda_pages_from_texts,
    locate_mda_pages,
)

TOU_PDF = Path(r"C:\Users\riley\.finlens\pdfs\TOU_FY2025.pdf")
ARX_PDF = Path(r"C:\Users\riley\.finlens\pdfs\ARX_FY2025.pdf")
CNQ_PDF = Path(r"C:\Users\riley\.finlens\pdfs\CNQ_FY2024.pdf")
PEY_PDF = Path(
    r"C:\Users\riley\.finlens\pdfs\_fetched"
    r"\Peyto_Exploration_Development_FY2025_annual_audited_financial_statements.pdf"
)
WCP_PDF = Path(
    r"C:\Users\riley\.finlens\pdfs\_fetched"
    r"\Whitecap_Resources_FY2025_annual_audited_financial_statements.pdf"
)


# ---------------------------------------------------------------------------
# Locator — real-PDF pins (skip when the canonical PDFs are absent, e.g. CI)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not TOU_PDF.exists(), reason="canonical TOU PDF not on this machine")
def test_locator_finds_tou_mda_pages_exactly():
    # TOU FY2025 combined pack (ground-truthed 2026-07-12): volumes pp. 7-8,
    # realized prices p. 11, per-boe costs p. 15, netback section pp. 19 +
    # 31-35; pp. 64-65 are the statements-side hedge note (accepted recall
    # bias, CB-034 mirror — the extraction prompt filters them).
    result = locate_mda_pages(str(TOU_PDF))
    assert result["pages"] == [7, 8, 11, 15, 19, 31, 32, 33, 34, 35, 64, 65]
    assert result["dropped_pages"] == []


@pytest.mark.skipif(not ARX_PDF.exists(), reason="canonical ARX PDF not on this machine")
def test_locator_finds_arx_netback_and_ffo_pages():
    # ARX FY2025 full annual report: the netback tables (pp. 29, 61) and the
    # FFO section (p. 62) must survive the score-ranked cap; the over-cap
    # remainder is disclosed, never silently dropped.
    result = locate_mda_pages(str(ARX_PDF))
    assert 29 in result["pages"]
    assert 61 in result["pages"]
    assert 62 in result["pages"]
    assert len(result["pages"]) == MAX_MDA_PAGES
    assert result["dropped_pages"]  # disclosed
    assert result["pages"] == sorted(result["pages"])


@pytest.mark.skipif(not CNQ_PDF.exists(), reason="canonical CNQ PDF not on this machine")
def test_locator_empty_on_cnq_statements_pack():
    result = locate_mda_pages(str(CNQ_PDF))
    assert result == {"pages": [], "dropped_pages": []}


@pytest.mark.skipif(not PEY_PDF.exists(), reason="fetched Peyto PDF not on this machine")
def test_locator_empty_on_peyto_statements_pack():
    result = locate_mda_pages(str(PEY_PDF))
    assert result == {"pages": [], "dropped_pages": []}


@pytest.mark.skipif(not WCP_PDF.exists(), reason="fetched WCP PDF not on this machine")
def test_locator_empty_on_wcp_statements_pack_despite_funds_flow_note():
    # THE motivating negative: WCP's capital-management note mentions "funds
    # flow" 8 times on one page — without the netback anchor gate the
    # locator would fire on a statements-only pack and suppress the honest
    # no_mda_detected that routes the filer to the fetch fallback.
    result = locate_mda_pages(str(WCP_PDF))
    assert result == {"pages": [], "dropped_pages": []}


# ---------------------------------------------------------------------------
# Locator — pure-function pins (run everywhere)
# ---------------------------------------------------------------------------

_NUMS = " ".join(str(n * 137) for n in range(1, 30))  # dense numeric filler

# A per-boe netback table page — the O&G MD&A signature (anchor + qualifier).
NETBACK_PAGE = (
    "Operating Netback ($/boe)\n"
    "Revenue 44.05 Royalties (4.34) Operating (5.00) Transportation (5.57)\n"
    "Operating netback 29.14 per boe\n"
    "Netback including hedging 30.02\n" + _NUMS
)

# A volumes table page — qualifies only once the document is anchored.
VOLUMES_PAGE = (
    "Average daily production\n"
    "Natural gas (mmcf/d) 1,533 Crude oil (bbls/d) 110,954\n"
    "Total (boe/d) 374,336 boe/d guidance boe/d\n" + _NUMS
)

# A capital-management-note page (WCP shape): funds-flow dense, no netback.
FUNDS_FLOW_NOTE_PAGE = (
    "Capital Management. Funds flow is a non-GAAP measure. funds flow\n"
    "funds flow funds from operations funds flow funds flow funds flow\n" + _NUMS
)

PROSE_PAGE = "Outlook remains strong. Netback improved. 1 2 3"


def test_anchored_document_collects_netback_and_volume_pages():
    result = _locate_mda_pages_from_texts([PROSE_PAGE, NETBACK_PAGE, VOLUMES_PAGE])
    assert result["pages"] == [1, 2]
    assert result["dropped_pages"] == []


def test_anchor_gate_blocks_funds_flow_only_document():
    # WCP shape: the funds-flow page scores well above the page threshold,
    # but with no netback anchor the DOCUMENT yields nothing.
    result = _locate_mda_pages_from_texts([FUNDS_FLOW_NOTE_PAGE, VOLUMES_PAGE])
    assert result == {"pages": [], "dropped_pages": []}


def test_funds_flow_page_qualifies_once_document_is_anchored():
    result = _locate_mda_pages_from_texts([NETBACK_PAGE, FUNDS_FLOW_NOTE_PAGE])
    assert result["pages"] == [0, 1]


def test_sparse_netback_prose_is_not_an_anchor():
    # "Netback improved." in prose (low numeric density) must not anchor.
    result = _locate_mda_pages_from_texts([PROSE_PAGE, VOLUMES_PAGE])
    assert result == {"pages": [], "dropped_pages": []}


def test_cap_keeps_highest_scoring_pages_and_discloses_dropped():
    # One anchor + more qualifying pages than the cap: the strongest pages
    # are kept, output ascending, remainder disclosed ascending.
    weak_page = VOLUMES_PAGE  # score 8 (3 volume-unit hits + boe/d repeats)
    strong_pages = [NETBACK_PAGE] * MAX_MDA_PAGES  # score >> weak
    result = _locate_mda_pages_from_texts(strong_pages + [weak_page])
    assert len(result["pages"]) == MAX_MDA_PAGES
    assert result["pages"] == list(range(MAX_MDA_PAGES))
    assert result["dropped_pages"] == [MAX_MDA_PAGES]
