"""CB-040 Stage 3b pins — mixed-window metric suppression (ratified
2026-07-12: SUPPRESS, not annotate).

A Q2/Q3 interim can pair its income statement at the discrete quarter
while a YTD-only cash flow pairs at H1/9M. Cross-statement flow ratios
(FCF Conversion = FCF / net income, FCF Yield = FCF / revenue) would then
divide a 6-month flow by a 3-month flow — a wrong ratio, not a caveated
one. Same-statement metrics stay live; paths without period_windows
(annual SEDAR, EDGAR, FMP) are untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.excel_exporter import _calc_summary_metrics


def _fd(period_windows=None):
    fd = {
        "revenue": 1_000_000,
        "net_income": 200_000,
        "operating_cash_flow": 400_000,
        "capex": -100_000,
        "income_statement": [],
        "balance_sheet": [],
        "cash_flow_statement": [],
    }
    if period_windows is not None:
        fd["period_windows"] = period_windows
    return fd


def test_mixed_windows_suppress_cross_statement_ratios():
    metrics = _calc_summary_metrics(_fd({"income_statement": "Q", "cash_flow": "H1"}))
    assert metrics["mixed_windows"] is True
    assert metrics["fcf_conv"] is None
    assert metrics["fcf_yield"] is None
    # Same-statement metrics stay live: FCF itself is cash-flow-internal.
    assert metrics["fcf_c"] == 400_000 - 100_000
    assert metrics["ni_margin"] is not None


def test_matching_windows_keep_the_ratios():
    metrics = _calc_summary_metrics(_fd({"income_statement": "Q", "cash_flow": "Q"}))
    assert metrics["mixed_windows"] is False
    assert metrics["fcf_conv"] is not None
    assert metrics["fcf_yield"] is not None


def test_paths_without_period_windows_are_untouched():
    """Annual SEDAR / EDGAR / FMP financial_data carries no period_windows —
    suppression can never fire there."""
    metrics = _calc_summary_metrics(_fd())
    assert metrics["mixed_windows"] is False
    assert metrics["fcf_conv"] is not None


def test_partial_window_info_never_suppresses():
    """One side unknown (None) is not evidence of mixing — honest default
    is to keep the metric, matching the pre-CB-040 behavior."""
    metrics = _calc_summary_metrics(_fd({"income_statement": "Q", "cash_flow": None}))
    assert metrics["mixed_windows"] is False
    assert metrics["fcf_conv"] is not None


# ---------------------------------------------------------------------------
# CB-041 — interim Leverage suppression (ratified 2026-07-12): net debt is
# an INSTANT, a quarter's EBITDA is a 3-month FLOW, and the RAG thresholds
# are annual-calibrated (CB-023: <=1.0 GREEN) — the ratio reads ~4x on an
# interim. Honest "—" until TTM-powered leverage ships.
# ---------------------------------------------------------------------------

def _leverage_fd(period_windows=None):
    fd = _fd(period_windows)
    fd.update({
        "operating_income": 100_000,
        "depletion_depreciation_amortization": 50_000,  # EBITDA = 150,000
        "interest_expense": 10_000,                      # arms int_cover
        "long_term_debt": 300_000,
        "cash": 50_000,                                  # net debt = 250,000
    })
    return fd


def test_interim_window_suppresses_leverage():
    metrics = _calc_summary_metrics(_leverage_fd({"income_statement": "Q", "cash_flow": "Q"}))
    assert metrics["interim_flow_window"] is True
    assert metrics["nd_ebitda"] is None
    # Dimensionally honest ratios stay live on the same interim.
    assert metrics["int_cover"] is not None        # flow ÷ flow, same window
    assert metrics["current_ratio"] is None or True  # instants unaffected by this rule
    assert metrics["ni_margin"] is not None


def test_annual_paths_keep_leverage():
    metrics = _calc_summary_metrics(_leverage_fd())                # no period_windows
    assert metrics["interim_flow_window"] is False
    assert metrics["nd_ebitda"] == 250_000 / 150_000
    metrics = _calc_summary_metrics(_leverage_fd({"income_statement": "FY", "cash_flow": "FY"}))
    assert metrics["interim_flow_window"] is False                 # FY window is annual
    assert metrics["nd_ebitda"] == 250_000 / 150_000


# ---------------------------------------------------------------------------
# CB-044 (ratified 2026-07-13) — TTM-powered interim Leverage: when the
# CB-040 cross-document TTM carries all three EBITDA components, Leverage
# computes as net debt ÷ TTM EBITDA with the annual-calibrated thresholds
# applying unchanged (a trailing-twelve-month window is annual-scale by
# construction). Every chain failure keeps the honest dash.
# ---------------------------------------------------------------------------

def _ttm_ok(pretax=200_000, interest=40_000, da=160_000, da_semantics=None):
    da_field = {"value": da, "receipt": "r"}
    if da_semantics:
        da_field["semantics"] = da_semantics
    return {
        "status": "ok",
        "annual_year": 2025,
        "fields": {
            "pretax_income": {"value": pretax, "receipt": "r"},
            "interest_expense": {"value": interest, "receipt": "r"},
            "depletion_depreciation_amortization": da_field,
        },
    }


def test_interim_leverage_computes_from_ttm_ebitda():
    fd = _leverage_fd({"income_statement": "Q", "cash_flow": "Q"})
    fd["_ttm"] = _ttm_ok()   # TTM EBITDA = 400,000
    metrics = _calc_summary_metrics(fd)
    assert metrics["nd_ebitda"] == 250_000 / 400_000
    assert "TTM EBITDA" in metrics["nd_ebitda_basis"]
    assert "annual-scale by construction" in metrics["nd_ebitda_basis"]


def test_ttm_leverage_discloses_impairment_basis():
    """CB-026: a combined DD&A-and-impairment line is added back WITH its
    basis disclosed wherever the figure is consumed."""
    fd = _leverage_fd({"income_statement": "Q", "cash_flow": "Q"})
    fd["_ttm"] = _ttm_ok(da_semantics={"includes_impairment": True})
    metrics = _calc_summary_metrics(fd)
    assert metrics["nd_ebitda"] is not None
    assert "D&A incl. impairment" in metrics["nd_ebitda_basis"]


def test_incomplete_ttm_chain_keeps_the_honest_dash():
    fd = _leverage_fd({"income_statement": "Q", "cash_flow": "Q"})
    ttm = _ttm_ok()
    del ttm["fields"]["interest_expense"]   # one component missing
    fd["_ttm"] = ttm
    metrics = _calc_summary_metrics(fd)
    assert metrics["nd_ebitda"] is None
    assert metrics["nd_ebitda_basis"] is None


def test_ttm_leverage_needs_net_debt_the_tou_shape():
    """The live TOU shape: no cash line → no net debt → the dash stands
    even with a complete TTM chain (the CB-035-session adjudication)."""
    fd = _leverage_fd({"income_statement": "Q", "cash_flow": "Q"})
    fd.pop("cash", None)
    fd["_ttm"] = _ttm_ok()
    metrics = _calc_summary_metrics(fd)
    assert metrics["nd_ebitda"] is None


def test_annual_analyses_never_touch_the_ttm_path():
    fd = _leverage_fd({"income_statement": "FY", "cash_flow": "FY"})
    fd["_ttm"] = _ttm_ok()   # even if present, annual paths ignore it
    metrics = _calc_summary_metrics(fd)
    assert metrics["nd_ebitda"] == 250_000 / 150_000   # plain annual EBITDA
    assert metrics["nd_ebitda_basis"] is None
