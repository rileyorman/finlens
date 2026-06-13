"""
SEDAR+ income-statement alias mapper.

Maps verbatim extracted line-item labels to FinLens canonical fields using the
data-only alias table in sedar_aliases.json.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from .rules import FINANCIAL_SECTOR_TOKENS


_ALIAS_FILE = Path(__file__).with_name("sedar_aliases.json")


@lru_cache(maxsize=1)
def _load_alias_table() -> dict[str, Any]:
    with _ALIAS_FILE.open(encoding="utf-8") as handle:
        return json.load(handle)


def _normalize_label(label: str) -> str:
    text = re.sub(r"\s*\([^)]*\bnote\b[^)]*\)", "", str(label or ""), flags=re.IGNORECASE)
    text = text.lower().strip()
    text = re.sub(r"[\s.,;:!?]+$", "", text)
    return re.sub(r"\s+", " ", text)


def _normalize_standard(s: str) -> str:
    return s.replace(".", "").replace(" ", "").casefold()


def _standard_allowed(rule: dict[str, Any], accounting_standard: str) -> bool:
    standards = rule.get("standards") or []
    norm = _normalize_standard(accounting_standard)
    return any(_normalize_standard(s) == norm for s in standards)


def _profile_for_sector(alias_table: dict[str, Any], sector: str | None) -> str | None:
    if not sector:
        return None

    sector_profiles = alias_table.get("sector_profiles") or {}
    sector_text = str(sector).lower()

    if sector_text in sector_profiles:
        return sector_text
    if "financial_sector" in sector_profiles and any(
        token in sector_text for token in FINANCIAL_SECTOR_TOKENS
    ):
        return "financial_sector"
    return None


def _iter_target_fields(alias_table: dict[str, Any], sector_profile: str | None):
    if sector_profile:
        profile = (alias_table.get("sector_profiles") or {}).get(sector_profile, {})
        fields = (profile.get("canonical_fields") or {}).items()
        for field_name, config in fields:
            yield field_name, config
        return

    for field_name, config in (alias_table.get("canonical_fields") or {}).items():
        yield field_name, config


def _build_match_indexes(
    alias_table: dict[str, Any],
    accounting_standard: str,
    sector_profile: str | None,
) -> tuple[dict[str, str], list[tuple[str, str]]]:
    exact: dict[str, str] = {}
    patterns: list[tuple[str, str]] = []

    for field_name, config in _iter_target_fields(alias_table, sector_profile):
        for alias in config.get("aliases") or []:
            if _standard_allowed(alias, accounting_standard):
                exact[alias["label"]] = field_name
        for pattern in config.get("patterns") or []:
            if _standard_allowed(pattern, accounting_standard):
                patterns.append((pattern["starts_with"], field_name))

    return exact, patterns


def _unmapped_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": item.get("label"),
        "value": item.get("value"),
    }


def _mapped_item(item: dict[str, Any], match_type: str) -> dict[str, Any]:
    return {
        "value": item.get("value"),
        "source_label": item.get("label"),
        "match_type": match_type,
        "confidence": item.get("confidence"),
    }


def map_line_items(
    line_items: list[dict[str, Any]],
    accounting_standard: str,
    sector: str | None = None,
) -> dict[str, Any]:
    alias_table = _load_alias_table()
    sector_profile = _profile_for_sector(alias_table, sector)
    exact, patterns = _build_match_indexes(alias_table, accounting_standard, sector_profile)

    normalized_items = [
        {
            "item": item,
            "normalized_label": _normalize_label(item.get("label", "")),
        }
        for item in line_items
    ]
    duplicate_labels = {
        label for label, count in Counter(row["normalized_label"] for row in normalized_items).items()
        if count > 1
    }

    unmapped: list[dict[str, Any]] = []
    candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in normalized_items:
        item = row["item"]
        normalized_label = row["normalized_label"]

        if normalized_label in duplicate_labels:
            unmapped.append(_unmapped_item(item))
            continue

        canonical_field = exact.get(normalized_label)
        match_type = "exact"

        if canonical_field is None:
            for prefix, field_name in patterns:
                if normalized_label.startswith(prefix):
                    canonical_field = field_name
                    match_type = "pattern"
                    break

        if canonical_field is None:
            unmapped.append(_unmapped_item(item))
            continue

        candidates[canonical_field].append({
            "item": item,
            "normalized_label": normalized_label,
            "match_type": match_type,
        })

    mapped: dict[str, dict[str, Any]] = {}
    collisions: list[dict[str, Any]] = []

    for canonical_field, matches in candidates.items():
        distinct_labels = {match["normalized_label"] for match in matches}
        if len(matches) > 1 and len(distinct_labels) > 1:
            collisions.append({
                "canonical_field": canonical_field,
                "labels": [match["item"].get("label") for match in matches],
            })
            for match in matches:
                unmapped.append(_unmapped_item(match["item"]))
            continue

        match = matches[0]
        mapped[canonical_field] = _mapped_item(match["item"], match["match_type"])

    mapped_count = len(mapped)
    unmapped_count = len(unmapped)
    total = len(line_items)
    assert mapped_count + unmapped_count == total

    return {
        "mapped": mapped,
        "unmapped": unmapped,
        "meta": {
            "accounting_standard": accounting_standard,
            "sector_profile": sector_profile,
            "total": total,
            "mapped_count": mapped_count,
            "unmapped_count": unmapped_count,
            "collisions": collisions,
        },
    }
