"""CB-040 Stage 3 pins — build_ttm_from_interim (cross-document TTM;
spec: docs/SEDAR_INTERIM_SPEC.md).

The synthetic shapes mirror the real documents: the ANNUAL uses TOU's
bare-year column keys ("2025"/"2024" — no window words, trusted as annual
by provenance); the INTERIM carries window-typed keys. The Q2 shape pins
the load-bearing subtlety: the row layer displays the discrete quarter,
but TTM must consume the YTD column.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.sedar_ttm import build_ttm_from_interim


def _annual(revenue=100_000, ocf=50_000, currency="CAD", scale="thousands"):
    return {
        "currency": currency,
        "scale": scale,
        "statements": {
            "income_statement": [
                {"label": "Commodity sales from production",
                 "values": {"2025": revenue, "2024": 90_000}},
            ],
            "cash_flow": [
                {"label": "Total cash flow from operating activities",
                 "values": {"2025": ocf, "2024": 45_000}},
            ],
        },
        "mapping": {"mapped": {
            "revenue": {"value": revenue, "source_label": "Commodity sales from production"},
            "operating_cash_flow": {"value": ocf, "source_label": "Total cash flow from operating activities"},
        }},
    }


def _q1_interim(currency="CAD", scale="thousands"):
    return {
        "currency": currency,
        "scale": scale,
        "statements": {
            "income_statement": [
                {"label": "Commodity sales from production", "values": {
                    "Three Months Ended March 31 2026": 30_000,
                    "Three Months Ended March 31 2025": 26_000,
                }},
            ],
            "cash_flow": [
                {"label": "Cash flow from operating activities", "values": {
                    "Three Months Ended March 31 2026": 14_000,
                    "Three Months Ended March 31 2025": 12_000,
                }},
            ],
        },
        "mapping": {"mapped": {
            "revenue": {"value": 30_000, "source_label": "Commodity sales from production"},
            "operating_cash_flow": {"value": 14_000, "source_label": "Cash flow from operating activities"},
        }},
    }


def test_q1_ttm_is_fy_plus_ytd_minus_prior_ytd():
    result = build_ttm_from_interim(_q1_interim(), _annual())
    assert result["status"] == "ok"
    assert result["annual_year"] == 2025 and result["interim_year"] == 2026
    assert result["fields"]["revenue"]["value"] == 100_000 + 30_000 - 26_000
    assert result["fields"]["operating_cash_flow"]["value"] == 50_000 + 14_000 - 12_000
    receipt = result["fields"]["revenue"]["receipt"]
    assert "FY2025" in receipt and "[stored annual]" in receipt
    assert "Three Months Ended March 31 2026" in receipt
    assert "Three Months Ended March 31 2025" in receipt


def test_q2_ttm_uses_the_ytd_column_not_the_discrete_quarter():
    """At Q2 the row layer displays the discrete 3-month column, but the
    TTM component is the SIX-month YTD — largest window wins here."""
    interim = _q1_interim()
    interim["statements"]["income_statement"][0]["values"] = {
        "Three Months Ended June 30 2026": 32_000,
        "Three Months Ended June 30 2025": 28_000,
        "Six Months Ended June 30 2026": 62_000,
        "Six Months Ended June 30 2025": 54_000,
    }
    interim["mapping"]["mapped"]["revenue"]["value"] = 32_000  # row layer: discrete Q
    del interim["statements"]["cash_flow"]
    del interim["mapping"]["mapped"]["operating_cash_flow"]
    result = build_ttm_from_interim(interim, _annual())
    assert result["status"] == "ok"
    assert result["fields"]["revenue"]["value"] == 100_000 + 62_000 - 54_000  # NOT 32k−28k
    assert "Six Months Ended June 30 2026" in result["fields"]["revenue"]["receipt"]


def test_scale_gate_blocks_everything():
    """The named live trap: annual-in-millions vs interim-in-thousands.
    Gate, never rescale."""
    result = build_ttm_from_interim(_q1_interim(scale="thousands"), _annual(scale="millions"))
    assert result["status"] == "gates_failed"
    assert result["gates"]["scale"]["pass"] is False
    assert result["fields"] == {}


def test_currency_gate_blocks_everything():
    result = build_ttm_from_interim(_q1_interim(currency="USD"), _annual(currency="CAD"))
    assert result["status"] == "gates_failed"
    assert result["gates"]["currency"]["pass"] is False
    assert result["fields"] == {}


def test_year_chain_gate_requires_immediately_preceding_annual():
    """An interim two years past the stored annual must not synthesize a
    TTM across the gap."""
    interim = _q1_interim()
    for stmt in interim["statements"].values():
        for row in stmt:
            row["values"] = {
                k.replace("2026", "2027").replace("2025", "2026"): v
                for k, v in row["values"].items()
            }
    result = build_ttm_from_interim(interim, _annual())
    assert result["status"] == "gates_failed"
    assert result["gates"]["year_chain"]["pass"] is False


def test_missing_comparative_is_field_level_honest_na():
    interim = _q1_interim()
    interim["statements"]["income_statement"][0]["values"] = {
        "Three Months Ended March 31 2026": 30_000,  # no prior-year comparative
    }
    result = build_ttm_from_interim(interim, _annual())
    assert result["status"] == "ok"
    assert "revenue" not in result["fields"]
    assert result["unavailable"]["revenue"] == "no_ytd_pair"
    # the other field still assembles — field-level, not document-level
    assert "operating_cash_flow" in result["fields"]


def test_unmapped_sides_are_honest_na():
    interim = _q1_interim()
    annual = _annual()
    del annual["mapping"]["mapped"]["revenue"]           # annual side unmapped
    del interim["mapping"]["mapped"]["operating_cash_flow"]  # interim side unmapped
    result = build_ttm_from_interim(interim, annual)
    assert result["unavailable"]["revenue"] == "annual_field_unmapped"
    assert result["unavailable"]["operating_cash_flow"] == "interim_field_unmapped"
    assert result["unavailable"]["net_income"] == "annual_field_unmapped"
    assert result["fields"] == {}


def test_ambiguous_duplicate_label_is_honest_na():
    """Two flow rows sharing the mapped source label → ambiguity is
    honest absence, never a guess."""
    interim = _q1_interim()
    interim["statements"]["cash_flow"].append(
        dict(interim["statements"]["income_statement"][0])
    )
    result = build_ttm_from_interim(interim, _annual())
    assert result["unavailable"]["revenue"] == "interim_row_ambiguous_or_missing"


def test_never_raises_on_garbage():
    assert build_ttm_from_interim({}, {})["status"] == "gates_failed"
    assert build_ttm_from_interim(None, None)["status"] == "gates_failed"
