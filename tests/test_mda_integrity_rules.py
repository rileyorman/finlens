"""MDA_FETCHER_SPEC Stage 3 pins — netback internal tie + FFO anchor tie.

Values are the real TOU FY2025 / ARX FY2025 figures from the first live
MD&A extraction (2026-07-12, both verified byte-exact against print), so
the pins double as concept documentation.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.integrity.engine import (
    _check_mda_ffo_anchor_tie,
    _check_mda_netback_internal_tie,
    _mda_amount_to_raw,
    _mda_ffo_anchor_raw,
    _mda_netback_groups,
    validate_filing,
)


def _nb_row(label, period, value, unit, is_total=False):
    return {"label": label, "period_label": period, "value": value,
            "unit": unit, "is_total": is_total, "source_page": 29}


# The real ARX FY2025 Table 13 ($ millions) and TOU FY2025 p32 ($/boe) rows.
ARX_MILLIONS = [
    _nb_row("Commodity sales from production", "Year Ended December 31, 2025", 5421.7, "$ millions"),
    _nb_row("Royalties", "Year Ended December 31, 2025", -536.8, "$ millions"),
    _nb_row("Operating", "Year Ended December 31, 2025", -735.8, "$ millions"),
    _nb_row("Transportation", "Year Ended December 31, 2025", -689.1, "$ millions"),
    _nb_row("Netback", "Year Ended December 31, 2025", 3460.0, "$ millions", is_total=True),
]
TOU_PER_BOE = [
    _nb_row("Revenue, excluding processing income", "Years Ended December 31, 2025", 28.30, "$/boe"),
    _nb_row("Royalties", "Years Ended December 31, 2025", -2.21, "$/boe"),
    _nb_row("Transportation costs", "Years Ended December 31, 2025", -5.14, "$/boe"),
    _nb_row("Operating expenses", "Years Ended December 31, 2025", -4.93, "$/boe"),
    _nb_row("Operating netback", "Years Ended December 31, 2025", 16.02, "$/boe", is_total=True),
]

NETBACK_RULE = {"params": {"absolute_tolerance": 0.06, "relative_tolerance": 0.002}}
FFO_RULE = {"params": {"relative_tolerance": 0.02}}


# ---------------------------------------------------------------------------
# _mda_amount_to_raw — scale parsing, honest None on unknown scales
# ---------------------------------------------------------------------------

def test_mda_amount_to_raw_scales():
    assert _mda_amount_to_raw(3460.0, "$ millions") == 3_460_000_000
    assert _mda_amount_to_raw(4904, "($000s)") == 4_904_000
    assert _mda_amount_to_raw(1.2, "billions") == 1_200_000_000
    assert _mda_amount_to_raw(100, None) is None
    assert _mda_amount_to_raw(100, "boe/d") is None
    assert _mda_amount_to_raw(None, "millions") is None


# ---------------------------------------------------------------------------
# Netback internal tie — components must sum to the printed total
# ---------------------------------------------------------------------------

def test_netback_groups_built_from_real_rows():
    metrics = {"status": "extracted", "netback_rows": ARX_MILLIONS + TOU_PER_BOE}
    groups = _mda_netback_groups(metrics)
    assert groups is not None and len(groups) == 2
    by_unit = {g["unit"]: g for g in groups}
    assert by_unit["$ millions"]["total"] == 3460.0
    assert by_unit["$ millions"]["n_components"] == 4
    assert by_unit["$/boe"]["total"] == 16.02


def test_netback_groups_none_without_extraction_or_rows():
    assert _mda_netback_groups(None) is None
    assert _mda_netback_groups({"status": "no_mda_detected"}) is None
    assert _mda_netback_groups({"status": "extracted", "netback_rows": []}) is None
    # A group with two total rows is ambiguous — excluded, never a vacuous tie.
    two_totals = ARX_MILLIONS + [_nb_row("Netback per boe", "Year Ended December 31, 2025",
                                         25.32, "$ millions", is_total=True)]
    assert _mda_netback_groups({"status": "extracted", "netback_rows": two_totals}) is None


def test_netback_internal_tie_passes_on_real_figures():
    metrics = {"status": "extracted", "netback_rows": ARX_MILLIONS + TOU_PER_BOE}
    ctx = {"mda_netback_groups": _mda_netback_groups(metrics)}
    observed, threshold, passed, message = _check_mda_netback_internal_tie(NETBACK_RULE, ctx)
    assert passed is True
    assert threshold["groups_checked"] == 2
    assert "tie to" in message


def test_netback_internal_tie_fails_on_misaligned_component():
    # A row/column misalignment: royalties picked up from the wrong column.
    bad = [dict(r) for r in ARX_MILLIONS]
    bad[1]["value"] = -524.9  # the FY2024 royalties figure in the FY2025 column
    ctx = {"mda_netback_groups": _mda_netback_groups(
        {"status": "extracted", "netback_rows": bad})}
    observed, threshold, passed, message = _check_mda_netback_internal_tie(NETBACK_RULE, ctx)
    assert passed is False
    assert "fail" in message


# ---------------------------------------------------------------------------
# FFO anchor tie — annual CFO anchor vs canonical operating_cash_flow
# ---------------------------------------------------------------------------

def _ff_row(label, period, value, scale, per_share=False):
    return {"label": label, "period_label": period, "value": value,
            "unit_scale": scale, "per_share": per_share, "source_page": 40}


def test_ffo_anchor_prefers_latest_annual_row():
    metrics = {"status": "extracted", "funds_flow_rows": [
        _ff_row("Cash flow from operating activities", "Three Months Ended December 31, 2025", 1438.8, "$ millions"),
        _ff_row("Cash flow from operating activities", "Year Ended December 31, 2024", 4100.0, "$ millions"),
        _ff_row("Cash flow from operating activities", "Year Ended December 31, 2025", 4806.0, "$ millions"),
        _ff_row("Funds from operations per share", "Year Ended December 31, 2025", 8.02, "$", per_share=True),
    ]}
    assert _mda_ffo_anchor_raw(metrics) == 4_806_000_000


def test_ffo_anchor_none_without_annual_anchor_or_scale():
    # Quarterly-only anchor: honest None (annual canonical would false-fire).
    quarterly = {"status": "extracted", "funds_flow_rows": [
        _ff_row("Cash flow from operating activities", "Three Months Ended December 31, 2025", 1438.8, "$ millions"),
    ]}
    assert _mda_ffo_anchor_raw(quarterly) is None
    # Unparseable scale: honest None, never a guessed unit.
    unscaled = {"status": "extracted", "funds_flow_rows": [
        _ff_row("Cash flow from operating activities", "Year Ended December 31, 2025", 4806.0, None),
    ]}
    assert _mda_ffo_anchor_raw(unscaled) is None


def test_ffo_anchor_tie_pass_and_fail():
    ctx_pass = {"mda_ffo_anchor_raw": 4_806_000_000, "operating_cash_flow": 4_806_400_000}
    observed, threshold, passed, message = _check_mda_ffo_anchor_tie(FFO_RULE, ctx_pass)
    assert passed is True

    ctx_fail = {"mda_ffo_anchor_raw": 4_806_000_000, "operating_cash_flow": 5_400_000_000}
    observed, threshold, passed, message = _check_mda_ffo_anchor_tie(FFO_RULE, ctx_fail)
    assert passed is False


# ---------------------------------------------------------------------------
# validate_filing wiring — rules run on SEDAR analyses with mda_metrics,
# skip honestly (field_unavailable) without one
# ---------------------------------------------------------------------------

def _base_sedar_data(**extra):
    data = {
        "income_statement": [], "balance_sheet": [], "cash_flow_statement": [],
        "mapping": {"mapped": {}, "meta": {}},
    }
    data.update(extra)
    return data


def test_validate_filing_runs_both_rules_with_mda_metrics():
    data = _base_sedar_data(
        mda_metrics={
            "status": "extracted",
            "netback_rows": ARX_MILLIONS,
            "funds_flow_rows": [
                _ff_row("Cash flow from operating activities", "Year Ended December 31, 2025", 4806.0, "$ millions"),
            ],
        },
        operating_cash_flow=4_806_000_000,
    )
    result = validate_filing(data, "ARX", "Energy")
    by_id = {c.rule_id: c for c in result.checks}
    assert by_id["mda_netback_internal_tie"].passed and not by_id["mda_netback_internal_tie"].skipped
    assert by_id["mda_ffo_anchor_tie"].passed and not by_id["mda_ffo_anchor_tie"].skipped


def test_validate_filing_skips_honestly_without_mda_metrics():
    result = validate_filing(_base_sedar_data(), "TOU", "Energy")
    by_id = {c.rule_id: c for c in result.checks}
    assert by_id["mda_netback_internal_tie"].skipped
    assert by_id["mda_netback_internal_tie"].skip_reason == "field_unavailable"
    assert by_id["mda_ffo_anchor_tie"].skipped
    assert by_id["mda_ffo_anchor_tie"].skip_reason == "field_unavailable"
