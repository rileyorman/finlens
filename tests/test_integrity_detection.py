from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.integrity.engine import validate_filing
from modules.integrity.sedar_mapper import map_line_items


BASELINE_PATH = Path(__file__).resolve().parent / "fixtures" / "NVDA_FY2026.json"
CSU_SEDAR_PATH = Path(__file__).resolve().parent / "fixtures" / "CSU_FY2025_sedar.json"
FILING_METADATA = {
    "source": "fixture",
    "filing_date": "2026-03-12",
    "accession": "poisoned-fixture",
}


def _load_nvda() -> dict:
    payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return payload["financial_data"]


def _load_csu_sedar_with_mapping() -> dict:
    payload = json.loads(CSU_SEDAR_PATH.read_text(encoding="utf-8"))
    rows = []
    for item in payload["statements"]["income_statement"]:
        values = item.get("values") or {}
        rows.append({
            "label": item["label"],
            "value": next(iter(values.values()), None),
            "confidence": item.get("confidence"),
        })
    payload["mapping"] = map_line_items(rows, payload["accounting_standard"])
    return payload


def _income_row(data: dict, label: str) -> dict:
    for row in data.get("income_statement", []):
        if row.get("line_item") == label:
            return row
    raise KeyError(label)


def _fired_rules(result) -> list[str]:
    return [c.rule_id for c in result.checks if not c.passed and not c.skipped]


def _warn_failures(result) -> list[str]:
    return [c.rule_id for c in result.checks if c.severity == "warn" and not c.passed and not c.skipped]


def _check(result, rule_id: str):
    for check in result.checks:
        if check.rule_id == rule_id:
            return check
    raise AssertionError(f"Rule not found: {rule_id}")


def poisoned_cases() -> list[tuple[str, dict, set[str]]]:
    baseline = _load_nvda()
    cases: list[tuple[str, dict, set[str]]] = []

    data = copy.deepcopy(baseline)
    revenue = _income_row(data, "Revenues")
    cost = _income_row(data, "Cost of Revenue")
    revenue["value"], cost["value"] = cost["value"], revenue["value"]
    cases.append(("swap Revenue and Cost of Revenue", data, {"revenue_reconciliation", "gross_margin_range"}))

    data = copy.deepcopy(baseline)
    data["fiscal_year"] = "FY2010"
    cases.append(("set fiscal year to 2010", data, {"fiscal_year_recency"}))

    data = copy.deepcopy(baseline)
    _income_row(data, "Revenues")["value"] = _income_row(data, "Gross Profit")["value"] / 2
    cases.append(("inflate gross margin above 100%", data, {"gross_margin_range"}))

    data = copy.deepcopy(baseline)
    _income_row(data, "Net Income")["value"] = _income_row(data, "Revenues")["value"] * 1.2
    cases.append(("set Net Income greater than Revenue", data, {"net_margin_ceiling"}))

    data = copy.deepcopy(baseline)
    revenue = _income_row(data, "Revenues")
    revenue["value_prior"] = revenue["value"] / 4
    cases.append(("set revenue growth to +300%", data, {"revenue_growth_sanity"}))

    return cases


def run_detection() -> list[dict]:
    rows = []
    for corruption, data, expected_rules in poisoned_cases():
        result = validate_filing(data, "NVDA", "Semiconductors", FILING_METADATA)
        fired = set(_fired_rules(result))
        caught = bool(fired & expected_rules)
        rows.append(
            {
                "corruption": corruption,
                "caught": caught,
                "rules": sorted(fired),
            }
        )
    return rows


def test_poisoned_fixtures_are_caught():
    rows = run_detection()
    assert all(row["caught"] for row in rows), rows


def test_sedar_extraction_confidence_rule_fires_for_low_mapped_confidence():
    data = _load_csu_sedar_with_mapping()
    data["mapping"]["mapped"]["interest_expense"]["confidence"] = 0.84

    result = validate_filing(data, "CSU", "Technology", {"source": "sedar_pdf"})

    check = _check(result, "sedar_extraction_confidence")
    assert check.severity == "warn"
    assert not check.passed
    assert check.observed_value == 0.84
    assert "Uncertain read" in check.message


def test_sedar_extraction_confidence_rule_silent_at_or_above_threshold():
    data = _load_csu_sedar_with_mapping()
    data["mapping"]["mapped"]["interest_expense"]["confidence"] = 0.85

    result = validate_filing(data, "CSU", "Technology", {"source": "sedar_pdf"})

    check = _check(result, "sedar_extraction_confidence")
    assert check.severity == "warn"
    assert check.passed


def test_sedar_pattern_match_is_informational_not_warning():
    data = _load_csu_sedar_with_mapping()
    data["mapping"]["mapped"]["interest_expense"]["match_type"] = "pattern"

    result = validate_filing(data, "CSU", "Technology", {"source": "sedar_pdf"})

    check = _check(result, "sedar_mapping_pattern_match")
    assert check.severity == "info"
    assert not check.passed
    assert "Uncertain mapping" in check.message
    assert "sedar_mapping_pattern_match" not in _warn_failures(result)


def test_sedar_accounting_standard_recorded_as_info_only():
    data = _load_csu_sedar_with_mapping()

    result = validate_filing(data, "CSU", "Technology", {"source": "sedar_pdf"})

    check = _check(result, "accounting_standard_recorded")
    assert check.severity == "info"
    assert check.passed
    assert "IFRS" in check.message
    assert result.accounting_standard == "IFRS"
    assert result.to_dict()["accounting_standard"] == "IFRS"


def test_sedar_total_assets_identity_passes_when_combined_line_matches():
    data = {
        "accounting_standard": "IFRS",
        "fiscal_year": "FY2025",
        "total_assets": 2325006,
        "mapping": {"mapped": {"total_assets": {"value": 2325006}}},
        "balance_sheet": [
            {"line_item": "Total liabilities and equity", "value": 2325006},
        ],
    }

    result = validate_filing(data, "RY", "Financial Services", {"source": "sedar_pdf"})

    check = _check(result, "sedar_total_assets_identity")
    assert check.severity == "warn"
    assert check.passed
    assert not check.skipped
    assert check.observed_value == 0


def test_sedar_total_assets_identity_flags_mismatch():
    data = {
        "accounting_standard": "IFRS",
        "fiscal_year": "FY2025",
        "total_assets": 2325006,
        "mapping": {"mapped": {"total_assets": {"value": 2325006}}},
        "balance_sheet": [
            {"line_item": "Total liabilities and shareholders' equity", "value": 2325005},
        ],
    }

    result = validate_filing(data, "RY", "Financial Services", {"source": "sedar_pdf"})

    check = _check(result, "sedar_total_assets_identity")
    assert not check.passed
    assert not check.skipped
    assert check.observed_value == 1
    assert "absolute difference" in check.message


def test_sedar_total_assets_identity_logs_skip_when_combined_line_missing():
    data = {
        "accounting_standard": "IFRS",
        "fiscal_year": "FY2025",
        "total_assets": 2325006,
        "mapping": {"mapped": {"total_assets": {"value": 2325006}}},
        "balance_sheet": [
            {"line_item": "Total liabilities", "value": 2185855},
        ],
    }

    result = validate_filing(data, "RY", "Financial Services", {"source": "sedar_pdf"})

    check = _check(result, "sedar_total_assets_identity")
    assert check.passed
    assert check.skipped
    assert check.skip_reason == "field_unavailable"


def test_unresolved_ticker_uses_company_name_and_runs_available_rules(tmp_path):
    """Filings without a resolvable ticker log under company name with ticker_unresolved=True,
    rules fire on available fields, and two different company entries don't collide on dedup."""
    from modules.integrity.log import append_to_log, read_log

    log_path = tmp_path / "integrity_log.jsonl"

    def _filing(company: str, revenue: float, net_income: float) -> dict:
        return {
            "company_name": company,
            "fiscal_year": "FY2024",
            "income_statement": [
                {"line_item": "Revenue", "value": revenue},
                {"line_item": "Net Income", "value": net_income},
            ],
            "balance_sheet": [],
            "cash_flow_statement": [],
        }

    meta = {"source": "pdf", "ticker_unresolved": True}

    result_a = validate_filing(_filing("Acme Corp", 5_000_000_000.0, 500_000_000.0), "Acme Corp", None, meta)
    append_to_log(result_a, log_path=log_path)

    result_b = validate_filing(_filing("Beta Ltd", 2_000_000_000.0, 200_000_000.0), "Beta Ltd", None, meta)
    append_to_log(result_b, log_path=log_path)

    records = read_log(log_path)

    # Both entries written — no dedup collision between different company names
    assert len(records) == 2

    rec_a = next(r for r in records if r["ticker"] == "Acme Corp")
    rec_b = next(r for r in records if r["ticker"] == "Beta Ltd")

    # Flag present and set
    assert rec_a["ticker_unresolved"] is True
    assert rec_b["ticker_unresolved"] is True

    # At least some rules ran (not an all-skipped shell)
    assert rec_a["rules_run"] > 0
    assert rec_b["rules_run"] > 0


if __name__ == "__main__":
    rows = run_detection()
    print("corruption | caught? | rule(s) fired")
    print("--- | --- | ---")
    for row in rows:
        status = "PASS" if row["caught"] else "FAIL"
        rules = ", ".join(row["rules"]) or "-"
        print(f"{row['corruption']} | {status} | {rules}")
