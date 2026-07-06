from __future__ import annotations

# Sunday audit runner for the Gemini second-extractor integrity signal.
# Cost note: this sends campaign PDFs to Gemini. Calls cost money; the spike
# estimated roughly $0.50 per filing. Run manually, not during normal app use.

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


MODEL = "gemini-3.5-flash"
SLEEP_SECONDS = 2
FLAG_SEVERITIES = ("hard", "soft", "unclassified")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.integrity.cross_extractor import cross_check_filing

FIXTURES_DIR = ROOT / "tests" / "fixtures"
REGISTRY_PATH = FIXTURES_DIR / "filing_registry.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_gemini_api_key() -> str:
    load_dotenv(ROOT / ".env", override=False)
    return os.environ.get("GEMINI_API_KEY", "").strip()


def _campaign_entries() -> list[dict[str, Any]]:
    if not REGISTRY_PATH.exists():
        return []
    registry = _load_json(REGISTRY_PATH)
    return [
        filing
        for filing in registry.get("filings", [])
        if filing.get("source") == "sedar" and filing.get("fixture_path")
    ]


def _enriched_entry(entry: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(entry)
    enriched.setdefault("currency", fixture.get("currency"))
    enriched.setdefault("scale", fixture.get("scale"))
    enriched.setdefault("fiscal_year_end", fixture.get("fiscal_year_end"))
    return enriched


def _filer_name(entry: dict[str, Any]) -> str:
    ticker = entry.get("ticker") or Path(str(entry.get("fixture_path") or "")).stem
    fiscal_year = entry.get("fiscal_year")
    return f"{ticker} {fiscal_year}" if fiscal_year else str(ticker)


def _field_severity(field: Any) -> str:
    severity = getattr(field, "severity", None)
    return severity if severity in ("hard", "soft") else "unclassified"


def _flagged_result_severity(result: Any) -> str:
    severities = [
        _field_severity(field)
        for field in result.fields
        if getattr(field, "status", None) == "CONFLICT"
    ]
    if "hard" in severities:
        return "hard"
    if "soft" in severities:
        return "soft"
    return "unclassified"


def _result_rows(filer: str, result) -> list[dict[str, str]]:
    if not result.fields:
        return [{
            "filer": filer,
            "field": "",
            "finlens_value": "",
            "gemini_value": "",
            "finlens_label": "",
            "gemini_label": "",
            "severity": "",
            "reason": "",
            "STATUS": result.state if not result.reason else f"{result.state}:{result.reason}",
        }]
    rows = []
    for field in result.fields:
        rows.append({
            "filer": filer,
            "field": field.canonical_field,
            "finlens_value": "" if field.finlens_value is None else str(field.finlens_value),
            "gemini_value": "" if field.gemini_value is None else str(field.gemini_value),
            "finlens_label": field.finlens_label,
            "gemini_label": field.gemini_label,
            "severity": getattr(field, "severity", None) or "",
            "reason": getattr(field, "reason", None) or "",
            "STATUS": field.status,
        })
    return rows


def _print_table(rows: list[dict[str, str]]) -> None:
    headers = [
        "filer",
        "field",
        "finlens_value",
        "gemini_value",
        "finlens_label",
        "gemini_label",
        "severity",
        "reason",
        "STATUS",
    ]
    if not rows:
        print("No comparison rows produced.")
        return

    widths = [
        max(len(row.get(header, "")) for row in rows + [{header: header}])
        for header in headers
    ]
    print(" | ".join(header.ljust(widths[idx]) for idx, header in enumerate(headers)))
    print("-+-".join("-" * width for width in widths))

    previous_filer = None
    for row in rows:
        filer = row["filer"]
        if previous_filer is not None and filer != previous_filer:
            print("-+-".join("-" * width for width in widths))
        print(" | ".join(row.get(header, "").ljust(widths[idx]) for idx, header in enumerate(headers)))
        previous_filer = filer


def main() -> int:
    api_key = _load_gemini_api_key()
    entries = _campaign_entries()
    rows: list[dict[str, str]] = []
    counts = {"VERIFIED": 0, "PARTIAL": 0, "FLAGGED": 0, "UNCHECKED": 0}
    flagged_severity_counts = {severity: 0 for severity in FLAG_SEVERITIES}

    print("Gemini cross-extractor corpus run")
    print("Cost note: Gemini calls cost money; spike estimate was roughly $0.50 per filing.")
    print(f"Model: {MODEL}")
    print(f"Filers: {len(entries)}")

    for idx, entry in enumerate(entries, start=1):
        fixture_path = ROOT / str(entry.get("fixture_path") or "")
        filer = _filer_name(entry)
        print(f"[{idx}/{len(entries)}] {filer}")
        if not fixture_path.exists():
            print("  FIXTURE_NOT_FOUND; continuing.")
            continue

        fixture = _load_json(fixture_path)
        mapped = ((fixture.get("mapping") or {}).get("mapped") or {})
        result = cross_check_filing(
            _enriched_entry(entry, fixture),
            mapped,
            api_key=api_key,
            model=MODEL,
        )
        counts[result.state] = counts.get(result.state, 0) + 1
        rows.extend(_result_rows(filer, result))
        state_suffix = f" ({result.reason})" if result.reason else ""
        if result.state == "FLAGGED":
            severity = _flagged_result_severity(result)
            flagged_severity_counts[severity] += 1
            state_suffix = f" ({severity})"
        print(f"  State: {result.state}{state_suffix}")

        if idx < len(entries):
            time.sleep(SLEEP_SECONDS)

    print()
    _print_table(rows)
    print()
    print("Summary")
    print(
        f"{counts.get('VERIFIED', 0)} VERIFIED / {counts.get('PARTIAL', 0)} PARTIAL / "
        f"{counts.get('FLAGGED', 0)} FLAGGED "
        f"({flagged_severity_counts.get('hard', 0)} hard / "
        f"{flagged_severity_counts.get('soft', 0)} soft / "
        f"{flagged_severity_counts.get('unclassified', 0)} unclassified) / "
        f"{counts.get('UNCHECKED', 0)} UNCHECKED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
