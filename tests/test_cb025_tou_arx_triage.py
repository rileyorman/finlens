"""CB-025 / CB-026 pinning tests — TOU FY2025 + ARX FY2025 triage rulings (2026-07-09).

The shapes below are transcribed from the candidate bundles
(candidates/TOU_FY2025 and candidates/ARX_FY2025); values are the real
as-filed figures so the pins double as concept documentation.

CB-025: resource canonical revenue = GROSS production top line. Both filers'
printed "Total revenue" is NET of royalties (component sums tie exactly:
TOU 6,019,970 includes Royalties -513,879; ARX 6,075.7 includes -536.8), so
the default rollup aliases are SUPPRESSED in resource_sector via the new
suppressed_default_aliases mechanism — the negative rule, machine-enforced.

CB-026 (re-ratified same day): a combined "DD&A and impairment" line maps to
depletion_depreciation_amortization WITH an includes_impairment semantics tag
(both are non-cash EBITDA add-backs in standard practice); the EBITDA caption
must disclose the composition.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.excel_exporter import _calc_summary_metrics
from modules.integrity.sedar_mapper import map_line_items


SECTOR = "Upstream Oil & Gas"


def _unmapped_labels(mapping: dict) -> list[str]:
    return [row["label"] for row in mapping["unmapped"]]


# ---------------------------------------------------------------------------
# CB-025: net-of-royalties "Total revenue" suppressed; gross line is canonical
# ---------------------------------------------------------------------------

def test_tou_shape_revenue_maps_gross_not_net_total_revenue():
    items = [
        {"label": "Commodity sales from production", "value": 4_940_024,
         "statement": "income_statement"},
        {"label": "Marketing revenue", "value": 132_679,
         "statement": "income_statement"},
        {"label": "Royalties", "value": -513_879,
         "statement": "income_statement"},
        {"label": "Total revenue", "value": 6_019_970,
         "statement": "income_statement"},
    ]
    mapping = map_line_items(items, "IFRS", sector=SECTOR)
    assert mapping["meta"]["sector_profile"] == "resource_sector"

    revenue = mapping["mapped"]["revenue"]
    assert revenue["value"] == 4_940_024
    assert revenue["source_label"] == "Commodity sales from production"

    # The NET rollup stays visible in unmapped[] — suppressed, never mapped.
    assert "Total revenue" in _unmapped_labels(mapping)
    # Components of the rollup stay unmapped too (no aliases by design).
    assert "Marketing revenue" in _unmapped_labels(mapping)


def test_bare_royalties_maps_negative_as_presented():
    items = [
        {"label": "Royalties", "value": -513_879, "statement": "income_statement"},
    ]
    mapping = map_line_items(items, "IFRS", sector=SECTOR)
    assert mapping["mapped"]["royalties"]["value"] == -513_879


def test_suppression_is_resource_scoped_default_sector_unchanged():
    # CSU-class filer: default profile still maps "Total revenue" — the
    # suppression must never leak outside resource_sector.
    items = [
        {"label": "Total revenue", "value": 1_000_000,
         "statement": "income_statement"},
    ]
    mapping = map_line_items(items, "IFRS", sector="Software")
    assert mapping["mapped"]["revenue"]["value"] == 1_000_000
    assert mapping["mapped"]["revenue"]["source_label"] == "Total revenue"


# ---------------------------------------------------------------------------
# CB-025 finding G: typographic apostrophe must not defeat CB-013 aliases
# ---------------------------------------------------------------------------

def test_arx_curly_apostrophe_total_equity_maps():
    items = [
        # U+2019 right single quote, exactly as ARX prints it.
        {"label": "Total shareholders’ equity", "value": 8_264.0,
         "statement": "balance_sheet"},
        {"label": "Total liabilities", "value": 7_046.3,
         "statement": "balance_sheet"},
        {"label": "Total assets", "value": 15_310.3,
         "statement": "balance_sheet"},
    ]
    mapping = map_line_items(items, "IFRS", sector=SECTOR)
    equity = mapping["mapped"]["total_equity"]
    assert equity["value"] == 8_264.0
    assert equity["source_label"] == "Total shareholders’ equity"
    # Identity closes: 7,046.3 + 8,264.0 = 15,310.3 — the mapped triple feeds
    # sedar_balance_sheet_identity at promotion.
    assert mapping["mapped"]["total_liabilities"]["value"] == 7_046.3
    assert mapping["mapped"]["total_assets"]["value"] == 15_310.3


# ---------------------------------------------------------------------------
# CB-026: combined DD&A+impairment maps WITH the includes_impairment tag
# ---------------------------------------------------------------------------

def test_combined_dda_impairment_maps_with_semantics_tag():
    items = [
        {"label": "Depletion, depreciation, amortization and impairment",
         "value": 3_000_251, "statement": "income_statement"},
        # The cash-flow add-back twin (same label, same value): the alias is
        # income_statement-scoped, so the CF row stays unmapped — CB-009
        # (label, statement) grouping keeps the two rows from self-blocking.
        {"label": "Depletion, depreciation, amortization and impairment",
         "value": 3_000_251, "statement": "cash_flow"},
    ]
    mapping = map_line_items(items, "IFRS", sector=SECTOR)
    dda = mapping["mapped"]["depletion_depreciation_amortization"]
    assert dda["value"] == 3_000_251
    assert dda["semantics"] == {"includes_impairment": True}
    assert ("Depletion, depreciation, amortization and impairment"
            in _unmapped_labels(mapping))


def test_arx_combined_dda_impairment_form_maps():
    items = [
        {"label": "Depletion, depreciation and amortization and impairment "
                  "of property, plant and equipment",
         "value": 1_547.2, "statement": "income_statement"},
    ]
    mapping = map_line_items(items, "IFRS", sector=SECTOR)
    dda = mapping["mapped"]["depletion_depreciation_amortization"]
    assert dda["value"] == 1_547.2
    assert dda["semantics"] == {"includes_impairment": True}


def test_cnq_pure_dda_carries_no_impairment_tag():
    items = [
        {"label": "Depletion, depreciation and amortization",
         "value": 6_681, "statement": "income_statement"},
    ]
    mapping = map_line_items(items, "IFRS", sector=SECTOR)
    dda = mapping["mapped"]["depletion_depreciation_amortization"]
    assert dda["value"] == 6_681
    assert "semantics" not in dda


# ---------------------------------------------------------------------------
# CB-025: capex stock/flow discrimination (TOU generic label, cash_flow-scoped)
# ---------------------------------------------------------------------------

def test_tou_capex_cash_flow_scoped_balance_sheet_stock_unmapped():
    items = [
        {"label": "Property, plant and equipment", "value": 19_620_271,
         "statement": "balance_sheet"},
        {"label": "Property, plant and equipment", "value": -2_988_595,
         "statement": "cash_flow"},
    ]
    mapping = map_line_items(items, "IFRS", sector=SECTOR)
    capex = mapping["mapped"]["capex"]
    assert capex["value"] == -2_988_595  # stored negative as-presented (CB-021)
    # The balance-sheet asset STOCK must stay unmapped.
    unmapped_values = [row["value"] for row in mapping["unmapped"]]
    assert 19_620_271 in unmapped_values


def test_scoped_capex_fails_closed_without_statement_attribution():
    items = [
        {"label": "Property, plant and equipment", "value": -2_988_595},
    ]
    mapping = map_line_items(items, "IFRS", sector=SECTOR)
    assert "capex" not in mapping["mapped"]


def test_arx_capex_development_expenditures_maps():
    items = [
        {"label": "Property, plant and equipment development expenditures",
         "value": -1_819.1, "statement": "cash_flow"},
    ]
    mapping = map_line_items(items, "IFRS", sector=SECTOR)
    assert mapping["mapped"]["capex"]["value"] == -1_819.1


# ---------------------------------------------------------------------------
# CB-025: OCF variants, current debt, pretax variant
# ---------------------------------------------------------------------------

def test_ocf_variants_map_for_both_filers():
    tou = map_line_items(
        [{"label": "Total cash flow from operating activities",
          "value": 3_387_019, "statement": "cash_flow"}],
        "IFRS", sector=SECTOR)
    assert tou["mapped"]["operating_cash_flow"]["value"] == 3_387_019

    arx = map_line_items(
        [{"label": "Cash flow from operating activities",
          "value": 3_093.5, "statement": "cash_flow"}],
        "IFRS", sector=SECTOR)
    assert arx["mapped"]["operating_cash_flow"]["value"] == 3_093.5


def test_current_debt_maps_short_term_debt():
    items = [
        {"label": "Current debt", "value": 800_000, "statement": "balance_sheet"},
        {"label": "Long-term debt", "value": 1_052_914, "statement": "balance_sheet"},
    ]
    mapping = map_line_items(items, "IFRS", sector=SECTOR)
    assert mapping["mapped"]["short_term_debt"]["value"] == 800_000
    assert mapping["mapped"]["long_term_debt"]["value"] == 1_052_914


def test_dirun_debt_pair_maps_completely():
    # Labeled ADDITION to the CB-025 ratified set: the ratified "current debt"
    # alias fires on DIR.UN's balance sheet, and WITHOUT its IFRS sibling the
    # D/E ratio would compute from the current portion alone (870,407) — an
    # understated leverage number on a REIT whose non-current debt (2,098,543)
    # stayed unmapped. Both halves of the CB-022 concept must map together.
    items = [
        {"label": "Non-current debt", "value": 2_098_543,
         "statement": "balance_sheet"},
        {"label": "Current debt", "value": 870_407,
         "statement": "balance_sheet"},
    ]
    mapping = map_line_items(items, "IFRS", sector="Real Estate Investment Trust")
    assert mapping["mapped"]["long_term_debt"]["value"] == 2_098_543
    assert mapping["mapped"]["short_term_debt"]["value"] == 870_407


def test_arx_pretax_variant_maps():
    items = [
        {"label": "Net income before income taxes", "value": 1_633.9,
         "statement": "income_statement"},
        {"label": "Net income", "value": 1_275.1,
         "statement": "income_statement"},
    ]
    mapping = map_line_items(items, "IFRS", sector=SECTOR)
    assert mapping["mapped"]["pretax_income"]["value"] == 1_633.9
    # The variant must never shadow the true bottom line.
    assert mapping["mapped"]["net_income"]["value"] == 1_275.1


# ---------------------------------------------------------------------------
# CB-026: EBITDA consumer discloses the D&A composition (da_basis)
# ---------------------------------------------------------------------------

def _fd_for_ebitda(semantics: dict | None) -> dict:
    mapped_entry = {"value": 30.0, "source_label": "whatever", "match_type": "exact"}
    if semantics:
        mapped_entry["semantics"] = semantics
    return {
        "income_statement": [], "balance_sheet": [], "cash_flow_statement": [],
        "revenue": 100.0,
        "pretax_income": 50.0,
        "interest_expense": 10.0,
        "depletion_depreciation_amortization": 30.0,
        "mapping": {
            "mapped": {"depletion_depreciation_amortization": mapped_entry},
            "meta": {"sector_profile": "resource_sector"},
        },
    }


def test_ebitda_caption_discloses_impairment_in_da():
    metrics = _calc_summary_metrics(_fd_for_ebitda({"includes_impairment": True}))
    assert metrics["ebitda_c"] == 90.0  # EBIT (50+10) + D&A 30
    assert metrics["da_basis"] == "D&A incl. impairment"
    assert "EBIT + D&A incl. impairment" in metrics["calcs"]["ebitda_margin"]


def test_ebitda_caption_plain_da_when_untagged():
    metrics = _calc_summary_metrics(_fd_for_ebitda(None))
    assert metrics["ebitda_c"] == 90.0
    assert metrics["da_basis"] == "D&A"
    assert "EBIT + D&A)" in metrics["calcs"]["ebitda_margin"]
