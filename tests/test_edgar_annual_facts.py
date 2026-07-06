"""Pinning tests for edgar_fetcher._annual_facts quarterly-fact exclusion.

Reference incident (2026-07-06, PLD FY2025): Prologis XBRL-tags its
"Selected Quarterly Financial Data" note, so the FY2025 10-K accession
carries Q4-2025 duration facts with form="10-K" and fp="FY" — identical
end date and filed date to the annual fact. The shipped "prior = next item
after current in the (end, filed) sort" logic picked the Q4-2025 fact as
the prior year, producing fiscal_year_prior == fiscal_year (FY2025/FY2025)
and prior revenue = one quarter's revenue. Live-API probe evidence in the
2026-07-06 session; values below mirror the real PLD facts.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.edgar_fetcher import _annual_facts, _is_annual_duration

ACCN_FY2025 = "0001193125-26-051453"
ACCN_FY2024 = "0000950170-25-021272"


def _fact(start, end, val, accn, filed, form="10-K"):
    return {"start": start, "end": end, "val": val, "accn": accn,
            "filed": filed, "form": form, "fp": "FY"}


def _facts_payload(items):
    return {"facts": {"us-gaap": {"Revenues": {"units": {"USD": items}}}}}


# Mirrors the real PLD companyfacts shape: annual + four quarters tagged in
# the same 10-K accession, plus the prior year's annual comparative.
_PLD_LIKE = [
    _fact("2025-01-01", "2025-12-31", 8_790_127_000, ACCN_FY2025, "2026-02-13"),
    _fact("2025-10-01", "2025-12-31", 2_252_712_000, ACCN_FY2025, "2026-02-13"),
    _fact("2025-07-01", "2025-09-30", 2_213_881_000, ACCN_FY2025, "2026-02-13"),
    _fact("2025-04-01", "2025-06-30", 2_183_869_000, ACCN_FY2025, "2026-02-13"),
    _fact("2025-01-01", "2025-03-31", 2_139_665_000, ACCN_FY2025, "2026-02-13"),
    _fact("2024-01-01", "2024-12-31", 8_201_610_000, ACCN_FY2025, "2026-02-13"),
    _fact("2024-10-01", "2024-12-31", 2_200_646_000, ACCN_FY2025, "2026-02-13"),
    _fact("2024-01-01", "2024-12-31", 8_201_610_000, ACCN_FY2024, "2025-02-14"),
]


def test_prior_year_skips_quarterly_facts_tagged_in_same_10k():
    """The PLD bug: prior must be FY2024 annual, never the Q4-2025 fact."""
    current, prior = _annual_facts(_facts_payload(_PLD_LIKE), ["Revenues"], ACCN_FY2025)
    assert current["val"] == 8_790_127_000
    assert current["start"] == "2025-01-01"
    assert prior["val"] == 8_201_610_000
    assert prior["start"] == "2024-01-01"
    # the degenerate label came from prior.end sharing current's year
    assert prior["end"][:4] != current["end"][:4]


def test_current_year_never_lands_on_a_quarterly_fact():
    """Current pick was only right by JSON ordering luck — pin it.

    Put the Q4 fact BEFORE the annual fact in the payload so a stable sort
    on the tied (end, filed) key would surface Q4 first without the filter.
    """
    reordered = [_PLD_LIKE[1], _PLD_LIKE[0], *_PLD_LIKE[2:]]
    current, prior = _annual_facts(_facts_payload(reordered), ["Revenues"], ACCN_FY2025)
    assert current["val"] == 8_790_127_000
    assert prior["val"] == 8_201_610_000


def test_filers_without_quarterly_tagging_unchanged():
    """MSFT-style filers (annual facts only) keep working exactly as before."""
    annual_only = [
        _fact("2025-07-01", "2026-06-30", 300_000_000_000, "accn-a", "2026-08-01"),
        _fact("2024-07-01", "2025-06-30", 280_000_000_000, "accn-a", "2026-08-01"),
    ]
    current, prior = _annual_facts(_facts_payload(annual_only), ["Revenues"], "accn-a")
    assert current["val"] == 300_000_000_000
    assert prior["val"] == 280_000_000_000


def test_capex_falls_through_to_productive_assets_when_ppe_tag_absent():
    """NVDA capex tag coverage (open-queue item, closed 2026-07-06): NVIDIA
    tags its combined PP&E + intangibles capex under
    PaymentsToAcquireProductiveAssets; the PP&E-only concept has NO facts in
    its 10-K accessions (live-API probed). The alias list must fall through
    to the combined tag and return the filed pair (FY2026 6,042M / prior
    3,236M). Values mirror the real NVDA facts."""
    accn = "0001045810-26-000021"
    facts = {"facts": {"us-gaap": {
        # PP&E concept exists for OTHER accessions only — must not match
        "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [
            _fact("2015-01-26", "2016-01-31", 86_000_000, "old-accn", "2016-03-12"),
        ]}},
        "PaymentsToAcquireProductiveAssets": {"units": {"USD": [
            _fact("2025-01-27", "2026-01-25", 6_042_000_000, accn, "2026-02-26"),
            _fact("2024-01-29", "2025-01-26", 3_236_000_000, accn, "2026-02-26"),
        ]}},
    }}}

    current, prior = _annual_facts(
        facts,
        ["PaymentsToAcquirePropertyPlantAndEquipment",
         "CapitalExpenditureDiscontinuedOperations",
         "PaymentsToAcquireProductiveAssets"],
        accn,
    )
    assert current["val"] == 6_042_000_000
    assert prior["val"] == 3_236_000_000


def test_is_annual_duration_boundaries():
    # quarters and half-years are not annual
    assert not _is_annual_duration({"start": "2025-10-01", "end": "2025-12-31"})
    assert not _is_annual_duration({"start": "2025-07-01", "end": "2025-12-31"})
    # standard and 53-week fiscal years are annual
    assert _is_annual_duration({"start": "2025-01-01", "end": "2025-12-31"})
    assert _is_annual_duration({"start": "2024-01-29", "end": "2025-02-02"})
    # instant (balance-sheet) facts have no start — always kept
    assert _is_annual_duration({"end": "2025-12-31"})
    # unparseable dates fail open (old behavior)
    assert _is_annual_duration({"start": "garbage", "end": "2025-12-31"})
