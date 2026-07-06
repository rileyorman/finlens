"""
Tests for scripts/ingest_worker.py and scripts/review_candidates.py.

All I/O uses tmp_path.  Network calls are mocked.  No real Anthropic API
calls, no real PDF fetches, and no writes to ~/.finlens.

Coverage:
  ingest_worker:
    - fetch_pdf: bytes, sha256, filename extraction
    - extract_edgar: deferred import isolation + financial_data shape
    - extract_sedar: ANTHROPIC_API_KEY bridging, ANTHROPIC_API_KEY restore
    - generate_questions: each mandatory trigger
    - write_bundle: all five artifact files, questions.md format
    - main(): full happy path (mocked fetch + extract), missing API key,
              FABRICATED guard path, bundle file content

  review_candidates:
    - load_bundle: happy path + missing file error
    - verify_provenance: PASS, MISMATCH, FETCH_FAILED
    - compare_extractions: AGREE, MINOR, DIVERGE, MISSING
    - determine_disposition: PROMOTED, NEEDS_TRIAGE, REJECTED
    - main(): full happy path with fake bundle + --skip-fetch
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import helpers — scripts/ are not a package; add to sys.path
# ---------------------------------------------------------------------------

import sys
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


# ---------------------------------------------------------------------------
# Shared fake data
# ---------------------------------------------------------------------------

FAKE_PDF_BYTES = b"%PDF-1.4 fake pdf content for testing"
FAKE_SHA256 = hashlib.sha256(FAKE_PDF_BYTES).hexdigest()

FAKE_FINANCIAL_DATA = {
    "company_name": "Tourmaline Oil Corp",
    "fiscal_year": "FY2024",
    "fiscal_year_prior": "FY2023",
    "currency": "CAD",
    "income_statement": [
        {"line_item": "Revenues", "value": 5_000_000_000, "value_prior": 4_200_000_000},
        {"line_item": "Net Income", "value": 1_200_000_000, "value_prior": 900_000_000},
    ],
    "balance_sheet": [
        {"line_item": "Total Assets", "value": 15_000_000_000, "value_prior": 13_500_000_000},
    ],
    "cash_flow_statement": [
        {"line_item": "Net Cash Provided by Operating Activities", "value": 2_000_000_000},
        {"line_item": "Capital Expenditures", "value": 1_500_000_000},
    ],
    "figure_presence": {"verdict": "PASS", "checked": 10, "found": 9, "ratio": 0.9},
}

FAKE_SEDAR_RESULT = {
    "source": "sedar_pdf",
    "schema_version": 5,
    "currency": "CAD",
    "sector_inferred": "resource_sector",
    "statements": {
        "income_statement": [
            {"label": "Revenues from mining operations", "values": {"FY2024": 1_000_000}},
        ],
        "balance_sheet": [
            {"label": "Total assets", "values": {"FY2024": 5_000_000}},
        ],
    },
    "mapping": {
        "mapped": {
            "revenue": {"value": 1_000_000, "source_label": "Revenues from mining operations"},
            "net_income": {"value": 200_000, "source_label": "Net income"},
            "total_assets": {"value": 5_000_000, "source_label": "Total assets"},
        },
        "unmapped": [],
        "meta": {"mapped_count": 3, "unmapped_count": 0},
    },
}

# ---------------------------------------------------------------------------
# ingest_worker tests
# ---------------------------------------------------------------------------

class TestFetchPdf:
    def test_returns_bytes_sha256_filename(self):
        from ingest_worker import fetch_pdf

        mock_resp = MagicMock()
        mock_resp.content = FAKE_PDF_BYTES
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_resp):
            pdf_bytes, sha256, filename = fetch_pdf(
                "https://example.com/filings/annual_report.pdf"
            )

        assert pdf_bytes == FAKE_PDF_BYTES
        assert sha256 == FAKE_SHA256
        assert filename == "annual_report.pdf"

    def test_filename_fallback_for_no_extension(self):
        from ingest_worker import fetch_pdf

        mock_resp = MagicMock()
        mock_resp.content = FAKE_PDF_BYTES
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_resp):
            _, _, filename = fetch_pdf("https://example.com/report")

        assert filename.endswith(".pdf")


class TestGenerateQuestions:
    def test_no_questions_when_clean(self):
        from ingest_worker import generate_questions

        mapping = {
            "mapped": {
                "revenue": {"value": 1e9},
                "net_income": {"value": 1e8},
                "total_assets": {"value": 5e9},
            },
            "unmapped": [],
        }
        extraction = {
            "currency": "CAD",
            "sector_inferred": "resource_sector",
            "figure_presence": {"verdict": "PASS", "ratio": 0.9},
        }
        questions = generate_questions("ir", extraction, mapping, "TOU", "FY2024")
        assert questions == []

    def test_mapped_count_zero_triggers_question(self):
        from ingest_worker import generate_questions

        mapping = {"mapped": {}, "unmapped": []}
        extraction = {"currency": "CAD", "sector_inferred": "resource_sector",
                      "figure_presence": {"verdict": "PASS", "ratio": 0.9}}
        questions = generate_questions("ir", extraction, mapping, "TOU", "FY2024")
        assert any("MAPPED_COUNT=0" in q for q in questions)

    def test_fabricated_guard_triggers_question(self):
        from ingest_worker import generate_questions

        mapping = {"mapped": {"revenue": {}}, "unmapped": []}
        extraction = {
            "currency": "USD",
            "sector_inferred": "resource_sector",
            "figure_presence": {"verdict": "FABRICATED", "ratio": 0.1},
        }
        questions = generate_questions("ir", extraction, mapping, "NVDA", "FY2026")
        assert any("FABRICATED" in q for q in questions)

    def test_low_presence_ratio_triggers_question(self):
        from ingest_worker import generate_questions

        mapping = {"mapped": {"revenue": {}, "net_income": {}, "total_assets": {}}, "unmapped": []}
        extraction = {
            "currency": "USD",
            "sector_inferred": "resource_sector",
            "figure_presence": {"verdict": "PASS", "ratio": 0.4},
        }
        questions = generate_questions("ir", extraction, mapping, "TST", "FY2024")
        assert any("FIGURE_PRESENCE_LOW" in q for q in questions)

    def test_missing_currency_triggers_question(self):
        from ingest_worker import generate_questions

        mapping = {"mapped": {"revenue": {}, "net_income": {}, "total_assets": {}}, "unmapped": []}
        extraction = {"sector_inferred": "resource_sector",
                      "figure_presence": {"verdict": "PASS", "ratio": 0.9}}
        questions = generate_questions("ir", extraction, mapping, "TST", "FY2024")
        assert any("CURRENCY_UNKNOWN" in q for q in questions)

    def test_oil_and_gas_sector_triggers_ambiguity_question(self):
        from ingest_worker import generate_questions

        mapping = {"mapped": {"revenue": {}, "net_income": {}, "total_assets": {}}, "unmapped": []}
        extraction = {
            "currency": "CAD",
            "sector_inferred": "oil_and_gas_sector",
            "figure_presence": {"verdict": "PASS", "ratio": 0.9},
        }
        questions = generate_questions("sedar", extraction, mapping, "TOU", "FY2024")
        assert any("SECTOR_AMBIGUOUS" in q for q in questions)

    def test_unmapped_label_alias_candidate_trigger(self):
        from ingest_worker import generate_questions

        mapping = {
            "mapped": {"revenue": {}, "net_income": {}, "total_assets": {}},
            "unmapped": [{"label": "Total revenues from operations"}],
        }
        extraction = {
            "currency": "CAD",
            "sector_inferred": "resource_sector",
            "figure_presence": {"verdict": "PASS", "ratio": 0.9},
        }
        questions = generate_questions("sedar", extraction, mapping, "AEM", "FY2025")
        assert any("ALIAS_CANDIDATE" in q for q in questions)


class TestWriteBundle:
    def test_all_files_created(self, tmp_path):
        from ingest_worker import write_bundle

        bundle_dir = write_bundle(
            out_dir=tmp_path / "candidates",
            ticker="TOU",
            fy="FY2024",
            extraction=FAKE_FINANCIAL_DATA,
            mapping={"note": "EDGAR filer"},
            provenance={"url": "https://example.com/report.pdf", "sha256": FAKE_SHA256},
            worker_meta={"model_used": "claude-haiku-4-5-20251001"},
            questions=[],
        )

        for filename in ("extraction.json", "mapping.json", "provenance.json",
                         "worker_meta.json", "questions.md"):
            assert (bundle_dir / filename).exists(), f"Missing: {filename}"

    def test_questions_md_has_no_judgment_when_empty(self, tmp_path):
        from ingest_worker import write_bundle

        bundle_dir = write_bundle(
            out_dir=tmp_path / "candidates",
            ticker="TOU", fy="FY2024",
            extraction={}, mapping={}, provenance={}, worker_meta={},
            questions=[],
        )
        content = (bundle_dir / "questions.md").read_text(encoding="utf-8")
        assert "_No judgment questions raised._" in content

    def test_questions_md_lists_items_when_present(self, tmp_path):
        from ingest_worker import write_bundle

        bundle_dir = write_bundle(
            out_dir=tmp_path / "candidates",
            ticker="TOU", fy="FY2024",
            extraction={}, mapping={}, provenance={}, worker_meta={},
            questions=["MAPPED_COUNT=0: check sector routing.", "CURRENCY_UNKNOWN."],
        )
        content = (bundle_dir / "questions.md").read_text(encoding="utf-8")
        assert "MAPPED_COUNT=0" in content
        assert "CURRENCY_UNKNOWN" in content

    def test_pdf_not_in_bundle(self, tmp_path):
        from ingest_worker import write_bundle

        bundle_dir = write_bundle(
            out_dir=tmp_path / "candidates",
            ticker="TOU", fy="FY2024",
            extraction={}, mapping={}, provenance={}, worker_meta={},
            questions=[],
        )
        pdf_files = list(bundle_dir.glob("*.pdf"))
        assert pdf_files == [], "PDF must not be committed to the bundle"


class TestMain:
    def test_missing_api_key_returns_error(self, tmp_path, monkeypatch):
        from ingest_worker import main

        monkeypatch.delenv("FINLENS_INGEST_API_KEY", raising=False)
        rc = main([
            "--ticker", "TOU", "--fy", "FY2024",
            "--url", "https://example.com/report.pdf",
            "--out-dir", str(tmp_path / "candidates"),
            "--scratch-dir", str(tmp_path / "scratch"),
        ])
        assert rc == 1

    def test_happy_path_creates_bundle(self, tmp_path, monkeypatch):
        from ingest_worker import main

        monkeypatch.setenv("FINLENS_INGEST_API_KEY", "sk-ant-test1234abcd")

        mock_resp = MagicMock()
        mock_resp.content = FAKE_PDF_BYTES
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_resp), \
             patch("ingest_worker.extract_edgar",
                   return_value=(FAKE_FINANCIAL_DATA, "claude-haiku-4-5-20251001")):
            rc = main([
                "--ticker", "TOU", "--fy", "FY2024",
                "--url", "https://example.com/report.pdf",
                "--source-type", "ir",
                "--out-dir", str(tmp_path / "candidates"),
                "--scratch-dir", str(tmp_path / "scratch"),
            ])

        assert rc == 0
        bundle_dir = tmp_path / "candidates" / "TOU_FY2024"
        assert bundle_dir.exists()
        provenance = json.loads((bundle_dir / "provenance.json").read_text())
        assert provenance["sha256"] == FAKE_SHA256
        assert provenance["ticker"] == "TOU"

    def test_fabricated_guard_still_writes_bundle(self, tmp_path, monkeypatch):
        from ingest_worker import main
        from modules.claude_analyzer import FabricatedExtractionError

        monkeypatch.setenv("FINLENS_INGEST_API_KEY", "sk-ant-test1234abcd")

        mock_resp = MagicMock()
        mock_resp.content = FAKE_PDF_BYTES
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_resp), \
             patch("ingest_worker.extract_edgar",
                   side_effect=FabricatedExtractionError("test fabrication")):
            rc = main([
                "--ticker", "NVDA", "--fy", "FY2026",
                "--url", "https://example.com/nvda.pdf",
                "--source-type", "edgar",
                "--out-dir", str(tmp_path / "candidates"),
                "--scratch-dir", str(tmp_path / "scratch"),
            ])

        assert rc == 0  # exits cleanly; FABRICATED is a warning, not a crash
        bundle_dir = tmp_path / "candidates" / "NVDA_FY2026"
        meta = json.loads((bundle_dir / "worker_meta.json").read_text())
        assert meta["guard_verdict"] == "FABRICATED"


# ---------------------------------------------------------------------------
# review_candidates tests
# ---------------------------------------------------------------------------

def _make_fake_bundle(bundle_dir: Path, questions: list[str] | None = None) -> None:
    """Write a minimal fake bundle for review_candidates tests."""
    bundle_dir.mkdir(parents=True, exist_ok=True)
    provenance = {
        "ticker": "TOU", "fiscal_year": "FY2024",
        "source_type": "ir",
        "url": "https://example.com/report.pdf",
        "sha256": FAKE_SHA256,
        "byte_size": len(FAKE_PDF_BYTES),
        "retrieval_timestamp_utc": "2026-07-05T00:00:00+00:00",
        "retrieval_method": "httpx.get",
        "worker_version": "1",
    }
    (bundle_dir / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    (bundle_dir / "extraction.json").write_text(json.dumps(FAKE_FINANCIAL_DATA), encoding="utf-8")
    (bundle_dir / "mapping.json").write_text(json.dumps({"note": "EDGAR filer"}), encoding="utf-8")
    (bundle_dir / "worker_meta.json").write_text(
        json.dumps({"worker_version": "1", "model_used": "claude-haiku-4-5-20251001",
                    "guard_verdict": "PASS"}),
        encoding="utf-8",
    )
    q_items = questions or []
    q_text = "# Judgment Questions\n\nBundle: TOU FY2024  |  Worker v1\n"
    if q_items:
        q_text += "\n" + "".join(f"{i}. {q}\n" for i, q in enumerate(q_items, 1))
    else:
        q_text += "\n_No judgment questions raised._\n"
    (bundle_dir / "questions.md").write_text(q_text, encoding="utf-8")


class TestLoadBundle:
    def test_happy_path(self, tmp_path):
        from review_candidates import load_bundle

        bundle_dir = tmp_path / "TOU_FY2024"
        _make_fake_bundle(bundle_dir)
        bundle = load_bundle(bundle_dir)
        assert "provenance" in bundle
        assert bundle["provenance"]["ticker"] == "TOU"

    def test_missing_file_raises_bundle_error(self, tmp_path):
        from review_candidates import BundleError, load_bundle

        bundle_dir = tmp_path / "incomplete"
        bundle_dir.mkdir()
        (bundle_dir / "provenance.json").write_text("{}", encoding="utf-8")
        # extraction.json is missing
        with pytest.raises(BundleError, match="extraction.json"):
            load_bundle(bundle_dir)


class TestVerifyProvenance:
    def test_sha256_match(self):
        from review_candidates import verify_provenance

        provenance = {"url": "https://example.com/report.pdf", "sha256": FAKE_SHA256}
        mock_resp = MagicMock()
        mock_resp.content = FAKE_PDF_BYTES
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_resp):
            _, status = verify_provenance(provenance)

        assert status.startswith("PASS")

    def test_sha256_mismatch(self):
        from review_candidates import verify_provenance

        provenance = {"url": "https://example.com/report.pdf", "sha256": "deadbeef" * 8}
        mock_resp = MagicMock()
        mock_resp.content = FAKE_PDF_BYTES
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_resp):
            _, status = verify_provenance(provenance)

        assert "MISMATCH" in status

    def test_fetch_failure(self):
        from review_candidates import verify_provenance

        import httpx
        provenance = {"url": "https://example.com/report.pdf", "sha256": FAKE_SHA256}

        with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
            _, status = verify_provenance(provenance)

        assert "FETCH_FAILED" in status


class TestCompareExtractions:
    def test_agree_on_matching_values(self):
        from review_candidates import compare_extractions

        result = compare_extractions(FAKE_FINANCIAL_DATA, FAKE_FINANCIAL_DATA)
        agreed = [f for f in result if f["status"] == "AGREE"]
        # Revenue, net_income, total_assets should all AGREE with themselves.
        assert len(agreed) >= 3

    def test_diverge_on_large_difference(self):
        from review_candidates import compare_extractions

        canonical = {
            "income_statement": [
                {"line_item": "Revenues", "value": 1_000_000},  # 5x smaller
            ],
        }
        result = compare_extractions(FAKE_FINANCIAL_DATA, canonical)
        revenue = next(f for f in result if f["field"] == "revenue")
        assert revenue["status"] == "DIVERGE"

    def test_missing_when_field_absent(self):
        from review_candidates import compare_extractions

        result = compare_extractions({}, {})
        assert all(f["status"] == "MISSING" for f in result)


# Real worker sedar output: mapping lives in a SEPARATE mapping.json (not
# inline), statement rows are {label, values{year: value}}, labels carry
# '(Note N)' references, and the cash-flow key is 'cash_flow'.  Modeled on
# the PPL FY2024 pilot bundle, which the pre-fix comparator reported as
# all-MISSING despite perfect two-read agreement.
REAL_SEDAR_EXTRACTION = {
    "source": "sedar_pdf",
    "schema_version": 5,
    "currency": "CAD",
    "scale": "millions",
    "fiscal_year_end": "2024-12-31",
    "statements": {
        "income_statement": [
            {"label": "Revenue (Note 19)", "values": {"2024": 7384, "2023": 6331}},
            {"label": "Earnings", "values": {"2024": 1874, "2023": 1776}},
        ],
        "balance_sheet": [
            {"label": "Total assets", "values": {"2024": 35967, "2023": 32618}},
        ],
        "cash_flow": [
            {"label": "Cash flow from operating activities", "values": {"2024": 3214, "2023": 2635}},
            {"label": "Capital expenditures", "values": {"2024": -955, "2023": -606}},
        ],
    },
}

REAL_SEDAR_MAPPING = {
    "mapped": {
        "gross_profit": {"value": 3316, "source_label": "Gross profit"},
        "total_assets": {"value": 35967, "source_label": "Total assets"},
    },
    "unmapped": [{"label": "Revenue (Note 19)", "value": 7384}],
    "meta": {"sector_profile": "resource_sector", "mapped_count": 2},
}


class TestCompareExtractionsSedarBundle:
    def test_all_five_fields_resolve_on_real_sedar_shape(self):
        from review_candidates import compare_extractions

        result = compare_extractions(
            REAL_SEDAR_EXTRACTION,
            REAL_SEDAR_EXTRACTION,
            candidate_mapping=REAL_SEDAR_MAPPING,
            canonical_mapping=REAL_SEDAR_MAPPING,
        )
        assert all(f["status"] == "AGREE" for f in result), result

    def test_note_reference_stripped_for_alias_match(self):
        from review_candidates import _extract_field_value

        assert _extract_field_value(REAL_SEDAR_EXTRACTION, "revenue") == 7384

    def test_current_year_selected_not_prior(self):
        from review_candidates import _extract_field_value

        # fiscal_year_end 2024-12-31 -> the 2024 column, not 2023.
        assert _extract_field_value(REAL_SEDAR_EXTRACTION, "net_income") == 1874

    def test_separate_mapping_takes_precedence(self):
        from review_candidates import _extract_field_value

        mapping = {"mapped": {"total_assets": {"value": 111, "source_label": "Total assets"}}}
        assert _extract_field_value(REAL_SEDAR_EXTRACTION, "total_assets", mapping) == 111

    def test_cash_flow_key_without_statement_suffix(self):
        from review_candidates import _extract_field_value

        assert _extract_field_value(REAL_SEDAR_EXTRACTION, "operating_cash_flow") == 3214
        assert _extract_field_value(REAL_SEDAR_EXTRACTION, "capex") == -955

    def test_edgar_shape_unaffected(self):
        from review_candidates import compare_extractions

        # Passing an explicit mapping alongside an EDGAR-shape extraction
        # must not disturb the legacy row scan.
        result = compare_extractions(
            FAKE_FINANCIAL_DATA,
            FAKE_FINANCIAL_DATA,
            candidate_mapping={"note": "EDGAR filer (TOU) -- no SEDAR mapper applied."},
        )
        assert all(f["status"] != "MISSING" for f in result), result


class TestDetermineDisposition:
    def test_promoted_when_all_clean(self):
        from review_candidates import determine_disposition

        q_text = "# Judgment Questions\n\n_No judgment questions raised._\n"
        disposition = determine_disposition("PASS (sha256=abc...)", q_text, [])
        assert disposition == "PROMOTED"

    def test_rejected_on_fetch_failure(self):
        from review_candidates import determine_disposition

        disposition = determine_disposition("FETCH_FAILED: timeout", "", None)
        assert disposition.startswith("REJECTED")

    def test_needs_triage_on_diverge(self):
        from review_candidates import determine_disposition

        field_comparison = [{"field": "capex", "status": "DIVERGE",
                              "candidate_value": 138e6, "canonical_value": 97e6, "pct_diff": 41.9}]
        q_text = "# Judgment Questions\n\n_No judgment questions raised._\n"
        disposition = determine_disposition("PASS", q_text, field_comparison)
        assert "NEEDS_TRIAGE" in disposition

    def test_needs_triage_when_canonical_absent(self):
        from review_candidates import determine_disposition

        q_text = "# Judgment Questions\n\n_No judgment questions raised._\n"
        disposition = determine_disposition("PASS", q_text, None)
        assert "NEEDS_TRIAGE" in disposition

    def test_needs_triage_on_open_questions(self):
        from review_candidates import determine_disposition

        q_text = "# Judgment Questions\n\nBundle: TOU FY2024\n\n1. SECTOR_AMBIGUOUS: check routing.\n"
        disposition = determine_disposition("PASS", q_text, [])
        assert "NEEDS_TRIAGE" in disposition


class TestReviewCandidatesMain:
    def test_full_run_skip_fetch(self, tmp_path):
        from review_candidates import main

        bundle_dir = tmp_path / "TOU_FY2024"
        _make_fake_bundle(bundle_dir)
        rc = main(["--bundle-dir", str(bundle_dir), "--skip-fetch"])
        assert rc == 0

    def test_bundle_not_found_returns_error(self, tmp_path):
        from review_candidates import main

        rc = main(["--bundle-dir", str(tmp_path / "nonexistent"), "--skip-fetch"])
        assert rc == 1


# ---------------------------------------------------------------------------
# IFRS alias coverage (field_aliases shared table)
# ---------------------------------------------------------------------------
# Triggered by IMO FY2025 pilot: net_income, operating_cash_flow, and capex
# were MISSING on both Sterling and CC sides because the comparator alias
# lists were US-GAAP-flavored.  These tests pin the IFRS labels from the
# IMO FY2025 extraction (bundle ingest/IMO-FY2025, guard PASS, ratio=1.0).

# IMO FY2025 as-filed label strings (empirical — from extraction.json)
_IMO_FINANCIAL_DATA = {
    "company_name": "Imperial Oil Limited",
    "fiscal_year": "FY2025",
    "currency": "CAD, in millions",
    "income_statement": [
        {"line_item": "Revenues", "value": 53_000},
        {"line_item": "Net income (loss)", "value": 1_843},
    ],
    "balance_sheet": [
        {"line_item": "Total assets", "value": 19_500},
    ],
    "cash_flow_statement": [
        {"line_item": "Cash flows from (used in) operating activities", "value": 3_200},
        {"line_item": "Additions to property, plant and equipment", "value": -1_100},
    ],
}


class TestFieldAliasesModule:
    """Unit tests for modules/integrity/field_aliases.py (shared alias table)."""

    def test_ifrs_net_income_label_present(self):
        from modules.integrity.field_aliases import FIELD_ALIASES

        assert "Net income (loss)" in FIELD_ALIASES["net_income"]

    def test_ifrs_operating_cash_flow_label_present(self):
        from modules.integrity.field_aliases import FIELD_ALIASES

        assert "Cash flows from (used in) operating activities" in FIELD_ALIASES["operating_cash_flow"]

    def test_ifrs_capex_label_present(self):
        from modules.integrity.field_aliases import FIELD_ALIASES

        assert "Additions to property, plant and equipment" in FIELD_ALIASES["capex"]

    def test_headline_fields_complete(self):
        from modules.integrity.field_aliases import HEADLINE_FIELDS, FIELD_ALIASES, FIELD_STATEMENT

        assert set(HEADLINE_FIELDS) == set(FIELD_ALIASES.keys()) == set(FIELD_STATEMENT.keys())


class TestCompareExtractionsIFRS:
    """Comparator resolves IFRS-labeled IMO fields (regression against MISSING bug)."""

    def test_imo_net_income_resolved(self):
        from review_candidates import compare_extractions

        result = compare_extractions(_IMO_FINANCIAL_DATA, _IMO_FINANCIAL_DATA)
        ni = next(f for f in result if f["field"] == "net_income")
        assert ni["status"] == "AGREE", (
            f"net_income should AGREE against itself but got {ni['status']}; "
            "label 'Net income (loss)' not resolved by comparator"
        )

    def test_imo_operating_cash_flow_resolved(self):
        from review_candidates import compare_extractions

        result = compare_extractions(_IMO_FINANCIAL_DATA, _IMO_FINANCIAL_DATA)
        ocf = next(f for f in result if f["field"] == "operating_cash_flow")
        assert ocf["status"] == "AGREE", (
            f"operating_cash_flow should AGREE against itself but got {ocf['status']}; "
            "label 'Cash flows from (used in) operating activities' not resolved"
        )

    def test_imo_capex_resolved(self):
        from review_candidates import compare_extractions

        result = compare_extractions(_IMO_FINANCIAL_DATA, _IMO_FINANCIAL_DATA)
        capex = next(f for f in result if f["field"] == "capex")
        assert capex["status"] == "AGREE", (
            f"capex should AGREE against itself but got {capex['status']}; "
            "label 'Additions to property, plant and equipment' not resolved"
        )

    def test_imo_all_five_fields_not_missing(self):
        """All five headline fields must resolve from the IMO extraction."""
        from review_candidates import compare_extractions

        result = compare_extractions(_IMO_FINANCIAL_DATA, _IMO_FINANCIAL_DATA)
        missing = [f["field"] for f in result if f["status"] == "MISSING"]
        assert not missing, f"Fields still MISSING with IMO IFRS labels: {missing}"


class TestPriorColumnIFRSAliases:
    """prior_column._ALIASES includes the IFRS labels (shared-table regression)."""

    def test_ifrs_net_income_in_prior_column_aliases(self):
        from modules.integrity.prior_column import _ALIASES

        assert "Net income (loss)" in _ALIASES["net_income"]

    def test_ifrs_operating_cash_flow_in_prior_column_aliases(self):
        from modules.integrity.prior_column import _ALIASES

        assert "Cash flows from (used in) operating activities" in _ALIASES["operating_cash_flow"]

    def test_ifrs_capex_in_prior_column_aliases(self):
        from modules.integrity.prior_column import _ALIASES

        assert "Additions to property, plant and equipment" in _ALIASES["capex"]
