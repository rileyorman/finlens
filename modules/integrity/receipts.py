"""Receipt-view builders for the SEDAR mapping and integrity results.

These functions turn the mapper's `mapping` dict and the engine's
`_integrity` result into plain row dicts the UI can render directly.
They are pure (no Streamlit, no I/O) so the receipt content is pinnable
by tests — the receipt is a trust surface, and its content should never
drift silently.

Design intent (Phase 2.2 header/receipts work, 2026-07-07): the receipt
shows the VERBATIM source label and the AS-FILED value for every mapped
canonical field, so a skeptical reader can tie each number back to the
printed filing line-by-line — the same tie-out the dry-run transcription
protocol does by hand.
"""

from __future__ import annotations

from typing import Any

# Human-readable names for the mapper's match_type values.
_MATCH_LABELS = {
    "exact": "exact label match",
    "pattern": "pattern match",
    "derived": "derived",
}


def _fmt_as_filed(value: Any) -> str:
    """Format a value exactly as it reads in the filing (no K/M/B scaling).

    Mapped values are as-extracted, in the filing's own scale (e.g.
    thousands), so rendering them with plain thousands separators makes
    the receipt directly comparable to the source PDF. Not a display
    formatter for raw dollars — do NOT reuse _fmt_num here.
    """
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v.is_integer():
        return f"{v:,.0f}"
    return f"{v:,.2f}"


def _component_parts(components: Any) -> tuple[list[str], list[str]]:
    """Flatten a derived entry's heterogeneous components into short strings.

    Returns (included, excluded): components under keys starting with
    "excluded" are lines the derivation deliberately LEAVES OUT (e.g. a
    blended REIT's development costs) — listing them under "derived from"
    would misstate the arithmetic. Components can hold single
    {source_label, value} dicts, lists of them, or plain strings; anything
    not recognized is skipped rather than crashing the receipt.
    """
    included: list[str] = []
    excluded: list[str] = []
    if not isinstance(components, dict):
        return included, excluded
    for key, comp in components.items():
        target = excluded if str(key).startswith("excluded") else included
        entries = comp if isinstance(comp, list) else [comp]
        for entry in entries:
            if isinstance(entry, dict) and entry.get("source_label") is not None:
                target.append(
                    f'"{entry.get("source_label")}" {_fmt_as_filed(entry.get("value"))}'
                )
    return included, excluded


def mapping_receipt_rows(mapping: dict | None) -> list[dict[str, str]]:
    """One receipt row per mapped canonical field.

    Columns: Canonical field | Value (as filed) | Source line item | Match | Notes.
    Notes carries semantics tags, derived components, and collision
    resolutions (from meta.resolved_collisions) — the judgment trail.
    """
    if not isinstance(mapping, dict):
        return []
    mapped = mapping.get("mapped") or {}
    meta = mapping.get("meta") or {}

    # Collision resolutions are recorded per canonical field in meta.
    resolutions = {
        r.get("canonical_field"): r
        for r in (meta.get("resolved_collisions") or [])
        if isinstance(r, dict)
    }

    rows: list[dict[str, str]] = []
    for field, entry in mapped.items():
        if not isinstance(entry, dict):
            continue
        match_type = entry.get("match_type") or ""
        notes: list[str] = []

        if entry.get("derived"):
            included, excluded = _component_parts(entry.get("components"))
            if included:
                notes.append("derived from " + " · ".join(included))
            else:
                notes.append("derived — not a printed filing line")
            if excluded:
                notes.append("excluding " + " · ".join(excluded))
        if entry.get("excludes_da"):
            notes.append("cost basis excludes D&A")

        semantics = entry.get("semantics")
        if isinstance(semantics, dict):
            for key, val in semantics.items():
                if val is True:
                    notes.append(key.replace("_", " "))
                elif isinstance(val, str):
                    notes.append(f"{key.replace('_', ' ')}: {val}")

        resolution = resolutions.get(field)
        if resolution:
            rejected = ", ".join(
                f'"{label}"' for label in (resolution.get("rejected_labels") or [])
            )
            notes.append(
                f'collision resolved ({resolution.get("rule")}) — '
                f'chose "{resolution.get("chosen_label")}" over {rejected}'
            )

        rows.append({
            "Canonical field": str(field),
            "Value (as filed)": _fmt_as_filed(entry.get("value")),
            "Source line item": str(entry.get("source_label") or "—"),
            "Match": _MATCH_LABELS.get(match_type, match_type or "—"),
            "Notes": "; ".join(notes),
        })
    return rows


# Badge text + colors keyed by the engine's overall_status values.
# Tones are (rgb string for backgrounds, hex text color) matching the
# existing chip styling in app.py.
_STATUS_BADGES = {
    "clean": ("CLEAN", "74,222,128", "#4ADE80"),
    "warnings": ("WARNINGS", "252,211,77", "#FCD34D"),
    "info_only": ("INFO", "96,165,250", "#60A5FA"),
    "unknown": ("UNKNOWN", "148,163,184", "#94A3B8"),
}


def integrity_status_badge(integrity: dict | None) -> tuple[str, str, str] | None:
    """(label, rgb, hex) for the overall integrity verdict pill, or None."""
    if not isinstance(integrity, dict):
        return None
    status = integrity.get("overall_status")
    if not status:
        return None
    return _STATUS_BADGES.get(str(status), (str(status).upper(), "148,163,184", "#94A3B8"))


def integrity_receipt_rows(integrity: dict | None) -> list[dict[str, str]]:
    """One row per integrity rule the engine ran: pass / flagged / skipped.

    Skipped rules are shown with their skip reason — an honest skip
    ("field unavailable") is part of the audit trail, not noise.
    """
    if not isinstance(integrity, dict):
        return []
    rows: list[dict[str, str]] = []
    for check in integrity.get("checks") or []:
        if not isinstance(check, dict):
            continue
        if check.get("skipped"):
            reason = check.get("skip_reason") or "skipped"
            result = f"— skipped ({str(reason).replace('_', ' ')})"
        elif check.get("passed"):
            result = "✓ pass"
        else:
            result = "⚑ flagged"
        observed = check.get("observed_value")
        rows.append({
            "Rule": str(check.get("rule_id") or "—"),
            "Result": result,
            "Observed": _fmt_as_filed(observed) if observed is not None else "—",
            "Detail": str(check.get("message") or ""),
        })
    return rows
