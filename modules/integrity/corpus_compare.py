"""CB-043 — corpus disagreement note for as-filed EDGAR quick figures.

Ratified by Riley 2026-07-13 (option (a), Stage 4 of FMP-zero): when a
cross-listed Canadian filer's as-filed EDGAR figure shares a fiscal year
with a validated SEDAR corpus mapping, FinLens serves the as-filed figure
WITH its tag receipt AND a note comparing it to the corpus canonical —
because same-named concepts differ by construction across sources
(ifrs-full:Revenue on CNQ is the NET-of-royalties line; the corpus
canonical revenue is GROSS per the 2026-06-17 ground-truth decision),
while on other filers they tie exactly (SU's RevenueFromContractsWith-
Customers IS the gross line). The note must COMPARE, never assume.

Read-only over the CI-locked corpus registry + fixtures. Returns None for
the overwhelming case (ticker not in the corpus) so callers can stay
one-liner cheap.
"""
from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY_PATH = _REPO_ROOT / "tests" / "fixtures" / "filing_registry.json"

# Relative tolerance for "ties": generous enough for rounding between a
# millions-printed statement and raw XBRL units, far below any real
# definitional split (CNQ's gross/net gap is ~16%).
_TIE_TOLERANCE = 0.005

_SCALE_FACTORS = {
    "ones": 1,
    "thousands": 1_000,
    "millions": 1_000_000,
    "billions": 1_000_000_000,
}


def _base_ticker(ticker: str) -> str:
    """Class/venue-suffix-insensitive base symbol (TECK.B ↔ TECK, TOU.TO ↔ TOU)."""
    return (ticker or "").strip().upper().split(".")[0]


def _load_registry() -> list[dict]:
    try:
        payload = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
        return payload.get("filings") or []
    except Exception:
        return []


def _fixture_revenue(entry: dict) -> dict | None:
    """The corpus canonical revenue for a registry entry, scaled to raw
    currency units. None when the fixture or its revenue mapping is absent."""
    try:
        fixture = json.loads(
            (_REPO_ROOT / entry.get("fixture_path", "")).read_text(encoding="utf-8")
        )
    except Exception:
        return None
    mapped = ((fixture.get("mapping") or {}).get("mapped") or {})
    revenue = mapped.get("revenue")
    if not isinstance(revenue, dict) or revenue.get("value") is None:
        return None
    factor = _SCALE_FACTORS.get(str(fixture.get("scale") or "").lower())
    if factor is None:
        return None  # unknown scale — never guess a magnitude
    return {
        "value_raw": float(revenue["value"]) * factor,
        "source_label": revenue.get("source_label"),
        "currency": fixture.get("currency"),
    }


def corpus_revenue_note(
    ticker: str,
    edgar_fd: dict | None,
) -> dict | None:
    """Compare an as-filed EDGAR quick dict against the validated corpus.

    Checks every fiscal year the quick dict emits (current + prior) against
    the corpus registry for the same base ticker. Returns None when there is
    no same-year corpus mapping (the overwhelming case); otherwise:

        {"status": "differs" | "ties" | "incomparable_currency",
         "fiscal_year": ..., "corpus_value_raw": ..., "corpus_label": ...,
         "corpus_currency": ..., "edgar_value": ..., "corpus_ticker": ...}
    """
    if not edgar_fd or not ticker:
        return None
    base = _base_ticker(ticker)
    if not base:
        return None

    year_values = [
        (edgar_fd.get("fiscal_year"), edgar_fd.get("revenue")),
        (edgar_fd.get("fiscal_year_prior"), edgar_fd.get("revenue_prior")),
    ]
    edgar_currency = edgar_fd.get("currency")

    for entry in _load_registry():
        if _base_ticker(entry.get("ticker", "")) != base:
            continue
        for fy, edgar_value in year_values:
            if not fy or fy != entry.get("fiscal_year") or edgar_value is None:
                continue
            corpus = _fixture_revenue(entry)
            if corpus is None:
                continue
            result = {
                "fiscal_year": fy,
                "corpus_ticker": entry.get("ticker"),
                "corpus_value_raw": corpus["value_raw"],
                "corpus_label": corpus["source_label"],
                "corpus_currency": corpus["currency"],
                "edgar_value": float(edgar_value),
            }
            if (corpus["currency"] or "").upper() != (edgar_currency or "").upper():
                result["status"] = "incomparable_currency"
                return result
            if corpus["value_raw"] and abs(
                float(edgar_value) - corpus["value_raw"]
            ) / abs(corpus["value_raw"]) <= _TIE_TOLERANCE:
                result["status"] = "ties"
            else:
                result["status"] = "differs"
            return result
    return None
