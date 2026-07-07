"""
SEDAR+ income-statement alias mapper.

Maps verbatim extracted line-item labels to FinLens canonical fields using the
data-only alias table in sedar_aliases.json.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from .rules import FINANCIAL_SECTOR_TOKENS, INSURANCE_SECTOR_TOKENS


_ALIAS_FILE = Path(__file__).with_name("sedar_aliases.json")
RESOURCE_SECTOR_TOKENS = (
    "resource_sector",
    "resource",
    "upstream oil",
    "oil & gas",
    "oil and gas",
    "crude oil",
    "natural gas",
    "exploration and production",
)
# reit_sector v1 baseline — 4 universal fields confirmed across 3 REITs (REI.UN/CAR.UN/DIR.UN, Jun 2026).
# DELIBERATELY EVOLVABLE: revisit as REIT corpus grows. Each new REIT filer must be checked against these 4
# fields (do they still hold?) and against the 2 'common, not universal' candidates (equity_accounted_income,
# fair_value_adjustments_financial_instruments — promote to canonical if a 4th REIT confirms). New label variants
# for existing fields get added as aliases. This profile is a living hypothesis, not a frozen answer.
REIT_SECTOR_TOKENS = (
    "reit",
    "real estate",
    "real estate investment trust",
)
# mining_sector v1 baseline — designed from AEM FY2025 (gold miner). DELIBERATELY EVOLVABLE:
# revisit as mining corpus grows (2nd miner confirms universals). Separate from resource_sector
# (O&G) by design: mining has no royalty-deduction line, carries mine-development amortization,
# care-and-maintenance, and mining-specific taxes that O&G lacks. AISC components (by-product
# credits, sustaining capex) are MD&A-only, not in income statement — future MD&A-extraction target.
MINING_EXPLORATION_SECTOR_TOKENS = (
    "mining_exploration_sector",
    "mineral exploration",
    "mining exploration",
    "exploration stage",
    "pre-revenue exploration",
    "junior miner",
)
MINING_SECTOR_TOKENS = (
    "gold mining",
    "mining",
    "precious metals",
    "mineral",
    "gold",
    "metals",
)
_TRAILING_FOOTNOTE_MARKER_RE = re.compile(
    r"\s*\((?:(?i:i{1,3}|iv|v|vi{0,3}|ix|x)|[a-z]|([a-z])\1)\)\s*$",
)


@lru_cache(maxsize=1)
def _load_alias_table() -> dict[str, Any]:
    with _ALIAS_FILE.open(encoding="utf-8") as handle:
        return json.load(handle)


# Bump ONLY on mapper LOGIC changes that leave sedar_aliases.json unchanged
# (a new derivation, routing rule, or collision mechanism). Alias/sector-profile
# edits are versioned automatically by the file hash below, so they need no bump.
_MAPPER_LOGIC_REV = "1"


@lru_cache(maxsize=1)
def mapper_version() -> str:
    """Content version of the SEDAR mapper — changes whenever its output could.

    Combines a hash of the alias table (sedar_aliases.json) with a manual
    logic-rev constant. The alias-hash half changes automatically on ANY
    alias/sector-profile edit (Task A, CB-011, CB-017, CB-018, …), so no one
    has to remember to bump a version — the common case is machine-enforced.
    The manual rev covers pure-logic changes and lives next to the code it
    versions. Used to detect and heal cached analyses whose stored mapping
    predates a mapper improvement (re-map is deterministic and free).

    lru_cached: the alias file does not change at runtime. Tests that mutate
    _ALIAS_FILE must call mapper_version.cache_clear() first.
    """
    try:
        digest = hashlib.sha256(_ALIAS_FILE.read_bytes()).hexdigest()[:12]
    except OSError:
        digest = "nofile"
    return f"{_MAPPER_LOGIC_REV}-{digest}"


def sedar_mapping_is_stale(financial_data: Any, current_version: str | None = None) -> bool:
    """True when a stored SEDAR analysis can AND should be re-mapped for free.

    All three must hold: (a) it is a SEDAR analysis (source == 'sedar_pdf');
    (b) the raw extraction with statements is still on hand to re-map from at
    zero API cost (financial_data['sedar_extraction']['statements']); (c) the
    stored mapper version differs from the current one — or none is stored
    (legacy caches predating this stamp). Everything else returns False (no-op):
    non-SEDAR analyses, already-current analyses, and analyses with no
    re-mappable extraction are all left untouched.
    """
    if not isinstance(financial_data, dict):
        return False
    if financial_data.get("source") != "sedar_pdf":
        return False
    extraction = financial_data.get("sedar_extraction")
    if not isinstance(extraction, dict) or not extraction.get("statements"):
        return False
    if current_version is None:
        current_version = mapper_version()
    return financial_data.get("_mapper_version") != current_version


def _normalize_label(label: str) -> str:
    text = re.sub(r"\s*\([^)]*\bnote\b[^)]*\)", "", str(label or ""), flags=re.IGNORECASE)
    text = _TRAILING_FOOTNOTE_MARKER_RE.sub("", text)
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


# CB-020 (ratified 2026-07-07): canonical net-income sign convention. A label
# that UNAMBIGUOUSLY declares a loss — contains "loss" and NONE of the profit
# words {income, profit, earnings} — carries a loss and must be stored
# NEGATIVE, regardless of the filer's presented sign. The profit-word
# exclusion protects the "Net income (loss)" TEMPLATE (used in both profit and
# loss years, where the value's own sign is authoritative). NGEx prints a
# positive-magnitude "Net loss"; AP.UN/SIG/NFG print the loss parenthetically
# (already negative). The rule signs the first and no-ops the others.
# Shared with excel_exporter's summary-card scrape (the load-bearing consumer);
# defined here in the lean mapper layer to keep a single source of truth for
# the exclusion set (see CB-020 OQ3).
_PROFIT_WORDS = ("income", "profit", "earnings")


def _is_loss_declaring_label(label: str | None) -> bool:
    li = (label or "").lower()
    if "loss" not in li:
        return False
    return not any(word in li for word in _PROFIT_WORDS)


def _standard_allowed(rule: dict[str, Any], accounting_standard: str) -> bool:
    standards = rule.get("standards") or []
    norm = _normalize_standard(accounting_standard)
    return any(_normalize_standard(s) == norm for s in standards)


def _has_explicit_exploration_token(sector_text: str) -> bool:
    return any(token in sector_text for token in MINING_EXPLORATION_SECTOR_TOKENS)


def _is_mining_family_sector(sector: str | None) -> bool:
    sector_text = str(sector or "").lower()
    return _has_explicit_exploration_token(sector_text) or any(
        token in sector_text for token in MINING_SECTOR_TOKENS
    )


def _income_statement_rows(line_items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    rows = [item for item in (line_items or []) if item.get("statement") == "income_statement"]
    return rows if rows else list(line_items or [])


def _mining_revenue_spine_label(normalized_label: str) -> bool:
    label = normalized_label.replace("-", " ")
    revenue_like = (
        label in {"revenue", "revenues", "sales", "product sales", "metal sales"}
        or label.startswith("revenue ")
        or label.startswith("revenues ")
        or label.startswith("sales ")
        or label.startswith("product sales ")
        or "revenues from mining operations" in label
    )
    if revenue_like and "sales tax" not in label and "sales taxes" not in label:
        return True

    cost_or_margin_like = (
        label in {"cost of sales", "cost of revenue", "gross profit", "production"}
        or label.startswith("cost of sales")
        or label.startswith("costs of sales")
        or label.startswith("cost of revenue")
        or label.startswith("gross profit")
    )
    mine_operations_like = (
        "mine operations" in label
        or "mining operations" in label
        or "mine operating" in label
    )
    return cost_or_margin_like or mine_operations_like


def _mining_exploration_loss_shape(line_items: list[dict[str, Any]] | None) -> bool:
    income_rows = _income_statement_rows(line_items)
    if not income_rows:
        return False

    labels = [_normalize_label(item.get("label", "")) for item in income_rows]
    has_revenue_spine = any(_mining_revenue_spine_label(label) for label in labels)
    has_loss_or_expense_shape = any(
        label.startswith("loss from operating")
        or label.startswith("operating loss")
        or "exploration" in label
        or label == "expenses"
        or label.endswith("expenses")
        or label.endswith("expenditures")
        for label in labels
    )
    return not has_revenue_spine and has_loss_or_expense_shape


def _profile_for_sector(
    alias_table: dict[str, Any],
    sector: str | None,
    line_items: list[dict[str, Any]] | None = None,
) -> str | None:
    if not sector:
        return None

    sector_profiles = alias_table.get("sector_profiles") or {}
    sector_text = str(sector).lower()

    if sector_text in sector_profiles:
        return sector_text
    # Insurance must win before financial_sector: SLF emits
    # "Insurance and Financial Services", which contains a financial token but
    # has IFRS 17 insurance statements, not bank-shaped financial statements.
    if "insurance_sector" in sector_profiles and any(
        token in sector_text for token in INSURANCE_SECTOR_TOKENS
    ):
        return "insurance_sector"
    if "financial_sector" in sector_profiles and any(
        token in sector_text for token in FINANCIAL_SECTOR_TOKENS
    ):
        return "financial_sector"
    # Mining-family must win before resource_sector: mining tokens ("mineral",
    # "gold", "mining"...) are strictly more specific than the generic
    # resource/O&G tokens, and resource_sector's broad "exploration and
    # production" token would otherwise shadow miners — "Mineral Exploration
    # and Production" must not get O&G royalty semantics. Same precedence
    # pattern as insurance-before-financial above. O&G sector strings contain
    # no mining tokens, so their routing is unchanged.
    if _is_mining_family_sector(sector_text):
        # Exploration-stage miners have pre-revenue statements, so they must not
        # route through the producer mining profile's revenue/production spine.
        if "mining_exploration_sector" in sector_profiles and (
            _has_explicit_exploration_token(sector_text)
            or _mining_exploration_loss_shape(line_items)
        ):
            return "mining_exploration_sector"
        if "mining_sector" in sector_profiles:
            return "mining_sector"
    if "resource_sector" in sector_profiles and any(
        token in sector_text for token in RESOURCE_SECTOR_TOKENS
    ):
        return "resource_sector"
    if "reit_sector" in sector_profiles and any(
        token in sector_text for token in REIT_SECTOR_TOKENS
    ):
        return "reit_sector"
    return None


def _iter_target_fields(alias_table: dict[str, Any], sector_profile: str | None):
    # OVERRIDE semantics: defaults always run; sector profile adds new canonical
    # fields or augments defaults at the same canonical name. Same canonical
    # name → aliases/patterns are appended. New canonical name → added.
    # Alias-label collisions across two different canonical names are resolved
    # in _build_match_indexes via first-write-wins; defaults are iterated first
    # here so they claim collided labels before the profile sees them.
    merged = dict(alias_table.get("canonical_fields") or {})
    if sector_profile:
        profile = (alias_table.get("sector_profiles") or {}).get(sector_profile, {})
        for field_name, profile_config in (profile.get("canonical_fields") or {}).items():
            if field_name not in merged:
                merged[field_name] = profile_config
                continue
            base_config = dict(merged[field_name])
            base_config["aliases"] = list(base_config.get("aliases") or []) + list(
                profile_config.get("aliases") or []
            )
            base_config["patterns"] = list(base_config.get("patterns") or []) + list(
                profile_config.get("patterns") or []
            )
            merged[field_name] = base_config
    for field_name, config in merged.items():
        yield field_name, config


def _build_match_indexes(
    alias_table: dict[str, Any],
    accounting_standard: str,
    sector_profile: str | None,
) -> tuple[dict[str, str], list[tuple[str, str]], dict[str, dict], dict[str, str], dict[str, set], dict[str, int]]:
    """Return (exact_map, patterns, semantics_map, collision_rules, statement_scope, alias_order).

    exact_map       normalized_label -> canonical_field_name
    patterns        list of (starts_with_prefix, canonical_field_name)
    semantics_map   normalized_label -> semantics dict (e.g. {"excludes_da": True})
    collision_rules canonical_field_name -> collision_resolution rule string.
                    Per-field opt-in (CB-010): a field config may declare
                    "collision_resolution": "prefer_specific_alias" to resolve
                    distinct-label collisions instead of blocking them.
                    CB-013 adds "prefer_primary_alias": the match whose alias
                    is declared EARLIEST in the field's alias list wins — the
                    declared order encodes a documented semantic tiering
                    (total_equity: a printed grand-total "Total equity" line
                    supersedes shareholder/unitholder-scoped lines, which are
                    NCI-excluding or attributable-only on some filers).
    statement_scope normalized_label -> set of statement keys the alias may
                    match in (CB-009): an alias may declare
                    "statements": ["cash_flow"] when the same label names a
                    DIFFERENT concept in another statement (SIG's cash-flow
                    "Exploration and evaluation assets" is the period's
                    capitalized additions; the identical balance-sheet label
                    is the asset stock). Scoped aliases FAIL CLOSED: an item
                    without statement attribution never matches them.
    alias_order     normalized_label -> declared position in its field's
                    alias list (CB-013). Positions use the field's FULL
                    declared list, so they are stable under standards
                    filtering. Consulted only by "prefer_primary_alias".
    """
    exact: dict[str, str] = {}
    patterns: list[tuple[str, str]] = []
    semantics_map: dict[str, dict] = {}
    collision_rules: dict[str, str] = {}
    statement_scope: dict[str, set] = {}
    alias_order: dict[str, int] = {}

    # First-write-wins on alias-label collisions: defaults are iterated before
    # sector-profile fields, so a default claims a collided label and the
    # profile's same-label alias is rejected. This is the RY-trap defuse —
    # without it, profile total_revenue_bank ("total revenue") would steal
    # the label from default revenue when the financial_sector profile resolves.
    for field_name, config in _iter_target_fields(alias_table, sector_profile):
        rule = config.get("collision_resolution")
        if rule:
            collision_rules[field_name] = rule
        for position, alias in enumerate(config.get("aliases") or []):
            if _standard_allowed(alias, accounting_standard):
                label = alias["label"]
                # Rare explicit sector-profile override for labels whose
                # sector meaning is more precise than a generic default.
                # Defaults still claim ordinary collisions first (RY trap).
                if label not in exact or alias.get("prefer_profile"):
                    exact[label] = field_name
                    alias_order[label] = position
                    sem = alias.get("semantics")
                    if sem:
                        semantics_map[label] = sem
                    else:
                        semantics_map.pop(label, None)
                    statements = alias.get("statements")
                    if statements:
                        statement_scope[label] = set(statements)
                    else:
                        statement_scope.pop(label, None)
        for pattern in config.get("patterns") or []:
            if _standard_allowed(pattern, accounting_standard):
                patterns.append((pattern["starts_with"], field_name))

    return exact, patterns, semantics_map, collision_rules, statement_scope, alias_order


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


def _reit_development_revenue_label(normalized_label: str) -> bool:
    label = normalized_label.replace("-", " ")
    has_development_term = "inventory" in label or "development" in label
    has_revenue_term = "sales" in label or "revenue" in label
    return (
        has_development_term
        and has_revenue_term
        and not _reit_development_cost_label(normalized_label)
    )


def _reit_development_cost_label(normalized_label: str) -> bool:
    label = normalized_label.replace("-", " ")
    has_development_term = "inventory" in label or "development" in label
    has_cost_term = (
        "cost of sales" in label
        or "costs of sales" in label
        or "cost of revenue" in label
        or "cogs" in label
    )
    return has_development_term and has_cost_term


def _reit_rental_operating_cost_label(normalized_label: str) -> bool:
    label = normalized_label.replace("-", " ")
    return (
        "recoverable under tenant leases" in label
        or "non recoverable costs" in label
        or "rental operating costs" in label
        or "rental operating expenses" in label
        or "realty taxes" in label
    )


def _coerce_cost_magnitude(value: Any) -> float | None:
    number = _coerce_number(value)
    if number is None:
        return None
    return abs(number)


def _clean_derived_number(value: float) -> int | float:
    rounded = round(value, 6)
    return int(rounded) if rounded.is_integer() else rounded


def _line_component(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_label": item.get("label"),
        "value": item.get("value"),
    }


def _derive_reit_rental_noi(
    mapped: dict[str, dict[str, Any]],
    unmapped: list[dict[str, Any]],
    normalized_items: list[dict[str, Any]],
    sector_profile: str | None,
) -> None:
    if sector_profile != "reit_sector":
        return

    development_revenue_items = [
        row["item"]
        for row in normalized_items
        if _reit_development_revenue_label(row["normalized_label"])
    ]
    development_cost_items = [
        row["item"]
        for row in normalized_items
        if _reit_development_cost_label(row["normalized_label"])
    ]
    if not development_revenue_items or not development_cost_items:
        return

    rental_revenue = mapped.get("rental_revenue")
    if rental_revenue is None:
        return

    rental_revenue_value = _coerce_number(rental_revenue.get("value"))
    if rental_revenue_value is None:
        return

    rental_cost_items = [
        row["item"]
        for row in normalized_items
        if _reit_rental_operating_cost_label(row["normalized_label"])
        and not _reit_development_cost_label(row["normalized_label"])
    ]
    rental_cost_values = [
        value
        for value in (_coerce_cost_magnitude(item.get("value")) for item in rental_cost_items)
        if value is not None
    ]

    rental_cost_source = "rental operating cost components"
    if rental_cost_values:
        rental_operating_costs = sum(rental_cost_values)
    else:
        property_operating_costs = mapped.get("property_operating_costs")
        property_operating_costs_value = (
            _coerce_cost_magnitude(property_operating_costs.get("value"))
            if property_operating_costs is not None
            else None
        )
        development_cost_values = [
            value
            for value in (
                _coerce_cost_magnitude(item.get("value")) for item in development_cost_items
            )
            if value is not None
        ]
        if property_operating_costs_value is None or not development_cost_values:
            return
        rental_operating_costs = property_operating_costs_value - sum(development_cost_values)
        rental_cost_source = "property_operating_costs excluding development inventory costs"

    if rental_operating_costs < 0:
        return

    reported_blended_subtotal = mapped.get("net_operating_income")
    if reported_blended_subtotal is not None:
        unmapped.append({
            "label": reported_blended_subtotal.get("source_label"),
            "value": reported_blended_subtotal.get("value"),
        })

    mapped["net_operating_income"] = {
        "value": _clean_derived_number(rental_revenue_value - rental_operating_costs),
        "source_label": "derived: rental_revenue - rental_operating_costs_excluding_development",
        "match_type": "derived",
        "confidence": None,
        "derived": True,
        "components": {
            "rental_revenue": {
                "source_label": rental_revenue.get("source_label"),
                "value": rental_revenue.get("value"),
            },
            "rental_operating_costs": [
                _line_component(item) for item in rental_cost_items
            ],
            "rental_operating_cost_source": rental_cost_source,
            "excluded_development_revenue": [
                _line_component(item) for item in development_revenue_items
            ],
            "excluded_development_costs": [
                _line_component(item) for item in development_cost_items
            ],
        },
    }

    # CB-012 (ratified 2026-07-06): property_operating_costs is RENTAL-ONLY —
    # the same definition, same conditional shape, and same components as the
    # NOI derivation above. This function only runs on blended REITs, so pure
    # REITs keep lifting their printed rental-only line; here the printed
    # blended subtotal (e.g. RioCan's "Total operating costs" 637,855, which
    # includes residential inventory cost of sales) moves to unmapped[] and
    # the field derives rental-only. The NOI identity then closes exactly:
    # rental_revenue - property_operating_costs == net_operating_income.
    printed_operating_costs = mapped.get("property_operating_costs")
    if printed_operating_costs is not None and not printed_operating_costs.get("derived"):
        unmapped.append({
            "label": printed_operating_costs.get("source_label"),
            "value": printed_operating_costs.get("value"),
        })
    mapped["property_operating_costs"] = {
        "value": _clean_derived_number(rental_operating_costs),
        "source_label": "derived: rental-only operating cost components (excluding development inventory costs)",
        "match_type": "derived",
        "confidence": None,
        "derived": True,
        "components": {
            "rental_operating_costs": [
                _line_component(item) for item in rental_cost_items
            ],
            "rental_operating_cost_source": rental_cost_source,
            "excluded_development_costs": [
                _line_component(item) for item in development_cost_items
            ],
        },
    }


def map_line_items(
    line_items: list[dict[str, Any]],
    accounting_standard: str,
    sector: str | None = None,
) -> dict[str, Any]:
    alias_table = _load_alias_table()
    sector_profile = _profile_for_sector(alias_table, sector, line_items=line_items)
    exact, patterns, semantics_map, collision_rules, statement_scope, alias_order = _build_match_indexes(
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
    # CB-009 (ratified 2026-07-06): grouped by (normalized_label, statement),
    # not label alone — the same label in DIFFERENT statements is two different
    # lines (SIG's balance-sheet "Exploration and evaluation assets" is the
    # asset STOCK; its cash-flow twin is the period's capitalized additions),
    # so cross-statement pairs must reach alias matching where statement-scoped
    # aliases discriminate. Same label in the SAME statement keeps today's
    # semantics. Items without statement attribution group under None,
    # preserving the old behavior exactly.
    label_index: dict[tuple, list[int]] = defaultdict(list)
    for i, row in enumerate(normalized_items):
        key = (row["normalized_label"], row["item"].get("statement"))
        label_index[key].append(i)

    benign_skip: set[int] = set()
    ambiguous_indices: set[int] = set()
    benign_duplicates_meta: list[dict] = []

    for (normalized_label, _statement), indices in label_index.items():
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

        # CB-009: statement-scoped alias enforcement. A scoped alias matches
        # only items attributed to one of its declared statements; items
        # without statement attribution fail closed (never match a scoped
        # alias) — the scope exists precisely because the same label names a
        # different concept elsewhere, so an unattributed row is unsafe.
        if canonical_field is not None:
            scope = statement_scope.get(normalized_label)
            if scope is not None and item.get("statement") not in scope:
                canonical_field = None
                item_semantics = None

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
    resolved_collisions: list[dict[str, Any]] = []

    for canonical_field, matches in candidates.items():
        distinct_labels = {match["normalized_label"] for match in matches}
        if len(matches) > 1 and len(distinct_labels) > 1:
            values = [_coerce_number(match["item"].get("value")) for match in matches]
            if (
                canonical_field == "cash"
                and values
                and values[0] is not None
                and len(set(values)) == 1
            ):
                match = matches[0]
                mapped[canonical_field] = _mapped_item(
                    match["item"], match["match_type"], match.get("semantics")
                )
                for duplicate_match in matches[1:]:
                    unmapped.append(_unmapped_item(duplicate_match["item"]))
                continue
            # CB-010 (ratified 2026-07-06): per-field opt-in resolution.
            # "prefer_specific_alias" — the match that arrived via the
            # LONGEST normalized alias label wins (the concept's full name
            # beats a note sub-component's bare label, e.g. SIG's
            # "Cash and cash equivalents (Note 4)" 15,208,214 over the
            # note-breakdown row "Cash" 1,883,531). Applies only when every
            # match is an exact alias match (pattern-prefix lengths are not
            # a specificity signal) and the longest label is unique — a
            # length tie stays genuinely ambiguous and blocks as before.
            # Resolutions are recorded in meta.resolved_collisions, never
            # silent.
            rule = collision_rules.get(canonical_field)
            if rule == "prefer_specific_alias" and all(
                match["match_type"] == "exact" for match in matches
            ):
                max_len = max(len(match["normalized_label"]) for match in matches)
                longest = [
                    match for match in matches
                    if len(match["normalized_label"]) == max_len
                ]
                if len(longest) == 1:
                    winner = longest[0]
                    mapped[canonical_field] = _mapped_item(
                        winner["item"], winner["match_type"], winner.get("semantics")
                    )
                    resolved_collisions.append({
                        "canonical_field": canonical_field,
                        "rule": rule,
                        "chosen_label": winner["item"].get("label"),
                        "rejected_labels": [
                            match["item"].get("label")
                            for match in matches
                            if match is not winner
                        ],
                    })
                    for match in matches:
                        if match is not winner:
                            unmapped.append(_unmapped_item(match["item"]))
                    continue
            # CB-013 (ratified 2026-07-06): "prefer_primary_alias" — the match
            # whose alias is declared EARLIEST in the field's alias list wins.
            # The declared order encodes documented judgment, not an arbitrary
            # tiebreak: for total_equity, a printed grand-total "Total equity"
            # line supersedes shareholder/unitholder-scoped lines, which are
            # the NCI-excluding subtotal on SLF and the attributable-only line
            # on DIR.UN. Note prefer_specific_alias (longest label) would pick
            # the WRONG line here — SLF's "total shareholders' equity" is
            # longer than "total equity" but is the subtotal — which is why
            # this is a distinct strategy. Exact alias matches only; every
            # matched label must carry a declared position and the earliest
            # position must be unique, else the collision blocks as before.
            # Resolutions are recorded in meta.resolved_collisions, never
            # silent; rejected rows stay visible in unmapped[].
            if rule == "prefer_primary_alias" and all(
                match["match_type"] == "exact"
                and match["normalized_label"] in alias_order
                for match in matches
            ):
                min_pos = min(alias_order[match["normalized_label"]] for match in matches)
                primary = [
                    match for match in matches
                    if alias_order[match["normalized_label"]] == min_pos
                ]
                if len(primary) == 1:
                    winner = primary[0]
                    mapped[canonical_field] = _mapped_item(
                        winner["item"], winner["match_type"], winner.get("semantics")
                    )
                    resolved_collisions.append({
                        "canonical_field": canonical_field,
                        "rule": rule,
                        "chosen_label": winner["item"].get("label"),
                        "rejected_labels": [
                            match["item"].get("label")
                            for match in matches
                            if match is not winner
                        ],
                    })
                    for match in matches:
                        if match is not winner:
                            unmapped.append(_unmapped_item(match["item"]))
                    continue
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
        # Same-label multi-match (possible since CB-009's per-statement
        # duplicate grouping lets cross-statement same-label rows reach
        # candidates): first occurrence maps, the rest stay visible in
        # unmapped[] — conservation requires every row land somewhere.
        for extra_match in matches[1:]:
            unmapped.append(_unmapped_item(extra_match["item"]))

    # --- CB-020: net-income sign normalization (defense-in-depth) ---
    # A loss-declaring bottom-line label carrying a POSITIVE magnitude is
    # stored negative (profit +, loss −). Only fires when the value is
    # positive, so parenthetical losses (already negative on SIG/NFG/AP.UN)
    # are left byte-identical — no fixture drift. No current corpus filer
    # triggers this at the mapper (all present losses parenthetically); it
    # guards the canonical path against a positive-magnitude long-form loss.
    for _ni_field in ("net_income", "net_loss"):
        _entry = mapped.get(_ni_field)
        if _entry is None:
            continue
        if _is_loss_declaring_label(_entry.get("source_label")):
            _num = _coerce_number(_entry.get("value"))
            if _num is not None and _num > 0:
                _entry["value"] = _clean_derived_number(-_num)

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

    _derive_reit_rental_noi(mapped, unmapped, normalized_items, sector_profile)

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
            "resolved_collisions": resolved_collisions,
        },
    }
