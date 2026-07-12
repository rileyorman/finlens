"""CB-039 pins — build_quarterly_financial_data_from_edgar_facts
(Latest Quarter + TTM from as-filed company-facts; design:
docs/EDGAR_COMPANY_FACTS_SPEC.md Phase-2 section).

Fixture shape mirrors the 2026-07-12 NVDA 10-Q probe:
- Operating cash flow (and every flow here) is derivable from YTD facts
  only — TTM = FY + YTD_current − YTD_prior is the only construction.
- The fp field LIES: the 181-day H1 facts below carry fp="Q2". If fp were
  trusted, H1 revenue 65,000 would be served as "the quarter"; date
  arithmetic derives the true Q2 = 65,000 − 30,000.
- Revenue is dual-tagged: a discrete mid-year Q2 fact exists with a
  DELIBERATELY WRONG value (999) to prove YTD differencing — not the
  dual-tagged fact — is the source.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import edgar_fetcher as ef


def _fact(end, val, filed, form="10-K", start=None, fp="FY"):
    item = {"end": end, "val": val, "filed": filed, "form": form,
            "accn": f"acc-{filed}", "fy": int(end[:4]), "fp": fp}
    if start:
        item["start"] = start
    return item


def _facts_payload(gaap: dict) -> dict:
    return {"entityName": "PROBE CORP", "facts": {"us-gaap": gaap}}


# Fiscal calendar (NVDA-style 52/53-week): FY2026 = 2025-01-27 → 2026-01-25.
# Post-FY 10-Qs: Q1 YTD 2026-01-26 → 2026-04-26 (90d), H1 YTD
# 2026-01-26 → 2026-07-26 (181d, fp="Q2" — the lie). Prior-year H1 YTD
# 2025-01-27 → 2025-07-27 (181d) anchors the TTM subtraction.
def _flow_chain(fy_val, q1_val, h1_val, prior_h1_val):
    return {"units": {"USD": [
        _fact("2026-01-25", fy_val, "2026-02-25", form="10-K", start="2025-01-27"),
        _fact("2026-04-26", q1_val, "2026-05-20", form="10-Q", start="2026-01-26", fp="Q1"),
        _fact("2026-07-26", h1_val, "2026-08-20", form="10-Q", start="2026-01-26", fp="Q2"),
        _fact("2025-07-27", prior_h1_val, "2025-08-20", form="10-Q", start="2025-01-27", fp="Q2"),
    ]}}


MIDYEAR_SHAPED = _facts_payload({
    "Revenues": {"units": {"USD": [
        _fact("2026-01-25", 100_000, "2026-02-25", form="10-K", start="2025-01-27"),
        _fact("2026-04-26", 30_000, "2026-05-20", form="10-Q", start="2026-01-26", fp="Q1"),
        _fact("2026-07-26", 65_000, "2026-08-20", form="10-Q", start="2026-01-26", fp="Q2"),
        # Dual-tagged DISCRETE Q2 fact (mid-year start) with a wrong value —
        # must be excluded from the YTD chain, never selected.
        _fact("2026-07-26", 999, "2026-08-20", form="10-Q", start="2026-04-27", fp="Q2"),
        _fact("2025-07-27", 40_000, "2025-08-20", form="10-Q", start="2025-01-27", fp="Q2"),
    ]}},
    "GrossProfit": _flow_chain(60_000, 18_000, 39_000, 24_000),
    "NetIncomeLoss": _flow_chain(20_000, 6_000, 13_000, 9_000),
    # YTD-ONLY flows (the 10-Q cash-flow shape — no discrete facts exist).
    "NetCashProvidedByUsedInOperatingActivities": _flow_chain(50_000, 10_000, 22_000, 15_000),
    # Capex re-runs the CB-038 trap on the quarterly path: the stale PP&E
    # tag must lose recency competition to ProductiveAssets.
    "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [
        _fact("2012-01-29", 138_735, "2012-03-13", form="10-K", start="2011-01-31"),
    ]}},
    "PaymentsToAcquireProductiveAssets": _flow_chain(8_000, 2_000, 4_500, 3_000),
    # CHAIN VIOLATIONS (both modes must yield honest N/A):
    # interest: an H1 fact with no Q1 YTD to difference and no FY fact.
    "InterestExpense": {"units": {"USD": [
        _fact("2026-07-26", 700, "2026-08-20", form="10-Q", start="2026-01-26", fp="Q2"),
    ]}},
    # dividends: FY + post-FY H1, but no Q1 YTD and no prior-year H1.
    "PaymentsOfDividends": {"units": {"USD": [
        _fact("2026-01-25", 1_000, "2026-02-25", form="10-K", start="2025-01-27"),
        _fact("2026-07-26", 500, "2026-08-20", form="10-Q", start="2026-01-26", fp="Q2"),
    ]}},
    # Balance instants: current as-of the Q2 end, plus older FY instants.
    "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
        _fact("2026-07-26", 5_000, "2026-08-20", form="10-Q"),
        _fact("2026-01-25", 4_000, "2026-02-25", form="10-K"),
    ]}},
    "Assets": {"units": {"USD": [
        _fact("2026-07-26", 200_000, "2026-08-20", form="10-Q"),
        _fact("2026-01-25", 190_000, "2026-02-25", form="10-K"),
    ]}},
    "AssetsCurrent": {"units": {"USD": [_fact("2026-07-26", 50_000, "2026-08-20", form="10-Q")]}},
    "LiabilitiesCurrent": {"units": {"USD": [_fact("2026-07-26", 20_000, "2026-08-20", form="10-Q")]}},
    "LongTermDebtNoncurrent": {"units": {"USD": [_fact("2026-07-26", 10_000, "2026-08-20", form="10-Q")]}},
    # STALE balance concept: only the FY-end instant exists — as-of gating
    # must leave it honestly absent at the Q2 anchor.
    "StockholdersEquity": {"units": {"USD": [
        _fact("2026-01-25", 120_000, "2026-02-25", form="10-K"),
    ]}},
})


# Year-end shape: the newest period on file is the fiscal year itself
# (no post-FY 10-Q yet). Latest Quarter must derive Q4 = FY − YTD_Q3;
# TTM must degenerate to FY exactly, receipted as such.
YEAR_END_SHAPED = _facts_payload({
    "Revenues": {"units": {"USD": [
        _fact("2026-01-25", 100_000, "2026-02-25", form="10-K", start="2025-01-27"),
        _fact("2025-10-26", 70_000, "2025-11-20", form="10-Q", start="2025-01-27", fp="Q3"),
    ]}},
    "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
        _fact("2026-01-25", 4_000, "2026-02-25", form="10-K"),
    ]}},
})


def _install(monkeypatch, payload):
    monkeypatch.setattr(ef, "get_cik", lambda ticker: "0000000001")
    monkeypatch.setattr(ef, "_get_companyfacts", lambda cik: payload)


def test_q2_from_ytd_differencing_not_fp_and_not_dual_tag(monkeypatch):
    """fp says 'Q2' on the 181-day H1 fact and a wrong-valued discrete
    dual-tag fact shares the same end — date arithmetic must win."""
    _install(monkeypatch, MIDYEAR_SHAPED)
    fd = ef.build_quarterly_financial_data_from_edgar_facts("NVDA", mode="quarter")
    assert fd is not None
    assert fd["revenue"] == 65_000 - 30_000          # NOT 65,000 (fp lie), NOT 999 (dual tag)
    assert fd["fiscal_year"] == "Q2 ended 2026-07-26"
    assert fd["receipts"]["revenue"].startswith("derived Q2: YTD 2026-01-26→2026-07-26")
    assert "acc-2026-08-20" in fd["receipts"]["revenue"]
    assert "acc-2026-05-20" in fd["receipts"]["revenue"]   # both component facts named


def test_ytd_only_ocf_derives_quarter_and_fcf(monkeypatch):
    _install(monkeypatch, MIDYEAR_SHAPED)
    fd = ef.build_quarterly_financial_data_from_edgar_facts("NVDA", mode="quarter")
    assert fd["operating_cash_flow"] == 22_000 - 10_000
    assert fd["capex"] == 4_500 - 2_000              # ProductiveAssets, not the stale PP&E tag
    assert "PaymentsToAcquireProductiveAssets" in fd["receipts"]["capex"]
    assert fd["free_cash_flow"] == 12_000 - 2_500


def test_ttm_is_fy_plus_ytd_minus_prior_ytd(monkeypatch):
    _install(monkeypatch, MIDYEAR_SHAPED)
    fd = ef.build_quarterly_financial_data_from_edgar_facts("NVDA", mode="ttm")
    assert fd is not None
    assert fd["revenue"] == 100_000 + 65_000 - 40_000
    assert fd["net_income"] == 20_000 + 13_000 - 9_000
    assert fd["operating_cash_flow"] == 50_000 + 22_000 - 15_000
    assert fd["free_cash_flow"] == 57_000 - (8_000 + 4_500 - 3_000)
    assert fd["fiscal_year"] == "TTM ended 2026-07-26"
    r = fd["receipts"]["revenue"]
    assert r.startswith("TTM = FY 2025-01-27→2026-01-25")
    assert "+ YTD 2026-01-26→2026-07-26" in r
    assert "− YTD 2025-01-27→2025-07-27" in r


def test_chain_violations_are_honest_na_with_no_receipt(monkeypatch):
    _install(monkeypatch, MIDYEAR_SHAPED)
    for mode in ("quarter", "ttm"):
        fd = ef.build_quarterly_financial_data_from_edgar_facts("NVDA", mode=mode)
        # interest: H1 fact with no Q1 to difference and no FY component.
        assert fd["interest_expense"] is None, mode
        assert "interest_expense" not in fd["receipts"], mode
        # dividends: no Q1 YTD (quarter) / no prior-year H1 (ttm).
        assert "dividends_paid" not in fd["receipts"], mode


def test_stale_balance_instant_gated_by_anchor_end(monkeypatch):
    """Equity's only instant is the FY end; the anchor is the Q2 end —
    the value must be honestly absent, not served stale."""
    _install(monkeypatch, MIDYEAR_SHAPED)
    fd = ef.build_quarterly_financial_data_from_edgar_facts("NVDA", mode="quarter")
    assert fd["equity"] is None
    assert "equity" not in fd["receipts"]
    assert fd["cash"] == 5_000                       # the as-of-anchor instant
    assert fd["total_assets"] == 200_000
    assert fd["current_ratio"] == 50_000 / 20_000
    assert fd["total_debt"] == 10_000
    assert "long-term only" in fd["receipts"]["total_debt"]


def test_output_contract(monkeypatch):
    _install(monkeypatch, MIDYEAR_SHAPED)
    fd = ef.build_quarterly_financial_data_from_edgar_facts("NVDA", mode="quarter")
    assert fd["source"] == "edgar"
    assert fd["scale"] == 1 and fd["_normalized"] is True
    assert fd["company_name"] == "PROBE CORP"
    assert "ebitda" not in fd                        # not an XBRL concept
    assert [row["label"] for row in fd["period_history"]] == ["Q2 ended 2026-07-26"]
    assert fd["gross_margin"] == (39_000 - 18_000) / (65_000 - 30_000)


def test_q4_derived_from_fy_minus_9m_ytd(monkeypatch):
    _install(monkeypatch, YEAR_END_SHAPED)
    fd = ef.build_quarterly_financial_data_from_edgar_facts("XXXX", mode="quarter")
    assert fd is not None
    assert fd["revenue"] == 100_000 - 70_000
    assert fd["fiscal_year"] == "Q4 ended 2026-01-25"
    assert fd["receipts"]["revenue"].startswith("derived Q4: FY 2025-01-27→2026-01-25")
    assert fd["cash"] == 4_000                       # FY-end instant is the anchor as-of


def test_ttm_degenerates_to_fy_when_no_post_fy_quarter(monkeypatch):
    _install(monkeypatch, YEAR_END_SHAPED)
    fd = ef.build_quarterly_financial_data_from_edgar_facts("XXXX", mode="ttm")
    assert fd is not None
    assert fd["revenue"] == 100_000                  # TTM == FY exactly
    assert fd["fiscal_year"] == "TTM ended 2026-01-25"
    assert "TTM equals FY exactly" in fd["receipts"]["revenue"]


def test_amendment_outranks_the_10q_it_corrects(monkeypatch):
    payload = _facts_payload({
        "Revenues": {"units": {"USD": [
            _fact("2026-01-25", 100_000, "2026-02-25", form="10-K", start="2025-01-27"),
            _fact("2026-04-26", 30_000, "2026-05-20", form="10-Q", start="2026-01-26"),
            _fact("2026-07-26", 65_000, "2026-08-20", form="10-Q", start="2026-01-26"),
            # The 10-Q/A re-states the same H1 window, filed later — it is
            # the MOST corrected statement of the period and must win.
            _fact("2026-07-26", 66_000, "2026-09-10", form="10-Q/A", start="2026-01-26"),
        ]}},
    })
    _install(monkeypatch, payload)
    fd = ef.build_quarterly_financial_data_from_edgar_facts("XXXX", mode="quarter")
    assert fd["revenue"] == 66_000 - 30_000
    assert "10-Q/A acc-2026-09-10" in fd["receipts"]["revenue"]


def test_honest_none_without_a_derivable_revenue_anchor(monkeypatch):
    payload = _facts_payload({
        # Balance-only filer shape: nothing quarterly is derivable.
        "Assets": {"units": {"USD": [_fact("2026-07-26", 1_000, "2026-08-20", form="10-Q")]}},
    })
    _install(monkeypatch, payload)
    assert ef.build_quarterly_financial_data_from_edgar_facts("XXXX", mode="quarter") is None
    assert ef.build_quarterly_financial_data_from_edgar_facts("XXXX", mode="ttm") is None


def test_invalid_mode_returns_none(monkeypatch):
    _install(monkeypatch, MIDYEAR_SHAPED)
    assert ef.build_quarterly_financial_data_from_edgar_facts("NVDA", mode="annual") is None
