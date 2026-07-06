"""Figure-presence extraction guard (modules/claude_analyzer.py).

Reference incident (2026-07-03): re-analysing NVDA from filing text that was
truncated BEFORE the financial statements produced a complete fabricated
extraction — real training-data numbers attached to the wrong fiscal year —
that passed every downstream check. The guard rejects any extraction whose
figures do not literally appear in the source text.
"""
from __future__ import annotations

import json

import pytest

from config import MAX_FILING_CHARS
from modules.claude_analyzer import (
    FabricatedExtractionError,
    _check_figure_presence,
    _figure_presence,
    _number_in_text,
    is_truncated_excerpt,
)
from modules.integrity.log import append_figure_presence_to_log


def _fd(rows):
    return {"company_name": "TestCo", "income_statement": rows}


@pytest.fixture(autouse=True)
def _no_real_log_writes(monkeypatch):
    """Tests must never write to the real ~/.finlens integrity log."""
    import modules.integrity.log as integrity_log
    monkeypatch.setattr(
        integrity_log, "append_figure_presence_to_log", lambda **kwargs: None
    )


def test_number_in_text_matches_common_filing_formats():
    text = "Revenue was 130,497 for the year and 60922 prior; EPS of 2.5 and margin 12.34"
    assert _number_in_text(130497, text)          # comma format
    assert _number_in_text(60922, text)           # plain format
    assert _number_in_text(2.5, text)             # short decimal
    assert _number_in_text(12.34, text)           # two-decimal
    assert not _number_in_text(215938, text)      # absent number


def test_fabricated_extraction_is_rejected(tmp_path):
    # None of the extracted values appear in the text — the NVDA case.
    rows = [
        {"line_item": "Revenue", "value": 130497},
        {"line_item": "Cost of revenue", "value": 37132},
        {"line_item": "Gross profit", "value": 93365},
        {"line_item": "R&D", "value": 14880},
        {"line_item": "Net income", "value": 68054},
    ]
    text = "Item 1A. Risk Factors. Long manufacturing lead times and uncertain supply..."
    with pytest.raises(FabricatedExtractionError) as excinfo:
        _check_figure_presence(_fd(rows), text, model="test-model")
    assert "do not" in str(excinfo.value) or "appear in the source" in str(excinfo.value)


def test_genuine_extraction_passes():
    rows = [
        {"line_item": "Revenue", "value": 130497},
        {"line_item": "Cost of revenue", "value": 37132},
        {"line_item": "Gross profit", "value": 93365},
        {"line_item": "R&D", "value": 14880},
        {"line_item": "Net income", "value": 68054},
    ]
    text = (
        "Revenue 130,497 Cost of revenue 37,132 Gross profit 93,365 "
        "Research and development 14,880 Net income 68,054"
    )
    presence = _check_figure_presence(_fd(rows), text, model="test-model")
    assert presence["verdict"] == "PASS"
    assert presence["checked"] == 5
    assert presence["found"] == 5


def test_small_extractions_are_not_judged():
    # Below FIGURE_PRESENCE_MIN_ROWS there is too little evidence to reject —
    # a sparse-but-honest extraction must not be blocked.
    rows = [
        {"line_item": "Revenue", "value": 111222},
        {"line_item": "Net income", "value": 333444},
    ]
    presence = _check_figure_presence(_fd(rows), "no numbers here", model="test-model")
    assert presence["verdict"] == "PASS"
    assert presence["found"] == 0


def test_section_headers_and_none_values_are_skipped():
    rows = [
        {"line_item": "OPERATING ACTIVITIES", "value": None},
        {"line_item": "Revenue", "value": 500},
    ]
    presence = _figure_presence(_fd(rows), "Revenue was 500")
    assert presence["checked"] == 1
    assert presence["found"] == 1


def test_figure_presence_log_record_written(tmp_path):
    log_path = tmp_path / "integrity_log.jsonl"
    append_figure_presence_to_log(
        company="TestCo",
        model="test-model",
        checked=5,
        found=0,
        ratio=0.0,
        verdict="FABRICATED",
        source_chars=80_000,
        log_path=log_path,
    )
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["record_type"] == "extraction_figure_presence"
    assert record["verdict"] == "FABRICATED"
    assert record["checked"] == 5
    assert record["source_chars"] == 80_000


# ---------------------------------------------------------------------------
# Per-row detail tests (Part B)
# ---------------------------------------------------------------------------

def test_figure_presence_per_row_detail():
    """_figure_presence returns a rows list with correct per-row found flags."""
    rows = [
        {"line_item": "Revenue", "value": 100},
        {"line_item": "Net income", "value": 200},
        {"line_item": "EBITDA", "value": 300},
    ]
    fd = {"company_name": "TestCo", "income_statement": rows}
    presence = _figure_presence(fd, "Revenue was 100 and EBITDA was 300")
    assert len(presence["rows"]) == 3
    by_item = {r["line_item"]: r for r in presence["rows"]}
    assert by_item["Revenue"]["found"] is True
    assert by_item["Revenue"]["section"] == "income_statement"
    assert by_item["Net income"]["found"] is False
    assert by_item["EBITDA"]["found"] is True


def test_missing_rows_cap(tmp_path):
    """missing_rows in log record is capped at 20; missing_count is total."""
    rows = [{"line_item": "Item" + str(i), "value": 100000 + i} for i in range(25)]
    fd = {"company_name": "TestCo", "income_statement": rows}
    presence = _figure_presence(fd, "no numbers here")
    missing_all = [
        r["section"] + ":" + r["line_item"]
        for r in presence["rows"]
        if not r["found"]
    ]
    missing_count = len(missing_all)
    missing_rows = missing_all[:20]
    log_path = tmp_path / "integrity_log.jsonl"
    append_figure_presence_to_log(
        company="TestCo",
        model="test-model",
        checked=presence["checked"],
        found=presence["found"],
        ratio=presence["ratio"],
        verdict="FABRICATED",
        source_chars=100,
        missing_rows=missing_rows,
        missing_count=missing_count,
        log_path=log_path,
    )
    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert len(record["missing_rows"]) == 20
    assert record["missing_count"] == 25


def test_aggregate_behavior_unchanged():
    """checked/found/ratio are identical before and after the per-row change."""
    rows = [
        {"line_item": "Revenue", "value": 130497},
        {"line_item": "Cost of revenue", "value": 37132},
        {"line_item": "Gross profit", "value": 93365},
        {"line_item": "R&D", "value": 14880},
        {"line_item": "Net income", "value": 68054},
    ]
    text = (
        "Revenue 130,497 Cost of revenue 37,132 Gross profit 93,365 "
        "Research and development 14,880 Net income 68,054"
    )
    presence = _figure_presence(_fd(rows), text)
    assert presence["checked"] == 5
    assert presence["found"] == 5
    assert presence["ratio"] == 1.0
    # rows list is additional output; aggregate fields are untouched
    assert "rows" in presence
    assert len(presence["rows"]) == 5


# ---------------------------------------------------------------------------
# Truncated-excerpt detection (fabrication fix (b))
# ---------------------------------------------------------------------------
# Stored library/cache text of exactly MAX_FILING_CHARS is the signature of a
# legacy text[:MAX_FILING_CHARS] write. Re-Analyse must never feed such an
# excerpt to extraction — it is routed to PDF re-extraction or an honest error.

def test_truncated_excerpt_signature_detected():
    assert is_truncated_excerpt("x" * MAX_FILING_CHARS)


def test_full_documents_are_not_flagged_as_truncated():
    assert not is_truncated_excerpt("x" * (MAX_FILING_CHARS + 1))   # full large doc
    assert not is_truncated_excerpt("x" * (MAX_FILING_CHARS - 1))   # genuinely small doc
    assert not is_truncated_excerpt("short filing text")
    assert not is_truncated_excerpt("")
    assert not is_truncated_excerpt(None)
