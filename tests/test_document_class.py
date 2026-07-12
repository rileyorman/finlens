"""CB-015 document-class classifier pins.

Positive signatures are synthetic reductions of the calibration evidence
(2026-07-06: 18/18 real corpus PDFs classified statements-present, auditor's
report absent only on CNQ FY2024 — the genuinely unaudited interim pack).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.integrity.document_class import (
    DOC_CLASS_EXTRACTION_EMPTY,
    DOC_CLASS_MDA,
    DOC_CLASS_NO_STATEMENTS,
    DOC_CLASS_STATEMENTS_AUDITED,
    DOC_CLASS_STATEMENTS_UNAUDITED,
    classify_document_text,
    mda_refusal_message,
    refusal_message,
    unaudited_warning_message,
)


_PAD = " The accompanying notes form part of these statements. " * 10

AUDITED_TEXT = (
    "Independent Auditor's Report\n"
    "Consolidated Statements of Financial Position\n"
    "Consolidated Statements of Income\n"
    "Consolidated Statements of Cash Flows\n"
    "Consolidated Statements of Changes in Equity\n"
    "Notes to the Consolidated Financial Statements\n" + _PAD
)

# CNQ FY2024 signature: full statement set + notes, NO auditor's report,
# unaudited markers present.
UNAUDITED_TEXT = (
    "Consolidated Balance Sheets (unaudited)\n"
    "Consolidated Statements of Earnings (unaudited)\n"
    "Consolidated Statements of Cash Flows (unaudited)\n"
    "Consolidated Statements of Changes in Equity (unaudited)\n"
    "Notes to the Interim Financial Statements\n" + _PAD
)

PRESS_RELEASE_TEXT = (
    "ACME Corp. Reports Record Fourth Quarter Results. TORONTO — ACME "
    "today announced revenue of $1.2 billion, up 12%. Net earnings were "
    "$300 million. The Board declared a quarterly dividend. A conference "
    "call will be held at 8:30 a.m. ET. Forward-looking statements apply. "
) * 3

MDA_TEXT = (
    "Management's Discussion and Analysis. This MD&A should be read in "
    "conjunction with our audited consolidated financial statements. "
    "Revenue increased 8%. Liquidity remains strong. Outlook: growth. "
) * 3


def test_audited_signature_classifies_audited():
    result = classify_document_text(AUDITED_TEXT)
    assert result["document_class"] == DOC_CLASS_STATEMENTS_AUDITED
    assert result["signals"]["statement_family_count"] == 4
    assert result["signals"]["auditor_report"] is True


def test_cnq_interim_signature_classifies_unaudited():
    result = classify_document_text(UNAUDITED_TEXT)
    assert result["document_class"] == DOC_CLASS_STATEMENTS_UNAUDITED
    assert result["signals"]["auditor_report"] is False
    assert result["signals"]["unaudited_marker_count"] >= 4


def test_press_release_refused():
    result = classify_document_text(PRESS_RELEASE_TEXT)
    assert result["document_class"] == DOC_CLASS_NO_STATEMENTS


def test_mda_only_classifies_mda_not_statements():
    """MD&A prose cites 'financial statements' constantly — the classifier
    must require the structural signature (statement headings + notes),
    not the phrase. Since MDA_FETCHER_SPEC Stage 0 the class is `mda`
    (previously no_statements_detected); the intent is unchanged — a
    standalone MD&A must NEVER classify as statements, and the app gate
    still refuses it for statement analysis."""
    result = classify_document_text(MDA_TEXT)
    assert result["document_class"] == DOC_CLASS_MDA
    assert result["signals"]["mda_marker"] is True


def test_statements_pack_referencing_mda_stays_statements():
    """Combined statements+MD&A packs (TOU shape) and statement packs that
    merely cross-reference the MD&A must keep their statements class — the
    statement signature is checked before the MD&A branch."""
    text = AUDITED_TEXT + " see Management's Discussion and Analysis for details "
    result = classify_document_text(text)
    assert result["document_class"] == DOC_CLASS_STATEMENTS_AUDITED
    assert result["signals"]["mda_marker"] is True


def test_press_release_citing_mda_abbreviation_stays_no_statements():
    """Press releases cite the MD&A by abbreviation; the `mda` class requires
    the spelled-out phrase, so abbreviation-only documents keep the
    no_statements refusal."""
    text = PRESS_RELEASE_TEXT + " This release should be read with the MD&A. "
    result = classify_document_text(text)
    assert result["document_class"] == DOC_CLASS_NO_STATEMENTS
    assert result["signals"]["mda_marker"] is False


def test_mda_refusal_message_names_class_and_lane():
    result = classify_document_text(MDA_TEXT)
    message = mda_refusal_message(result["signals"])
    assert "MD&A" in message
    assert "will not run a statements analysis" in message


def test_empty_and_tiny_text_classify_extraction_empty():
    assert classify_document_text("")["document_class"] == DOC_CLASS_EXTRACTION_EMPTY
    assert classify_document_text(None)["document_class"] == DOC_CLASS_EXTRACTION_EMPTY
    assert classify_document_text("short")["document_class"] == DOC_CLASS_EXTRACTION_EMPTY


def test_three_of_four_families_tolerated():
    """AEM-style: equity statement title not matched -> 3/4 still classifies
    statements-present (calibration: title variants are marker gaps, not
    document gaps)."""
    text = (
        "Independent Auditor's Report\n"
        "Consolidated Balance Sheets\n"
        "Consolidated Statements of Income\n"
        "Consolidated Statements of Cash Flows\n"
        "Notes to the Consolidated Financial Statements\n" + _PAD
    )
    result = classify_document_text(text)
    assert result["document_class"] == DOC_CLASS_STATEMENTS_AUDITED
    assert result["signals"]["statement_family_count"] == 3


def test_two_of_four_families_refused():
    text = (
        "Consolidated Statements of Income\n"
        "Consolidated Statements of Cash Flows\n"
        "Notes to the Consolidated Financial Statements\n" + _PAD
    )
    assert classify_document_text(text)["document_class"] == DOC_CLASS_NO_STATEMENTS


def test_statements_without_notes_refused():
    """The notes requirement is load-bearing: statement headings can appear
    in an MD&A's cross-references; the notes section is the filing body."""
    text = (
        "Consolidated Balance Sheets\n"
        "Consolidated Statements of Income\n"
        "Consolidated Statements of Cash Flows\n"
        "Consolidated Statements of Changes in Equity\n" + ("filler text " * 30)
    )
    assert classify_document_text(text)["document_class"] == DOC_CLASS_NO_STATEMENTS


def test_curly_apostrophe_auditor_report_matches():
    text = AUDITED_TEXT.replace("Auditor's", "Auditor’s")
    result = classify_document_text(text)
    assert result["document_class"] == DOC_CLASS_STATEMENTS_AUDITED


def test_unaudited_markers_do_not_flip_audited_documents():
    """ATD-style: an audited annual filing whose MD&A prose says 'unaudited'
    stays audited — the auditor's report is the discriminator, not the
    marker words."""
    text = AUDITED_TEXT + " certain unaudited interim figures are condensed "
    result = classify_document_text(text)
    assert result["document_class"] == DOC_CLASS_STATEMENTS_AUDITED
    assert result["signals"]["unaudited_marker_count"] == 1


def test_refusal_message_names_what_was_looked_for():
    result = classify_document_text(PRESS_RELEASE_TEXT)
    message = refusal_message(result["signals"])
    assert "Looked for" in message
    assert "notes to the financial" in message


def test_unaudited_warning_states_observation_not_verdict():
    result = classify_document_text(UNAUDITED_TEXT)
    message = unaudited_warning_message(result["signals"])
    assert "auditor's report" in message
    assert "will proceed" in message.lower() or "proceed" in message
