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


# ---------------------------------------------------------------------------
# Canonical-first revenue/net-income (TD FY2025 financial-or-insurer cold slot)
# ---------------------------------------------------------------------------
# The revenue label scrape matched "Repurchase agreements and short sales
# (Interest expense)" via the bare "sales" alias while the mapper had "Total
# revenue" correctly mapped; the wrong value cascaded into the YoY delta, a
# false revenue-decline red flag, Quality 0/100, and a 177% "net margin".
# Canonical mapped values must outrank any label scrape wherever they exist.

from modules.excel_exporter import two_year_statement_pairs


def _td_shaped_fd():
    return {
        "income_statement": [
            # Decoy rows precede the real ones in statement order:
            {"line_item": "Repurchase agreements and short sales (Interest expense)",
             "value": 11_602e6, "value_prior": 13_322e6, "row_type": "data"},
            {"line_item": "Net interest income",
             "value": 33_062e6, "value_prior": 30_472e6, "row_type": "data"},
            {"line_item": "Total revenue",
             "value": 67_777e6, "value_prior": 57_223e6, "row_type": "data"},
            {"line_item": "Net income",
             "value": 20_538e6, "value_prior": 8_842e6, "row_type": "data"},
        ],
        "balance_sheet": [],
        "cash_flow_statement": [],
        # Promoted canonical fields (raw dollars, as app.py promotes them):
        "revenue": 67_777e6,
        "net_income": 20_538e6,
        "mapping": {"mapped": {
            "revenue": {"value": 67_777, "source_label": "Total revenue"},
            "net_income": {"value": 20_538, "source_label": "Net income"},
        }},
    }


def test_revenue_card_prefers_canonical_over_label_scrape():
    m = _calc_summary_metrics(_td_shaped_fd())
    assert m["rev_c"] == 67_777e6           # NOT 11_602e6 (the scrape decoy)
    assert round(m["yoy_rev"], 1) == 18.4   # prior from the SAME row (57,223)
    assert round(m["ni_margin"], 1) == 30.3  # NOT 177.0


def test_revenue_prior_none_when_source_label_row_missing():
    # Canonical current with no matching statement row -> honest None prior,
    # never a differently-matched scrape row.
    fd = _td_shaped_fd()
    fd["income_statement"] = [r for r in fd["income_statement"]
                              if r["line_item"] != "Total revenue"]
    m = _calc_summary_metrics(fd)
    assert m["rev_c"] == 67_777e6
    assert m["yoy_rev"] is None


def test_revenue_scrape_fallback_unchanged_without_canonical_field():
    fd = _td_shaped_fd()
    for key in ("revenue", "net_income", "mapping"):
        fd.pop(key)
    m = _calc_summary_metrics(fd)
    # Pre-existing scrape behaviour is the deliberate fallback for non-mapped
    # paths (EDGAR/manual uploads): row order wins, warts and all.
    assert m["rev_c"] == 11_602e6


def test_two_year_pairs_use_canonical_revenue_and_net_income():
    pairs = two_year_statement_pairs(_td_shaped_fd())
    assert pairs["Revenue"] == {"current": 67_777e6, "prior": 57_223e6}
    # Pre-fix the chart matched "Net interest income" by row order:
    assert pairs["Net Income"] == {"current": 20_538e6, "prior": 8_842e6}


# ---------------------------------------------------------------------------
# CB-021: canonical-first Operating Cash Flow + CapEx, sector-aware CapEx basis
# (general = PP&E; O&G/mining = PP&E + E&E), acquisitions excluded, composition
# disclosed, every ratio carrying a calculation caption. (− = minus sign,
# ÷ = division sign, matching the app's captions.)
# ---------------------------------------------------------------------------

def test_fcf_canonical_first_capex_basis_ppe_only():
    fd = _fd(is_rows=[_row("Total revenue", 41_509_000_000, "total")])
    fd["operating_cash_flow"] = 13_386_000_000
    fd["capex"] = -5_291_000_000  # PP&E additions, stored negative as-presented
    m = _calc_summary_metrics(fd)
    assert m["ocf_c"] == 13_386_000_000
    assert m["capex_c"] == 5_291_000_000
    assert m["capex_basis"] == "PP&E"
    assert m["fcf_c"] == 13_386_000_000 - 5_291_000_000
    assert m["calcs"]["fcf"] == "OCF 13.39B − CapEx 5.29B (PP&E)"


def test_fcf_capex_includes_ee_for_resource_mining():
    # CNQ shape: an O&G filer maps E&E capex, so CapEx = PP&E + E&E (disclosed).
    # The Chevron-style acquisition never enters — it is not mapped to capex.
    fd = _fd(is_rows=[_row("Total revenue", 41_509_000_000, "total")])
    fd["operating_cash_flow"] = 13_386_000_000
    fd["capex"] = -5_291_000_000
    fd["capitalized_exploration_additions"] = -92_000_000
    fd["net_income"] = 6_106_000_000
    m = _calc_summary_metrics(fd)
    assert m["capex_c"] == 5_383_000_000        # 5,291 + 92
    assert m["capex_basis"] == "PP&E + E&E"
    assert m["fcf_c"] == 8_003_000_000          # 13,386 - 5,383
    assert m["calcs"]["fcf"] == "OCF 13.39B − CapEx 5.38B (PP&E + E&E)"
    assert m["calcs"]["ni_margin"] == "net income 6.11B ÷ revenue 41.51B"


def test_capex_canonical_outranks_scrape():
    # A cash-flow row the scrape would match must not override the mapped capex.
    fd = _fd(cf_rows=[_row("Purchases of property, plant and equipment", -9_999)])
    fd["operating_cash_flow"] = 100
    fd["capex"] = -40
    m = _calc_summary_metrics(fd)
    assert m["capex_c"] == 40   # canonical, not the 9,999 scrape row
    assert m["fcf_c"] == 60


def test_capex_scrape_fallback_unchanged_without_canonical_field():
    # Non-mapped paths (EDGAR/manual) keep the pre-existing scrape + PP&E basis.
    fd = _fd(cf_rows=[
        _row("Net cash provided by operating activities", 102_720, "total"),
        _row("Purchases of property, plant and equipment", -6_100),
    ])
    m = _calc_summary_metrics(fd)
    assert m["fcf_c"] == 102_720 - 6_100
    assert m["capex_basis"] == "PP&E"


def test_two_year_capex_chart_matches_card_ppe_plus_ee():
    # The chart's CapEx mirrors the card (PP&E + E&E), so OCF - CapEx on the
    # chart reconciles to the card's FCF (Change Propagation).
    fd = _fd(cf_rows=[
        {"line_item": "Net expenditures on property, plant and equipment",
         "value": -5_291_000_000, "value_prior": -4_000_000_000, "row_type": "data"},
        {"line_item": "Net expenditures on exploration and evaluation assets",
         "value": -92_000_000, "value_prior": -80_000_000, "row_type": "data"},
        {"line_item": "Cash flows from operating activities",
         "value": 13_386_000_000, "value_prior": 12_000_000_000, "row_type": "total"},
    ])
    fd["operating_cash_flow"] = 13_386_000_000
    fd["capex"] = -5_291_000_000
    fd["capitalized_exploration_additions"] = -92_000_000
    fd["mapping"] = {"mapped": {
        "operating_cash_flow": {"value": 13_386,
                                "source_label": "Cash flows from operating activities"},
        "capex": {"value": -5_291,
                  "source_label": "Net expenditures on property, plant and equipment"},
        "capitalized_exploration_additions": {"value": -92,
                  "source_label": "Net expenditures on exploration and evaluation assets"},
    }}
    pairs = two_year_statement_pairs(fd)
    assert pairs["Capital Expenditures"]["current"] == 5_383_000_000  # PP&E + E&E
    assert pairs["Capital Expenditures"]["prior"] == 4_080_000_000    # 4,000 + 80
    assert pairs["Operating Cash Flow"]["current"] == 13_386_000_000


# ---------------------------------------------------------------------------
# CB-022: Debt/Equity leverage ratio — canonical-first total debt (LT +
# current portion; leases and acquisitions excluded), disclosed composition,
# suppressed for banks/insurers (deposits/policy liabilities != leverage debt).
# ---------------------------------------------------------------------------

def test_debt_equity_canonical_first_with_disclosure():
    fd = _fd()
    fd["long_term_debt"] = 16_419_000_000
    fd["short_term_debt"] = 2_400_000_000
    fd["total_equity"] = 39_468_000_000
    fd["mapping"] = {"meta": {"sector_profile": "resource_sector"}}
    m = _calc_summary_metrics(fd)
    assert round(m["de_ratio"], 4) == 0.4768   # 18,819 / 39,468
    assert m["calcs"]["debt_equity"] == (
        "total debt 18.82B ÷ equity 39.47B (LT debt + current portion)")


def test_debt_equity_suppressed_for_financial_sector():
    fd = _fd()
    fd["long_term_debt"] = 100_000
    fd["total_equity"] = 500_000
    fd["mapping"] = {"meta": {"sector_profile": "financial_sector"}}
    m = _calc_summary_metrics(fd)
    assert m["de_ratio"] is None            # deposits != leverage debt -> honest N/A
    assert m["calcs"]["debt_equity"] is None


def test_debt_equity_scrape_fallback_when_not_mapped():
    # Non-mapped path (EDGAR/manual): total debt from the balance-sheet scrape,
    # equity still read canonically.
    fd = _fd(bs_rows=[
        _row("Long-term debt", 16_419),
        _row("Current portion of long-term debt", 2_400),
    ])
    fd["total_equity"] = 39_468
    m = _calc_summary_metrics(fd)
    assert round(m["de_ratio"], 4) == 0.4768


# ---------------------------------------------------------------------------
# CB-023: EBIT = pre-tax income + interest (add-back) when no printed operating
# income; feeds EBITDA margin, interest cover, and leverage — with the EBIT
# derivation disclosed. Suppressed for banks/insurers.
# ---------------------------------------------------------------------------

def test_ebit_derived_from_pretax_plus_interest_feeds_ebitda_and_coverage():
    # CNQ shape: no operating-income line, so EBIT = pretax + interest.
    fd = _fd(cf_rows=[_row("Depletion, depreciation and amortization", 6_681_000_000)])
    fd["revenue"] = 41_509_000_000
    fd["interest_expense"] = 592_000_000
    fd["pretax_income"] = 8_059_000_000
    fd["mapping"] = {"meta": {"sector_profile": "resource_sector"}}
    m = _calc_summary_metrics(fd)
    assert m["ebitda_c"] == 15_332_000_000       # EBIT 8,651 + D&A 6,681
    assert round(m["ebitda_margin"], 1) == 36.9   # 15,332 / 41,509
    assert round(m["int_cover"], 1) == 14.6        # EBIT 8,651 / interest 592
    assert m["calcs"]["int_cover"] == "EBIT 8.65B ÷ interest 592.0M"
    assert m["calcs"]["ebit"] == "EBIT 8.65B = pretax 8.06B + interest 592.0M"
    assert m["calcs"]["ebitda_margin"] == "EBITDA 15.33B ÷ revenue 41.51B (EBIT + D&A)"


def test_ebit_derivation_suppressed_for_financial_sector():
    # Banks/insurers: interest is core, not a financing add-back — honest N/A.
    fd = _fd(cf_rows=[_row("Depreciation and amortization", 1_000_000_000)])
    fd["revenue"] = 100_000_000_000
    fd["interest_expense"] = 50_000_000_000
    fd["pretax_income"] = 20_000_000_000
    fd["mapping"] = {"meta": {"sector_profile": "financial_sector"}}
    m = _calc_summary_metrics(fd)
    assert m["ebitda_c"] is None
    assert m["ebitda_margin"] is None
    assert m["int_cover"] is None
    assert m["calcs"]["ebit"] is None


def test_printed_operating_income_preferred_over_ebit_derivation():
    fd = _fd(
        is_rows=[_row("Operating income", 5_000_000_000, "total")],
        cf_rows=[_row("Depreciation and amortization", 1_000_000_000)],
    )
    fd["interest_expense"] = 500_000_000
    fd["pretax_income"] = 4_000_000_000
    m = _calc_summary_metrics(fd)
    assert m["ebitda_c"] == 6_000_000_000    # printed OI 5.0B + D&A 1.0B, NOT derived 4.5B
    assert m["calcs"].get("ebit") is None    # not derived -> no derivation caption
