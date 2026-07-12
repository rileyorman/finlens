"""Structural-subtotal classifier (docs/STRUCTURAL_SUBTOTAL_SPEC.md, Stage 0).

Deterministic, zero-API arithmetic inference over extracted statement rows:
a row whose value equals the sum of the contiguous rows above it (since the
last inferred subtotal) is structurally a SUBTOTAL; a row that equals the
sum of prior inferred subtotals is a grand TOTAL — whatever either row's
label says. Labels are never trusted for structure; structure is never
guessed (a row that proves nothing stays "data", meaning "not proven").

The CB-033 detection: an UNQUALIFIED grand-category label ("total
liabilities" — not "total non-current assets") that ties only as a BLOCK
sum while a prior same-category subtotal sits OUTSIDE its sum is a
label-vs-structure CONTRADICTION (Peyto's extractor-invented "Total
liabilities" on the non-current block, 2,241,748 vs true 2,607,658).

Recall-biased by design: rounding beyond tolerance, memo lines, and deep
nesting degrade to honest non-classification, never a wrong classification.
"""
from __future__ import annotations

import re

STRUCTURE_SUBTOTAL = "subtotal"
STRUCTURE_TOTAL = "total"
STRUCTURE_DATA = "data"

# Tolerance per comparison: covers printed rounding without letting
# genuinely different numbers tie. Values are in filing units (thousands/
# millions), so 1.0 absolute is one printed unit.
_ABS_TOL = 1.0
_REL_TOL = 0.005

# Unqualified grand-category total claims. Qualified forms ("total
# non-current assets", "total current liabilities") legitimately scope to a
# block and are exempt.
_CATEGORY_WORDS = ("assets", "liabilities", "equity")
_TOTAL_CLAIM_RE = re.compile(r"^total\s+(assets|liabilities|equity)$")


def _ties(target: float, total: float) -> bool:
    return abs(target - total) <= max(_ABS_TOL, _REL_TOL * abs(target))


def _norm_label(label) -> str:
    return re.sub(r"\s+", " ", str(label or "")).strip().lower()


def _claimed_category(label: str) -> str | None:
    """The grand category an UNQUALIFIED total label claims, else None."""
    match = _TOTAL_CLAIM_RE.match(label)
    return match.group(1) if match else None


def _classify_column(rows: list[dict], period: str) -> list[dict]:
    """One walk over one period column. Returns per-row dicts with
    structure / conflict for rows that have a numeric value in this column,
    or None entries for rows without one."""
    out: list[dict | None] = []
    block: list[float] = []
    # (value, normalized label) of inferred subtotals since the last total
    subtotals: list[tuple[float, str]] = []

    for row in rows:
        value = (row.get("values") or {}).get(period)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            out.append(None)
            continue

        label = _norm_label(row.get("label"))
        annotation = {"structure": STRUCTURE_DATA, "structure_conflict": False,
                      "conflict_note": None}

        # Grand-total hypothesis first: sum of >= 2 prior subtotals. Tested
        # before the block hypothesis so a total following a subtotal (empty
        # block) classifies correctly.
        if len(subtotals) >= 2 and _ties(value, sum(v for v, _ in subtotals)):
            annotation["structure"] = STRUCTURE_TOTAL
            subtotals = []           # a grand total closes its section
            block = []
        elif len(block) >= 2 and _ties(value, sum(block)):
            annotation["structure"] = STRUCTURE_SUBTOTAL
            # CB-033 contradiction: unqualified grand-category claim tying
            # only as a block sum while a prior SAME-CATEGORY subtotal sits
            # outside the sum.
            category = _claimed_category(label)
            if category and any(category in sub_label for _, sub_label in subtotals):
                annotation["structure_conflict"] = True
                annotation["conflict_note"] = (
                    f"label claims grand '{category}' total but arithmetic "
                    f"proves a block subtotal; prior '{category}' subtotal(s) "
                    "are outside its sum"
                )
            subtotals.append((value, label))
            block = []
        else:
            block.append(value)

        out.append(annotation)
    return out


def classify_statement_structure(rows: list[dict]) -> list[dict]:
    """Classify one statement's rows. rows: [{"label": str,
    "values": {period: number|None}}]. Returns one annotation per row
    (index-aligned): {"structure", "structure_conflict", "conflict_note"}.

    Multi-period agreement: a row is classified only when every period
    column carrying a numeric value for it agrees; disagreement degrades to
    honest "data" (never a wrong classification)."""
    periods: list[str] = []
    for row in rows:
        for period in (row.get("values") or {}):
            if period not in periods:
                periods.append(period)

    per_column = {period: _classify_column(rows, period) for period in periods}

    annotations = []
    for idx in range(len(rows)):
        column_views = [per_column[p][idx] for p in periods
                        if per_column[p][idx] is not None]
        if not column_views:
            annotations.append({"structure": STRUCTURE_DATA,
                                "structure_conflict": False,
                                "conflict_note": None})
            continue
        structures = {view["structure"] for view in column_views}
        conflicts = {view["structure_conflict"] for view in column_views}
        if len(structures) == 1 and len(conflicts) == 1:
            chosen = dict(column_views[0])
        else:
            chosen = {"structure": STRUCTURE_DATA, "structure_conflict": False,
                      "conflict_note": None}
        annotations.append(chosen)
    return annotations
