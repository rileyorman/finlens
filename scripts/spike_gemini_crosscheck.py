from __future__ import annotations

# Standalone SEDAR/Gemini corpus validation spike.
# Dependency note: install the SDK with:
#   .\venv\Scripts\python.exe -m pip install google-genai
# Rate/cost note: this sends 13 whole PDFs to gemini-3.5-flash, roughly
# $0.50 each. The script sleeps between calls to avoid rate-limit spikes.
# This script is intentionally not wired into the production pipeline,
# integrity log, engine, or sedar_extractor.attach_mapping().

import json
import os
import re
import time
from pathlib import Path
from typing import Any


MODEL = "gemini-3.5-flash"
SLEEP_SECONDS = 2

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "tests" / "fixtures"
REGISTRY_PATH = FIXTURES_DIR / "filing_registry.json"
SEDAR_FIXTURE_PATHS = tuple(
    sorted(FIXTURES_DIR.glob("*_sedar*.json"), key=lambda path: path.name.lower())
)

FIELD_DESCRIPTIONS = {
    "cost_of_revenue": "Costs directly attributable to revenue, cost of sales, or equivalent.",
    "depletion_depreciation_amortization": "Resource-sector depletion, depreciation, and amortization expense.",
    "exploration_expense": "Mining or resource exploration expense.",
    "gross_profit": "Gross profit, or revenue less cost of revenue if clearly derivable.",
    "insurance_finance_result": "Net insurance finance income or expense under IFRS 17.",
    "insurance_revenue": "IFRS 17 insurance revenue.",
    "insurance_service_expenses": "IFRS 17 insurance service expenses.",
    "interest_expense": "Interest, finance costs, financial expenses, or equivalent expense.",
    "investment_property_fair_value_delta": "Fair value gain or loss on investment properties.",
    "mine_development_amortization": "Mining property, plant, mine development, or related amortization.",
    "net_income": "Net income, net earnings, profit, or loss attributable to the consolidated entity.",
    "net_insurance_service_result": "IFRS 17 insurance service result.",
    "net_interest_income": "Banking net interest income.",
    "net_investment_result": "Insurance net investment return or result.",
    "net_operating_income": "REIT net operating income or net rental income.",
    "operating_expense": "Resource-sector production or operating expense.",
    "operating_income": "Operating income, income from operations, or equivalent.",
    "production_costs": "Mining production costs.",
    "property_operating_costs": "REIT property operating costs or investment property operating expenses.",
    "provision_for_credit_losses": "Banking provision for credit losses.",
    "rental_revenue": "REIT rental revenue, investment property revenue, or equivalent.",
    "revenue": "Total revenue, revenues, sales, or equivalent top-line revenue.",
    "royalties": "Resource-sector royalties.",
    "total_assets": "Total assets from the consolidated balance sheet or statement of financial position.",
    "total_revenue": "Resource-sector gross total revenue or product sales before deductions.",
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _registry_by_fixture() -> dict[str, dict[str, Any]]:
    if not REGISTRY_PATH.exists():
        return {}
    registry = _load_json(REGISTRY_PATH)
    return {
        Path(filing["fixture_path"]).name: filing
        for filing in registry.get("filings", [])
        if filing.get("source") == "sedar" and filing.get("fixture_path")
    }


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    unique_paths: list[Path] = []
    for path in paths:
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        unique_paths.append(path)
    return unique_paths


def _checked_pdf_paths(fixture_path: Path, fixture: dict[str, Any], registry_entry: dict[str, Any] | None) -> list[Path]:
    home = Path.home()
    paths: list[Path] = []

    source_pdf_path = (registry_entry or {}).get("source_pdf_path")
    if source_pdf_path:
        source_path = Path(source_pdf_path)
        paths.append(source_path)
        paths.append(home / ".finlens" / "sedar" / "filings" / source_path.name)
        paths.append(home / ".finlens" / "pdfs" / source_path.name)

    provenance = fixture.get("source_provenance") or {}
    origin_url = provenance.get("pdf_origin_url") or (registry_entry or {}).get("provenance", {}).get("issuer_url")
    if origin_url:
        origin_name = origin_url.rstrip("/").split("/")[-1]
        if origin_name.lower().endswith(".pdf"):
            paths.append(home / ".finlens" / "pdfs" / origin_name)
            paths.append(home / ".finlens" / "sedar" / "filings" / origin_name)

    stem = fixture_path.stem
    paths.extend([
        home / ".finlens" / "sedar" / "filings" / f"{stem}.pdf",
        home / ".finlens" / "sedar" / "filings" / f"{stem}.pdf.pdf",
        home / ".finlens" / "pdfs" / f"{stem}.pdf",
        home / ".finlens" / "pdfs" / f"{stem}.pdf.pdf",
    ])
    return _dedupe_paths(paths)


def _locate_pdf(fixture_path: Path, fixture: dict[str, Any], registry_entry: dict[str, Any] | None) -> tuple[Path | None, list[Path]]:
    checked = _checked_pdf_paths(fixture_path, fixture, registry_entry)
    for path in checked:
        if path.exists():
            return path, checked
    return None, checked


def _filer_name(fixture_path: Path, registry_entry: dict[str, Any] | None) -> str:
    if registry_entry:
        ticker = registry_entry.get("ticker") or fixture_path.stem
        fiscal_year = registry_entry.get("fiscal_year")
        return f"{ticker} {fiscal_year}" if fiscal_year else str(ticker)
    return fixture_path.stem


def _field_lines(fields: dict[str, dict[str, Any]]) -> str:
    lines = []
    for field in fields:
        description = FIELD_DESCRIPTIONS.get(field, "FinLens canonical mapped field from the stored fixture.")
        lines.append(f"- {field}: {description}")
    return "\n".join(lines)


def _prompt(
    fixture_path: Path,
    fixture: dict[str, Any],
    registry_entry: dict[str, Any] | None,
    fields: dict[str, dict[str, Any]],
) -> str:
    company = (registry_entry or {}).get("company_name") or fixture_path.stem
    fiscal_year = (registry_entry or {}).get("fiscal_year") or fixture.get("fiscal_year_end") or ""
    currency = fixture.get("currency") or "the filing currency"
    scale = fixture.get("scale") or "the filing native scale"
    field_names = ", ".join(fields)
    return f"""
You are independently validating FinLens extraction for {company} {fiscal_year}.

Read the whole attached PDF and extract values from the consolidated financial
statements only. Return JSON ONLY, with no prose and no markdown fences, in
this exact shape:
{{"fields": [{{"canonical_field": "...", "value": <number>, "source_label": "...", "page": <int>}}]}}

Canonical fields to extract: {field_names}.

Field descriptions:
{_field_lines(fields)}

Use the filing's native units: currency={currency}, scale={scale}. Preserve
sign conventions. Use consolidated income, operations, earnings, or profit/loss
statements for income-statement fields; use the consolidated balance sheet or
statement of financial position for balance-sheet fields such as total_assets.
If a gross_profit value is not explicitly shown but is directly derivable from
displayed revenue and cost of revenue lines, return the derived value and use a
source_label that says it is derived. Omit any field you cannot find rather than
guessing.
""".strip()


def _gemini_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text:
        return str(text)
    return str(response)


def _strip_json_response(raw: str) -> str:
    text = raw.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end >= start:
        return text[start : end + 1]
    return text


def _parse_gemini_json(raw: str) -> dict[str, Any]:
    cleaned = _strip_json_response(raw)
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("fields"), list):
        raise ValueError("Gemini JSON must be an object with a fields list")
    return parsed


def _normalize_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)

    text = str(value).strip()
    if not text or text in {"-", "--", "n/a", "N/A"}:
        return None

    negative = text.startswith("(") and text.endswith(")")
    cleaned = text.replace(",", "")
    cleaned = re.sub(
        r"(?i)\b(cad|c\$|usd|us\$|dollars?|millions?|million|mn|thousands?|thousand|bn|billion)\b",
        "",
        cleaned,
    )
    cleaned = cleaned.replace("$", "").replace("(", "").replace(")", "")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None

    number = float(match.group(0))
    return -abs(number) if negative else number


def _same_sign(left: float, right: float) -> bool:
    return (left >= 0 and right >= 0) or (left < 0 and right < 0)


def _status(claude_value: float | None, gemini_value: float | None) -> str:
    if gemini_value is None:
        return "GEMINI_MISSING"
    if claude_value is None:
        return "CONFLICT"
    denominator = max(abs(claude_value), 1.0)
    relative_diff = abs(claude_value - gemini_value) / denominator
    if relative_diff <= 0.005 and _same_sign(claude_value, gemini_value):
        return "AGREE"
    return "CONFLICT"


def _gemini_fields_by_name(parsed: dict[str, Any], expected_fields: set[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in parsed.get("fields", []):
        if not isinstance(item, dict):
            continue
        field = item.get("canonical_field")
        if field in expected_fields:
            result[str(field)] = item
    return result


def _format_value(value: Any) -> str:
    normalized = _normalize_number(value)
    if normalized is None:
        return ""
    if normalized.is_integer():
        return str(int(normalized))
    return str(normalized)


def _compare_fields(
    filer: str,
    claude_fields: dict[str, dict[str, Any]],
    gemini_fields: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, str]], dict[str, int]]:
    rows: list[dict[str, str]] = []
    counts = {"AGREE": 0, "CONFLICT": 0, "GEMINI_MISSING": 0}

    for field, claude in claude_fields.items():
        gemini = gemini_fields.get(field)
        claude_value = _normalize_number(claude.get("value"))
        gemini_value = _normalize_number(gemini.get("value")) if gemini else None
        status = _status(claude_value, gemini_value)
        counts[status] += 1
        rows.append({
            "filer": filer,
            "field": field,
            "claude_value": _format_value(claude.get("value")),
            "gemini_value": _format_value(gemini.get("value")) if gemini else "",
            "claude_label": str(claude.get("source_label", "")),
            "gemini_label": str(gemini.get("source_label", "")) if gemini else "",
            "gemini_page": str(gemini.get("page", "")) if gemini else "",
            "STATUS": status,
        })
    return rows, counts


def _print_table(rows: list[dict[str, str]]) -> None:
    headers = [
        "filer",
        "field",
        "claude_value",
        "gemini_value",
        "claude_label",
        "gemini_label",
        "gemini_page",
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


def _run_gemini(pdf_path: Path, prompt: str, api_key: str) -> str:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise SystemExit(
            "google-genai is not installed. Install it with: "
            r".\venv\Scripts\python.exe -m pip install google-genai"
        ) from exc

    client = genai.Client(api_key=api_key)
    pdf_part = types.Part.from_bytes(
        data=pdf_path.read_bytes(),
        mime_type="application/pdf",
    )
    response = client.models.generate_content(
        model=MODEL,
        contents=[prompt, pdf_part],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    return _gemini_text(response)


def _print_final_summary(
    filer_counts: dict[str, dict[str, int]],
    conflicts_by_filer: dict[str, list[str]],
    missing_by_filer: dict[str, list[str]],
    pdf_not_found: dict[str, list[Path]],
    errors: dict[str, str],
) -> None:
    clean = [
        filer
        for filer, counts in filer_counts.items()
        if counts["CONFLICT"] == 0 and counts["GEMINI_MISSING"] == 0
    ]
    with_conflicts = {
        filer: fields
        for filer, fields in conflicts_by_filer.items()
        if fields
    }
    with_missing = {
        filer: fields
        for filer, fields in missing_by_filer.items()
        if fields
    }

    print()
    print("Final summary")
    print(f"CLEAN filers: {', '.join(clean) if clean else '(none)'}")
    if with_conflicts:
        conflict_text = "; ".join(
            f"{filer}: {', '.join(fields)}"
            for filer, fields in with_conflicts.items()
        )
    else:
        conflict_text = "(none)"
    print(f"Filers WITH CONFLICTS: {conflict_text}")
    if with_missing:
        missing_text = "; ".join(
            f"{filer}: {', '.join(fields)}"
            for filer, fields in with_missing.items()
        )
    else:
        missing_text = "(none)"
    print(f"Filers WITH GEMINI_MISSING fields: {missing_text}")
    print(f"PDF_NOT_FOUND filers: {', '.join(pdf_not_found) if pdf_not_found else '(none)'}")
    print(f"Errored filers: {len(errors)}")
    for filer, error in errors.items():
        print(f"  {filer}: {error}")

    if pdf_not_found:
        print()
        print("PDF_NOT_FOUND paths checked")
        for filer, paths in pdf_not_found.items():
            print(f"{filer}:")
            for path in paths:
                print(f"  {path}")


def main() -> int:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY is not set. Set it in the environment and rerun.")
        return 1

    registry_by_fixture = _registry_by_fixture()
    all_rows: list[dict[str, str]] = []
    filer_counts: dict[str, dict[str, int]] = {}
    conflicts_by_filer: dict[str, list[str]] = {}
    pdf_not_found: dict[str, list[Path]] = {}
    errors: dict[str, str] = {}
    missing_by_filer: dict[str, list[str]] = {}

    for idx, fixture_path in enumerate(SEDAR_FIXTURE_PATHS, start=1):
        fixture = _load_json(fixture_path)
        registry_entry = registry_by_fixture.get(fixture_path.name)
        filer = _filer_name(fixture_path, registry_entry)
        claude_fields = fixture["mapping"]["mapped"]
        print(f"[{idx}/{len(SEDAR_FIXTURE_PATHS)}] {filer}: {len(claude_fields)} fields")

        pdf_path, checked_paths = _locate_pdf(fixture_path, fixture, registry_entry)
        if pdf_path is None:
            print(f"  PDF_NOT_FOUND for {filer}; continuing.")
            pdf_not_found[filer] = checked_paths
            continue

        raw = ""
        try:
            prompt = _prompt(fixture_path, fixture, registry_entry, claude_fields)
            raw = _run_gemini(pdf_path, prompt, api_key)
            parsed = _parse_gemini_json(raw)
            gemini_fields = _gemini_fields_by_name(parsed, set(claude_fields))
            rows, counts = _compare_fields(filer, claude_fields, gemini_fields)
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"  PARSE_ERROR for {filer}: {exc}; continuing.")
            print("  Raw Gemini response:")
            for line in str(raw).splitlines():
                print(f"    {line}")
            errors[filer] = f"PARSE_ERROR: {exc}"
            continue
        except Exception as exc:
            print(f"  ERROR for {filer}: {exc}; continuing.")
            errors[filer] = str(exc)
            continue

        all_rows.extend(rows)
        filer_counts[filer] = counts
        conflicts_by_filer[filer] = [
            row["field"]
            for row in rows
            if row["STATUS"] == "CONFLICT"
        ]
        missing_by_filer[filer] = [
            row["field"]
            for row in rows
            if row["STATUS"] == "GEMINI_MISSING"
        ]
        print(
            f"  Summary: {counts['AGREE']} agree / "
            f"{counts['CONFLICT']} conflict / {counts['GEMINI_MISSING']} missing"
        )

        if idx < len(SEDAR_FIXTURE_PATHS):
            time.sleep(SLEEP_SECONDS)

    print()
    _print_table(all_rows)
    print()
    print("Per-filer summaries")
    for filer, counts in filer_counts.items():
        print(
            f"{filer}: {counts['AGREE']} agree / "
            f"{counts['CONFLICT']} conflict / {counts['GEMINI_MISSING']} missing"
        )
    _print_final_summary(filer_counts, conflicts_by_filer, missing_by_filer, pdf_not_found, errors)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
