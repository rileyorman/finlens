import json
from types import SimpleNamespace

import pytest

import sedar_extractor


def _page(heading: str) -> str:
    numbers = " ".join(str(i) for i in range(10))
    return f"{heading}\nFor the years ended December 31\n{numbers}\nAssets 1 2 3"


def test_page_locator_matches_core_statement_headings_and_following_pages():
    page_texts = [
        _page("Consolidated Statement of Financial Position"),
        "continuation 1 2 3 4 5 6 7 8 9 10",
        _page("Consolidated Statements of Operations"),
        "continuation 1 2 3 4 5 6 7 8 9 10",
        _page("Consolidated Statements of Cash Flows"),
        "continuation 1 2 3 4 5 6 7 8 9 10",
    ]

    result = sedar_extractor._locate_statement_pages_from_texts(page_texts)

    assert result == {
        "balance_sheet": [0, 1],
        "income_statement": [2, 3],
        "cash_flow": [4, 5],
    }


def test_page_locator_skips_toc_references_and_low_numeric_pages():
    page_texts = [
        "Table of Contents\nConsolidated Statements of Cash Flows........ 55\n1 2",
        "Intro text\n" * 30 + "Consolidated Balance Sheets\n" + " ".join(str(i) for i in range(20)),
        _page("Consolidated Balance Sheets"),
    ]

    result = sedar_extractor._locate_statement_pages_from_texts(page_texts)

    assert result["balance_sheet"] == [2]
    assert result["income_statement"] == []
    assert result["cash_flow"] == []


def test_number_parsing_parentheses_commas_and_scale_preserved():
    payload = {
        "accounting_standard": "IFRS",
        "currency": "CAD",
        "scale": "thousands",
        "fiscal_year_end": "December 31, 2025",
        "statements": {
            "balance_sheet": [
                {"label": "Cash", "values": {"2025": "1,234", "2024": "(5,678)"}, "confidence": 0.9}
            ],
            "income_statement": [],
            "cash_flow": [],
        },
    }

    result = sedar_extractor._normalize_extraction_payload(payload)

    row = result["statements"]["balance_sheet"][0]
    assert row["values"] == {"2025": 1234, "2024": -5678}
    assert result["scale"] == "thousands"


def test_extract_sedar_filing_contract_shape_with_mocked_claude(monkeypatch):
    raw_response = json.dumps(
        {
            "accounting_standard": "IFRS",
            "currency": "CAD",
            "scale": "millions",
            "fiscal_year_end": "December 31",
            "statements": {
                "balance_sheet": [
                    {"label": "Total assets", "values": {"2025": "10,000"}, "confidence": 0.97}
                ],
                "income_statement": [
                    {"label": "Net income", "values": {"2025": "(250)"}, "confidence": 0.88}
                ],
                "cash_flow": [
                    {"label": "Cash from operating activities", "values": {"2025": "500"}, "confidence": 0.93}
                ],
            },
        }
    )

    class FakeMessages:
        def create(self, **kwargs):
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=raw_response)])

    fake_client = SimpleNamespace(messages=FakeMessages())

    monkeypatch.setattr(sedar_extractor, "locate_statement_pages", lambda pdf_path: {
        "balance_sheet": [1, 2],
        "income_statement": [3, 4],
        "cash_flow": [5, 6],
    })
    monkeypatch.setattr(sedar_extractor, "_extract_located_page_text", lambda pdf_path, pages: "statement pages")
    monkeypatch.setattr(sedar_extractor, "_api_key", lambda: "test-key")
    monkeypatch.setattr(sedar_extractor, "_make_client", lambda api_key: fake_client)

    result = sedar_extractor.extract_sedar_filing("dummy.pdf")

    assert result["source"] == "sedar_pdf"
    assert result["schema_version"] == 4
    assert result["accounting_standard"] == "IFRS"
    assert result["currency"] == "CAD"
    assert result["scale"] == "millions"
    assert result["fiscal_year_end"] == "December 31"
    assert result["pages_used"]["balance_sheet"] == [1, 2]
    assert set(result["statements"].keys()) == {"balance_sheet", "income_statement", "cash_flow"}
    assert result["statements"]["income_statement"][0]["values"]["2025"] == -250
    assert result["extraction_confidence"] == pytest.approx(0.88)


# ---------------------------------------------------------------------------
# CSU FY2025 fixture test — PDF-verified assertions (campaign filer #1)
# ---------------------------------------------------------------------------

import json as _json
from pathlib import Path as _Path

_FIXTURE = _Path(__file__).parent / "fixtures" / "CSU_FY2025_sedar.json"
_FY2025_PERIOD = "Year ended December 31, 2025"


def _is_value(items: list, label: str) -> int | float | None:
    """Return the FY2025 income-statement value for an exact label match."""
    for item in items:
        if item["label"] == label:
            return item["values"].get(_FY2025_PERIOD)
    labels_found = [item["label"] for item in items]
    raise AssertionError(
        f"Label not found in income statement: {label!r}\nLabels present: {labels_found}"
    )


@pytest.mark.skipif(not _FIXTURE.exists(), reason="CSU fixture not present")
def test_csu_fy2025_fixture_contract_invariants():
    data = _json.loads(_FIXTURE.read_text(encoding="utf-8"))

    assert data["schema_version"] == 4
    assert data["source"] == "sedar_pdf"
    assert data["currency"] == "USD"
    assert data["accounting_standard"] == "IFRS"
    assert data["scale"] == "millions"
    assert "December 31, 2025" in data["fiscal_year_end"]
    assert data["extraction_confidence"] >= 0.9
    assert set(data["statements"].keys()) == {"balance_sheet", "income_statement", "cash_flow"}


@pytest.mark.skipif(not _FIXTURE.exists(), reason="CSU fixture not present")
def test_csu_fy2025_fixture_income_statement_pdf_verified():
    """
    Values verified against the actual CSU FY2025 IFRS filing (PDF page-by-eye,
    June 2026). Do NOT adjust assertions to make the test pass — a failure means
    the extraction has a real bug.
    """
    data = _json.loads(_FIXTURE.read_text(encoding="utf-8"))
    items = data["statements"]["income_statement"]

    assert _is_value(items, "Total Revenue") == 11623
    assert _is_value(items, "Net income (loss)") == 586
    assert _is_value(items, "Staff") == 5924
    assert _is_value(items, "Amortization of intangible assets (note 10)") == 1182
    # Finance and other expense (income) is parenthesized in the filing — must be negative.
    # A positive 228 here is a sign-handling bug.
    assert _is_value(items, "Finance and other expense (income) (note 18)") == -228
    assert _is_value(items, "Income tax expense (recovery)") == 353
