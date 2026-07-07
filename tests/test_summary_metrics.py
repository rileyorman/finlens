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


# ---------------------------------------------------------------------------
# CB-017 (AP.UN FY2025 dry-run): component rows and interest rows must never
# masquerade as the bottom line / capex in the summary cards.
# ---------------------------------------------------------------------------

def test_ni_component_row_never_outranks_bottom_line():
    """The Allied incident: "Net income from joint venture" (0) appeared
    BEFORE "Net loss and comprehensive loss" and the substring matcher
    displayed Net Income 0 against a filed $(1,327,532)K loss."""
    fd = _fd(
        is_rows=[
            _row("Rental revenue", 592_379_000),
            _row("Net income from joint venture", 0),
            _row("Net loss and comprehensive loss", -1_327_532_000),
        ],
    )
    m = _calc_summary_metrics(fd)
    assert m["ni_c"] == -1_327_532_000


def test_ni_canonical_promoted_value_wins_over_scrape():
    """SEDAR filings promote mapped net_income to the top level — the card
    reads the canonical value first, regardless of row ordering quirks."""
    fd = _fd(
        is_rows=[
            _row("Net income from joint venture", 0),
        ],
    )
    fd["net_income"] = -1_327_532_000.0
    m = _calc_summary_metrics(fd)
    assert m["ni_c"] == -1_327_532_000.0


def test_capex_interest_row_excluded_fcf_honest_none():
    """The Allied incident: the stemmed fallback matched "Interest expense
    (net of the impact of capitalization)" as capex and the FCF card showed
    OCF - interest expense (119.8M vs defensible ~68.2M). Interest rows are
    excluded; with no genuine capex line matched, FCF is an honest None."""
    fd = _fd(
        cf_rows=[
            _row("Cash provided by operating activities", 255_288_000, "total"),
            _row("Interest expense (net of the impact of capitalization)", 135_453_000),
            _row("Additions to investment properties (including capitalized interest)", -187_090_000),
        ],
    )
    m = _calc_summary_metrics(fd)
    assert m["fcf_c"] is None  # REIT capex deliberately unclaimed -> honest dash


def test_capex_genuine_line_with_capitalized_interest_suffix_still_matches():
    """The exclusion is narrow: a real capex label carrying an
    "(including capitalized interest)" suffix must still match."""
    fd = _fd(
        cf_rows=[
            _row("Cash provided by operating activities", 255_288_000, "total"),
            _row("Purchases of property, plant and equipment (including capitalized interest)", -6_100_000),
        ],
    )
    m = _calc_summary_metrics(fd)
    assert m["fcf_c"] == 255_288_000 - 6_100_000
