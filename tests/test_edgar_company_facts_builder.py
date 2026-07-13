"""CB-038 pins — build_financial_data_from_edgar_facts (as-filed quick
financials; design: docs/EDGAR_COMPANY_FACTS_SPEC.md).

The centerpiece is the NVDA phantom-capex trap, reproduced from the live
2026-07-12 probe: the stale PaymentsToAcquirePropertyPlantAndEquipment tag
HAS annual facts (ending 2012, $138.7M) — first-concept-with-facts would
serve a 14-year-old number as current capex. The recency-competition rule
must retire it automatically.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import edgar_fetcher as ef


def _fact(end, val, filed, form="10-K", start=None):
    item = {"end": end, "val": val, "filed": filed, "form": form,
            "accn": f"acc-{filed}", "fy": int(end[:4]), "fp": "FY"}
    if start:
        item["start"] = start
    return item


def _facts_payload(gaap: dict, dei: dict | None = None) -> dict:
    facts = {"us-gaap": gaap}
    if dei:
        facts["dei"] = dei
    return {"entityName": "PROBE CORP", "facts": facts}


NVDA_SHAPED = _facts_payload({
    # Revenue: two annual periods + a same-period restatement duplicate
    # (older filed) that must LOSE to the later filing.
    "Revenues": {"units": {"USD": [
        _fact("2026-01-25", 215_938_000_000, "2026-02-25", start="2025-01-27"),
        _fact("2025-01-26", 130_497_000_000, "2025-02-26", start="2024-01-29"),
        _fact("2025-01-26", 130_000_000_000, "2024-06-01", start="2024-01-29"),  # stale duplicate
    ]}},
    "CostOfRevenue": {"units": {"USD": [
        _fact("2026-01-25", 60_000_000_000, "2026-02-25", start="2025-01-27"),
        _fact("2025-01-26", 35_000_000_000, "2025-02-26", start="2024-01-29"),
    ]}},
    "NetIncomeLoss": {"units": {"USD": [
        _fact("2026-01-25", 100_000_000_000, "2026-02-25", start="2025-01-27"),
        _fact("2025-01-26", 72_880_000_000, "2025-02-26", start="2024-01-29"),
    ]}},
    "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
        _fact("2026-01-25", 102_700_000_000, "2026-02-25", start="2025-01-27"),
        _fact("2025-01-26", 64_089_000_000, "2025-02-26", start="2024-01-29"),
    ]}},
    # THE TRAP: the PP&E-only tag has annual facts — ending in 2012.
    "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [
        _fact("2012-01-29", 138_735_000, "2012-03-13", start="2011-01-31"),
    ]}},
    "PaymentsToAcquireProductiveAssets": {"units": {"USD": [
        _fact("2026-01-25", 6_042_000_000, "2026-02-25", start="2025-01-27"),
        _fact("2025-01-26", 3_236_000_000, "2025-02-26", start="2024-01-29"),
    ]}},
    "Assets": {"units": {"USD": [
        _fact("2026-01-25", 200_000_000_000, "2026-02-25"),
        _fact("2025-01-26", 111_601_000_000, "2025-02-26"),
    ]}},
    "AssetsCurrent": {"units": {"USD": [_fact("2026-01-25", 100_000_000_000, "2026-02-25")]}},
    "LiabilitiesCurrent": {"units": {"USD": [_fact("2026-01-25", 25_000_000_000, "2026-02-25")]}},
    "LongTermDebtNoncurrent": {"units": {"USD": [_fact("2026-01-25", 8_460_000_000, "2026-02-25")]}},
    "StockholdersEquity": {"units": {"USD": [_fact("2026-01-25", 120_000_000_000, "2026-02-25")]}},
    "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
        _fact("2026-01-25", 12_000_000_000, "2026-02-25"),
        _fact("2025-01-26", 8_500_000_000, "2025-02-26"),
    ]}},
})


def _install(monkeypatch, payload):
    monkeypatch.setattr(ef, "get_cik", lambda ticker: "0000000001")
    monkeypatch.setattr(ef, "_get_companyfacts", lambda cik: payload)


def test_recency_competition_retires_the_stale_ppe_tag(monkeypatch):
    _install(monkeypatch, NVDA_SHAPED)
    fd = ef.build_financial_data_from_edgar_facts("NVDA", limit=2)
    assert fd is not None
    assert fd["capex"] == 6_042_000_000                       # NOT 138_735_000
    assert "PaymentsToAcquireProductiveAssets" in fd["receipts"]["capex"]
    assert fd["free_cash_flow"] == 102_700_000_000 - 6_042_000_000


def test_restatement_duplicate_resolves_to_latest_filed(monkeypatch):
    _install(monkeypatch, NVDA_SHAPED)
    fd = ef.build_financial_data_from_edgar_facts("NVDA", limit=2)
    assert fd["revenue_prior"] == 130_497_000_000             # not the stale 130.0B


def test_output_contract_and_receipts(monkeypatch):
    _install(monkeypatch, NVDA_SHAPED)
    fd = ef.build_financial_data_from_edgar_facts("NVDA", limit=2)
    assert fd["source"] == "edgar"
    assert fd["scale"] == 1 and fd["_normalized"] is True     # raw dollars
    assert fd["revenue"] == 215_938_000_000
    assert fd["fiscal_year"] == "FY2026"
    assert fd["company_name"] == "PROBE CORP"
    # Per-figure receipt: tag + accession + form + end + unit (the Stage-4
    # hotfix — receipts carry the fact's own reporting unit).
    assert fd["receipts"]["revenue"] == (
        "us-gaap:Revenues · 10-K acc-2026-02-25 · ended 2026-01-25 · USD"
    )
    assert fd["currency"] == "USD"
    # Derivations disclose their inputs.
    assert fd["gross_profit"] == 215_938_000_000 - 60_000_000_000
    assert fd["receipts"]["gross_profit"].startswith("derived: revenue − cost")
    # CB-022 pair: LTD present, no current-portion fact — disclosed as such.
    assert fd["total_debt"] == 8_460_000_000
    assert "long-term only" in fd["receipts"]["total_debt"]
    # ebitda: not an XBRL concept — honestly absent.
    assert "ebitda" not in fd
    # dividends_paid rides top-level for the Stock Tracker snapshot
    # (FMP-zero Stage 2); no dividend facts in this payload -> honest None.
    assert fd["dividends_paid"] is None
    # period_history spans the two annual ends.
    assert [row["label"] for row in fd["period_history"]] == ["FY2026", "FY2025"]
    assert fd["period_history"][1]["revenue"] == 130_497_000_000


def test_stale_concept_emits_no_value_and_no_receipt(monkeypatch):
    """Found on the first live run: NVDA stopped filing InterestExpense
    after FY2024 — the current value must be honestly None AND no receipt
    may cite the stale fact (a receipt cites only the exact fact emitted)."""
    payload = _facts_payload({
        "Revenues": {"units": {"USD": [
            _fact("2026-01-25", 1_000_000, "2026-02-25", start="2025-01-27"),
        ]}},
        "InterestExpense": {"units": {"USD": [
            _fact("2024-01-28", 999, "2024-02-21", start="2023-01-30"),  # stale
        ]}},
    })
    _install(monkeypatch, payload)
    fd = ef.build_financial_data_from_edgar_facts("XXXX")
    assert fd["interest_expense"] is None
    assert "interest_expense" not in fd["receipts"]


def test_honest_none_without_revenue_anchor(monkeypatch):
    _install(monkeypatch, _facts_payload({
        "Assets": {"units": {"USD": [_fact("2026-01-25", 1_000, "2026-02-25")]}},
    }))
    assert ef.build_financial_data_from_edgar_facts("XXXX") is None


def test_missing_components_stay_honestly_absent(monkeypatch):
    payload = _facts_payload({
        "Revenues": {"units": {"USD": [
            _fact("2026-01-25", 1_000_000, "2026-02-25", start="2025-01-27"),
        ]}},
        # no cost, no gross profit, no OCF/capex, no debt tags
    })
    _install(monkeypatch, payload)
    fd = ef.build_financial_data_from_edgar_facts("XXXX")
    assert fd["revenue"] == 1_000_000
    assert fd["gross_profit"] is None       # cannot derive without cost
    assert fd["free_cash_flow"] is None     # CB-021: needs BOTH components
    assert fd["total_debt"] is None         # no LTD fact -> honest None
    assert fd["current_ratio"] is None
    # FMP-zero batch: per-share/share-count fields honestly absent too.
    assert fd["eps_basic"] is None
    assert fd["shares_outstanding"] is None
    assert "shares_outstanding" not in fd["receipts"]


# ---------------------------------------------------------------------------
# FMP-zero batch (2026-07-13): unit-aware selection + EPS + dei share count
# ---------------------------------------------------------------------------

def test_eps_selected_from_per_share_units(monkeypatch):
    """EPS facts live under 'USD/shares' — the monetary USD-first rule must
    not blank them, and a stray same-concept USD series must lose."""
    payload = _facts_payload({
        "Revenues": {"units": {"USD": [
            _fact("2026-01-25", 1_000_000, "2026-02-25", start="2025-01-27"),
        ]}},
        "EarningsPerShareBasic": {"units": {
            "USD/shares": [_fact("2026-01-25", 3.93, "2026-02-25", start="2025-01-27")],
            "USD": [_fact("2026-01-25", 999.0, "2026-02-25", start="2025-01-27")],
        }},
        "EarningsPerShareDiluted": {"units": {
            "USD/shares": [_fact("2026-01-25", 3.90, "2026-02-25", start="2025-01-27")],
        }},
    })
    _install(monkeypatch, payload)
    fd = ef.build_financial_data_from_edgar_facts("XXXX")
    assert fd["eps_basic"] == 3.93                     # NOT the stray USD 999.0
    assert fd["eps_diluted"] == 3.90
    assert "EarningsPerShareBasic" in fd["receipts"]["eps_basic"]


def test_dei_share_count_latest_as_of_with_receipt(monkeypatch):
    """The cover-page count is served AS-OF its own date (cover dates trail
    period ends), restatement-resolved, with the as-of framing in the
    receipt — never period-matched to a statement column."""
    payload = _facts_payload(
        {
            "Revenues": {"units": {"USD": [
                _fact("2026-01-25", 1_000_000, "2026-02-25", start="2025-01-27"),
            ]}},
        },
        dei={"EntityCommonStockSharesOutstanding": {"units": {"shares": [
            {"end": "2026-02-20", "val": 24_400_000_000, "filed": "2026-02-25",
             "form": "10-K", "accn": "acc-k"},
            {"end": "2026-02-20", "val": 24_000_000_000, "filed": "2026-01-01",
             "form": "10-Q", "accn": "acc-stale"},   # same end, earlier filed — loses
            {"end": "2025-11-20", "val": 24_500_000_000, "filed": "2025-11-25",
             "form": "10-Q", "accn": "acc-q3"},      # older as-of — loses
        ]}}},
    )
    _install(monkeypatch, payload)
    fd = ef.build_financial_data_from_edgar_facts("XXXX")
    assert fd["shares_outstanding"] == 24_400_000_000
    r = fd["receipts"]["shares_outstanding"]
    assert "dei:EntityCommonStockSharesOutstanding" in r
    assert "as of 2026-02-20" in r and "not period-matched" in r
# ---------------------------------------------------------------------------
# Stage-4 hotfix pins — the ENB trap: a dual registrant filing 10-Ks with
# CAD-unit facts. Currency must come from the facts' own units, and a field
# in a DIFFERENT unit than the revenue anchor must go honest-N/A (never
# mixed into composites, never relabeled).
# ---------------------------------------------------------------------------

ENB_SHAPED = _facts_payload({
    "Revenues": {"units": {"CAD": [
        _fact("2025-12-31", 65_194_000_000, "2026-02-13", start="2025-01-01"),
        _fact("2024-12-31", 53_000_000_000, "2025-02-14", start="2024-01-01"),
    ]}},
    "NetIncomeLoss": {"units": {"CAD": [
        _fact("2025-12-31", 6_000_000_000, "2026-02-13", start="2025-01-01"),
    ]}},
    "Assets": {"units": {"CAD": [_fact("2025-12-31", 180_000_000_000, "2026-02-13")]}},
    # Mixed-unit trap: a USD-only series on one concept must NOT ride into a
    # CAD filing's output.
    "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
        _fact("2025-12-31", 1_000_000_000, "2026-02-13"),
    ]}},
    "EarningsPerShareBasic": {"units": {"CAD/shares": [
        _fact("2025-12-31", 2.79, "2026-02-13", start="2025-01-01"),
    ]}},
})


def test_cad_unit_filer_labels_cad_never_usd(monkeypatch):
    _install(monkeypatch, ENB_SHAPED)
    fd = ef.build_financial_data_from_edgar_facts("ENB", limit=2)
    assert fd is not None
    assert fd["currency"] == "CAD"
    assert fd["revenue"] == 65_194_000_000
    assert fd["receipts"]["revenue"].endswith("· CAD")
    # Per-share facts ride the <currency>/shares unit.
    assert fd["eps_basic"] == 2.79


def test_field_in_different_unit_than_anchor_is_honest_na(monkeypatch):
    _install(monkeypatch, ENB_SHAPED)
    fd = ef.build_financial_data_from_edgar_facts("ENB", limit=2)
    assert fd["cash"] is None
    assert "cash" not in fd["receipts"]


# ---------------------------------------------------------------------------
# Stage 4.1 pins (ratified 2026-07-13) — tiered resolution for cross-listed
# Canadian issuers: us-gaap/10-K → us-gaap/40-F+20-F → ifrs-full/40-F+20-F.
# Probe-grounded shapes: TRP (us-gaap tagged in 40-F forms), CNQ (ifrs-full,
# grand Borrowings printed), SU (dead ifrs-full:Revenue tag), AEM (USD
# ifrs-full, no grand Borrowings).
# ---------------------------------------------------------------------------

def _fact40(end, val, filed, form="40-F", start=None):
    return _fact(end, val, filed, form=form, start=start)


TRP_SHAPED = {"entityName": "PROBE PIPELINE", "facts": {"us-gaap": {
    "Revenues": {"units": {"CAD": [
        _fact40("2025-12-31", 16_000_000_000, "2026-02-20", start="2025-01-01"),
    ]}},
    "NetIncomeLoss": {"units": {"CAD": [
        _fact40("2025-12-31", 4_000_000_000, "2026-02-20", start="2025-01-01"),
    ]}},
    "Assets": {"units": {"CAD": [_fact40("2025-12-31", 120_000_000_000, "2026-02-20")]}},
}}}


CNQ_SHAPED = {"entityName": "PROBE RESOURCES", "facts": {"ifrs-full": {
    "Revenue": {"units": {"CAD": [
        _fact40("2025-12-31", 38_762_000_000, "2026-03-04", start="2025-01-01"),
        _fact40("2024-12-31", 35_656_000_000, "2025-03-05", start="2024-01-01"),
    ]}},
    "ProfitLoss": {"units": {"CAD": [
        _fact40("2025-12-31", 6_100_000_000, "2026-03-04", start="2025-01-01"),
    ]}},
    "ProfitLossBeforeTax": {"units": {"CAD": [
        _fact40("2025-12-31", 8_000_000_000, "2026-03-04", start="2025-01-01"),
    ]}},
    "FinanceCosts": {"units": {"CAD": [
        _fact40("2025-12-31", 900_000_000, "2026-03-04", start="2025-01-01"),
    ]}},
    "Assets": {"units": {"CAD": [_fact40("2025-12-31", 85_000_000_000, "2026-03-04")]}},
    "Equity": {"units": {"CAD": [_fact40("2025-12-31", 42_000_000_000, "2026-03-04")]}},
    # Grand printed total AND the pair — the lift must win (one receipt).
    "Borrowings": {"units": {"CAD": [_fact40("2025-12-31", 12_000_000_000, "2026-03-04")]}},
    "LongtermBorrowings": {"units": {"CAD": [_fact40("2025-12-31", 10_000_000_000, "2026-03-04")]}},
    "CurrentPortionOfLongtermBorrowings": {"units": {"CAD": [_fact40("2025-12-31", 2_000_000_000, "2026-03-04")]}},
    "CashFlowsFromUsedInOperatingActivities": {"units": {"CAD": [
        _fact40("2025-12-31", 14_000_000_000, "2026-03-04", start="2025-01-01"),
    ]}},
    "BasicEarningsLossPerShare": {"units": {"CAD/shares": [
        _fact40("2025-12-31", 2.90, "2026-03-04", start="2025-01-01"),
    ]}},
}}}


def test_tier2_us_gaap_40f_filer_resolves_with_cad(monkeypatch):
    """TRP class: us-gaap taxonomy tagged only in 40-F forms."""
    _install(monkeypatch, TRP_SHAPED)
    fd = ef.build_financial_data_from_edgar_facts("TRP")
    assert fd is not None
    assert fd["currency"] == "CAD"
    assert fd["xbrl_taxonomy"] == "us-gaap"
    assert fd["form_note"] == "40-F/20-F annual reports (amendments included)"
    assert fd["revenue"] == 16_000_000_000
    assert "40-F" in fd["receipts"]["revenue"]


def test_tier3_ifrs_full_filer_resolves_with_lifted_borrowings(monkeypatch):
    """CNQ class: ifrs-full/40-F. The printed grand Borrowings is LIFTED
    (ratified decision 2), never composed when present."""
    _install(monkeypatch, CNQ_SHAPED)
    fd = ef.build_financial_data_from_edgar_facts("CNQ")
    assert fd is not None
    assert fd["currency"] == "CAD"
    assert fd["xbrl_taxonomy"] == "ifrs-full"
    assert fd["revenue"] == 38_762_000_000
    assert fd["receipts"]["revenue"].startswith("ifrs-full:Revenue ·")
    assert fd["net_income"] == 6_100_000_000            # ProfitLoss incl. NCI (CB-011)
    assert fd["equity"] == 42_000_000_000               # Equity incl. NCI (CB-013)
    assert fd["interest_expense"] == 900_000_000        # FinanceCosts rollup (CB-035)
    assert fd["total_debt"] == 12_000_000_000           # lifted, NOT 10B + 2B composed
    assert "Borrowings" in fd["receipts"]["total_debt"]
    assert "lifted" in fd["receipts"]["total_debt"]
    assert fd["eps_basic"] == 2.90


def test_ifrs_dead_revenue_tag_loses_recency_competition(monkeypatch):
    """SU class: bare ifrs-full:Revenue died in 2017; the current
    RevenueFromContractsWithCustomers series must win — the queue item's
    'SU is stale' claim was a concept-level artifact, not a filer fact."""
    payload = {"entityName": "PROBE ENERGY", "facts": {"ifrs-full": {
        "Revenue": {"units": {"CAD": [
            _fact40("2017-12-31", 32_000_000_000, "2018-03-01", start="2017-01-01"),
        ]}},
        "RevenueFromContractsWithCustomers": {"units": {"CAD": [
            _fact40("2025-12-31", 50_000_000_000, "2026-02-26", start="2025-01-01"),
        ]}},
    }}}
    _install(monkeypatch, payload)
    fd = ef.build_financial_data_from_edgar_facts("SU")
    assert fd["revenue"] == 50_000_000_000
    assert "RevenueFromContractsWithCustomers" in fd["receipts"]["revenue"]
    assert fd["fiscal_year"] == "FY2025"


def test_ifrs_without_borrowings_composes_with_disclosure(monkeypatch):
    """AEM class: USD ifrs-full filer with no grand Borrowings — CB-022
    pair composition, long-term-only disclosed."""
    payload = {"entityName": "PROBE GOLD", "facts": {"ifrs-full": {
        "RevenueFromContractsWithCustomers": {"units": {"USD": [
            _fact40("2025-12-31", 8_000_000_000, "2026-02-12", start="2025-01-01"),
        ]}},
        "LongtermBorrowings": {"units": {"USD": [
            _fact40("2025-12-31", 40_000_000, "2026-02-12"),
        ]}},
    }}}
    _install(monkeypatch, payload)
    fd = ef.build_financial_data_from_edgar_facts("AEM")
    assert fd["currency"] == "USD"
    assert fd["total_debt"] == 40_000_000
    assert "long-term only" in fd["receipts"]["total_debt"]


def test_tier1_wins_when_both_10k_and_ifrs_facts_exist(monkeypatch):
    """Dual-registrant precedence: a filer with us-gaap 10-K facts must
    resolve to tier 1 even when ifrs-full 40-F facts also exist — fields
    never mix tiers."""
    payload = {"entityName": "PROBE DUAL", "facts": {
        "us-gaap": {"Revenues": {"units": {"CAD": [
            _fact("2025-12-31", 65_000_000_000, "2026-02-13", start="2025-01-01"),
        ]}}},
        "ifrs-full": {"Revenue": {"units": {"CAD": [
            _fact40("2025-12-31", 99_000_000_000, "2026-02-13", start="2025-01-01"),
        ]}}},
    }}
    _install(monkeypatch, payload)
    fd = ef.build_financial_data_from_edgar_facts("ENB")
    assert fd["xbrl_taxonomy"] == "us-gaap"
    assert fd["form_note"] == "10-Ks"
    assert fd["revenue"] == 65_000_000_000


def test_quarterly_stays_honestly_refused_for_ifrs_only_filers(monkeypatch):
    """Ratified: Quarter/TTM for 40-F/20-F names is refused — 6-K interims
    are not reliably XBRL-tagged; no ifrs-full quarterly path exists."""
    _install(monkeypatch, CNQ_SHAPED)
    for mode in ("quarter", "ttm"):
        assert ef.build_quarterly_financial_data_from_edgar_facts("CNQ", mode=mode) is None


def test_stale_tier_loses_recency_competition_to_current_tier(monkeypatch):
    """Found live 2026-07-13: AEM carries ANCIENT us-gaap facts (FY2009 via
    a 2010-era 20-F) alongside CURRENT ifrs-full facts. First-tier-with-an-
    anchor would serve FY2009 as 'latest annual' — tiers must compete on
    recency exactly like concepts do."""
    payload = {"entityName": "PROBE GOLD", "facts": {
        "us-gaap": {"Revenues": {"units": {"USD": [
            _fact40("2009-12-31", 640_076_000, "2010-03-26", form="20-F", start="2009-01-01"),
        ]}}},
        "ifrs-full": {"RevenueFromContractsWithCustomers": {"units": {"USD": [
            _fact40("2025-12-31", 8_000_000_000, "2026-02-12", start="2025-01-01"),
        ]}}},
    }}
    _install(monkeypatch, payload)
    fd = ef.build_financial_data_from_edgar_facts("AEM")
    assert fd["xbrl_taxonomy"] == "ifrs-full"
    assert fd["fiscal_year"] == "FY2025"
    assert fd["revenue"] == 8_000_000_000
