"""
Tests for modules/integrity/prior_column.py -- Prior-Column Continuity Checker.

All I/O is parameterized via tmp_path.  No test ever reads or writes to the
real ~/.finlens integrity log or analysis directory.

Test cases per spec:
  1. Consecutive-year MATCH -> VERIFIED
  2. Capex-style CONFLICT   -> FLAGGED, pct_diff correct
  3. Missing field           -> PARTIAL
  4. No prior filing         -> UNCHECKED / no_prior_filing
  5. Currency mismatch       -> UNCHECKED / currency_mismatch (no FX)
  6. Corrupt prior JSON      -> UNCHECKED / reader_error (fail-closed)
  7. Multiple candidates     -> newest timestamp wins
  8. Disposition round-trip  -> reader shows DISPOSITIONED
  9. Fabrication regression  -> FLAGGED (synthetic NVDA-incident pair)
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.integrity.prior_column import (
    RECORD_TYPE,
    check_prior_column,
)
from modules.integrity.log import (
    append_prior_column_disposition_to_log,
    read_log,
)
from modules.integrity.analyze import analyze_log


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_payload(
    ticker: str,
    fiscal_year: str,
    fiscal_year_prior: str | None,
    currency: str = "USD",
    income: list[dict] | None = None,
    balance: list[dict] | None = None,
    cashflow: list[dict] | None = None,
    timestamp: str = "2026-01-01T00:00:00+00:00",
    schema_version: int = 6,
) -> dict:
    """Build a minimal analysis-cache payload."""
    financial_data: dict = {
        "company_name": f"{ticker} Inc.",
        "fiscal_year": fiscal_year,
        "fiscal_year_prior": fiscal_year_prior,
        "currency": currency,
        "income_statement": income or [],
        "balance_sheet": balance or [],
        "cash_flow_statement": cashflow or [],
    }
    return {
        "ticker": ticker,
        "period": fiscal_year,
        "timestamp": timestamp,
        "schema_version": schema_version,
        "financial_data": financial_data,
    }


def _row(line_item: str, value, value_prior=None) -> dict:
    """Build a statement row dict."""
    return {"line_item": line_item, "value": value, "value_prior": value_prior}


def _write_payload(analysis_dir: Path, filename: str, payload: dict) -> None:
    """Write a payload JSON to the analysis dir."""
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / filename).write_text(
        json.dumps(payload), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# 1. Consecutive-year MATCH -> VERIFIED
# ---------------------------------------------------------------------------

def test_verified_when_all_fields_match(tmp_path):
    """All five fields tie between N's prior column and N-1's current year."""
    analysis_dir = tmp_path / "analysis"

    # N-1 filing: FY2024 actuals (the 'value' column)
    n1 = _make_payload(
        ticker="TST",
        fiscal_year="FY2024",
        fiscal_year_prior="FY2023",
        income=[
            _row("Revenues", 1_000_000),
            _row("Net Income", 100_000),
        ],
        balance=[
            _row("Total Assets", 5_000_000),
        ],
        cashflow=[
            _row("Net Cash Provided by Operating Activities", 200_000),
            _row("Capital Expenditures", 50_000),
        ],
    )
    _write_payload(analysis_dir, "TST_FY2024.json", n1)

    # N filing: FY2025 current year + prior column matching N-1
    n = _make_payload(
        ticker="TST",
        fiscal_year="FY2025",
        fiscal_year_prior="FY2024",
        income=[
            _row("Revenues", 1_200_000, 1_000_000),
            _row("Net Income", 120_000, 100_000),
        ],
        balance=[
            _row("Total Assets", 5_500_000, 5_000_000),
        ],
        cashflow=[
            _row("Net Cash Provided by Operating Activities", 220_000, 200_000),
            _row("Capital Expenditures", 55_000, 50_000),
        ],
    )

    log_path = tmp_path / "integrity_log.jsonl"
    record = check_prior_column(n, analysis_dir=analysis_dir, log_path=log_path)

    assert record["state"] == "VERIFIED"
    assert record["record_type"] == RECORD_TYPE
    assert record["ticker"] == "TST"
    assert record["fiscal_year"] == "FY2025"
    assert record["prior_fiscal_year"] == "FY2024"
    statuses = [f["status"] for f in record["fields"]]
    assert "CONFLICT" not in statuses
    assert "MATCH" in statuses

    # Confirm the record was appended to the log.
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    logged = json.loads(lines[0])
    assert logged["state"] == "VERIFIED"


# ---------------------------------------------------------------------------
# 2. Capex-style CONFLICT -> FLAGGED, pct_diff correct
# ---------------------------------------------------------------------------

def test_flagged_on_capex_conflict(tmp_path):
    """A capex mismatch beyond 0.5% tolerance is CONFLICT -> FLAGGED."""
    analysis_dir = tmp_path / "analysis"

    n1 = _make_payload(
        ticker="CAP",
        fiscal_year="FY2023",
        fiscal_year_prior="FY2022",
        income=[_row("Revenues", 500_000), _row("Net Income", 50_000)],
        balance=[_row("Total Assets", 2_000_000)],
        cashflow=[
            _row("Net Cash Provided by Operating Activities", 80_000),
            _row("Capital Expenditures", 100_000),  # true N-1 capex
        ],
    )
    _write_payload(analysis_dir, "CAP_FY2023.json", n1)

    # N claims prior capex was 138_000 -- real incident-style divergence
    n = _make_payload(
        ticker="CAP",
        fiscal_year="FY2024",
        fiscal_year_prior="FY2023",
        income=[_row("Revenues", 600_000, 500_000), _row("Net Income", 60_000, 50_000)],
        balance=[_row("Total Assets", 2_200_000, 2_000_000)],
        cashflow=[
            _row("Net Cash Provided by Operating Activities", 90_000, 80_000),
            _row("Capital Expenditures", 120_000, 138_000),  # diverges from 100_000
        ],
    )

    log_path = tmp_path / "integrity_log.jsonl"
    record = check_prior_column(n, analysis_dir=analysis_dir, log_path=log_path)

    assert record["state"] == "FLAGGED"
    capex_field = next(f for f in record["fields"] if f["canonical_field"] == "capex")
    assert capex_field["status"] == "CONFLICT"
    # pct_diff should be non-zero and reflect the divergence
    assert capex_field["pct_diff"] is not None
    assert capex_field["pct_diff"] > 0
    # The divergence: |138_000 - 100_000| / max(138_000, 100_000) = 38/138 ~ 27.5%
    assert capex_field["pct_diff"] > 20.0


# ---------------------------------------------------------------------------
# 3. Missing field -> PARTIAL
# ---------------------------------------------------------------------------

def test_partial_when_some_fields_missing(tmp_path):
    """When capex is absent from both filings, state is PARTIAL (not FLAGGED or VERIFIED)."""
    analysis_dir = tmp_path / "analysis"

    n1 = _make_payload(
        ticker="PAR",
        fiscal_year="FY2023",
        fiscal_year_prior="FY2022",
        income=[_row("Revenues", 300_000), _row("Net Income", 30_000)],
        balance=[_row("Total Assets", 1_000_000)],
        cashflow=[_row("Net Cash Provided by Operating Activities", 60_000)],
        # No Capital Expenditures row
    )
    _write_payload(analysis_dir, "PAR_FY2023.json", n1)

    n = _make_payload(
        ticker="PAR",
        fiscal_year="FY2024",
        fiscal_year_prior="FY2023",
        income=[_row("Revenues", 350_000, 300_000), _row("Net Income", 35_000, 30_000)],
        balance=[_row("Total Assets", 1_100_000, 1_000_000)],
        cashflow=[_row("Net Cash Provided by Operating Activities", 65_000, 60_000)],
        # No Capital Expenditures row
    )

    log_path = tmp_path / "integrity_log.jsonl"
    record = check_prior_column(n, analysis_dir=analysis_dir, log_path=log_path)

    assert record["state"] == "PARTIAL"
    statuses = [f["status"] for f in record["fields"]]
    assert "MATCH" in statuses
    assert "FIELD_MISSING" in statuses
    assert "CONFLICT" not in statuses


# ---------------------------------------------------------------------------
# 4. No prior filing -> UNCHECKED / no_prior_filing
# ---------------------------------------------------------------------------

def test_unchecked_no_prior_filing(tmp_path):
    """When no prior filing exists in the analysis dir, state is UNCHECKED."""
    analysis_dir = tmp_path / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)  # empty

    n = _make_payload(
        ticker="NOP",
        fiscal_year="FY2025",
        fiscal_year_prior="FY2024",
        income=[_row("Revenues", 100_000, 90_000)],
    )

    log_path = tmp_path / "integrity_log.jsonl"
    record = check_prior_column(n, analysis_dir=analysis_dir, log_path=log_path)

    assert record["state"] == "UNCHECKED"
    assert record["reason"] == "no_prior_filing"


# ---------------------------------------------------------------------------
# 5. Currency mismatch -> UNCHECKED / currency_mismatch (no FX)
# ---------------------------------------------------------------------------

def test_unchecked_currency_mismatch(tmp_path):
    """When currencies differ, state is UNCHECKED -- no FX conversion attempted."""
    analysis_dir = tmp_path / "analysis"

    n1 = _make_payload(
        ticker="FX",
        fiscal_year="FY2023",
        fiscal_year_prior="FY2022",
        currency="CAD",  # prior filing is CAD
        income=[_row("Revenues", 1_000_000)],
    )
    _write_payload(analysis_dir, "FX_FY2023.json", n1)

    n = _make_payload(
        ticker="FX",
        fiscal_year="FY2024",
        fiscal_year_prior="FY2023",
        currency="USD",  # current filing is USD
        income=[_row("Revenues", 900_000, 750_000)],
    )

    log_path = tmp_path / "integrity_log.jsonl"
    record = check_prior_column(n, analysis_dir=analysis_dir, log_path=log_path)

    assert record["state"] == "UNCHECKED"
    assert record["reason"] == "currency_mismatch"
    # Confirm no FX conversion: no field records attempted
    assert record["fields"] == []


# ---------------------------------------------------------------------------
# 6. Corrupt prior JSON -> UNCHECKED / reader_error (fail-closed)
# ---------------------------------------------------------------------------

def test_unchecked_reader_error_on_corrupt_prior(tmp_path):
    """A corrupt prior JSON is skipped; the check returns UNCHECKED/reader_error."""
    analysis_dir = tmp_path / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    # Write a payload that parses as valid JSON and matches on ticker + period,
    # but has financial_data as a non-dict value.  _find_prior_filing finds it
    # via the top-level 'period' key; check_prior_column detects the malformed
    # financial_data and returns reader_error (fail-closed).
    (analysis_dir / "CRP_FY2023.json").write_text(
        json.dumps({
            "ticker": "CRP",
            "period": "FY2023",
            "timestamp": "2025-01-01T00:00:00+00:00",
            "financial_data": "not-a-dict",  # invalid shape -> reader_error
        }),
        encoding="utf-8",
    )

    n = _make_payload(
        ticker="CRP",
        fiscal_year="FY2024",
        fiscal_year_prior="FY2023",
        income=[_row("Revenues", 500_000, 400_000)],
    )

    log_path = tmp_path / "integrity_log.jsonl"
    record = check_prior_column(n, analysis_dir=analysis_dir, log_path=log_path)

    assert record["state"] == "UNCHECKED"
    assert record["reason"] == "reader_error"


# ---------------------------------------------------------------------------
# 7. Multiple candidates -> newest timestamp wins
# ---------------------------------------------------------------------------

def test_newest_candidate_wins(tmp_path):
    """When two files match ticker+fiscal_year_prior, the most recent timestamp wins."""
    analysis_dir = tmp_path / "analysis"

    older = _make_payload(
        ticker="WIN",
        fiscal_year="FY2023",
        fiscal_year_prior="FY2022",
        income=[_row("Revenues", 999_999)],   # wrong value -- older run
        timestamp="2024-01-01T00:00:00+00:00",
    )
    newer = _make_payload(
        ticker="WIN",
        fiscal_year="FY2023",
        fiscal_year_prior="FY2022",
        income=[_row("Revenues", 800_000)],   # correct value -- newer run
        timestamp="2025-06-01T00:00:00+00:00",
    )
    _write_payload(analysis_dir, "WIN_FY2023_old.json", older)
    _write_payload(analysis_dir, "WIN_FY2023_new.json", newer)

    n = _make_payload(
        ticker="WIN",
        fiscal_year="FY2024",
        fiscal_year_prior="FY2023",
        income=[_row("Revenues", 850_000, 800_000)],   # matches newer
    )

    log_path = tmp_path / "integrity_log.jsonl"
    record = check_prior_column(n, analysis_dir=analysis_dir, log_path=log_path)

    # Revenue should MATCH because the newer candidate's value (800_000) matches.
    revenue_field = next(
        (f for f in record["fields"] if f["canonical_field"] == "revenue"), None
    )
    assert revenue_field is not None
    assert revenue_field["status"] in ("MATCH", "FIELD_MISSING")
    # If resolved, the prior_filing value should be from the newer candidate.
    if revenue_field["status"] == "MATCH":
        assert revenue_field["value_prior_filing"] == 800_000.0

    # Confirm the newer source file was chosen.
    assert record.get("prior_source_file") == "WIN_FY2023_new.json"


# ---------------------------------------------------------------------------
# 8. Disposition round-trip -> reader shows DISPOSITIONED
# ---------------------------------------------------------------------------

def test_disposition_round_trip(tmp_path):
    """Write a disposition then confirm analyze_log renders it as DISPOSITIONED."""
    analysis_dir = tmp_path / "analysis"
    log_path = tmp_path / "integrity_log.jsonl"

    # Create a FLAGGED record.
    n1 = _make_payload(
        ticker="DIS",
        fiscal_year="FY2023",
        fiscal_year_prior="FY2022",
        cashflow=[_row("Capital Expenditures", 100_000)],
    )
    _write_payload(analysis_dir, "DIS_FY2023.json", n1)

    n = _make_payload(
        ticker="DIS",
        fiscal_year="FY2024",
        fiscal_year_prior="FY2023",
        cashflow=[_row("Capital Expenditures", 120_000, 75_000)],  # diverges
    )
    record = check_prior_column(n, analysis_dir=analysis_dir, log_path=log_path)
    assert record["state"] == "FLAGGED"

    # Write a disposition.
    append_prior_column_disposition_to_log(
        ticker="DIS",
        fiscal_year="FY2024",
        canonical_field="capex",
        checker_version="1",
        disposition="restatement",
        rationale="Q4 restatement confirmed in 2024 annual filing.",
        log_path=log_path,
    )

    # Read the log and confirm disposition is there.
    all_records = read_log(log_path)
    disp_records = [r for r in all_records if r.get("record_type") == "prior_column_disposition"]
    assert len(disp_records) == 1
    assert disp_records[0]["disposition"] == "restatement"
    assert disp_records[0]["canonical_field"] == "capex"

    # Confirm analyze_log renders DISPOSITIONED in the report.
    report = analyze_log(log_path)
    assert "DISPOSITIONED" in report


# ---------------------------------------------------------------------------
# 10. Degenerate prior year guard (fiscal_year_prior == fiscal_year)
# ---------------------------------------------------------------------------

def test_unchecked_degenerate_prior_year(tmp_path):
    """When fiscal_year_prior == fiscal_year, return UNCHECKED/degenerate_prior_year."""
    analysis_dir = tmp_path / "analysis"
    log_path = tmp_path / "integrity_log.jsonl"

    # Payload where both fiscal years are identical (bad stored data).
    payload = _make_payload(
        ticker="MSFT",
        fiscal_year="FY2010",
        fiscal_year_prior="FY2010",  # degenerate: same as current year
        income=[_row("Revenues", 62_484_000_000, 62_484_000_000)],
    )

    record = check_prior_column(payload, analysis_dir=analysis_dir, log_path=log_path)

    assert record["state"] == "UNCHECKED"
    assert record["reason"] == "degenerate_prior_year"


# ---------------------------------------------------------------------------
# 11. Self-exclusion via source_basename
# ---------------------------------------------------------------------------

def test_self_exclusion_via_source_basename(tmp_path):
    """A filing must not match itself even if fiscal_year values happen to allow it."""
    analysis_dir = tmp_path / "analysis"
    log_path = tmp_path / "integrity_log.jsonl"

    # Write the filing to disk so it appears as a candidate.
    payload = _make_payload(
        ticker="PLD",
        fiscal_year="FY2025",
        fiscal_year_prior="FY2025",  # degenerate AND in the analysis dir
        income=[_row("Revenues", 5_000_000_000)],
    )
    basename = "PLD_FY2025.json"
    _write_payload(analysis_dir, basename, payload)

    record = check_prior_column(
        payload,
        analysis_dir=analysis_dir,
        log_path=log_path,
        source_basename=basename,
    )

    # Degenerate year guard fires before the lookup, so reason is degenerate_prior_year.
    # (If somehow the degenerate guard were absent, self-exclusion prevents self-match.)
    assert record["state"] == "UNCHECKED"
    # Either guard is acceptable; the important invariant is no FLAGGED self-comparison.
    assert record["reason"] in ("degenerate_prior_year", "no_prior_filing")


# ---------------------------------------------------------------------------
# 12. All fields FIELD_MISSING -> UNCHECKED with reason no_comparable_fields
# ---------------------------------------------------------------------------

def test_unchecked_no_comparable_fields(tmp_path):
    """When both filings exist but share no resolvable v1 fields, state is UNCHECKED
    with reason 'no_comparable_fields' (not missing or unknown)."""
    analysis_dir = tmp_path / "analysis"
    log_path = tmp_path / "integrity_log.jsonl"

    # Prior filing: has only an unrecognised line item.
    n1 = _make_payload(
        ticker="NOFLD",
        fiscal_year="FY2023",
        fiscal_year_prior="FY2022",
        income=[_row("Some Other Metric", 999_000)],
    )
    _write_payload(analysis_dir, "NOFLD_FY2023.json", n1)

    # Current filing: also only unrecognised line items, and no value_prior for v1 fields.
    n = _make_payload(
        ticker="NOFLD",
        fiscal_year="FY2024",
        fiscal_year_prior="FY2023",
        income=[_row("Some Other Metric", 1_100_000, 999_000)],
    )

    record = check_prior_column(n, analysis_dir=analysis_dir, log_path=log_path)

    assert record["state"] == "UNCHECKED"
    assert record.get("reason") == "no_comparable_fields"


# ---------------------------------------------------------------------------
# 9. Fabrication regression -- synthetic NVDA-incident pair
# ---------------------------------------------------------------------------

def test_fabrication_regression_nvda_incident(tmp_path):
    """
    Synthetic pair modeled on the 2026-07-03 incident:
    N payload (FY2026) carries a prior column (FY2025) with real-FY2024-style
    numbers (138.7M capex) rather than the actual FY2025 figure (97.9M).
    The N-1 payload (FY2025) has the true FY2025 current-year capex.
    The checker must return FLAGGED.
    """
    analysis_dir = tmp_path / "analysis"

    # N-1: FY2025 as-filed (actual capex 97_890_000)
    n1 = _make_payload(
        ticker="NVDA",
        fiscal_year="FY2025",
        fiscal_year_prior="FY2024",
        cashflow=[
            _row("Net Cash Provided by Operating Activities", 64_089_000_000),
            _row("Capital Expenditures", 97_890_000),   # true FY2025 value
        ],
        income=[
            _row("Revenues", 130_497_000_000),
            _row("Net Income", 72_880_000_000),
        ],
        balance=[_row("Total Assets", 111_600_000_000)],
        currency="USD",
    )
    _write_payload(analysis_dir, "NVDA_FY2025.json", n1)

    # N: FY2026 with a fabricated prior column for capex (138_735_000 -- FY2024 actual)
    n = _make_payload(
        ticker="NVDA",
        fiscal_year="FY2026",
        fiscal_year_prior="FY2025",
        cashflow=[
            _row("Net Cash Provided by Operating Activities", 102_718_000_000, 64_089_000_000),
            _row("Capital Expenditures", 138_735_000, 138_735_000),  # wrong prior: FY2024 capex, not FY2025
        ],
        income=[
            _row("Revenues", 215_938_000_000, 130_497_000_000),
            _row("Net Income", 72_880_000_000, 72_880_000_000),
        ],
        balance=[_row("Total Assets", 130_000_000_000, 111_600_000_000)],
        currency="USD",
    )

    log_path = tmp_path / "integrity_log.jsonl"
    record = check_prior_column(n, analysis_dir=analysis_dir, log_path=log_path)

    assert record["state"] == "FLAGGED"
    capex_field = next(f for f in record["fields"] if f["canonical_field"] == "capex")
    assert capex_field["status"] == "CONFLICT"
    # 138_735_000 vs 97_890_000 -> diff > 40%
    assert capex_field["pct_diff"] is not None
    assert capex_field["pct_diff"] > 25.0
