from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.integrity import sedar_mapper
from modules.integrity.sedar_mapper import map_line_items


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _line_items(data: dict) -> list[dict]:
    rows = []
    for item in data["statements"]["income_statement"]:
        values = item.get("values") or {}
        rows.append({
            "label": item["label"],
            "value": next(iter(values.values()), None),
            "confidence": item.get("confidence"),
        })
    return rows


def _source_value(data: dict, label: str) -> int | float | None:
    for item in data["statements"]["income_statement"]:
        if item["label"] == label:
            return next(iter((item.get("values") or {}).values()), None)
    raise AssertionError(f"Label not found: {label}")


def _mapped_fixture(name: str, sector: str | None = None) -> tuple[dict, dict]:
    data = _load_fixture(name)
    return data, map_line_items(_line_items(data), data["accounting_standard"], sector=sector)


def _assert_conservation(result: dict) -> None:
    meta = result["meta"]
    total = meta["total"]
    benign_skipped = meta.get("benign_skipped_count", 0)
    assert meta["mapped_count"] + meta["unmapped_count"] + benign_skipped == total


def _assert_unmapped_labels_are_verbatim(data: dict, result: dict) -> None:
    from collections import Counter
    fixture_labels = Counter(item["label"] for item in data["statements"]["income_statement"])
    unmapped_labels = Counter(item["label"] for item in result["unmapped"])
    assert unmapped_labels <= fixture_labels


def test_cnr_fixture_maps_required_income_statement_fields():
    data, result = _mapped_fixture("CNR_FY2025_sedar.json")
    mapped = result["mapped"]

    assert mapped["revenue"]["value"] == 17304
    assert mapped["revenue"]["match_type"] == "exact"
    assert mapped["revenue"]["source_label"] == "Revenues"

    assert mapped["operating_income"]["value"] == _source_value(data, "Operating income")
    assert mapped["interest_expense"]["value"] == _source_value(data, "Interest expense")
    assert mapped["net_income"]["value"] == _source_value(data, "Net income")
    assert result["meta"]["mapped_count"] == 4
    _assert_conservation(result)
    _assert_unmapped_labels_are_verbatim(data, result)


def test_csu_fixture_maps_required_fields_and_keeps_duplicate_net_income_unmapped():
    data, result = _mapped_fixture("CSU_FY2025_sedar.json")
    mapped = result["mapped"]

    assert mapped["interest_expense"]["source_label"] == "Finance costs (note 18)"
    assert mapped["interest_expense"]["value"] == _source_value(data, "Finance costs (note 18)")
    assert mapped["revenue"]["source_label"] == "Revenue total"
    assert mapped["revenue"]["value"] == _source_value(data, "Revenue total")
    assert mapped["net_income"]["source_label"] == "Net income (loss)"
    assert mapped["net_income"]["value"] == _source_value(data, "Net income (loss)")
    assert result["meta"]["mapped_count"] == 3

    # "Net income (loss)" appears twice in CSU IS with the same value — benign duplicate.
    # The first occurrence maps to net_income; the second is benign-skipped.
    unmapped_labels = [item["label"] for item in result["unmapped"]]
    assert "Revenue total" not in unmapped_labels
    assert unmapped_labels.count("Net income (loss)") == 0
    assert result["meta"]["benign_skipped_count"] == 2
    _assert_conservation(result)
    _assert_unmapped_labels_are_verbatim(data, result)


def test_ry_fixture_uses_financial_sector_profile_only():
    data, result = _mapped_fixture("RY_FY2025_sedar.json", sector="Financial Services")
    mapped = result["mapped"]

    assert set(k for k, v in mapped.items() if not v.get("derived")) == {
        "net_interest_income",
        "provision_for_credit_losses",
        "total_revenue_bank",
    }
    assert "revenue" not in mapped
    assert "net_income" not in mapped
    assert result["meta"]["sector_profile"] == "financial_sector"
    _assert_conservation(result)
    _assert_unmapped_labels_are_verbatim(data, result)


def test_collision_guard_keeps_both_distinct_labels_unmapped(monkeypatch):
    alias_table = {
        "schema_version": 1,
        "scope": "income_statement",
        "canonical_fields": {
            "revenue": {
                "aliases": [
                    {"label": "sales", "standards": ["IFRS"], "source": "synthetic"},
                    {"label": "turnover", "standards": ["IFRS"], "source": "synthetic"},
                ],
                "patterns": [],
            }
        },
        "sector_profiles": {},
    }
    monkeypatch.setattr(sedar_mapper, "_load_alias_table", lambda: alias_table)

    result = map_line_items(
        [
            {"label": "Sales", "value": 100},
            {"label": "Turnover", "value": 200},
        ],
        "IFRS",
    )

    assert "revenue" not in result["mapped"]
    assert [item["label"] for item in result["unmapped"]] == ["Sales", "Turnover"]
    assert result["meta"]["collisions"]
    _assert_conservation(result)


def test_standard_filter_rejects_ifrs_only_alias_for_us_gaap():
    result = map_line_items(
        [{"label": "Finance costs", "value": 297, "confidence": 0.99}],
        "US GAAP",
    )

    assert "interest_expense" not in result["mapped"]
    assert result["unmapped"] == [{"label": "Finance costs", "value": 297}]
    _assert_conservation(result)


def test_standard_normalization_us_gaap_with_periods():
    # "U.S. GAAP" (Claude verbatim extraction) must match alias table tag "US GAAP".
    result = map_line_items(
        [{"label": "Finance costs", "value": 297, "confidence": 0.99}],
        "U.S. GAAP",
    )
    # "Finance costs" is IFRS-only — still rejected even after normalization.
    assert "interest_expense" not in result["mapped"]
    assert result["unmapped"] == [{"label": "Finance costs", "value": 297}]
    _assert_conservation(result)


def test_standard_normalization_us_gaap_with_periods_maps_us_gaap_alias():
    # "U.S. GAAP" input must allow US GAAP-tagged aliases to fire.
    result = map_line_items(
        [{"label": "Operating income", "value": 500, "confidence": 0.99}],
        "U.S. GAAP",
    )
    assert result["mapped"]["operating_income"]["value"] == 500
    assert result["mapped"]["operating_income"]["match_type"] == "exact"
    _assert_conservation(result)


def test_standard_normalization_maps_accounting_family_variants():
    assert sedar_mapper._normalize_standard("IFRS") == "ifrs"
    assert sedar_mapper._normalize_standard("IFRS Accounting Standards") == "ifrs"
    assert sedar_mapper._normalize_standard("IFRS 16") == "ifrs"
    assert sedar_mapper._normalize_standard("US GAAP") == "usgaap"
    assert sedar_mapper._normalize_standard("U.S. GAAP") == "usgaap"
    assert sedar_mapper._normalize_standard("United States GAAP") == "usgaap"


def test_operating_income_maps_under_ifrs():
    result = map_line_items(
        [{"label": "Operating income", "value": 798716, "confidence": 0.99}],
        "IFRS",
    )
    assert result["mapped"]["operating_income"]["value"] == 798716
    assert result["mapped"]["operating_income"]["match_type"] == "exact"
    _assert_conservation(result)


def test_standard_normalization_ifrs_exact_passes():
    # "IFRS" must continue to work as before.
    result = map_line_items(
        [{"label": "Finance costs", "value": 297, "confidence": 0.99}],
        "IFRS",
    )
    assert result["mapped"]["interest_expense"]["value"] == 297
    _assert_conservation(result)


def test_standard_normalization_different_standard_still_rejects():
    # A genuinely different standard ("Japanese GAAP") must not match US GAAP or IFRS aliases.
    result = map_line_items(
        [
            {"label": "Finance costs", "value": 100},
            {"label": "Operating income", "value": 200},
        ],
        "Japanese GAAP",
    )
    assert result["mapped"] == {}
    assert result["meta"]["mapped_count"] == 0
    _assert_conservation(result)


def test_normalization_maps_note_references_case_and_trailing_punctuation():
    result = map_line_items(
        [{"label": "  Finance Costs (Note 18).  ", "value": 297, "confidence": 0.99}],
        "IFRS",
    )

    assert result["mapped"]["interest_expense"]["value"] == 297
    assert result["mapped"]["interest_expense"]["source_label"] == "  Finance Costs (Note 18).  "
    assert result["mapped"]["interest_expense"]["match_type"] == "exact"
    _assert_conservation(result)


def test_shop_fixture_maps_four_fields_us_gaap():
    """
    SHOP (Shopify, US GAAP, USD, December year-end) maps four fields after
    alias additions (item 1, Jun 2026):
    - "Total revenues" → revenue
    - "Gross profit" → gross_profit
    - "Income (loss) from operations" → operating_income
    - "Net income" → net_income

    Persistent alias gap: "Interest income" does NOT match "interest expense".
    When mapped_count changes, update the expected value and document the new alias.
    Do NOT weaken assertions to make the test pass.
    """
    data = _load_fixture("SHOP_FY2025_sedar.json")
    assert data["accounting_standard"] == "U.S. GAAP"
    result = map_line_items(_line_items(data), data["accounting_standard"])
    mapped = result["mapped"]

    assert mapped["gross_profit"]["value"] == 5555
    assert mapped["gross_profit"]["match_type"] == "exact"
    assert mapped["gross_profit"]["source_label"] == "Gross profit"

    assert mapped["operating_income"]["value"] == 1468
    assert mapped["operating_income"]["match_type"] == "exact"
    assert mapped["operating_income"]["source_label"] == "Income (loss) from operations"

    assert mapped["net_income"]["value"] == 1231
    assert mapped["net_income"]["match_type"] == "exact"
    assert mapped["net_income"]["source_label"] == "Net income"

    assert mapped["revenue"]["value"] == 11556
    assert mapped["revenue"]["match_type"] == "exact"
    assert mapped["revenue"]["source_label"] == "Total revenues"
    assert "interest_expense" not in mapped

    assert result["meta"]["mapped_count"] == 4
    _assert_conservation(result)
    _assert_unmapped_labels_are_verbatim(data, result)

    unmapped_labels = [item["label"] for item in result["unmapped"]]
    assert "Total revenues" not in unmapped_labels
    assert "Net unrealized (loss) gain on equity and other investments" in unmapped_labels


def test_atd_fixture_maps_five_fields_with_derived_gross_profit():
    """
    ATD (Alimentation Couche-Tard, IFRS, USD, April year-end).

    After alias additions (item 1) and benign-duplicate relaxation (item 13),
    five IS line items map:
    - "Revenues" → revenue
    - "Cost of sales, excluding depreciation, amortization and impairment" → cost_of_revenue
      (semantics.excludes_da: True — D&A not included in this cost line)
    - "Operating income" → operating_income
    - "Financial expenses" → interest_expense
    - "Net earnings" → net_income (first of two identical occurrences; second benign-skipped)

    Gross profit is DERIVED (revenue - cost_of_revenue = 13021.3).
    Derived entries are NOT counted in mapped_count.

    Do NOT weaken assertions. If mapped_count changes, update and document the new alias.
    """
    data = _load_fixture("ATD_FY2025_sedar.json")
    assert data["accounting_standard"] == "IFRS Accounting Standards"
    result = map_line_items(_line_items(data), data["accounting_standard"])
    mapped = result["mapped"]

    assert mapped["revenue"]["source_label"] == "Revenues"
    assert mapped["revenue"]["value"] == _source_value(data, "Revenues")

    assert mapped["cost_of_revenue"]["source_label"] == (
        "Cost of sales, excluding depreciation, amortization and impairment (Note 7)"
    )
    assert mapped["cost_of_revenue"]["value"] == _source_value(
        data, "Cost of sales, excluding depreciation, amortization and impairment (Note 7)"
    )
    assert mapped["cost_of_revenue"].get("semantics", {}).get("excludes_da") is True

    assert mapped["operating_income"]["source_label"] == "Operating income"
    assert mapped["operating_income"]["value"] == _source_value(data, "Operating income")

    assert mapped["interest_expense"]["source_label"] == "Financial expenses (Note 9)"
    assert mapped["interest_expense"]["value"] == _source_value(data, "Financial expenses (Note 9)")

    assert mapped["net_income"]["source_label"] == "Net earnings"
    assert mapped["net_income"]["value"] == _source_value(data, "Net earnings")

    # Derived gross profit — not a line-item mapping.
    assert "gross_profit" in mapped
    assert mapped["gross_profit"]["derived"] is True
    assert mapped["gross_profit"]["excludes_da"] is True
    assert abs(mapped["gross_profit"]["value"] - 13021.3) < 0.01

    assert result["meta"]["mapped_count"] == 5
    assert result["meta"]["gross_profit_derived"] is True
    assert result["meta"]["benign_skipped_count"] == 1  # second "Net earnings"

    _assert_conservation(result)
    _assert_unmapped_labels_are_verbatim(data, result)

    unmapped_labels = [item["label"] for item in result["unmapped"]]
    assert "Revenues" not in unmapped_labels
    assert "Operating income" not in unmapped_labels
    assert "Financial expenses (Note 9)" not in unmapped_labels
    # "Net financial expenses" is a separate label and remains unmapped.
    assert "Net financial expenses" in unmapped_labels


def test_reiun_fixture_maps_three_fields_after_alias_additions():
    """
    REI.UN (Canadian Retail REIT, IFRS, CAD, December year-end).

    After alias additions (item 1) and benign-duplicate relaxation (item 13),
    three IS line items map:
    - "Operating income" → operating_income  (alias promoted to IFRS)
    - "Interest costs, net" → interest_expense  (new IFRS alias from REI.UN evidence)
    - "Net income" → net_income  (alias promoted to IFRS; first of two identical occurrences)

    "Rental revenue" is deliberately NOT mapped to generic revenue — it belongs in a
    future REIT sector profile (Phase 2 Design, validated Jun 2026).

    Do NOT weaken assertions. If mapped_count changes, update and document the new alias.
    """
    data = _load_fixture("REIUN_FY2025_sedar.json")
    assert data["accounting_standard"] == "IFRS"
    result = map_line_items(_line_items(data), data["accounting_standard"])
    mapped = result["mapped"]

    assert mapped["operating_income"]["source_label"] == "Operating income"
    assert mapped["operating_income"]["value"] == _source_value(data, "Operating income")

    assert mapped["interest_expense"]["source_label"] == "Interest costs, net"
    assert mapped["interest_expense"]["value"] == _source_value(data, "Interest costs, net")

    assert mapped["net_income"]["source_label"] == "Net income"
    assert mapped["net_income"]["value"] == _source_value(data, "Net income")

    assert mapped["revenue"]["source_label"] == "Total revenue"
    assert mapped["revenue"]["value"] == _source_value(data, "Total revenue")

    assert result["meta"]["mapped_count"] == 4
    assert result["meta"]["benign_skipped_count"] == 1  # second "Net income"

    unmapped_labels = [item["label"] for item in result["unmapped"]]

    # REIT-specific labels that must remain unmapped (no generic alias exists).
    assert "Rental revenue" in unmapped_labels
    assert "Fair value loss on investment properties, net" in unmapped_labels

    _assert_conservation(result)
    _assert_unmapped_labels_are_verbatim(data, result)


def test_benign_duplicate_same_value_maps_first_occurrence(monkeypatch):
    """Same normalized label + same value = benign duplicate: first occurrence maps."""
    alias_table = {
        "schema_version": 1,
        "scope": "income_statement",
        "canonical_fields": {
            "net_income": {
                "aliases": [
                    {"label": "net earnings", "standards": ["IFRS"], "source": "synthetic"},
                ],
                "patterns": [],
            }
        },
        "sector_profiles": {},
    }
    monkeypatch.setattr(sedar_mapper, "_load_alias_table", lambda: alias_table)

    result = map_line_items(
        [
            {"label": "Net earnings", "value": 2592.4},
            {"label": "Net earnings", "value": 2592.4},
        ],
        "IFRS",
    )

    assert result["mapped"]["net_income"]["value"] == 2592.4
    assert result["meta"]["mapped_count"] == 1
    assert result["meta"]["benign_skipped_count"] == 1
    meta = result["meta"]
    assert meta["mapped_count"] + meta["unmapped_count"] + meta["benign_skipped_count"] == meta["total"]


def test_ambiguous_duplicate_different_values_still_blocks(monkeypatch):
    """Same normalized label + different values = ambiguous: all occurrences go to unmapped."""
    alias_table = {
        "schema_version": 1,
        "scope": "income_statement",
        "canonical_fields": {
            "net_income": {
                "aliases": [
                    {"label": "net earnings", "standards": ["IFRS"], "source": "synthetic"},
                ],
                "patterns": [],
            }
        },
        "sector_profiles": {},
    }
    monkeypatch.setattr(sedar_mapper, "_load_alias_table", lambda: alias_table)

    result = map_line_items(
        [
            {"label": "Net earnings", "value": 2592.4},
            {"label": "Net earnings", "value": 2580.4},
        ],
        "IFRS",
    )

    assert "net_income" not in result["mapped"]
    assert len(result["unmapped"]) == 2
    assert result["meta"]["mapped_count"] == 0
    assert result["meta"].get("benign_skipped_count", 0) == 0
    meta = result["meta"]
    assert meta["mapped_count"] + meta["unmapped_count"] + meta.get("benign_skipped_count", 0) == meta["total"]
