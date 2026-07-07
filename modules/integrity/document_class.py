"""
Document-class validation at ingest (CB-015, ratified 2026-07-06).

FinLens's analysis flows assume the uploaded document contains financial
statements. Fed an MD&A, a press release, or a prospectus, the pipeline
would extract whatever is present and render a confident analysis of the
wrong document class — a silent-error class UPSTREAM of every extraction
guard. This module classifies extracted document text with deterministic
structural heuristics (zero API cost) so ingest flows can refuse or warn
honestly BEFORE any Claude spend.

Classes (CB-015 ruling 2):
  statements_audited        >=3 of 4 statement families + notes + auditor's report
  statements_unaudited      >=3 of 4 statement families + notes, NO auditor's report
                            (the CNQ FY2024 interim-pack signature)
  no_statements_detected    the target failure class (MD&A-only, press release, ...)
  extraction_empty          no usable text (scanned/image-based PDF)

Calibration evidence (2026-07-06): the marker set classified 18/18 real
corpus PDFs as statements-present with zero false blocks; the auditor's
report was absent ONLY on CNQ FY2024, the one genuinely unaudited pack.
A Claude classification call was deliberately REJECTED for v1 (cost per
upload, non-determinism, and the lexical signals proved decisive) —
escalate only if a real misclassification is observed.

KNOWN LIMITATION (recorded in CB-015): markers are English-only. A
French-language filing lands no_statements_detected with an honest
refusal message until French markers are added (the gate's French
edge-slot is a separately queued concern).
"""
from __future__ import annotations

import re

DOC_CLASS_STATEMENTS_AUDITED = "statements_audited"
DOC_CLASS_STATEMENTS_UNAUDITED = "statements_unaudited"
DOC_CLASS_NO_STATEMENTS = "no_statements_detected"
DOC_CLASS_EXTRACTION_EMPTY = "extraction_empty"

# Below this many characters the text cannot carry a filing (matches the
# existing app-level "very little text was extracted" threshold).
_MIN_TEXT_CHARS = 200

# Minimum distinct statement families for "statements present". 3 of 4
# tolerates title variants the calibration exposed (e.g. AEM's equity
# statement is not titled "changes in equity").
_MIN_STATEMENT_FAMILIES = 3

_AUDITOR_RE = re.compile(
    r"independent auditor'?s'? report"
    r"|report of independent registered public accounting firm"
)

# The four primary-statement families. Titles vary by filer; each pattern
# was calibrated against the 18 canonical corpus PDFs (2026-07-06).
_STATEMENT_FAMILY_RES = {
    "financial_position": re.compile(
        r"(?:consolidated |condensed )?(?:interim )?balance sheets?"
        r"|statements? of financial position"
    ),
    "income": re.compile(
        r"statements? of (?:income|operations|earnings|profit"
        r"|loss(?: and comprehensive loss)?|comprehensive (?:income|loss))"
    ),
    "cash_flows": re.compile(r"statements? of cash flows?"),
    "changes_equity": re.compile(
        r"statements? of changes in (?:shareholders'? |unitholders'? |total )?equity"
        r"|statements? of (?:shareholders'? |unitholders'? )?equity\b"
        r"|statements? of changes in net assets"
    ),
}

_NOTES_RE = re.compile(
    r"notes to (?:the )?(?:consolidated |condensed )?(?:interim )?financial statements"
)

# Corroboration markers — recorded in signals, deliberately NOT used as the
# audited/unaudited discriminator: audited annual filings mention "unaudited"
# in MD&A prose (ATD x4) and "condensed" in note text (RY x5). The auditor's
# report presence is the discriminator.
_UNAUDITED_RE = re.compile(r"\bunaudited\b")
_INTERIM_RE = re.compile(r"\binterim\b")
_CONDENSED_RE = re.compile(r"\bcondensed\b")
_MDA_RE = re.compile(r"management'?s discussion and analysis")


def _normalize(text: str) -> str:
    # Curly apostrophes appear in real filing PDFs; fold them so the
    # auditor's-report pattern matches both forms.
    return (text or "").replace("’", "'").replace("‘", "'").casefold()


def classify_document_text(text: str | None) -> dict:
    """Classify extracted document text into a CB-015 document class.

    Returns a dict with:
      document_class    one of the four DOC_CLASS_* constants
      signals           the observed structural evidence (statement families
                        found, auditor/notes presence, corroboration marker
                        counts) — rendered in refusal/warning messages so the
                        user sees WHAT was looked for, not just a verdict.
    """
    normalized = _normalize(text)

    families_found = sorted(
        name for name, pattern in _STATEMENT_FAMILY_RES.items()
        if pattern.search(normalized)
    )
    signals = {
        "statement_families_found": families_found,
        "statement_family_count": len(families_found),
        "notes_to_financial_statements": bool(_NOTES_RE.search(normalized)),
        "auditor_report": bool(_AUDITOR_RE.search(normalized)),
        "unaudited_marker_count": len(_UNAUDITED_RE.findall(normalized)),
        "interim_marker_count": len(_INTERIM_RE.findall(normalized)),
        "condensed_marker_count": len(_CONDENSED_RE.findall(normalized)),
        "mda_marker": bool(_MDA_RE.search(normalized)),
        "text_chars": len(normalized),
    }

    if len(normalized.strip()) < _MIN_TEXT_CHARS:
        document_class = DOC_CLASS_EXTRACTION_EMPTY
    elif (
        signals["statement_family_count"] >= _MIN_STATEMENT_FAMILIES
        and signals["notes_to_financial_statements"]
    ):
        if signals["auditor_report"]:
            document_class = DOC_CLASS_STATEMENTS_AUDITED
        else:
            document_class = DOC_CLASS_STATEMENTS_UNAUDITED
    else:
        document_class = DOC_CLASS_NO_STATEMENTS

    return {"document_class": document_class, "signals": signals}


def refusal_message(signals: dict) -> str:
    """Honest refusal text for no_statements_detected — names what was
    looked for and what was found, never just a bare verdict."""
    found = signals.get("statement_families_found") or []
    found_text = ", ".join(found) if found else "none"
    notes_text = "found" if signals.get("notes_to_financial_statements") else "not found"
    return (
        "This document does not look like a set of financial statements, so "
        "FinLens will not analyze it (analyzing the wrong document class "
        "produces confidently wrong output). Looked for: the four primary "
        "statement headings (balance sheet / income / cash flows / changes in "
        f"equity — found: {found_text}) and the notes to the financial "
        f"statements ({notes_text}). If this IS a filing, it may be scanned "
        "without a text layer, or a non-English filing (not yet supported by "
        "this check)."
    )


def unaudited_warning_message(signals: dict) -> str:
    """Warning banner text for statements_unaudited — states exactly what
    was observed (honest even when the classified text is an excerpt)."""
    unaudited_count = signals.get("unaudited_marker_count", 0)
    corroboration = (
        f' The document says "unaudited" {unaudited_count} time(s).'
        if unaudited_count
        else ""
    )
    return (
        "No independent auditor's report was found in the analyzed text — "
        "this looks like an unaudited/interim statement set rather than "
        f"audited annual statements.{corroboration} The analysis will "
        "proceed; treat period labels and year-over-year comparisons with "
        "care (interim packs can mix quarterly and annual columns)."
    )
