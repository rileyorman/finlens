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
    _mda_figure_presence,
    _normalize_mda_payload,
    extract_mda_metrics,
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


# ---------------------------------------------------------------------------
# Normalization — pure pins over transcribed real table rows (ARX FY2025
# Q1-2026 netback Tables 12/12a and funds-flow figures from the verified
# coverage-gap research; they double as schema documentation)
# ---------------------------------------------------------------------------

ARX_SHAPE_PAYLOAD = {
    "as_of": "Three months ended March 31, 2026",
    "production_volumes": [
        {"product": "natural_gas", "label": "Natural gas (MMcf/d)",
         "period_label": "Q1 2026", "volume": "1,533", "volume_unit": "MMcf/d",
         "source_page": 21, "verbatim_notes": None},
        {"product": "total_boe", "label": "Total (boe/d)",
         "period_label": "2025", "volume": "374,336", "volume_unit": "boe/d",
         "source_page": 21, "verbatim_notes": None},
    ],
    "commodity_mix": {"verbatim": "59% natural gas and 41% crude oil and liquids",
                      "gas_pct": 59, "liquids_pct": "41", "source_page": 3},
    "netback_definition_verbatim": "Operating netback is calculated as commodity sales less royalties, operating, and transportation expense.",
    "netback_includes_hedging": False,
    "netback_rows": [
        {"label": "Commodity sales from production", "period_label": "Q1 2026",
         "value": "44.05", "unit": "$/boe", "is_total": False, "source_page": 29},
        {"label": "Royalties", "period_label": "Q1 2026",
         "value": "(4.34)", "unit": "$/boe", "is_total": False, "source_page": 29},
        {"label": "Transportation expense", "period_label": "Q1 2026",
         "value": "(5.57)", "unit": "$/boe", "is_total": False, "source_page": 29},
        {"label": "Operating expense", "period_label": "Q1 2026",
         "value": "(5.00)", "unit": "$/boe", "is_total": False, "source_page": 29},
        {"label": "Operating netback", "period_label": "Q1 2026",
         "value": "29.14", "unit": "$/boe", "is_total": True, "source_page": 29},
    ],
    "funds_flow_definition_verbatim": "Funds from operations is cash flow from operating activities before changes in non-cash working capital.",
    "funds_flow_rows": [
        {"label": "Cash flow from operating activities", "period_label": "Q1 2026",
         "value": "1,051", "unit_scale": "CAD millions", "per_share": False, "source_page": 40},
        {"label": "Funds from operations", "period_label": "Q1 2026",
         "value": "967", "unit_scale": "CAD millions", "per_share": False, "source_page": 40},
    ],
    "realized_prices": [
        {"product": "natural_gas", "label": "Natural gas ($/Mcf)", "period_label": "Q1 2026",
         "value": "3.51", "unit": "$/Mcf", "benchmark_label": None,
         "benchmark_value": None, "source_page": 11},
    ],
    "guidance_disclosures": [
        {"topic": "capex_program", "verbatim": "capital program of $473 million",
         "value": "473", "unit": "CAD millions", "source_page": 5},
    ],
    "extraction_confidence": 0.95,
}


def test_normalize_mda_payload_parses_numbers_and_keeps_verbatim():
    result = _normalize_mda_payload(ARX_SHAPE_PAYLOAD)

    assert result["production_volumes"][0]["volume"] == 1533
    assert result["production_volumes"][0]["volume_unit"] == "MMcf/d"
    assert result["production_volumes"][1]["volume"] == 374336

    # Parenthetical netback deductions parse negative; the total row is flagged.
    values = {row["label"]: row["value"] for row in result["netback_rows"]}
    assert values["Commodity sales from production"] == 44.05
    assert values["Royalties"] == -4.34
    assert values["Transportation expense"] == -5.57
    assert values["Operating expense"] == -5.0
    assert values["Operating netback"] == 29.14
    total_rows = [r for r in result["netback_rows"] if r.get("is_total")]
    assert [r["label"] for r in total_rows] == ["Operating netback"]

    # The ratified trust policy: definition strings survive verbatim.
    assert result["netback_definition_verbatim"].startswith("Operating netback is calculated")
    assert result["netback_includes_hedging"] is False
    assert result["funds_flow_definition_verbatim"].startswith("Funds from operations is cash flow")

    assert result["funds_flow_rows"][0]["value"] == 1051
    assert result["funds_flow_rows"][1]["value"] == 967
    assert result["commodity_mix"]["gas_pct"] == 59
    assert result["commodity_mix"]["liquids_pct"] == 41
    assert result["realized_prices"][0]["value"] == 3.51
    assert result["guidance_disclosures"][0]["value"] == 473
    assert result["extraction_confidence"] == 0.95


def test_normalize_mda_payload_empty_and_malformed():
    result = _normalize_mda_payload({})
    assert result["production_volumes"] == []
    assert result["netback_rows"] == []
    assert result["funds_flow_rows"] == []
    assert result["commodity_mix"] is None
    assert result["netback_definition_verbatim"] is None
    assert result["netback_includes_hedging"] is None
    assert result["extraction_confidence"] == 0.0

    # Non-list blocks and non-dict records are dropped, not crashed on.
    messy = _normalize_mda_payload(
        {"netback_rows": "not a list", "production_volumes": [42, {"volume": "10"}]}
    )
    assert messy["netback_rows"] == []
    assert messy["production_volumes"] == [{"volume": 10}]


# ---------------------------------------------------------------------------
# Figure-presence guard — fabrication surfaced, never silent
# ---------------------------------------------------------------------------

def test_mda_figure_presence_all_found():
    metrics = _normalize_mda_payload(ARX_SHAPE_PAYLOAD)
    page_text = (
        "Natural gas 1,533 MMcf/d Total 374,336 boe/d 59% natural gas 41% liquids\n"
        "Commodity sales from production 44.05 Royalties (4.34)\n"
        "Transportation (5.57) Operating (5.00) Operating netback 29.14\n"
        "Cash flow from operating activities 1,051 Funds from operations 967\n"
        "Natural gas realized 3.51 capital program of $473 million"
    )
    presence = _mda_figure_presence(metrics, page_text)
    assert presence["checked"] > 0
    assert presence["missing_count"] == 0
    assert presence["missing"] == []


def test_mda_figure_presence_flags_fabricated_value():
    metrics = _normalize_mda_payload(ARX_SHAPE_PAYLOAD)
    # Page text missing the netback total: 29.14 must surface as missing.
    page_text = (
        "Natural gas 1,533 MMcf/d Total 374,336 boe/d 59% 41%\n"
        "Commodity sales from production 44.05 Royalties (4.34)\n"
        "Transportation (5.57) Operating (5.00)\n"
        "Cash flow from operating activities 1,051 Funds from operations 967\n"
        "3.51 473"
    )
    presence = _mda_figure_presence(metrics, page_text)
    assert presence["missing_count"] == 1
    assert presence["missing"] == ["29.14"]


# ---------------------------------------------------------------------------
# Zero-spend honest exit — a statements-only PDF must return no_mda_detected
# BEFORE any client/API-key use (runs on the real fetched WCP PDF)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not WCP_PDF.exists(), reason="fetched WCP PDF not on this machine")
def test_extract_mda_metrics_zero_spend_exit_on_statements_pack():
    result = extract_mda_metrics(str(WCP_PDF))
    assert result == {"status": "no_mda_detected", "source_pages": [], "dropped_pages": []}
