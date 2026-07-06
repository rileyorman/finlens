"""Pinning tests for outcome-sensitive integrity-log idempotency.

Reference incident (2026-07-06, PLD FY2025): after the XBRL quarterly-fact
fix, the in-app re-fetch produced a CLEAN validation for the same accession
that had logged info_only the night before. append_to_log keyed on
filing_accession alone, found the stale record in the scan window, and
silently dropped the healed record — the healing transition never reached
the audit trail. Idempotency is now keyed on filing + outcome.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.integrity.engine import validate_filing
from modules.integrity.log import append_to_log, read_log

ACCN = "0001193125-26-051453"


def _filing(revenue: float, revenue_prior: float, net_income: float) -> dict:
    return {
        "company_name": "Prologis, Inc.",
        "fiscal_year": "FY2025",
        "fiscal_year_prior": "FY2024",
        "currency": "USD",
        "income_statement": [
            {"line_item": "Revenues", "value": revenue, "value_prior": revenue_prior, "row_type": "total"},
            {"line_item": "Net Income", "value": net_income, "value_prior": 3_731_635_000.0, "row_type": "total"},
        ],
        "balance_sheet": [],
        "cash_flow_statement": [],
    }


_META = {"source": "edgar", "accession": ACCN}


def test_identical_revalidation_still_dedupes(tmp_path):
    """The original idempotency goal survives: same filing, same outcome — one record."""
    log_path = tmp_path / "integrity_log.jsonl"
    filing = _filing(8_790_127_000.0, 8_201_610_000.0, 3_328_231_000.0)

    append_to_log(validate_filing(filing, "PLD", None, _META), log_path=log_path)
    append_to_log(validate_filing(filing, "PLD", None, _META), log_path=log_path)

    assert len(read_log(log_path)) == 1


def test_changed_outcome_for_same_accession_appends(tmp_path):
    """The PLD incident: a healed verdict for the same filing must append."""
    log_path = tmp_path / "integrity_log.jsonl"

    # degenerate prior column (Q4 value) — revenue_growth_sanity fires
    damaged = _filing(8_790_127_000.0, 2_252_712_000.0, 3_328_231_000.0)
    result_damaged = validate_filing(damaged, "PLD", None, _META)
    append_to_log(result_damaged, log_path=log_path)

    # healed prior column — clean run, same accession
    healed = _filing(8_790_127_000.0, 8_201_610_000.0, 3_328_231_000.0)
    result_healed = validate_filing(healed, "PLD", None, _META)
    append_to_log(result_healed, log_path=log_path)

    records = read_log(log_path)
    assert len(records) == 2, (
        "healed re-validation of the same accession was dropped as a duplicate"
    )
    # sanity: the two outcomes genuinely differ (else this test proves nothing)
    assert result_damaged.overall_status != result_healed.overall_status or any(
        c.passed != h.passed
        for c, h in zip(result_damaged.checks, result_healed.checks)
    )


def test_legacy_accession_only_records_do_not_block_new_appends(tmp_path):
    """Records written before content-hash keying must not suppress new outcomes."""
    log_path = tmp_path / "integrity_log.jsonl"
    # a legacy-format line: same accession, minimal fields, no checks detail
    legacy_line = (
        '{"timestamp": "2026-06-10T22:45:33+00:00", "ticker": "PLD", '
        f'"fiscal_year": "FY2025", "overall_status": "info_only", "filing_accession": "{ACCN}", '
        '"checks": []}'
    )
    log_path.write_text(legacy_line + "\n", encoding="utf-8")

    healed = _filing(8_790_127_000.0, 8_201_610_000.0, 3_328_231_000.0)
    append_to_log(validate_filing(healed, "PLD", None, _META), log_path=log_path)

    assert len(read_log(log_path)) == 2
