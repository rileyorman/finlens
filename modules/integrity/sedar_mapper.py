"""
SEDAR+ income-statement alias mapper.

Maps verbatim extracted line-item labels to FinLens canonical fields using the
data-only alias table in sedar_aliases.json.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
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
    compact = re.sub(r"[^a-z0-9]", "", str(s or "").casefold())
    if compact.startswith("ifrs"):
        return "ifrs"
    if compact.startswith("usgaap") or compact.startswith("unitedstatesgaap"):
        return "usgaap"
    return compact


def _coerce_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
) -> tuple[dict[str, str], list[tuple[str, str]], dict[str, dict]]:
    """Return (exact_map, patterns, semantics_map).

    exact_map     normalized_label -> canonical_field_name
    patterns      list of (starts_with_prefix, canonical_field_name)
    semantics_map normalized_label -> semantics dict (e.g. {"excludes_da": True})
    """
    exact: dict[str, str] = {}
    patterns: list[tuple[str, str]] = []
    semantics_map: dict[str, dict] = {}

    for field_name, config in _iter_target_fields(alias_table, sector_profile):
        for alias in config.get("aliases") or []:
            if _standard_allowed(alias, accounting_standard):
                exact[alias["label"]] = field_name
                sem = alias.get("semantics")
                if sem:
                    semantics_map[alias["label"]] = sem
        for pattern in config.get("patterns") or []:
            if _standard_allowed(pattern, accounting_standard):
                patterns.append((pattern["starts_with"], field_name))

    return exact, patterns, semantics_map


def _unmapped_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": item.get("label"),
        "value": item.get("value"),
    }


def _mapped_item(
    item: dict[str, Any],
    match_type: str,
    semantics: dict | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "value": item.get("value"),
        "source_label": item.get("label"),
        "match_type": match_type,
        "confidence": item.get("confidence"),
    }
    if semantics:
        result["semantics"] = semantics
    return result


def map_line_items(
    line_items: list[dict[str, Any]],
    accounting_standard: str,
    sector: str | None = None,
) -> dict[str, Any]:
    alias_table = _load_alias_table()
    sector_profile = _profile_for_sector(alias_table, sector)
    exact, patterns, semantics_map = _build_match_indexes(
        alias_table, accounting_standard, sector_profile
    )

    normalized_items = [
        {
            "item": item,
            "normalized_label": _normalize_label(item.get("label", "")),
        }
        for item in line_items
    ]

    # --- Part C: Value-equality duplicate classification ---
    # Same normalized label with identical non-null value = benign duplicate (e.g.
    # "Net earnings" repeated at the top of a Comprehensive Income section).
    # First occurrence proceeds normally; subsequent occurrences are silently skipped.
    # Same normalized label with different values = ambiguous; all go to unmapped.
    label_index: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(normalized_items):
        label_index[row["normalized_label"]].append(i)

    benign_skip: set[int] = set()
    ambiguous_indices: set[int] = set()
    benign_duplicates_meta: list[dict] = []

    for normalized_label, indices in label_index.items():
        if len(indices) <= 1:
            continue
        values = [_coerce_number(normalized_items[i]["item"].get("value")) for i in indices]
        if len(set(values)) == 1 and values[0] is not None:
            # Benign: identical non-null value — use first occurrence, skip the rest.
            for idx in indices[1:]:
                benign_skip.add(idx)
            benign_duplicates_meta.append({
                "normalized_label": normalized_label,
                "occurrence_count": len(indices),
                "value": values[0],
            })
        else:
            # Ambiguous: different values or null — all go to unmapped.
            for idx in indices:
                ambiguous_indices.add(idx)

    # --- Main mapping loop ---
    unmapped: list[dict[str, Any]] = []
    candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for i, row in enumerate(normalized_items):
        item = row["item"]
        normalized_label = row["normalized_label"]

        if i in benign_skip:
            continue  # silently skip; counted in benign_skipped_count

        if i in ambiguous_indices:
            unmapped.append(_unmapped_item(item))
            continue

        canonical_field = exact.get(normalized_label)
        match_type = "exact"
        item_semantics = semantics_map.get(normalized_label)

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
            "semantics": item_semantics,
        })

    # --- Collision guard ---
    # Two distinct normalized labels both matching the same canonical field → collision.
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
        mapped[canonical_field] = _mapped_item(
            match["item"], match["match_type"], match.get("semantics")
        )

    # --- Part B: Derived gross profit ---
    # When gross_profit is not directly mapped but both revenue and cost_of_revenue are,
    # derive gross_profit = revenue - cost_of_revenue. Not a line-item mapping — excluded
    # from mapped_count. If cost_of_revenue carries excludes_da: True, propagate the flag
    # so the engine can attach a D&A caveat to margin rule messages.
    gross_profit_derived = False
    if "gross_profit" not in mapped:
        rev_item = mapped.get("revenue")
        cor_item = mapped.get("cost_of_revenue")
        if rev_item is not None and cor_item is not None:
            rev_val = _coerce_number(rev_item.get("value"))
            cor_val = _coerce_number(cor_item.get("value"))
            if rev_val is not None and cor_val is not None:
                excludes_da = bool((cor_item.get("semantics") or {}).get("excludes_da"))
                mapped["gross_profit"] = {
                    "value": round(rev_val - cor_val, 6),
                    "source_label": "derived: revenue - cost_of_revenue",
                    "match_type": "derived",
                    "confidence": None,
                    "derived": True,
                    "excludes_da": excludes_da,
                }
                gross_profit_derived = True

    # mapped_count counts only line-item-backed entries (not derived synthetic values).
    mapped_count = sum(1 for v in mapped.values() if not v.get("derived"))
    unmapped_count = len(unmapped)
    benign_skipped_count = len(benign_skip)
    total = len(line_items)
    assert mapped_count + unmapped_count + benign_skipped_count == total

    return {
        "mapped": mapped,
        "unmapped": unmapped,
        "meta": {
            "accounting_standard": accounting_standard,
            "sector_profile": sector_profile,
            "total": total,
            "mapped_count": mapped_count,
            "unmapped_count": unmapped_count,
            "benign_skipped_count": benign_skipped_count,
            "benign_duplicates": benign_duplicates_meta,
            "gross_profit_derived": gross_profit_derived,
            "collisions": collisions,
        },
    }
