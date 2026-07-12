"""CB-031 / CB-032 pinning tests — Peyto FY2025 cold-load drill triage (2026-07-11).

Shapes are transcribed from the real as-filed Peyto FY2025 statements (the
first cold-load drill filer, agent-fetched via CB-028) and WCP FY2025, so the
pins double as concept documentation.

CB-031: the n=4 resource gross-revenue-label adjudication — "Petroleum and
natural gas sales" (WCP) and "Natural gas and natural gas liquid sales"
(Peyto) join the gross-of-royalties canonical revenue family. Each filer's
"…net of royalties" line ties arithmetically and stays unmapped; Peyto's
derivative-polluted "Total revenue, other income, and derivative financial
instruments" rollup stays suppressed (the CB-025 negative rule held cold).

CB-032: the Peyto cold-load alias pack — "Earnings for the year" (net_income),
"Net income and comprehensive income" (net_income, WCP's combined-SCI form),
"Depletion and depreciation" (D&A, plain CB-026 family), "Operating
activities" (operating_cash_flow, cash_flow-scoped), "Additions to property,
plant, and equipment" (capex, negative as-presented). net_income gains
collision_resolution=prefer_primary_alias (CB-013 mechanism): TOU prints BOTH
a cash-flow "Net income" opener row and an income-statement "Net income and
comprehensive income" line — the earliest-declared alias wins and the
resolution is recorded in meta.resolved_collisions.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.integrity.sedar_mapper import map_line_items


SECTOR = "Upstream Oil & Gas"


def _unmapped_labels(mapping: dict) -> list[str]:
    return [row["label"] for row in mapping["unmapped"]]


# ---------------------------------------------------------------------------
# CB-031: the two new gross revenue labels; net-of-royalties lines stay out
# ---------------------------------------------------------------------------

def test_peyto_shape_revenue_maps_gross_line():
    items = [
        {"label": "Natural gas and natural gas liquid sales", "value": 1_080_438,
         "statement": "income_statement"},
        {"label": "Royalties", "value": -47_203, "statement": "income_statement"},
        {"label": "Marketing revenue", "value": 23_118,
         "statement": "income_statement"},
        {"label": "Natural gas and natural gas liquid sales, net of royalties",
         "value": 1_056_353, "statement": "income_statement"},
        {"label": "Total revenue, other income, and derivative financial instruments",
         "value": 1_320_055, "statement": "income_statement"},
    ]
    mapping = map_line_items(items, "IFRS", sector=SECTOR)
    assert mapping["meta"]["sector_profile"] == "resource_sector"

    assert mapping["mapped"]["revenue"]["value"] == 1_080_438
    assert (mapping["mapped"]["revenue"]["source_label"]
            == "Natural gas and natural gas liquid sales")
    # The net-of-royalties line and the derivative-polluted rollup stay unmapped.
    assert ("Natural gas and natural gas liquid sales, net of royalties"
            in _unmapped_labels(mapping))
    assert ("Total revenue, other income, and derivative financial instruments"
            in _unmapped_labels(mapping))


def test_wcp_shape_revenue_maps_gross_line():
    items = [
        {"label": "Petroleum and natural gas sales", "value": 5_908.8,
         "statement": "income_statement"},
        {"label": "Royalties", "value": -739.1, "statement": "income_statement"},
        {"label": "Petroleum and natural gas sales, net of royalties",
         "value": 5_169.7, "statement": "income_statement"},
        {"label": "Total revenue and other income", "value": 5_511.1,
         "statement": "income_statement"},
    ]
    mapping = map_line_items(items, "IFRS", sector=SECTOR)

    assert mapping["mapped"]["revenue"]["value"] == 5_908.8
    assert (mapping["mapped"]["revenue"]["source_label"]
            == "Petroleum and natural gas sales")
    assert ("Petroleum and natural gas sales, net of royalties"
            in _unmapped_labels(mapping))


# ---------------------------------------------------------------------------
# CB-032: the Peyto alias pack
# ---------------------------------------------------------------------------

def test_peyto_bottom_line_earnings_for_the_year_maps():
    items = [
        {"label": "Earnings for the year", "value": 418_586,
         "statement": "income_statement"},
    ]
    mapping = map_line_items(items, "IFRS", sector=SECTOR)
    assert mapping["mapped"]["net_income"]["value"] == 418_586


def test_wcp_combined_sci_bottom_line_maps():
    # WCP prints ONLY the combined form (no bare "Net income" income-statement
    # row) — the combined label must map on its own.
    items = [
        {"label": "Net income and comprehensive income", "value": 984.6,
         "statement": "income_statement"},
    ]
    mapping = map_line_items(items, "IFRS", sector=SECTOR)
    assert mapping["mapped"]["net_income"]["value"] == 984.6


def test_net_income_collision_prefers_primary_alias_tou_shape():
    # TOU regression shape: cash-flow "Net income" opener + income-statement
    # combined line. prefer_primary_alias keeps the earliest-declared alias
    # ("net income") and records the resolution — the field must NOT drop.
    items = [
        {"label": "Net income and comprehensive income", "value": 262_672,
         "statement": "income_statement"},
        {"label": "Net income", "value": 262_672, "statement": "cash_flow"},
    ]
    mapping = map_line_items(items, "IFRS", sector=SECTOR)

    assert mapping["mapped"]["net_income"]["value"] == 262_672
    assert mapping["mapped"]["net_income"]["source_label"] == "Net income"
    resolutions = mapping["meta"].get("resolved_collisions") or []
    assert any(r.get("canonical_field") == "net_income" for r in resolutions)


def test_peyto_plain_depletion_and_depreciation_maps():
    items = [
        {"label": "Depletion and depreciation", "value": 387_533,
         "statement": "income_statement"},
    ]
    mapping = map_line_items(items, "IFRS", sector=SECTOR)
    da = mapping["mapped"]["depletion_depreciation_amortization"]
    assert da["value"] == 387_533
    # Plain D&D: no impairment semantics tag (CB-026 combined forms carry one).
    assert not (da.get("semantics") or {}).get("includes_impairment")


def test_peyto_operating_activities_ocf_is_cash_flow_scoped():
    # The bare label maps on the cash-flow statement...
    cf = map_line_items(
        [{"label": "Operating activities", "value": 857_562,
          "statement": "cash_flow"}],
        "IFRS", sector=SECTOR,
    )
    assert cf["mapped"]["operating_cash_flow"]["value"] == 857_562
    # ...and must NOT fire on an income-statement row (the scoping is the
    # entire safety argument for this loosest-in-slate alias).
    inc = map_line_items(
        [{"label": "Operating activities", "value": 857_562,
          "statement": "income_statement"}],
        "IFRS", sector=SECTOR,
    )
    assert "operating_cash_flow" not in inc["mapped"]


def test_peyto_capex_additions_maps_negative_as_presented():
    items = [
        {"label": "Additions to property, plant, and equipment",
         "value": -473_349, "statement": "cash_flow"},
    ]
    mapping = map_line_items(items, "IFRS", sector=SECTOR)
    assert mapping["mapped"]["capex"]["value"] == -473_349
