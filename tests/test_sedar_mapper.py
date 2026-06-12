from __future__ import annotations

import json
import sys
from collections import Counter
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


def _mapped_fixture(name: str, accounting_standard: str, sector: str | None = None) -> tuple[dict, dict]:
    data = _load_fixture(name)
    assert data["accounting_standard"] == accounting_standard
    return data, map_line_items(_line_items(data), accounting_standard, sector=sector)


def _assert_conservation(result: dict) -> None:
    meta = result["meta"]
    assert meta["mapped_count"] + meta["unmapped_count"] == meta["total"]


def _assert_unmapped_labels_are_verbatim(data: dict, result: dict) -> None:
    fixture_labels = Counter(item["label"] for item in data["statements"]["income_statement"])
    unmapped_labels = Counter(item["label"] for item in result["unmapped"])
    assert unmapped_labels <= fixture_labels


def test_cnr_fixture_maps_required_income_statement_fields():
    data, result = _mapped_fixture("CNR_FY2025_sedar.json", "US GAAP")
    mapped = result["mapped"]

    assert mapped["revenue"]["value"] == 17304
    assert mapped["revenue"]["match_type"] == "exact"
    assert mapped["revenue"]["source_label"] == "Revenues (Note 4)"

    assert mapped["operating_income"]["value"] == _source_value(data, "Operating income")
    assert mapped["interest_expense"]["value"] == _source_value(data, "Interest expense")
    assert mapped["net_income"]["value"] == _source_value(data, "Net income")
    assert result["meta"]["mapped_count"] == 4
    _assert_conservation(result)
    _assert_unmapped_labels_are_verbatim(data, result)


def test_csu_fixture_maps_required_fields_and_keeps_duplicate_net_income_unmapped():
    data, result = _mapped_fixture("CSU_FY2025_sedar.json", "IFRS")
    mapped = result["mapped"]

    assert mapped["interest_expense"]["source_label"] == "Finance costs (note 18)"
    assert mapped["interest_expense"]["value"] == _source_value(data, "Finance costs (note 18)")
    assert mapped["revenue"]["source_label"] == "Total Revenue"
    assert mapped["revenue"]["value"] == _source_value(data, "Total Revenue")
    assert result["meta"]["mapped_count"] == 2

    unmapped_labels = [item["label"] for item in result["unmapped"]]
    assert unmapped_labels.count("Net income (loss)") == 2
    assert "net_income" not in mapped
    _assert_conservation(result)
    _assert_unmapped_labels_are_verbatim(data, result)


def test_ry_fixture_uses_financial_sector_profile_only():
    data, result = _mapped_fixture("RY_FY2025_sedar.json", "IFRS", sector="Financial Services")
    mapped = result["mapped"]

    assert set(mapped) == {
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


def test_normalization_maps_note_references_case_and_trailing_punctuation():
    result = map_line_items(
        [{"label": "  Finance Costs (Note 18).  ", "value": 297, "confidence": 0.99}],
        "IFRS",
    )

    assert result["mapped"]["interest_expense"]["value"] == 297
    assert result["mapped"]["interest_expense"]["source_label"] == "  Finance Costs (Note 18).  "
    assert result["mapped"]["interest_expense"]["match_type"] == "exact"
    _assert_conservation(result)


def test_reiun_fixture_zero_mapped_under_current_alias_table():
    """
    REI.UN (Canadian Retail REIT, IFRS, CAD, December year-end) has no income
    statement labels that match any current IFRS alias exactly:
    - Revenue total is an unlabeled subtotal row — no "Total Revenue" label.
    - Interest line is "Interest costs, net" — not the IFRS alias "Finance costs".
    - "Operating income" exists but is currently tagged ["US GAAP"] only.

    This test locks in the CURRENT alias-table behavior. When "operating income"
    is retagged to ["IFRS", "US GAAP"] (open queue item 1), this assertion will
    need to be updated to mapped_count == 1.

    Do NOT weaken this to make it pass — a surprise mapping is a finding.
    """
    data = _load_fixture("REIUN_FY2025_sedar.json")
    assert data["accounting_standard"] == "IFRS"
    result = map_line_items(_line_items(data), "IFRS")

    # Under current alias table, no REIT income statement labels map.
    assert result["meta"]["mapped_count"] == 0

    unmapped_labels = [item["label"] for item in result["unmapped"]]

    # Key REIT-specific labels that must remain unmapped (no generic alias exists).
    assert "Rental revenue" in unmapped_labels
    assert "Operating income" in unmapped_labels
    assert "Fair value loss on investment properties, net" in unmapped_labels
    assert "Interest costs, net" in unmapped_labels
    assert "Net income" in unmapped_labels

    _assert_conservation(result)
    _assert_unmapped_labels_are_verbatim(data, result)
