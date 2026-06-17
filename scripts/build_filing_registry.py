from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.integrity.sedar_mapper import map_line_items


FIXTURES_DIR = ROOT / "tests" / "fixtures"
REGISTRY_PATH = FIXTURES_DIR / "filing_registry.json"


FILING_MANIFEST = {
    "CSU_FY2025_sedar.json": {
        "order": 1,
        "ticker": "CSU",
        "company_name": "Constellation Software Inc.",
        "fiscal_year": "FY2025",
        "source_pdf_path": r"C:\Users\riley\.finlens\sedar\filings\CSU_FY2025_annual_financials.pdf.pdf",
        "commit": "f93868b",
        "notes": "Source PDF has .pdf.pdf double extension; filing_date null reflects known cover-date gap.",
    },
    "CNR_FY2025_sedar.json": {
        "order": 2,
        "ticker": "CNR",
        "company_name": "Canadian National Railway Company",
        "fiscal_year": "FY2025",
        "source_pdf_path": r"C:\Users\riley\.finlens\sedar\filings\CNR_FY2025_annual_financials.pdf.pdf",
        "commit": "49f14d0",
        "notes": "Source PDF has .pdf.pdf double extension.",
    },
    "RY_FY2025_sedar.json": {
        "order": 3,
        "ticker": "RY",
        "company_name": "Royal Bank of Canada",
        "fiscal_year": "FY2025",
        "source_pdf_path": r"C:\Users\riley\.finlens\sedar\filings\RY_FY2025_annual_financials.pdf.pdf",
        "sector_override": "Financial Services",
        "commit": "49f14d0",
        "notes": (
            "Source PDF has .pdf.pdf double extension. Stored fixture mapping is aligned with the "
            "financial_sector profile: stored_field_count equals resolved_field_count, and the "
            "registry row is campaign_validated."
        ),
    },
    "REIUN_FY2025_sedar.json": {
        "order": 4,
        "ticker": "REI.UN",
        "company_name": "RioCan Real Estate Investment Trust",
        "fiscal_year": "FY2025",
        "source_pdf_path": r"C:\Users\riley\.finlens\sedar\filings\RioCan_FY2025_annual_financials.pdf.pdf",
        "commit": "d8dd41c",
        "notes": (
            "Source PDF has .pdf.pdf double extension; filing_date resolved by cover-page extraction input; "
            r"byte-identical duplicate exists at C:\Users\riley\.finlens\pdfs\REI_UN_2025.pdf; "
            "only library-registered filer."
        ),
    },
    "SHOP_FY2025_sedar.json": {
        "order": 5,
        "ticker": "SHOP",
        "company_name": "Shopify Inc.",
        "fiscal_year": "FY2025",
        "source_pdf_path": r"C:\Users\riley\.finlens\sedar\filings\SHOP_FY2025_annual_financials.pdf",
        "commit": "b6e79c5",
        "notes": "",
    },
    "ATD_FY2025_sedar.json": {
        "order": 6,
        "ticker": "ATD",
        "company_name": "Alimentation Couche-Tard Inc.",
        "fiscal_year": "FY2025",
        "source_pdf_path": r"C:\Users\riley\.finlens\sedar\filings\ATD_FY2025_annual_financials.pdf",
        "commit": "e941cb7",
        "notes": (
            "Stored fixture mapping is aligned after the IFRS-standard normalizer refresh: "
            "stored_field_count equals resolved_field_count, including 5 mapped fields plus "
            "derived gross_profit, and the registry row is campaign_validated."
        ),
    },
    "cnq_fy2024_sedar.json": {
        "order": 7,
        "ticker": "CNQ",
        "company_name": "Canadian Natural Resources Limited",
        "fiscal_year": "FY2024",
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\CNQ_FY2024_financial_statements.pdf",
        "commit": "be3c4c0",
        "notes": (
            "Fixture filename is lowercase (predates casing convention); two source PDFs exist: "
            r"C:\Users\riley\.finlens\pdfs\CNQ_FY2024.pdf is the CID-unreadable annual report, "
            "and Q4 financial statements were used for extraction."
        ),
    },
    "CARUN_FY2024_sedar.json": {
        "order": 8,
        "ticker": "CAR.UN",
        "company_name": "Canadian Apartment Properties REIT",
        "fiscal_year": "FY2024",
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\CARUN_FY2024_annual_report.pdf",
        "commit": "e012859",
        "notes": "",
    },
    "DIRUN_FY2024_sedar.json": {
        "order": 9,
        "ticker": "DIR.UN",
        "company_name": "Dream Industrial REIT",
        "fiscal_year": "FY2024",
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\DIRUN_FY2024_annual_report.pdf",
        "commit": "24cf477",
        "notes": "",
    },
    "AEM_FY2025_sedar.json": {
        "order": 10,
        "ticker": "AEM",
        "company_name": "Agnico Eagle Mines Limited",
        "fiscal_year": "FY2025",
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\Agnico_2025-Annual-Report.pdf",
        "commit": "60cfff3",
        "notes": (
            "Tier-3 manual issuer download; orphan superseded FY2024 mirror PDF exists at "
            r"C:\Users\riley\.finlens\pdfs\AEM_FY2024_annual_report.pdf for design evidence only."
        ),
    },
    "TECKB_FY2025_sedar.json": {
        "order": 11,
        "ticker": "TECK.B",
        "company_name": "Teck Resources Limited",
        "fiscal_year": "FY2025",
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\Teck-Annual-Financial-Statements-2025.pdf",
        "commit": None,
        "notes": (
            "Tier-1 manual issuer download; polymetallic mining evidence. Existing mining_sector "
            "resolves, but Teck currently maps only gross_profit pending profile-extension review."
        ),
    },
    "IFC_FY2025_sedar.json": {
        "order": 12,
        "ticker": "IFC",
        "company_name": "Intact Financial Corporation",
        "fiscal_year": "FY2025",
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\IFC_FY2025_financial_statements.pdf",
        "commit": None,
        "notes": (
            "Manual issuer download; first P&C insurance filer (IFRS 17 evidence base). Resolves "
            "through insurance_sector after the second-insurer confirmation pass, preserving "
            "default net_income while adding the IFRS 17 core insurance fields."
        ),
    },
    "SLF_FY2025_sedar.json": {
        "order": 13,
        "ticker": "SLF",
        "company_name": "Sun Life Financial Inc.",
        "fiscal_year": "FY2025",
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\SLF_FY2025_financial_statements.pdf",
        "commit": None,
        "notes": (
            "Manual issuer download; second insurance filer and first LIFE insurer. Standalone Q4 "
            "2025 Consolidated Financial Statements (Deloitte LLP auditor). Confirms with IFC that "
            "the IFRS 17 income-statement core is structural across P&C and Life. Resolves through "
            "insurance_sector despite sector_inferred containing 'Financial Services', preserving "
            "default net_income via 'Total net income (loss)' while adding the IFRS 17 core fields."
        ),
    },
}


REGISTRY_NOTES = [
    "AEM FY2024 annualreports.com mirror PDF and extraction artifact are superseded design-evidence only (f52ca62).",
    "CNQ has two source PDFs: the annual report is CID-unreadable, so issuer-hosted Q4 financial statements were used.",
    r"REI.UN source PDF is duplicated across C:\Users\riley\.finlens\sedar\filings and C:\Users\riley\.finlens\pdfs.",
    "CNR, CSU, RioCan/REI.UN, and RY source PDFs carry the legacy .pdf.pdf double extension.",
    "cnq_fy2024_sedar.json uses lowercase fixture naming and predates the current casing convention.",
    "RY resolves through the financial_sector profile; the fixture now persists sector_inferred and its stored mapping is aligned.",
    "ATD and RY stored mappings have been realigned with the current mapper; both registry rows are campaign_validated.",
    "IFC and SLF resolve through insurance_sector; insurance routing intentionally wins before financial_sector.",
]


def _load_fixture(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _stored_field_count(fixture: dict) -> int:
    return int(((fixture.get("mapping") or {}).get("meta") or {}).get("mapped_count", 0))


def _mapper_source_value(values: dict) -> int | float | None:
    annual_candidates = []
    for idx, (period, value) in enumerate((values or {}).items()):
        period_text = str(period)
        period_lower = period_text.lower()
        if (
            "year ended" not in period_lower
            and "years ended" not in period_lower
            and not period_lower.startswith("year ")
        ):
            continue
        import re

        match = re.search(r"(\d{4})", period_text)
        year = int(match.group(1)) if match else -1
        annual_candidates.append((year, idx, value))
    if annual_candidates:
        return sorted(annual_candidates, key=lambda row: (row[0], -row[1]), reverse=True)[0][2]
    return next(iter((values or {}).values()), None)


def _line_items_from_fixture(fixture: dict) -> list[dict]:
    rows = []
    for statement_key in ("income_statement", "balance_sheet"):
        for item in fixture["statements"][statement_key]:
            values = item.get("values") or {}
            rows.append({
                "label": item["label"],
                "value": _mapper_source_value(values),
                "confidence": item.get("confidence"),
            })
    return rows


def _sector_argument(fixture: dict, manifest_entry: dict) -> str | None:
    return manifest_entry.get("sector_override") or fixture.get("sector_inferred") or None


def _resolved_mapping(fixture: dict, sector_override: str | None) -> dict:
    return map_line_items(
        _line_items_from_fixture(fixture),
        fixture["accounting_standard"],
        sector=sector_override,
    )


def _resolved_field_count(fixture: dict, sector_override: str | None) -> int:
    result = _resolved_mapping(fixture, sector_override)
    return int(result["meta"]["mapped_count"])


def _sector_profile(fixture: dict, resolved_mapping: dict) -> str | None:
    stored_profile = ((fixture.get("mapping") or {}).get("meta") or {}).get("sector_profile")
    if stored_profile:
        return stored_profile
    return resolved_mapping["meta"].get("sector_profile")


def _provenance(fixture: dict) -> dict:
    source_provenance = fixture.get("source_provenance") or {}
    issuer_url = source_provenance.get("pdf_origin_url")
    retrieval_method = source_provenance.get("retrieval_method")

    if not retrieval_method and issuer_url:
        retrieval_method = "issuer-hosted direct download; retrieval_method was not captured in fixture"
    elif not retrieval_method:
        retrieval_method = "legacy SEDAR campaign fixture; source_provenance was not captured"

    return {
        "issuer_url": issuer_url,
        "retrieval_method": retrieval_method,
    }


def _build_entry(fixture_path: Path) -> dict:
    manifest_entry = FILING_MANIFEST[fixture_path.name]
    fixture = _load_fixture(fixture_path)
    relative_fixture_path = fixture_path.relative_to(ROOT).as_posix()
    sector_override = _sector_argument(fixture, manifest_entry)
    resolved_mapping = _resolved_mapping(fixture, sector_override)
    stored_field_count = _stored_field_count(fixture)
    resolved_field_count = int(resolved_mapping["meta"]["mapped_count"])
    validation_status = (
        "campaign_validated"
        if stored_field_count == resolved_field_count
        else "stale_mapping_pending_reextract"
    )

    return {
        "ticker": manifest_entry["ticker"],
        "company_name": manifest_entry["company_name"],
        "fiscal_year": manifest_entry["fiscal_year"],
        "source": "sedar",
        "sector": _sector_profile(fixture, resolved_mapping),
        "validation_status": validation_status,
        "fixture_path": relative_fixture_path,
        "source_pdf_path": manifest_entry["source_pdf_path"],
        "provenance": _provenance(fixture),
        "stored_field_count": stored_field_count,
        "resolved_field_count": resolved_field_count,
        "filing_date": fixture.get("filing_date"),
        "commit": manifest_entry.get("commit"),
        "notes": manifest_entry.get("notes", ""),
    }


def build_registry() -> dict:
    fixture_paths = sorted(FIXTURES_DIR.glob("*_sedar*.json"))
    fixture_names = {path.name for path in fixture_paths}
    expected_names = set(FILING_MANIFEST)

    missing = sorted(expected_names - fixture_names)
    unexpected = sorted(fixture_names - expected_names)
    if missing or unexpected:
        raise RuntimeError(
            "Fixture/manifest mismatch: "
            f"missing={missing or 'none'}, unexpected={unexpected or 'none'}"
        )

    entries = [_build_entry(path) for path in fixture_paths]
    entries.sort(key=lambda entry: FILING_MANIFEST[Path(entry["fixture_path"]).name]["order"])

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "filings": entries,
        "registry_notes": REGISTRY_NOTES,
    }


def write_registry() -> dict:
    registry = build_registry()
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    return registry


def main() -> None:
    registry = write_registry()
    print(f"Wrote {REGISTRY_PATH.relative_to(ROOT).as_posix()} with {len(registry['filings'])} filings")
    print("ticker | sector | validation_status | stored_field_count | resolved_field_count")
    for filing in registry["filings"]:
        print(
            f"{filing['ticker']} | {filing['sector']} | "
            f"{filing['validation_status']} | {filing['stored_field_count']} | "
            f"{filing['resolved_field_count']}"
        )


if __name__ == "__main__":
    main()
