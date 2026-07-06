"""
Derived summary metrics must degrade honestly when a component is missing.

Pins the fix for the FCF-fallback-mislabels-OCF bug (found live 2026-07-05
on the NVDA EDGAR re-run): _calc_summary_metrics previously fell back to
plain OCF when capex was missing (fcf_c showed 102.72B as "FREE CASH FLOW"
vs true ~96.6B), and to plain operating income when D&A was missing
(labelled "EBITDA"). Both are the confident-wrong-number class the
cold-load gate bans: a missing component must yield None (rendered "—"),
never a different metric wearing the label.
"""

from modules.excel_exporter import _calc_summary_metrics


def _row(label, value, row_type="data"):
    return {"line_item": label, "value": value, "row_type": row_type}


def _fd(is_rows=(), cf_rows=(), bs_rows=()):
    return {
        "income_statement": list(is_rows),
        "cash_flow_statement": list(cf_rows),
        "balance_sheet": list(bs_rows),
    }


# ---------------------------------------------------------------------------
# Free Cash Flow = OCF - capex, or honestly absent
# ---------------------------------------------------------------------------

def test_fcf_derived_when_ocf_and_capex_present():
    fd = _fd(
        cf_rows=[
            _row("Net cash provided by operating activities", 102_720, "total"),
            _row("Purchases of property, plant and equipment", -6_100),
        ],
    )
    m = _calc_summary_metrics(fd)
    assert m["fcf_c"] == 102_720 - 6_100  # capex abs()'d, subtracted


def test_fcf_none_when_capex_missing():
    # The NVDA scenario: OCF extracted, capex line absent. FCF must be None,
    # NOT plain OCF relabelled as free cash flow.
    fd = _fd(
        is_rows=[
            _row("Total revenue", 500_000, "total"),
            _row("Net income", 100_000, "total"),
        ],
        cf_rows=[
            _row("Net cash provided by operating activities", 102_720, "total"),
        ],
    )
    m = _calc_summary_metrics(fd)
    assert m["fcf_c"] is None
    # Dependents inherit the honest absence:
    assert m["fcf_yield"] is None
    assert m["fcf_conv"] is None


def test_fcf_none_when_ocf_missing():
    fd = _fd(
        cf_rows=[
            _row("Purchases of property, plant and equipment", -6_100),
        ],
    )
    m = _calc_summary_metrics(fd)
    assert m["fcf_c"] is None


# ---------------------------------------------------------------------------
# EBITDA = OI + D&A, or honestly absent (sibling of the same bug class)
# ---------------------------------------------------------------------------

def test_ebitda_derived_when_oi_and_da_present():
    fd = _fd(
        is_rows=[_row("Operating income", 100_000, "total")],
        cf_rows=[_row("Depreciation and amortization", 20_000)],
    )
    m = _calc_summary_metrics(fd)
    assert m["ebitda_c"] == 120_000


def test_ebitda_none_when_da_missing():
    # Plain operating income must not be relabelled "EBITDA".
    fd = _fd(
        is_rows=[
            _row("Total revenue", 500_000, "total"),
            _row("Operating income", 100_000, "total"),
        ],
    )
    m = _calc_summary_metrics(fd)
    assert m["ebitda_c"] is None
    assert m["ebitda_margin"] is None
    assert m["nd_ebitda"] is None
