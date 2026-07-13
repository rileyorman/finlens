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
