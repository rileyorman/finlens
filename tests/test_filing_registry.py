from __future__ import annotations

import json
from pathlib import Path

from modules.integrity.sedar_mapper import _is_mining_family_sector, map_line_items
from scripts.build_filing_registry import FILING_MANIFEST


ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "tests" / "fixtures"
REGISTRY_PATH = FIXTURES_DIR / "filing_registry.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture_mapped_count(path: Path) -> int:
    fixture = _load_json(path)
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


def _mapping_statement_keys(sector: str | None) -> tuple[str, ...]:
    if _is_mining_family_sector(sector):
        return ("income_statement", "balance_sheet", "cash_flow")
    return ("income_statement", "balance_sheet")


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


def _resolved_mapped_count(fixture_path: Path) -> int:
    fixture = _load_json(fixture_path)
    manifest_entry = FILING_MANIFEST[fixture_path.name]
    sector_override = manifest_entry.get("sector_override") or fixture.get("sector_inferred") or None
    result = map_line_items(
        _line_items_from_fixture(fixture, sector_override),
        fixture["accounting_standard"],
        sector=sector_override,
    )
    return int(result["meta"]["mapped_count"])


def _registry() -> dict:
    return _load_json(REGISTRY_PATH)


def test_every_sedar_fixture_has_registry_entry():
    fixture_paths = {
        path.relative_to(ROOT).as_posix()
        for path in FIXTURES_DIR.glob("*_sedar*.json")
    }
    registry_paths = {
        filing["fixture_path"]
        for filing in _registry()["filings"]
        if filing["source"] == "sedar"
    }

    assert fixture_paths <= registry_paths


def test_sedar_registry_fixture_paths_exist_and_pdf_paths_are_recorded():
    for filing in _registry()["filings"]:
        if filing["source"] != "sedar":
            continue

        assert (ROOT / filing["fixture_path"]).exists()
        assert filing["source_pdf_path"]


def test_registry_stored_field_counts_match_fixtures():
    for filing in _registry()["filings"]:
        if filing["source"] != "sedar":
            continue

        fixture_path = ROOT / filing["fixture_path"]
        assert filing["stored_field_count"] == _fixture_mapped_count(fixture_path)


def test_registry_resolved_field_counts_match_live_mapper():
    for filing in _registry()["filings"]:
        if filing["source"] != "sedar":
            continue

        fixture_path = ROOT / filing["fixture_path"]
        assert filing["resolved_field_count"] == _resolved_mapped_count(fixture_path)


def test_registry_validation_status_follows_uniform_staleness_rule():
    for filing in _registry()["filings"]:
        if filing["source"] != "sedar":
            continue

        expected = (
            "campaign_validated"
            if filing["stored_field_count"] == filing["resolved_field_count"]
            else "stale_mapping_pending_reextract"
        )
        assert filing["validation_status"] == expected
