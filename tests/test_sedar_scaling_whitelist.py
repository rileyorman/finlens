"""Guard the top-level unit-scaling whitelist against SEDAR canonical drift.

app.py promotes EVERY mapped SEDAR canonical field to a top-level
financial_data key (app.py ~848-850). normalize_financial_data() unit-scales a
fixed set of top-level scalars. If a canonical field is promoted but absent from
that set, its top-level copy stays in filing units (thousands/millions) while its
statement row is scaled to raw dollars -- a silent 1000x/1e6x magnitude bug for
the next consumer that reads the top-level key (see CLAUDE.md "Normalize at the
Boundary" + "Number Formatters Must Handle Full Magnitude Range").

Per the Minimize Human Error principle, this must not depend on a developer
remembering to update the whitelist when adding a sector profile. This test
machine-enforces that every canonical field in sedar_aliases.json is classified
exactly once: either scalable (a dollar magnitude) or explicitly non-scaled (a
ratio/margin). Adding a canonical field without classifying it fails here.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from modules.claude_analyzer import (
    _CANONICAL_SCALE_FIELDS,
    _NON_SCALED_CANONICAL_FIELDS,
    normalize_financial_data,
)

ROOT = Path(__file__).resolve().parents[1]
ALIASES_PATH = ROOT / "modules" / "integrity" / "sedar_aliases.json"


def _all_canonical_field_names() -> set[str]:
    """Every canonical field name defined in sedar_aliases.json (default profile
    plus every sector profile)."""
    aliases = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
    names: set[str] = set(aliases.get("canonical_fields", {}))
    for profile in (aliases.get("sector_profiles") or {}).values():
        names.update((profile or {}).get("canonical_fields", {}))
    return names


def test_every_canonical_field_is_classified_scale_or_no_scale():
    """The scaling whitelist plus the explicit non-scaled set must together cover
    exactly the canonical fields -- no missing field, no stale/typo'd entry."""
    canonical = _all_canonical_field_names()
    classified = set(_CANONICAL_SCALE_FIELDS) | set(_NON_SCALED_CANONICAL_FIELDS)

    unclassified = sorted(canonical - classified)
    stale_entries = sorted(classified - canonical)

    assert not unclassified, (
        "canonical field(s) promoted to top-level but not classified for unit "
        f"scaling: {unclassified}. Add each to _CANONICAL_SCALE_FIELDS (dollar "
        "magnitude) or _NON_SCALED_CANONICAL_FIELDS (ratio/margin) in "
        "modules/claude_analyzer.py."
    )
    assert not stale_entries, (
        "whitelist classifies field(s) that are not SEDAR canonical fields "
        f"(typo or removed alias?): {stale_entries}"
    )


def test_scale_and_no_scale_sets_are_disjoint():
    overlap = sorted(set(_CANONICAL_SCALE_FIELDS) & set(_NON_SCALED_CANONICAL_FIELDS))
    assert not overlap, f"field(s) classified as both scaled and non-scaled: {overlap}"


def test_promoted_sector_field_is_scaled_in_thousands_filer():
    """A REIT sector field promoted to top-level must be scaled with the unit
    factor, not left in filing units."""
    financial_data = {
        "company_name": "Thousands REIT filer",
        "currency": "CAD",
        "scale": "thousands",
        "net_operating_income": 720_404,   # promoted canonical field, in thousands
        "rental_revenue": 1_176_428,
        "revenue": 1_176_428,              # already-whitelisted control
    }

    normalized = normalize_financial_data(deepcopy(financial_data))

    assert normalized["net_operating_income"] == 720_404_000
    assert normalized["rental_revenue"] == 1_176_428_000
    assert normalized["revenue"] == 1_176_428_000


def test_non_scaled_ratio_field_is_left_untouched():
    """A ratio-type canonical field (gross_margin) must never be unit-scaled."""
    assert "gross_margin" in _NON_SCALED_CANONICAL_FIELDS
    financial_data = {
        "company_name": "Thousands filer with a margin ratio",
        "currency": "USD",
        "scale": "thousands",
        "gross_margin": 0.42,
        "revenue": 1_000,
    }

    normalized = normalize_financial_data(deepcopy(financial_data))

    assert normalized["gross_margin"] == 0.42      # untouched
    assert normalized["revenue"] == 1_000_000       # scaled control
