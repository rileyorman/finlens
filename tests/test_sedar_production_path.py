"""SEDAR production-path mapping guard.

Companion to tests/test_sedar_value_snapshot.py, which reconstructs the mapper
input via the filing-registry path (build_filing_registry, including
sector_override from FILING_MANIFEST). That path is NOT the one users hit: for
a filer whose registry sector_override differs from its raw sector_inferred
(currently RY: override "Financial Services" vs inferred "Banking"), the
snapshot test proves nothing about production.

This test closes that gap by driving the ACTUAL production function
sedar_extractor.attach_mapping() — which uses sector_inferred, its own
value-extraction helper, and its own statement-key selection — over each
stored fixture and asserting it reproduces the stored mapping. A fixture is
shaped like a stored extraction_result (statements / sector_inferred /
accounting_standard), so it can be fed straight in.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sedar_extractor import attach_mapping
from scripts.build_filing_registry import FILING_MANIFEST

FIXTURES_DIR = ROOT / "tests" / "fixtures"
SEDAR_FIXTURE_PATHS = tuple(
    sorted(FIXTURES_DIR.glob("*_sedar*.json"), key=lambda path: path.name.lower())
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _override_differs_from_inferred(path: Path) -> bool:
    """True where the registry sector_override != the fixture's raw sector_inferred.

    These are exactly the filers the registry-path snapshot test does not cover
    for production, because production attach_mapping() ignores the override.
    """
    fixture = _load_json(path)
    override = FILING_MANIFEST[path.name].get("sector_override")
    return bool(override) and override != fixture.get("sector_inferred")


@pytest.mark.parametrize(
    "fixture_path",
    SEDAR_FIXTURE_PATHS,
    ids=lambda path: path.stem,
)
def test_production_attach_mapping_reproduces_stored_mapping(fixture_path: Path):
    """The path users hit (attach_mapping via sector_inferred) must match the
    stored fixture mapping, for every SEDAR filer."""
    fixture = _load_json(fixture_path)
    stored_mapped = fixture["mapping"]["mapped"]

    produced_mapped = attach_mapping(fixture)["mapping"]["mapped"]

    missing_from_produced = sorted(set(stored_mapped) - set(produced_mapped))
    unexpected_produced = sorted(set(produced_mapped) - set(stored_mapped))
    assert not missing_from_produced and not unexpected_produced, (
        f"{fixture_path.name} production mapping keys drifted: "
        f"missing_from_produced={missing_from_produced}, "
        f"unexpected_produced={unexpected_produced}"
    )

    for field in sorted(stored_mapped):
        assert stored_mapped[field] == produced_mapped[field], (
            f"{fixture_path.name} production mapping drift for {field}: "
            f"stored={stored_mapped[field]} produced={produced_mapped[field]}"
        )

    assert stored_mapped == produced_mapped


def test_override_differs_from_inferred_population_is_exercised():
    """Pin the coverage-gap population so it cannot silently empty out.

    The whole reason this file exists is the override!=inferred case. If a future
    change removes RY's override (or realigns its sector_inferred), this test
    fails loudly rather than letting the parametrized guard pass vacuously for
    the case it was written to protect.
    """
    differing = sorted(
        path.name for path in SEDAR_FIXTURE_PATHS if _override_differs_from_inferred(path)
    )
    assert differing == ["RY_FY2025_sedar.json"], (
        "override!=inferred population changed; update this guard deliberately: "
        f"{differing}"
    )
