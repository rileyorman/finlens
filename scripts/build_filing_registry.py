from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.integrity.sedar_mapper import map_line_items, mapper_statement_keys
from modules.sedar_periods import select_current_period_value


FIXTURES_DIR = ROOT / "tests" / "fixtures"
REGISTRY_PATH = FIXTURES_DIR / "filing_registry.json"


FILING_MANIFEST = {
    "CSU_FY2025_sedar.json": {
        "order": 1,
        "ticker": "CSU",
        "company_name": "Constellation Software Inc.",
        "fiscal_year": "FY2025",
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\CSU_FY2025.pdf",
        "commit": "f93868b",
        "notes": "filing_date null reflects known cover-date gap. PDF consolidated to canonical pdfs root 2026-06-17 (legacy .pdf.pdf double extension removed).",
    },
    "CNR_FY2025_sedar.json": {
        "order": 2,
        "ticker": "CNR",
        "company_name": "Canadian National Railway Company",
        "fiscal_year": "FY2025",
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\CNR_FY2025.pdf",
        "commit": "49f14d0",
        "notes": "PDF consolidated to canonical pdfs root 2026-06-17 (legacy .pdf.pdf double extension removed).",
    },
    "RY_FY2025_sedar.json": {
        "order": 3,
        "ticker": "RY",
        "company_name": "Royal Bank of Canada",
        "fiscal_year": "FY2025",
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\RY_FY2025.pdf",
        "sector_override": "Financial Services",
        "commit": "49f14d0",
        "notes": (
            "PDF consolidated to canonical pdfs root 2026-06-17 (legacy .pdf.pdf double extension removed). "
            "Stored fixture mapping is aligned with the "
            "financial_sector profile: stored_field_count equals resolved_field_count, and the "
            "registry row is campaign_validated."
        ),
    },
    "REIUN_FY2025_sedar.json": {
        "order": 4,
        "ticker": "REI.UN",
        "company_name": "RioCan Real Estate Investment Trust",
        "fiscal_year": "FY2025",
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\REI_UN_FY2025.pdf",
        "commit": "d8dd41c",
        "notes": (
            "filing_date resolved by cover-page extraction input; PDF consolidated to canonical pdfs root "
            "2026-06-17 (legacy .pdf.pdf double extension removed); byte-identical duplicate removed during "
            "the same consolidation; only library-registered filer."
        ),
    },
    "SHOP_FY2025_sedar.json": {
        "order": 5,
        "ticker": "SHOP",
        "company_name": "Shopify Inc.",
        "fiscal_year": "FY2025",
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\SHOP_FY2025.pdf",
        "commit": "b6e79c5",
        "notes": "",
    },
    "ATD_FY2025_sedar.json": {
        "order": 6,
        "ticker": "ATD",
        "company_name": "Alimentation Couche-Tard Inc.",
        "fiscal_year": "FY2025",
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\ATD_FY2025.pdf",
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
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\CNQ_FY2024.pdf",
        "commit": "be3c4c0",
        "notes": (
            "Fixture filename is lowercase (predates casing convention). The CID-unreadable annual-report "
            "wrapper was moved to pdfs/_superseded/ during 2026-06-17 consolidation; canonical CNQ_FY2024.pdf "
            "is now the Q4 financial statements used for extraction."
        ),
    },
    "CARUN_FY2024_sedar.json": {
        "order": 8,
        "ticker": "CAR.UN",
        "company_name": "Canadian Apartment Properties REIT",
        "fiscal_year": "FY2024",
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\CAR_UN_FY2024.pdf",
        "commit": "e012859",
        "notes": "",
    },
    "DIRUN_FY2024_sedar.json": {
        "order": 9,
        "ticker": "DIR.UN",
        "company_name": "Dream Industrial REIT",
        "fiscal_year": "FY2024",
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\DIR_UN_FY2024.pdf",
        "commit": "24cf477",
        "notes": "",
    },
    "AEM_FY2025_sedar.json": {
        "order": 10,
        "ticker": "AEM",
        "company_name": "Agnico Eagle Mines Limited",
        "fiscal_year": "FY2025",
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\AEM_FY2025.pdf",
        "commit": "60cfff3",
        "notes": (
            "Tier-3 manual issuer download; superseded FY2024 mirror moved to pdfs/_superseded/ during "
            "2026-06-17 consolidation; canonical is AEM_FY2025.pdf."
        ),
    },
    "TECKB_FY2025_sedar.json": {
        "order": 11,
        "ticker": "TECK.B",
        "company_name": "Teck Resources Limited",
        "fiscal_year": "FY2025",
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\TECK_B_FY2025.pdf",
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
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\IFC_FY2025.pdf",
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
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\SLF_FY2025.pdf",
        "commit": None,
        "notes": (
            "Manual issuer download; second insurance filer and first LIFE insurer. Standalone Q4 "
            "2025 Consolidated Financial Statements (Deloitte LLP auditor). Confirms with IFC that "
            "the IFRS 17 income-statement core is structural across P&C and Life. Resolves through "
            "insurance_sector despite sector_inferred containing 'Financial Services', preserving "
            "default net_income via 'Total net income (loss)' while adding the IFRS 17 core fields."
        ),
    },
    "NFG_FY2024_sedar.json": {
        "order": 14,
        "ticker": "NFG",
        "company_name": "New Found Gold Corp.",
        "fiscal_year": "FY2024",
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\NFG_FY2024.pdf",
        "commit": None,
        "notes": (
            "Manual issuer-IR download; first pre-revenue mining exploration filer. "
            "Resolves through mining_exploration_sector, preserving the expensed-vs-capitalized "
            "E&E split: expensed exploration maps, capitalized E&E assets remain unmapped context."
        ),
    },
    "SIG_FY2024_sedar.json": {
        "order": 15,
        "ticker": "SIG",
        "company_name": "Sitka Gold Corp.",
        "fiscal_year": "FY2024",
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\SIG_FY2024.pdf",
        "commit": None,
        "notes": (
            "Explorer-shape n=2 (the boring TSXV junior); promoted 2026-07-06 from the "
            "Sterling pilot bundle (two-read agreement 51/51 rows; provenance sha256 "
            "independently re-verified by CC on promotion). Capitalizes E&E where NFG "
            "expenses it — first live carrier of CB-009 capitalized_exploration_additions "
            "and CB-010 cash collision resolution (prefer_specific_alias). HUMAN "
            "GROUND-TRUTH: PASS (Riley, 2026-07-06, transcription protocol) — all 6 "
            "mapped fields + 8 unmapped majors tie to source, both identities close, "
            "CB-009/CB-010 verified against the filing."
        ),
    },
    "TOU_FY2025_sedar.json": {
        "order": 16,
        "ticker": "TOU",
        "company_name": "Tourmaline Oil Corp.",
        "fiscal_year": "FY2025",
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\TOU_FY2025.pdf",
        "commit": None,
        "notes": (
            "First agent-fetched corpus fixture (with ARX #17): Sterling located the "
            "issuer URL over the gateway channel, the ingest worker re-fetched "
            "independently, sha256 byte-identical across 5 fetches by promotion. "
            "CB-025 evidence base (rollup-printing gas producer: canonical revenue = "
            "'Commodity sales from production' 4,940,024; the printed net-of-royalties "
            "'Total revenue' 6,019,970 is suppressed via suppressed_default_aliases and "
            "preserved in unmapped[]) and CB-026 carrier (combined DD&A+impairment maps "
            "with includes_impairment semantics). Cross-extractor FLAGGED (soft) with "
            "11/11 value agreement — the single net_income label-scope flag "
            "dispositioned deliberate_mapping_decision (moat record 222). HUMAN "
            "GROUND-TRUTH: PASS (Riley, 2026-07-10, transcription protocol — full "
            "three-statement row inventory transcribed, 92/92 rows tie to source "
            "incl. all 11 mapped fields; net_income's clean-row provenance confirmed "
            "as the cash-flow opening line; the filer prints NO standalone total-"
            "liabilities subtotal, honest absence confirmed). Benign observation: "
            "the 6,019,970 revenue subtotal is printed UNLABELED; the stored 'Total "
            "revenue' label is extraction-assigned (value ties both years)."
        ),
    },
    "ARX_FY2025_sedar.json": {
        "order": 17,
        "ticker": "ARX",
        "company_name": "ARC Resources Ltd.",
        "fiscal_year": "FY2025",
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\ARX_FY2025.pdf",
        "commit": None,
        "notes": (
            "First agent-fetched, zero-human-upload filer to reach VERIFIED (Gemini "
            "12/12 AGREE first run, 2026-07-09). Second CB-025 carrier (canonical "
            "revenue = 'Commodity sales from production' 5,421.7; printed net 'Total "
            "revenue' 6,075.7 suppressed, preserved in unmapped[]). Typographic-"
            "apostrophe fold evidence base: 'Total shareholders' equity' 8,264.0 maps "
            "only after the U+2019 fold (CB-025 mechanism 5), which arms the "
            "balance-sheet identity — ties exactly (7,046.3 + 8,264.0 = 15,310.3). "
            "HUMAN STAMP WAIVED by Riley (2026-07-10, recorded decision; the PDF "
            "blocks text copy): CC VISUAL READ instead — statement pages rendered to "
            "pixels (pypdfium2, independent of the extraction's text layer) and all "
            "12 mapped fields + full statement pages verified, incl. the printed "
            "net-of-royalties 'Total revenue' 6,075.7 (ties: 5,421.7 − 536.8 + "
            "1,190.8) staying unmapped and the curly-apostrophe equity label in "
            "print. Benign observations: unlabeled current-asset/liability subtotals "
            "stored under standard names; tax rows stored contextualized ('Current' "
            "→ 'Current income taxes'). CB-029 (2026-07-10) promoted the deferred "
            "alias candidates surfaced at promotion: 'Exploration and evaluation "
            "asset expenditures' −53.6 → capitalized_exploration_additions "
            "(cash_flow-scoped; FCF capex is now PP&E + E&E per CB-021) and "
            "'Interest and financing' 151.3 → interest_expense "
            "(income_statement-scoped; arms EBIT/EBITDA/interest-cover per CB-023). "
            "Stored mapping regenerated 12 → 14 fields."
        ),
    },
    "TOU_Q1_2026_sedar.json": {
        "order": 18,
        "ticker": "TOU",
        "company_name": "Tourmaline Oil Corp.",
        "fiscal_year": "Q1 2026",
        "source_pdf_path": r"C:\Users\riley\.finlens\pdfs\TOU_Q1_2026.pdf",
        "commit": None,
        "notes": (
            "FIRST INTERIM fixture in the corpus (quarter-only IAS 34 pack; sibling "
            "of annual #16). CB-040 carrier: quarter-only window-class column "
            "pairing exercised live ('Three Months Ended March 31, 2026/2025' on "
            "income + cash flow; instant pair 'March 31, 2026'/'December 31, 2025' "
            "on the balance sheet); document_class statements_unaudited — this "
            "filer is the evidence base for the CB-015 notes-regex qualifier-order "
            "fix (605cddf) and the honest_period_label fix (72f58f0), both found "
            "on its first live run. Cross-document TTM live-verified against "
            "fixture #16 (all gates PASS: revenue 4,929,506 / net_income 707,554 / "
            "OCF 3,241,335 / capex -2,834,859, CAD thousands). Agent-fetched twice "
            "independently same day (CC direct download + the in-app CB-028 front "
            "door), sha256 byte-identical. HUMAN GROUND-TRUTH: PASS (Riley, "
            "2026-07-12, transcription protocol) — the four TTM input rows "
            "transcribed from the source PDF first, both columns, 8/8 "
            "byte-identical (incl. as-presented parenthetical-negative capex)."
        ),
    },
}


REGISTRY_NOTES = [
    "2026-06-17 storage consolidation: all campaign source PDFs moved to a single canonical root (~/.finlens/pdfs/) with TICKER_FYxxxx.pdf naming; superseded files in pdfs/_superseded/, non-campaign files in pdfs/_noncampaign/.",
    "AEM FY2024 annualreports.com mirror PDF and extraction artifact are superseded design-evidence only (f52ca62); moved to pdfs/_superseded/ on 2026-06-17.",
    "CNQ annual-report wrapper is CID-unreadable; the issuer-hosted Q4 financial statements are canonical (CNQ_FY2024.pdf); wrapper moved to pdfs/_superseded/ on 2026-06-17.",
    "REI.UN byte-identical duplicate removed during the 2026-06-17 consolidation; canonical is pdfs/REI_UN_FY2025.pdf.",
    "CNR, CSU, REI.UN, and RY legacy .pdf.pdf double extensions were removed during the 2026-06-17 consolidation.",
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
    # CB-040: delegates to the shared period-column ranking (this was the
    # third copy of the picker — sedar_extractor._first_statement_value and
    # the row layer are the others; triplication is the CB-021 drift
    # pattern. One source of truth now lives in modules/sedar_periods.py).
    return select_current_period_value(values or {})


def _mapping_statement_keys(sector: str | None) -> tuple[str, ...]:
    # Delegates to the mapper's single source of truth so the fixture/registry
    # path can never drift from production attach_mapping (CB-021).
    return mapper_statement_keys(sector)


def _line_items_from_fixture(fixture: dict, sector: str | None = None) -> list[dict]:
    rows = []
    sector_arg = sector if sector is not None else fixture.get("sector_inferred")
    for statement_key in _mapping_statement_keys(sector_arg):
        for item in fixture["statements"][statement_key]:
            values = item.get("values") or {}
            rows.append({
                "label": item["label"],
                "value": _mapper_source_value(values),
                "confidence": item.get("confidence"),
                "statement": statement_key,
            })
    return rows


def _sector_argument(fixture: dict, manifest_entry: dict) -> str | None:
    return manifest_entry.get("sector_override") or fixture.get("sector_inferred") or None


def _resolved_mapping(fixture: dict, sector_override: str | None) -> dict:
    return map_line_items(
        _line_items_from_fixture(fixture, sector_override),
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

    entry = {
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
    # Optional second document slot (docs/MDA_FETCHER_SPEC.md Stage 0):
    # a standalone-MD&A PDF for filers whose statement pack lacks the MD&A
    # prose. Additive — entries without one carry no key.
    if manifest_entry.get("mda_pdf_path"):
        entry["mda_pdf_path"] = manifest_entry["mda_pdf_path"]
    return entry


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
