from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.integrity.engine import validate_filing


BASELINE_PATH = Path.home() / ".finlens" / "analysis" / "NVDA_FY2026.json"
FILING_METADATA = {
    "source": "fixture",
    "filing_date": "2026-03-12",
    "accession": "poisoned-fixture",
}


def _load_nvda() -> dict:
    payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return payload["financial_data"]


def _income_row(data: dict, label: str) -> dict:
    for row in data.get("income_statement", []):
        if row.get("line_item") == label:
            return row
    raise KeyError(label)


def _fired_rules(result) -> list[str]:
    return [c.rule_id for c in result.checks if not c.passed and not c.skipped]


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


if __name__ == "__main__":
    rows = run_detection()
    print("corruption | caught? | rule(s) fired")
    print("--- | --- | ---")
    for row in rows:
        status = "PASS" if row["caught"] else "FAIL"
        rules = ", ".join(row["rules"]) or "-"
        print(f"{row['corruption']} | {status} | {rules}")
