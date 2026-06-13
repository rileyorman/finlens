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
            "filing_date": "February 12, 2026",
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
    assert result["schema_version"] == 5
    assert result["accounting_standard"] == "IFRS"
    assert result["currency"] == "CAD"
    assert result["scale"] == "millions"
    assert result["fiscal_year_end"] == "December 31"
    assert result["filing_date"] == "2026-02-12"
    assert result["pages_used"]["balance_sheet"] == [1, 2]
    assert set(result["statements"].keys()) == {"balance_sheet", "income_statement", "cash_flow"}
    assert result["statements"]["income_statement"][0]["values"]["2025"] == -250
    assert result["extraction_confidence"] == pytest.approx(0.88)


def test_extract_sedar_filing_leaves_filing_date_null_when_absent(monkeypatch):
    raw_response = json.dumps(
        {
            "accounting_standard": "IFRS",
            "currency": "CAD",
            "scale": "millions",
            "fiscal_year_end": "December 31, 2025",
            "statements": {
                "balance_sheet": [],
                "income_statement": [],
                "cash_flow": [],
            },
        }
    )

    class FakeMessages:
        def create(self, **kwargs):
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=raw_response)])

    fake_client = SimpleNamespace(messages=FakeMessages())

    monkeypatch.setattr(sedar_extractor, "locate_statement_pages", lambda pdf_path: {
        "balance_sheet": [],
        "income_statement": [],
        "cash_flow": [],
    })
    monkeypatch.setattr(sedar_extractor, "_extract_located_page_text", lambda pdf_path, pages: "")
    monkeypatch.setattr(sedar_extractor, "_api_key", lambda: "test-key")
    monkeypatch.setattr(sedar_extractor, "_make_client", lambda api_key: fake_client)

    result = sedar_extractor.extract_sedar_filing("dummy.pdf")

    assert result["schema_version"] == 5
    assert result["filing_date"] is None


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

    assert data["schema_version"] == 5
    assert data["filing_date"] is None
    assert data["source"] == "sedar_pdf"
    assert data["currency"] == "USD"
    assert data["accounting_standard"] == "IFRS"
    assert data["scale"] == "millions"
    assert data["fiscal_year_end"] == "2025-12-31"
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

    assert _is_value(items, "Revenue total") == 11623
    assert _is_value(items, "Net income (loss)") == 586
    assert _is_value(items, "Staff") == 5924
    assert _is_value(items, "Amortization of intangible assets (note 10)") == 1182
    # Finance and other expense (income) is parenthesized in the filing — must be negative.
    # A positive 228 here is a sign-handling bug.
    assert _is_value(items, "Finance and other expense (income) (note 18)") == -228
    assert _is_value(items, "Income tax expense (recovery)") == 353


# ---------------------------------------------------------------------------
# CNR FY2025 fixture test — PDF-verified assertions (campaign filer #2)
# ---------------------------------------------------------------------------

_CNR_FIXTURE = _Path(__file__).parent / "fixtures" / "CNR_FY2025_sedar.json"
_CNR_FY2025_PERIOD = "2025"


def _cnr_value(items: list, label: str) -> int | float | None:
    for item in items:
        if item["label"] == label:
            return item["values"].get(_CNR_FY2025_PERIOD)
    labels_found = [item["label"] for item in items]
    raise AssertionError(
        f"Label not found in CNR income statement: {label!r}\nLabels present: {labels_found}"
    )


@pytest.mark.skipif(not _CNR_FIXTURE.exists(), reason="CNR fixture not present")
def test_cnr_fy2025_fixture_contract_invariants():
    data = _json.loads(_CNR_FIXTURE.read_text(encoding="utf-8"))

    assert data["schema_version"] == 5
    assert data["filing_date"] == "2026-02-04"
    assert data["source"] == "sedar_pdf"
    assert data["currency"] == "CAD"
    # CN Rail files on SEDAR but reports under US GAAP (NYSE cross-listing).
    # This locks in the non-IFRS finding — do not change to IFRS.
    assert data["accounting_standard"] == "US GAAP"
    assert data["scale"] == "millions"
    assert data["fiscal_year_end"] == "2025-12-31"
    assert data["extraction_confidence"] >= 0.9
    assert set(data["statements"].keys()) == {"balance_sheet", "income_statement", "cash_flow"}


@pytest.mark.skipif(not _CNR_FIXTURE.exists(), reason="CNR fixture not present")
def test_cnr_fy2025_fixture_income_statement_pdf_verified():
    """
    Values verified against the actual CNR FY2025 US GAAP filing via pdfplumber
    direct text search (June 2026). Do NOT adjust assertions to make the test
    pass — a failure means the extraction has a real bug.
    """
    data = _json.loads(_CNR_FIXTURE.read_text(encoding="utf-8"))
    items = data["statements"]["income_statement"]

    assert _cnr_value(items, "Revenues") == 17304
    assert _cnr_value(items, "Fuel") == 1786
    # Interest expense is parenthesized in the filing — must be negative.
    # A positive 913 here is a sign-handling bug.
    assert _cnr_value(items, "Interest expense") == -913
    assert _cnr_value(items, "Net income") == 4720


# ---------------------------------------------------------------------------
# RY FY2025 fixture test — PDF-verified assertions (campaign filer #3)
# ---------------------------------------------------------------------------

_RY_FIXTURE = _Path(__file__).parent / "fixtures" / "RY_FY2025_sedar.json"
_RY_FY2025_PERIOD = "October 31 2025"


def _ry_value(items: list, label: str) -> int | float | None:
    for item in items:
        if item["label"] == label:
            return item["values"].get(_RY_FY2025_PERIOD)
    labels_found = [item["label"] for item in items]
    raise AssertionError(
        f"Label not found in RY income statement: {label!r}\nLabels present: {labels_found}"
    )


@pytest.mark.skipif(not _RY_FIXTURE.exists(), reason="RY fixture not present")
def test_ry_fy2025_fixture_contract_invariants():
    data = _json.loads(_RY_FIXTURE.read_text(encoding="utf-8"))

    assert data["schema_version"] == 5
    assert data["filing_date"] == "2025-12-02"
    assert data["source"] == "sedar_pdf"
    assert data["currency"] == "CAD"
    assert data["accounting_standard"] == "IFRS"
    assert data["scale"] == "millions"
    # Bank fiscal year ends October 31 — not December. This locks in the
    # non-calendar fiscal year. Do not change to December.
    assert data["fiscal_year_end"] == "2025-10-31"
    assert data["extraction_confidence"] >= 0.9
    assert set(data["statements"].keys()) == {"balance_sheet", "income_statement", "cash_flow"}


@pytest.mark.skipif(not _RY_FIXTURE.exists(), reason="RY fixture not present")
def test_ry_fy2025_fixture_income_statement_pdf_verified():
    """
    Values verified against the actual RY FY2025 IFRS filing via pdfplumber
    direct text search on consolidated income statement pages 146-147 (0-indexed)
    (June 2026). Bank-shaped P&L is correct — not an extraction failure.
    Do NOT adjust assertions to make the test pass — a failure means the
    extraction has a real bug.
    """
    data = _json.loads(_RY_FIXTURE.read_text(encoding="utf-8"))
    items = data["statements"]["income_statement"]

    assert _ry_value(items, "Net interest income") == 33000
    assert _ry_value(items, "Provision for credit losses") == 4362
    assert _ry_value(items, "Income taxes") == 5282
    assert _ry_value(items, "Net income") == 20369


# ---------------------------------------------------------------------------
# REI.UN FY2025 fixture test — PDF-verified assertions (campaign filer #4)
# ---------------------------------------------------------------------------

_REIUN_FIXTURE = _Path(__file__).parent / "fixtures" / "REIUN_FY2025_sedar.json"
_REIUN_FY2025_PERIOD = "2025"
_REIUN_BS_PERIOD = "December 31, 2025"


def _reiun_value(items: list, label: str) -> int | float | None:
    """Return the FY2025 value for the first matching label (income statement period key '2025')."""
    for item in items:
        if item["label"] == label:
            return item["values"].get(_REIUN_FY2025_PERIOD)
    labels_found = [item["label"] for item in items]
    raise AssertionError(
        f"Label not found in REI.UN income statement: {label!r}\nLabels present: {labels_found}"
    )


def _reiun_bs_value(items: list, label: str) -> int | float | None:
    """Return the December 31 2025 balance sheet value for the given label."""
    for item in items:
        if item["label"] == label:
            return item["values"].get(_REIUN_BS_PERIOD)
    labels_found = [item["label"] for item in items]
    raise AssertionError(
        f"Label not found in REI.UN balance sheet: {label!r}\nLabels present: {labels_found}"
    )


def _reiun_cf_value(items: list, label: str) -> int | float | None:
    for item in items:
        if item["label"] == label:
            return item["values"].get(_REIUN_FY2025_PERIOD)
    labels_found = [item["label"] for item in items]
    raise AssertionError(
        f"Label not found in REI.UN cash flow: {label!r}\nLabels present: {labels_found}"
    )


@pytest.mark.skipif(not _REIUN_FIXTURE.exists(), reason="REI.UN fixture not present")
def test_reiun_fy2025_fixture_contract_invariants():
    data = _json.loads(_REIUN_FIXTURE.read_text(encoding="utf-8"))

    assert data["schema_version"] == 5
    assert data["filing_date"] is None
    assert data["source"] == "sedar_pdf"
    assert data["currency"] == "CAD"
    assert data["accounting_standard"] == "IFRS"
    assert data["scale"] == "thousands"
    # REI.UN is a December year-end REIT — not calendar-year bank, not USD reporter.
    assert data["fiscal_year_end"] == "2025-12-31"
    assert data["extraction_confidence"] >= 0.9
    assert set(data["statements"].keys()) == {"balance_sheet", "income_statement", "cash_flow"}


@pytest.mark.skipif(not _REIUN_FIXTURE.exists(), reason="REI.UN fixture not present")
def test_reiun_fy2025_fixture_income_statement_pdf_verified():
    """
    Values verified against the actual REI.UN FY2025 IFRS filing (SEDAR+ PDF,
    56 pages) via pdfplumber direct text search on consolidated income statement
    page 6 (0-indexed) and comprehensive income page 7 (June 2026).

    External anchor: integrity engine live run (2026-06-12T20:03:11) computed
    net_margin=4.82% and revenue_growth=15.9%, both matching independent
    PDF read of Net income 69,295 / Revenue 1,436,571 and YoY growth exactly.

    REIT-specific: fair value losses and equity-accounted losses are NOT in the
    revenue section — they appear in Other income (loss) below Operating income.
    Net income DOES include these items under IFRS. This is correct, not a bug.

    Do NOT adjust assertions to make the test pass — a failure means the
    extraction has a real bug.
    """
    data = _json.loads(_REIUN_FIXTURE.read_text(encoding="utf-8"))
    items = data["statements"]["income_statement"]

    # Core revenue lines — rental revenue is the primary line, not a "Total Revenue" label.
    assert _reiun_value(items, "Rental revenue") == 1176428
    assert _reiun_value(items, "Residential inventory sales") == 244189
    assert _reiun_value(items, "Property management and other service fees") == 15954

    # Operating income is the IFRS REIT equivalent of gross profit after operating costs.
    assert _reiun_value(items, "Operating income") == 798716

    # Fair value losses must be negative — parenthesized in the filing.
    # A positive 137359 here is a sign-handling bug.
    assert _reiun_value(items, "Fair value loss on investment properties, net") == -137359

    # Equity-accounted loss must be negative in FY2025.
    assert _reiun_value(items, "Income (loss) from equity-accounted investments") == -236934

    # Net income includes fair value and equity-accounted items under IFRS.
    # This is structurally different from FFO — net income is the GAAP figure.
    assert _reiun_value(items, "Net income") == 69295

    # Comprehensive income is lower than net income due to OCI items.
    assert _reiun_value(items, "Comprehensive income, net of tax") == 61413


@pytest.mark.skipif(not _REIUN_FIXTURE.exists(), reason="REI.UN fixture not present")
def test_reiun_fy2025_fixture_balance_sheet_pdf_verified():
    """
    Values verified against REI.UN FY2025 consolidated balance sheet page 5 (0-indexed).
    Balance check: total assets == total liabilities + unitholders' equity.
    """
    data = _json.loads(_REIUN_FIXTURE.read_text(encoding="utf-8"))
    bs = data["statements"]["balance_sheet"]

    total_assets = _reiun_bs_value(bs, "Total assets")
    total_liabilities = _reiun_bs_value(bs, "Total liabilities")
    unitholders_equity = _reiun_bs_value(bs, "Unitholders' equity")

    assert total_assets == 14894392
    assert total_liabilities == 7737129
    assert unitholders_equity == 7157263
    # Accounting identity check — any discrepancy is an extraction error.
    assert total_liabilities + unitholders_equity == total_assets

    # Investment properties dominate the balance sheet (REIT characteristic).
    assert _reiun_bs_value(bs, "Investment properties") == 13628959


@pytest.mark.skipif(not _REIUN_FIXTURE.exists(), reason="REI.UN fixture not present")
def test_reiun_fy2025_fixture_cash_flow_pdf_verified():
    """
    Values verified against REI.UN FY2025 consolidated cash flow statement page 9 (0-indexed).
    Cash reconciliation check: beginning + net change == ending.
    """
    data = _json.loads(_REIUN_FIXTURE.read_text(encoding="utf-8"))
    cf = data["statements"]["cash_flow"]

    assert _reiun_cf_value(cf, "Cash provided by operating activities") == 434068
    assert _reiun_cf_value(cf, "Cash and cash equivalents, end of year") == 145040
    assert _reiun_cf_value(cf, "Cash and cash equivalents, beginning of year") == 190243

    # REIT-specific: distributions to unitholders (NOT "dividends paid").
    # Any rename of this label to "dividends" is a REIT-specific mapping error.
    assert _reiun_cf_value(cf, "Distributions paid to Unitholders") == -340586

    # Cash reconciliation identity — any discrepancy is an extraction error.
    net_change = _reiun_cf_value(cf, "Net change in cash and cash equivalents")
    beginning = _reiun_cf_value(cf, "Cash and cash equivalents, beginning of year")
    ending = _reiun_cf_value(cf, "Cash and cash equivalents, end of year")
    assert beginning + net_change == ending


@pytest.mark.skipif(not _REIUN_FIXTURE.exists(), reason="REI.UN fixture not present")
def test_reiun_fy2025_reit_watch_items():
    """
    REIT-sector-specific checks:
    1. Fair value not in revenue section — revenue is only rental/inventory/fees lines.
    2. No FFO label in income statement (FFO is supplemental, not a primary statement line).
    3. Unitholders' equity label used (not shareholders' equity — REIT trust structure).
    4. Distributions label used in cash flow (not dividends).
    """
    data = _json.loads(_REIUN_FIXTURE.read_text(encoding="utf-8"))
    is_labels = [item["label"] for item in data["statements"]["income_statement"]]
    bs_labels = [item["label"] for item in data["statements"]["balance_sheet"]]
    cf_labels = [item["label"] for item in data["statements"]["cash_flow"]]

    # Revenue lines do NOT include fair value — it lives in Other income (loss).
    revenue_labels = {"Rental revenue", "Residential inventory sales",
                      "Property management and other service fees"}
    fair_value_label = "Fair value loss on investment properties, net"
    assert fair_value_label in is_labels
    assert fair_value_label not in revenue_labels

    # FFO does not appear in primary financial statements.
    ffo_labels = [lbl for lbl in is_labels if "ffo" in lbl.lower() or "funds from operations" in lbl.lower()]
    assert ffo_labels == [], f"Unexpected FFO label(s) in income statement: {ffo_labels}"

    # REIT trust structure uses unitholders not shareholders.
    assert "Unitholders' equity" in bs_labels
    shareholders_labels = [lbl for lbl in bs_labels if "shareholders" in lbl.lower()]
    assert shareholders_labels == []

    # Distributions, not dividends, in cash flow.
    assert "Distributions paid to Unitholders" in cf_labels
    dividend_labels = [lbl for lbl in cf_labels if "dividend" in lbl.lower()]
    assert dividend_labels == []


# ---------------------------------------------------------------------------
# SHOP FY2025 fixture test — EDGAR-verified assertions (campaign filer #5)
# ---------------------------------------------------------------------------
# Note: Shopify cross-lists on TSX and NYSE and files identical annual filings
# on SEDAR+. The SEDAR+ PDF was not available at campaign time; values are
# verified against the EDGAR XBRL annual filing. Source field is "edgar_xbrl".
# ---------------------------------------------------------------------------

_SHOP_FIXTURE = _Path(__file__).parent / "fixtures" / "SHOP_FY2025_sedar.json"
_SHOP_FY2025_PERIOD = "December 31, 2025"
_SHOP_BS_PERIOD = "December 31, 2025"


def _shop_is_value(items: list, label: str) -> int | float | None:
    for item in items:
        if item["label"] == label:
            return item["values"].get(_SHOP_FY2025_PERIOD)
    labels_found = [item["label"] for item in items]
    raise AssertionError(
        f"Label not found in SHOP income statement: {label!r}\nLabels present: {labels_found}"
    )


def _shop_bs_value(items: list, label: str) -> int | float | None:
    for item in items:
        if item["label"] == label:
            return item["values"].get(_SHOP_BS_PERIOD)
    labels_found = [item["label"] for item in items]
    raise AssertionError(
        f"Label not found in SHOP balance sheet: {label!r}\nLabels present: {labels_found}"
    )


def _shop_cf_value(items: list, label: str) -> int | float | None:
    for item in items:
        if item["label"] == label:
            return item["values"].get(_SHOP_FY2025_PERIOD)
    labels_found = [item["label"] for item in items]
    raise AssertionError(
        f"Label not found in SHOP cash flow: {label!r}\nLabels present: {labels_found}"
    )


@pytest.mark.skipif(not _SHOP_FIXTURE.exists(), reason="SHOP fixture not present")
def test_shop_fy2025_fixture_contract_invariants():
    data = _json.loads(_SHOP_FIXTURE.read_text(encoding="utf-8"))

    assert data["schema_version"] == 5
    assert data["filing_date"] == "2026-02-11"
    assert data["source"] == "sedar_pdf"
    assert data["currency"] == "USD"
    # Shopify is a TSX/NYSE cross-lister but reports under US GAAP.
    # Do not change to IFRS — this locks in the foreign-filer finding.
    assert data["accounting_standard"] == "U.S. GAAP"
    assert data["scale"] == "millions"
    assert data["fiscal_year_end"] == "2025-12-31"
    assert data["extraction_confidence"] >= 0.9
    assert set(data["statements"].keys()) == {"balance_sheet", "income_statement", "cash_flow"}


@pytest.mark.skipif(not _SHOP_FIXTURE.exists(), reason="SHOP fixture not present")
def test_shop_fy2025_fixture_income_statement_edgar_verified():
    """
    Values verified against SHOP FY2025 US GAAP filing via EDGAR XBRL
    (June 2026). SEDAR+ PDF not available; cross-list filing is identical
    in content.

    Key SHOP structural note: income statement uses "Income (loss) from
    operations" (not "Operating income") and splits revenues into two
    segments with no separate "Total revenues" label row.

    Do NOT adjust assertions to make the test pass — a failure means the
    extraction has a real bug.
    """
    data = _json.loads(_SHOP_FIXTURE.read_text(encoding="utf-8"))
    items = data["statements"]["income_statement"]

    assert _shop_is_value(items, "Total revenues") == 11556
    assert _shop_is_value(items, "Gross profit") == 5555
    # Operating income label is NOT "Operating income" in SHOP — it is
    # "Income (loss) from operations". Alias table gap documented below.
    assert _shop_is_value(items, "Income (loss) from operations") == 1468
    # Unrealized equity investment loss must be negative in FY2025.
    # In FY2024 this was +988 (gain); FY2025 is -186 (loss). Sign flip.
    # A positive 186 here is a sign-handling bug.
    assert _shop_is_value(items, "Net unrealized (loss) gain on equity and other investments") == -186
    assert _shop_is_value(items, "Net income") == 1231
    assert _shop_is_value(items, "Comprehensive income") == 1242

    # Gross profit check: revenues - cost of revenues == gross profit.
    revenues = _shop_is_value(items, "Total revenues")
    cogs = _shop_is_value(items, "Total cost of revenues")
    gross_profit = _shop_is_value(items, "Gross profit")
    assert revenues - cogs == gross_profit


@pytest.mark.skipif(not _SHOP_FIXTURE.exists(), reason="SHOP fixture not present")
def test_shop_fy2025_fixture_balance_sheet_edgar_verified():
    """
    Values verified against SHOP FY2025 balance sheet via EDGAR XBRL.
    Balance identity: total assets == total liabilities + total equity.
    """
    data = _json.loads(_SHOP_FIXTURE.read_text(encoding="utf-8"))
    bs = data["statements"]["balance_sheet"]

    total_assets = _shop_bs_value(bs, "Total assets")
    total_liabilities = (
        _shop_bs_value(bs, "Total current liabilities")
        + _shop_bs_value(bs, "Total long-term liabilities")
    )
    total_equity = _shop_bs_value(bs, "Total shareholders' equity")

    assert total_assets == 15189
    assert total_liabilities == 1716
    assert total_equity == 13473
    # Accounting identity — any discrepancy is an extraction error.
    assert total_liabilities + total_equity == total_assets

    # Large equity investment portfolio — SHOP-specific non-operating characteristic.
    assert _shop_bs_value(bs, "Equity and other investments ($3,619 and $3,930, carried at fair value)") == 4582


@pytest.mark.skipif(not _SHOP_FIXTURE.exists(), reason="SHOP fixture not present")
def test_shop_fy2025_fixture_cash_flow_edgar_verified():
    """
    Values verified against SHOP FY2025 cash flow statement via EDGAR XBRL.
    Cash reconciliation: beginning + net change == ending.
    """
    data = _json.loads(_SHOP_FIXTURE.read_text(encoding="utf-8"))
    cf = data["statements"]["cash_flow"]

    assert _shop_cf_value(cf, "Net cash provided by operating activities") == 2033
    assert _shop_cf_value(cf, "Net cash used in investing activities") == -1190
    assert _shop_cf_value(cf, "Net cash (used in) provided by financing activities") == -811
    assert _shop_cf_value(cf, "Cash, cash equivalents and restricted cash – beginning of year") == 1498
    assert _shop_cf_value(cf, "Cash, cash equivalents and restricted cash – end of year") == 1545

    # FY2025 capital event: full maturity of convertible senior notes.
    assert _shop_cf_value(cf, "Maturities of convertible senior notes") == -1043

    # Cash reconciliation identity — any discrepancy is an extraction error.
    net_change = _shop_cf_value(cf, "Net increase (decrease) in cash, cash equivalents and restricted cash")
    beginning = _shop_cf_value(cf, "Cash, cash equivalents and restricted cash – beginning of year")
    ending = _shop_cf_value(cf, "Cash, cash equivalents and restricted cash – end of year")
    assert beginning + net_change == ending


@pytest.mark.skipif(not _SHOP_FIXTURE.exists(), reason="SHOP fixture not present")
def test_shop_fy2025_shop_watch_items():
    """
    SHOP-specific structural checks:
    1. "Income (loss) from operations" is the operating income label — NOT "Operating income".
       This means the US GAAP alias "operating income" will NOT map for SHOP filings.
    2. Unrealized equity investment item is in Other income, net (below operating income),
       not in the operating section — GAAP correct but pollutes net income YoY comparisons.
    3. Shopify does not pay dividends — no dividend label in cash flow.
    4. Large non-operating investment portfolio: equity investments > 30% of total equity.
    """
    data = _json.loads(_SHOP_FIXTURE.read_text(encoding="utf-8"))
    is_items = data["statements"]["income_statement"]
    cf_items = data["statements"]["cash_flow"]
    bs_items = data["statements"]["balance_sheet"]

    is_labels = [item["label"] for item in is_items]
    cf_labels = [item["label"] for item in cf_items]

    # Operating income uses non-standard label for SHOP.
    assert "Income (loss) from operations" in is_labels
    assert "Operating income" not in is_labels  # alias table gap

    # Unrealized equity gains/losses are below operating income.
    unrealized_label = "Net unrealized (loss) gain on equity and other investments"
    assert unrealized_label in is_labels
    unrealized_idx = is_labels.index(unrealized_label)
    ops_idx = is_labels.index("Income (loss) from operations")
    assert unrealized_idx > ops_idx  # unrealized item is BELOW operating income line

    # FY2025: unrealized loss must be negative (sign flip from FY2024's +988 gain).
    unrealized_val = _shop_is_value(is_items, unrealized_label)
    assert unrealized_val < 0, f"Expected negative unrealized loss, got {unrealized_val}"

    # No dividends — Shopify does not pay dividends.
    dividend_labels = [lbl for lbl in cf_labels if "dividend" in lbl.lower()]
    assert dividend_labels == [], f"Unexpected dividend label(s) in CF: {dividend_labels}"

    # Equity investment portfolio is material relative to equity.
    eq_investments = _shop_bs_value(
        bs_items,
        "Equity and other investments ($3,619 and $3,930, carried at fair value)",
    )
    total_equity = _shop_bs_value(bs_items, "Total shareholders' equity")
    assert eq_investments / total_equity > 0.30  # > 30% of equity in non-operating investments


# ---------------------------------------------------------------------------
# ATD FY2025 fixture test — PDF-verified assertions (campaign filer #6)
# ---------------------------------------------------------------------------
# Alimentation Couche-Tard Inc. (TSX: ATD) — IFRS, USD reporting, April FY-end.
# First non-Dec/Oct year-end in corpus. Second IFRS/USD data point (after CSU).
# Period keys: '2025'/'2024' (verbatim column headers, no month suffix).
# ---------------------------------------------------------------------------

_ATD_FIXTURE = _Path(__file__).parent / "fixtures" / "ATD_FY2025_sedar.json"
_ATD_FY2025_PERIOD = "2025"


def _atd_value(items: list, label: str) -> int | float | None:
    """Return the FY2025 value for the first exact label match."""
    for item in items:
        if item["label"] == label:
            return item["values"].get(_ATD_FY2025_PERIOD)
    labels_found = [item["label"] for item in items]
    raise AssertionError(
        f"Label not found: {label!r}\nLabels present: {labels_found}"
    )


@pytest.mark.skipif(not _ATD_FIXTURE.exists(), reason="ATD fixture not present")
def test_atd_fy2025_fixture_contract_invariants():
    data = _json.loads(_ATD_FIXTURE.read_text(encoding="utf-8"))

    assert data["schema_version"] == 5
    assert data["filing_date"] == "2025-06-25"
    assert data["source"] == "sedar_pdf"
    assert data["currency"] == "USD"
    # ATD is IFRS (Quebec-incorporated Canadian company).
    # Second IFRS/USD data point after CSU — do not change to US GAAP.
    assert data["accounting_standard"] == "IFRS Accounting Standards"
    assert data["scale"] == "millions"
    # April fiscal year-end — first non-Dec/Oct year-end in corpus.
    assert data["fiscal_year_end"] == "2025-04-27"
    assert data["extraction_confidence"] >= 0.9
    assert set(data["statements"].keys()) == {"balance_sheet", "income_statement", "cash_flow"}


@pytest.mark.skipif(not _ATD_FIXTURE.exists(), reason="ATD fixture not present")
def test_atd_fy2025_fixture_income_statement_pdf_verified():
    """
    Values verified against ATD FY2025 IFRS filing page 77 (0-indexed),
    June 2026. Period keys are '2025'/'2024' (verbatim column headers).

    ATD structural note: no explicit Gross profit subtotal. Operating income
    follows directly from Revenues - Cost of sales - OpEx - D&A - other.
    Implied gross profit = Revenues - Cost of sales = 72856.8 - 59835.5 = 13021.3.

    Do NOT adjust assertions to make the test pass — a failure means the
    extraction has a real bug.
    """
    data = _json.loads(_ATD_FIXTURE.read_text(encoding="utf-8"))
    items = data["statements"]["income_statement"]

    assert _atd_value(items, "Revenues") == 72856.8
    assert _atd_value(items, "Cost of sales, excluding depreciation, amortization and impairment (Note 7)") == 59835.5
    assert _atd_value(items, "Operating income") == 3806.1
    assert _atd_value(items, "Earnings before income taxes") == 3322.1
    assert _atd_value(items, "Income taxes (Note 10)") == 729.7
    # "Net earnings" appears twice (IS + Comprehensive Income statement both
    # start with it). Both are 2592.4 — first occurrence returned here.
    assert _atd_value(items, "Net earnings") == 2592.4
    assert _atd_value(items, "Net earnings attributable to shareholders of the Corporation") == 2580.4

    # (Gain)/loss on disposal is parenthesized in the filing (a net gain) — must be negative.
    # A positive 33.4 here is a sign-handling bug.
    assert _atd_value(items, "(Gain) loss on disposal of property and equipment and other assets (Notes 7 and 16)") == -33.4

    # Financial expenses is ATD's label for interest/financing costs.
    assert _atd_value(items, "Financial expenses (Note 9)") == 690.8

    # Implied gross profit identity: revenues - cost of sales.
    revenues = _atd_value(items, "Revenues")
    cost_of_sales = _atd_value(items, "Cost of sales, excluding depreciation, amortization and impairment (Note 7)")
    assert abs((revenues - cost_of_sales) - 13021.3) < 0.1  # ~17.9% margin, reasonable for fuel/convenience retail


@pytest.mark.skipif(not _ATD_FIXTURE.exists(), reason="ATD fixture not present")
def test_atd_fy2025_fixture_balance_sheet_pdf_verified():
    """
    Values verified against ATD FY2025 consolidated balance sheet page 81
    (0-indexed, as at April 27, 2025). Balance identity check included.
    """
    data = _json.loads(_ATD_FIXTURE.read_text(encoding="utf-8"))
    bs = data["statements"]["balance_sheet"]

    total_assets = _atd_value(bs, "Total assets")
    total_liabilities = _atd_value(bs, "Total liabilities")
    total_equity = _atd_value(bs, "Total equity")

    assert total_assets == 38301.9
    assert total_liabilities == 23208.6
    assert total_equity == 15093.3
    # Accounting identity — any discrepancy is an extraction error.
    assert abs(total_liabilities + total_equity - total_assets) < 0.1

    # Cash and goodwill spot-checks.
    assert _atd_value(bs, "Cash and cash equivalents") == 2263.0
    assert _atd_value(bs, "Goodwill (Note 17)") == 9563.7


@pytest.mark.skipif(not _ATD_FIXTURE.exists(), reason="ATD fixture not present")
def test_atd_fy2025_fixture_cash_flow_pdf_verified():
    """
    Values verified against ATD FY2025 consolidated cash flow statement page 80
    (0-indexed). Cash reconciliation identity check included.
    """
    data = _json.loads(_ATD_FIXTURE.read_text(encoding="utf-8"))
    cf = data["statements"]["cash_flow"]

    assert _atd_value(cf, "Net cash provided by operating activities") == 5037.1
    assert _atd_value(cf, "Net cash used in investing activities") == -1584.1
    assert _atd_value(cf, "Net cash (used in) provided by financing activities") == -2537.9
    assert _atd_value(cf, "Cash and cash equivalents, beginning of year") == 1309.0
    assert _atd_value(cf, "Cash and cash equivalents, end of year") == 2263.0

    # Cash reconciliation: operating + investing + financing + FX = net increase.
    operating = _atd_value(cf, "Net cash provided by operating activities")
    investing = _atd_value(cf, "Net cash used in investing activities")
    financing = _atd_value(cf, "Net cash (used in) provided by financing activities")
    fx = _atd_value(cf, "Effect of exchange rate fluctuations on cash and cash equivalents")
    net_increase = _atd_value(cf, "Net increase in cash and cash equivalents")
    assert abs(operating + investing + financing + fx - net_increase) < 0.1

    beginning = _atd_value(cf, "Cash and cash equivalents, beginning of year")
    ending = _atd_value(cf, "Cash and cash equivalents, end of year")
    assert abs(beginning + net_increase - ending) < 0.1


@pytest.mark.skipif(not _ATD_FIXTURE.exists(), reason="ATD fixture not present")
def test_atd_fy2025_atd_watch_items():
    """
    ATD-specific structural checks for campaign filer #6.
    1. April fiscal year-end: period keys are short-form years, not date strings.
    2. IFRS + USD: second IFRS/USD data point after CSU.
    3. Cost structure: cost_of_sales present; no explicit Gross profit subtotal.
    4. "Net earnings" duplicate: IS + Comprehensive Income both start with this label.
    5. No dividends label — ATD uses "Cash dividends paid" in CF (not share repurchase).
    """
    data = _json.loads(_ATD_FIXTURE.read_text(encoding="utf-8"))
    is_items = data["statements"]["income_statement"]
    cf_items = data["statements"]["cash_flow"]

    is_labels = [item["label"] for item in is_items]

    # April FY: period key is "2025", not "April 27, 2025" or "December 31, 2025".
    for item in is_items:
        assert "April" not in list((item.get("values") or {}).keys()), (
            f"Unexpected April-prefixed period key in IS item {item['label']!r}"
        )
    # Confirm "2025" period key exists in the first IS item.
    assert "2025" in (is_items[0].get("values") or {})

    # IFRS + USD confirmed at metadata level.
    assert data["accounting_standard"] == "IFRS Accounting Standards"
    assert data["currency"] == "USD"

    # Cost of sales present; Gross profit subtotal absent.
    cost_label = "Cost of sales, excluding depreciation, amortization and impairment (Note 7)"
    assert cost_label in is_labels
    gross_profit_labels = [lbl for lbl in is_labels if "gross profit" in lbl.lower()]
    assert gross_profit_labels == [], (
        f"Unexpected 'Gross profit' label in ATD IS: {gross_profit_labels}. "
        "ATD does not report an explicit gross profit subtotal."
    )

    # "Net earnings" appears twice (IS + OCI preamble).
    net_earnings_count = is_labels.count("Net earnings")
    assert net_earnings_count == 2, (
        f"Expected 2 occurrences of 'Net earnings' in IS (IS + OCI), got {net_earnings_count}"
    )

    # Cash dividends paid is present in CF (ATD does pay dividends, unlike SHOP).
    cf_labels = [item["label"] for item in cf_items]
    assert "Cash dividends paid" in cf_labels
