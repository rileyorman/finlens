"""Pinning tests for the mapped-fields receipt view builders.

The receipt is a trust surface: it shows the verbatim source label and
as-filed value behind every mapped canonical field. These tests pin the
row content so it cannot drift silently.
"""

from modules.integrity.receipts import (
    integrity_receipt_rows,
    integrity_status_badge,
    mapping_receipt_rows,
)


def _rei_un_style_mapping():
    """A miniature mapping shaped like the real mapper output (REI.UN-style)."""
    return {
        "mapped": {
            "rental_revenue": {
                "value": 1176428,
                "source_label": "Rental revenue",
                "match_type": "exact",
                "confidence": 0.98,
            },
            "net_income": {
                "value": -1327532,
                "source_label": "Net loss and comprehensive loss",
                "match_type": "pattern",
                "confidence": 0.9,
            },
            "net_operating_income": {
                "value": 720404,
                "source_label": "derived: rental_revenue - rental_operating_costs_excluding_development",
                "match_type": "derived",
                "confidence": None,
                "derived": True,
                "components": {
                    "rental_revenue": {
                        "source_label": "Rental revenue",
                        "value": 1176428,
                    },
                    "rental_operating_costs": [
                        {"source_label": "Recoverable under tenant leases", "value": 414386},
                        {"source_label": "Non-recoverable costs", "value": 41638},
                    ],
                    "rental_operating_cost_source": "component rental cost lines",
                },
            },
            "cost_of_revenue": {
                "value": 8099,
                "source_label": "Cost of sales",
                "match_type": "exact",
                "confidence": 0.97,
                "semantics": {"excludes_da": True},
            },
            "total_equity": {
                "value": 25492,
                "source_label": "Total equity",
                "match_type": "exact",
                "confidence": 0.99,
            },
        },
        "unmapped": [{"label": "Operating income", "value": 798716}],
        "meta": {
            "mapped_count": 4,
            "total": 12,
            "resolved_collisions": [
                {
                    "canonical_field": "total_equity",
                    "rule": "prefer_primary_alias",
                    "chosen_label": "Total equity",
                    "rejected_labels": ["Total shareholders' equity"],
                }
            ],
        },
    }


def test_receipt_has_one_row_per_mapped_field():
    rows = mapping_receipt_rows(_rei_un_style_mapping())
    assert [r["Canonical field"] for r in rows] == [
        "rental_revenue",
        "net_income",
        "net_operating_income",
        "cost_of_revenue",
        "total_equity",
    ]


def test_receipt_shows_verbatim_source_label_and_as_filed_value():
    rows = mapping_receipt_rows(_rei_un_style_mapping())
    by_field = {r["Canonical field"]: r for r in rows}
    # Verbatim label, thousands-separated as-filed value — no K/M/B scaling.
    assert by_field["rental_revenue"]["Source line item"] == "Rental revenue"
    assert by_field["rental_revenue"]["Value (as filed)"] == "1,176,428"
    assert by_field["rental_revenue"]["Match"] == "exact label match"
    # Negative values keep their sign (Allied's net loss class).
    assert by_field["net_income"]["Value (as filed)"] == "-1,327,532"
    assert by_field["net_income"]["Match"] == "pattern match"


def test_receipt_derived_row_lists_components():
    rows = mapping_receipt_rows(_rei_un_style_mapping())
    noi = next(r for r in rows if r["Canonical field"] == "net_operating_income")
    assert noi["Match"] == "derived"
    assert '"Rental revenue" 1,176,428' in noi["Notes"]
    assert '"Recoverable under tenant leases" 414,386' in noi["Notes"]
    assert '"Non-recoverable costs" 41,638' in noi["Notes"]


def test_receipt_derived_row_separates_excluded_components():
    # Blended-REIT derivations (CB-012) deliberately EXCLUDE development
    # lines; the receipt must not list them under "derived from".
    mapping = {
        "mapped": {
            "property_operating_costs": {
                "value": 456024,
                "source_label": "derived: rental-only operating cost components",
                "match_type": "derived",
                "derived": True,
                "components": {
                    "rental_operating_costs": [
                        {"source_label": "Recoverable under tenant leases", "value": 414386},
                    ],
                    "excluded_development_costs": [
                        {"source_label": "Residential inventory cost of sales", "value": 181831},
                    ],
                },
            }
        },
        "meta": {},
    }
    notes = mapping_receipt_rows(mapping)[0]["Notes"]
    assert 'derived from "Recoverable under tenant leases" 414,386' in notes
    assert 'excluding "Residential inventory cost of sales" 181,831' in notes
    # The excluded line must not appear inside the derived-from clause.
    derived_clause = notes.split("; ")[0]
    assert "Residential inventory" not in derived_clause


def test_receipt_semantics_tag_surfaces():
    rows = mapping_receipt_rows(_rei_un_style_mapping())
    cor = next(r for r in rows if r["Canonical field"] == "cost_of_revenue")
    assert "excludes da" in cor["Notes"]


def test_receipt_collision_resolution_surfaces():
    rows = mapping_receipt_rows(_rei_un_style_mapping())
    eq = next(r for r in rows if r["Canonical field"] == "total_equity")
    assert "prefer_primary_alias" in eq["Notes"]
    assert 'chose "Total equity"' in eq["Notes"]
    assert "Total shareholders' equity" in eq["Notes"]


def test_receipt_per_share_value_keeps_decimals():
    mapping = {
        "mapped": {
            "eps_basic": {
                "value": 11.57,
                "source_label": "Basic",
                "match_type": "exact",
                "confidence": 0.95,
            }
        },
        "meta": {},
    }
    rows = mapping_receipt_rows(mapping)
    assert rows[0]["Value (as filed)"] == "11.57"


def test_receipt_handles_missing_or_malformed_mapping():
    assert mapping_receipt_rows(None) == []
    assert mapping_receipt_rows({}) == []
    assert mapping_receipt_rows({"mapped": {"revenue": "not-a-dict"}}) == []


def _integrity_result():
    return {
        "overall_status": "clean",
        "checks": [
            {
                "rule_id": "sedar_balance_sheet_identity",
                "severity": "warn",
                "passed": True,
                "skipped": False,
                "skip_reason": None,
                "observed_value": 0.0,
                "message": "assets = liabilities + equity (diff 0.0)",
            },
            {
                "rule_id": "net_margin_sanity",
                "severity": "warn",
                "passed": False,
                "skipped": True,
                "skip_reason": "field_unavailable",
                "observed_value": None,
                "message": "net_income unavailable",
            },
            {
                "rule_id": "revenue_growth_sanity",
                "severity": "warn",
                "passed": False,
                "skipped": False,
                "skip_reason": None,
                "observed_value": 177.0,
                "message": "YoY revenue growth 177.0% exceeds threshold",
            },
        ],
    }


def test_integrity_rows_cover_pass_flag_and_honest_skip():
    rows = integrity_receipt_rows(_integrity_result())
    by_rule = {r["Rule"]: r for r in rows}
    assert by_rule["sedar_balance_sheet_identity"]["Result"] == "✓ pass"
    assert by_rule["net_margin_sanity"]["Result"] == "— skipped (field unavailable)"
    assert by_rule["revenue_growth_sanity"]["Result"] == "⚑ flagged"
    assert by_rule["revenue_growth_sanity"]["Observed"] == "177"


def test_integrity_badge_maps_all_engine_statuses():
    assert integrity_status_badge({"overall_status": "clean"})[0] == "CLEAN"
    assert integrity_status_badge({"overall_status": "warnings"})[0] == "WARNINGS"
    assert integrity_status_badge({"overall_status": "info_only"})[0] == "INFO"
    assert integrity_status_badge({"overall_status": "unknown"})[0] == "UNKNOWN"
    assert integrity_status_badge(None) is None
    assert integrity_status_badge({}) is None
