"""SEDAR stored-mapping value snapshot.

This guards that each fixture's stored mapping matches the live mapper output
as reconstructed by the filing-registry path, including sector_override from
scripts.build_filing_registry.FILING_MANIFEST.

It does not prove that production attach_mapping() in sedar_extractor.py will
reproduce the stored mapping for filers where sector_override differs from the
fixture's raw sector_inferred value; production attach_mapping() uses only
sector_inferred. This test shares that boundary with test_filing_registry.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.integrity.sedar_mapper import map_line_items
from scripts.build_filing_registry import (
    FILING_MANIFEST,
    _line_items_from_fixture,
    _sector_argument,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "tests" / "fixtures"
SEDAR_FIXTURE_PATHS = tuple(
    sorted(FIXTURES_DIR.glob("*_sedar*.json"), key=lambda path: path.name.lower())
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "fixture_path",
    SEDAR_FIXTURE_PATHS,
    ids=lambda path: path.stem,
)
def test_sedar_fixture_stored_mapping_matches_live_mapper(fixture_path: Path):
    fixture = _load_json(fixture_path)
    stored_mapped = fixture["mapping"]["mapped"]
    sector = _sector_argument(fixture, FILING_MANIFEST[fixture_path.name])
    live_mapped = map_line_items(
        _line_items_from_fixture(fixture, sector),
        fixture["accounting_standard"],
        sector=sector,
    )["mapped"]

    missing_from_live = sorted(set(stored_mapped) - set(live_mapped))
    unexpected_live = sorted(set(live_mapped) - set(stored_mapped))
    assert not missing_from_live and not unexpected_live, (
        f"{fixture_path.name} mapping keys drifted: "
        f"missing_from_live={missing_from_live}, unexpected_live={unexpected_live}"
    )

    for field in sorted(stored_mapped):
        assert stored_mapped[field] == live_mapped[field], (
            f"{fixture_path.name} mapping drift for {field}"
        )

    assert stored_mapped == live_mapped
