"""Cache mapper-version stamp + free re-map heal (cache mapper-version gap).

Covers the testable core of the heal: the mapper version stamp, the staleness
decision, and proof that re-running the mapper on a stored extraction delivers
the current mapping. The thin app.py wrapper (_heal_sedar_mapping) composes
these with the fresh-path builder and is exercised live, not here (app.py is not
test-importable — same constraint that put the CB-016 period picker in a module).
"""
from __future__ import annotations

import re

from sedar_extractor import attach_mapping
from modules.integrity import sedar_mapper
from modules.integrity.sedar_mapper import mapper_version, sedar_mapping_is_stale


def _sedar_fd(**overrides) -> dict:
    """A minimal SEDAR financial_data with a re-mappable extraction."""
    fd = {
        "source": "sedar_pdf",
        "company_name": "Test Filer Inc.",
        "ticker": "TEST",
        "_mapper_version": "stale-000000000000",
        "sedar_extraction": {
            "source": "sedar_pdf",
            "accounting_standard": "IFRS",
            "sector_inferred": "Software",
            "statements": {
                "income_statement": [
                    {
                        "label": "Total revenue",
                        "values": {
                            "Year ended December 31, 2024": 1000,
                            "Year ended December 31, 2023": 900,
                        },
                    }
                ]
            },
        },
    }
    fd.update(overrides)
    return fd


def test_mapper_version_format_and_determinism():
    v1 = mapper_version()
    v2 = mapper_version()
    assert v1 == v2  # deterministic within a run
    # "<logic-rev>-<12 hex>" (or the nofile fallback if the alias file is gone).
    assert re.fullmatch(r"\d+-([0-9a-f]{12}|nofile)", v1)


def test_mapper_version_changes_with_alias_content(tmp_path, monkeypatch):
    original = mapper_version()

    alt = tmp_path / "aliases.json"
    alt.write_bytes(b'{"schema_version": 1, "canonical_fields": {"revenue": {}}}')
    monkeypatch.setattr(sedar_mapper, "_ALIAS_FILE", alt)
    mapper_version.cache_clear()
    try:
        changed = mapper_version()
        assert changed != original  # different alias bytes -> different version
    finally:
        # Restore the real file + clear the cache so later tests see production.
        monkeypatch.undo()
        mapper_version.cache_clear()

    assert mapper_version() == original


def test_is_stale_true_for_sedar_with_old_version_and_statements():
    assert sedar_mapping_is_stale(_sedar_fd()) is True


def test_is_stale_false_when_version_current():
    fd = _sedar_fd(_mapper_version=mapper_version())
    assert sedar_mapping_is_stale(fd) is False


def test_is_stale_false_for_non_sedar_source():
    fd = _sedar_fd(source="edgar")
    assert sedar_mapping_is_stale(fd) is False


def test_is_stale_false_without_remappable_extraction():
    # No sedar_extraction at all, and extraction present but no statements.
    assert sedar_mapping_is_stale(_sedar_fd(sedar_extraction=None)) is False
    assert sedar_mapping_is_stale(_sedar_fd(sedar_extraction={"statements": {}})) is False


def test_is_stale_false_for_non_dict():
    assert sedar_mapping_is_stale(None) is False
    assert sedar_mapping_is_stale("not a dict") is False


def test_is_stale_true_when_no_version_stored_legacy_cache():
    fd = _sedar_fd()
    fd.pop("_mapper_version")
    assert sedar_mapping_is_stale(fd) is True


def test_attach_mapping_remaps_stored_extraction_to_current():
    # The delivery guarantee: re-running the mapper on the stored extraction
    # produces the current mapping (revenue mapped from "Total revenue"), even
    # if the cached copy carried an empty/old mapping.
    extraction = _sedar_fd()["sedar_extraction"]
    extraction["mapping"] = {"mapped": {}, "unmapped": [], "meta": {}}  # stale/empty

    healed = attach_mapping(extraction)
    mapped = (healed.get("mapping") or {}).get("mapped") or {}
    assert "revenue" in mapped
    assert mapped["revenue"]["value"] == 1000  # most-recent annual column
