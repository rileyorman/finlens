import json

import pytest

from modules.integrity import cross_extractor as ce
from modules.integrity import analyze as integrity_analyze
from modules.integrity.analyze import analyze_log
from modules.integrity import log as integrity_log


def _entry(**overrides):
    entry = {
        "ticker": "AEM",
        "company_name": "Agnico Eagle Mines Limited",
        "fiscal_year": "FY2025",
        "filing_accession": "AEM_FY2025_sedar.json",
        "currency": "USD",
        "scale": "thousands",
    }
    entry.update(overrides)
    return entry


def _mapped(**values):
    if not values:
        values = {"revenue": 100.0, "net_income": 10.0}
    return {
        field: {"value": value, "source_label": f"FinLens {field}"}
        for field, value in values.items()
    }


def _json(fields):
    return json.dumps({"fields": fields})


def _patch_pdf_and_log(monkeypatch, tmp_path):
    pdf_path = tmp_path / "filing.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\n")
    monkeypatch.setattr(ce, "resolve_campaign_pdf", lambda _entry: pdf_path)
    monkeypatch.setattr(
        "modules.integrity.log.append_cross_extractor_to_log",
        lambda _result: None,
    )
    return pdf_path


def test_classify_flag_severity_atd_component_label_is_soft():
    assert ce.classify_flag_severity(
        "Financial expenses (Note 9)",
        "Interest on lease liabilities",
    ) == "soft"


def test_classify_flag_severity_strips_note_reference():
    assert ce.classify_flag_severity(
        "Financial expenses (Note 9)",
        "financial expenses",
    ) == "hard"


def test_classify_flag_severity_collapses_case_and_whitespace():
    assert ce.classify_flag_severity("Total  Revenue", "total revenue") == "hard"


def test_cross_extractor_verified_when_all_fields_agree(monkeypatch, tmp_path):
    _patch_pdf_and_log(monkeypatch, tmp_path)
    monkeypatch.setattr(ce, "_run_gemini", lambda *_args: _json([
        {"canonical_field": "revenue", "value": 100.0, "source_label": "Gemini revenue"},
        {"canonical_field": "net_income", "value": 10.0, "source_label": "Gemini net income"},
    ]))

    result = ce.cross_check_filing(_entry(), _mapped(), api_key="key", model="gemini-test")

    assert result.state == "VERIFIED"
    assert [field.status for field in result.fields] == ["AGREE", "AGREE"]
    assert "severity" not in result.fields[0].to_dict()
    assert result.checker_version == "2"


def test_cross_extractor_flagged_when_any_field_conflicts(monkeypatch, tmp_path):
    _patch_pdf_and_log(monkeypatch, tmp_path)
    monkeypatch.setattr(ce, "_run_gemini", lambda *_args: _json([
        {"canonical_field": "revenue", "value": 101.0, "source_label": "Gemini revenue"},
        {"canonical_field": "net_income", "value": 10.0, "source_label": "Gemini net income"},
    ]))

    result = ce.cross_check_filing(_entry(), _mapped(), api_key="key", model="gemini-test")

    assert result.state == "FLAGGED"
    assert {field.canonical_field: field.status for field in result.fields}["revenue"] == "CONFLICT"
    assert {field.canonical_field: field.severity for field in result.fields}["revenue"] == "soft"


def test_cross_extractor_same_label_value_mismatch_is_hard(monkeypatch, tmp_path):
    _patch_pdf_and_log(monkeypatch, tmp_path)
    monkeypatch.setattr(ce, "_run_gemini", lambda *_args: _json([
        {"canonical_field": "revenue", "value": 101.0, "source_label": "Total revenue"},
    ]))

    result = ce.cross_check_filing(
        _entry(),
        {"revenue": {"value": 100.0, "source_label": "Total revenue"}},
        api_key="key",
        model="gemini-test",
    )
    field = result.fields[0]

    assert result.state == "FLAGGED"
    assert field.status == "CONFLICT"
    assert field.severity == "hard"
    assert field.to_dict()["severity"] == "hard"


def test_cross_extractor_empty_gemini_label_conflict_is_soft(monkeypatch, tmp_path):
    _patch_pdf_and_log(monkeypatch, tmp_path)
    monkeypatch.setattr(ce, "_run_gemini", lambda *_args: _json([
        {"canonical_field": "revenue", "value": 101.0},
    ]))

    result = ce.cross_check_filing(_entry(), _mapped(revenue=100.0), api_key="key", model="gemini-test")

    assert result.state == "FLAGGED"
    assert result.fields[0].gemini_label == ""
    assert result.fields[0].severity == "soft"


def test_cross_extractor_partial_when_gemini_abstains_without_conflict(monkeypatch, tmp_path):
    _patch_pdf_and_log(monkeypatch, tmp_path)
    monkeypatch.setattr(ce, "_run_gemini", lambda *_args: _json([
        {"canonical_field": "revenue", "value": 100.0, "source_label": "Gemini revenue"},
    ]))

    result = ce.cross_check_filing(_entry(), _mapped(), api_key="key", model="gemini-test")

    assert result.state == "PARTIAL"
    assert result.state != "FLAGGED"
    assert {field.canonical_field: field.status for field in result.fields}["net_income"] == "GEMINI_MISSING"


def test_cross_extractor_unchecked_when_pdf_unresolvable(monkeypatch):
    monkeypatch.setattr(ce, "resolve_campaign_pdf", lambda _entry: None)
    monkeypatch.setattr(
        "modules.integrity.log.append_cross_extractor_to_log",
        lambda _result: None,
    )

    result = ce.cross_check_filing(_entry(), _mapped(), api_key="key", model="gemini-test")

    assert result.state == "UNCHECKED"
    assert result.reason == "pdf_unresolvable"


def test_cross_extractor_unchecked_when_no_key(monkeypatch, tmp_path):
    _patch_pdf_and_log(monkeypatch, tmp_path)

    result = ce.cross_check_filing(_entry(), _mapped(), api_key="", model="gemini-test")

    assert result.state == "UNCHECKED"
    assert result.reason == "no_key"


def test_cross_extractor_unchecked_when_mapped_fields_empty(monkeypatch, tmp_path):
    _patch_pdf_and_log(monkeypatch, tmp_path)

    result = ce.cross_check_filing(_entry(), {}, api_key="key", model="gemini-test")

    assert result.state == "UNCHECKED"
    assert result.reason == "no_mapped_fields"


def test_cross_extractor_unchecked_when_gemini_raises(monkeypatch, tmp_path):
    _patch_pdf_and_log(monkeypatch, tmp_path)

    def _raise(*_args):
        raise RuntimeError("quota")

    monkeypatch.setattr(ce, "_run_gemini", _raise)

    result = ce.cross_check_filing(_entry(), _mapped(), api_key="key", model="gemini-test")

    assert result.state == "UNCHECKED"
    assert result.reason == "gemini_error"


def test_cross_extractor_unchecked_on_bad_json(monkeypatch, tmp_path):
    _patch_pdf_and_log(monkeypatch, tmp_path)
    monkeypatch.setattr(ce, "_run_gemini", lambda *_args: "not json")

    result = ce.cross_check_filing(_entry(), _mapped(), api_key="key", model="gemini-test")

    assert result.state == "UNCHECKED"
    assert result.reason == "parse_error"


def test_cross_extractor_captures_finlens_and_gemini_labels(monkeypatch, tmp_path):
    _patch_pdf_and_log(monkeypatch, tmp_path)
    monkeypatch.setattr(ce, "_run_gemini", lambda *_args: _json([
        {"canonical_field": "revenue", "value": 100.0, "source_label": "Gemini revenue line"},
        {"canonical_field": "net_income", "value": 10.0, "source_label": "Gemini income line"},
    ]))

    result = ce.cross_check_filing(_entry(), _mapped(), api_key="key", model="gemini-test")
    first = result.fields[0]

    assert first.finlens_label == "FinLens revenue"
    assert first.gemini_label == "Gemini revenue line"


def test_cross_extractor_log_writer_is_idempotent_by_filing_accession_and_version(tmp_path):
    result = ce.CrossCheckResult(
        state="VERIFIED",
        fields=[],
        timestamp="2026-07-03T00:00:00+00:00",
        ticker="AEM",
        fiscal_year="FY2025",
        filing_accession="AEM_FY2025_sedar.json",
        model="gemini-test",
    )
    path = tmp_path / "integrity_log.jsonl"

    integrity_log.append_cross_extractor_to_log(result, path)
    integrity_log.append_cross_extractor_to_log(result, path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["record_type"] == "cross_extractor_agreement"
    assert record["checker_version"] == "2"


def test_cross_extractor_log_allows_new_version_after_legacy_definitive(tmp_path):
    legacy_v1 = {
        "record_type": "cross_extractor_agreement",
        "timestamp": "2026-07-03T00:00:00+00:00",
        "ticker": "AEM",
        "fiscal_year": "FY2025",
        "filing_accession": "AEM_FY2025_sedar.json",
        "state": "VERIFIED",
        "reason": None,
        "model": "gemini-test",
        "cross_extractor_fields": [],
    }
    result_v2 = ce.CrossCheckResult(
        state="VERIFIED",
        fields=[],
        timestamp="2026-07-04T00:00:00+00:00",
        ticker="AEM",
        fiscal_year="FY2025",
        filing_accession="AEM_FY2025_sedar.json",
        model="gemini-test",
    )
    path = tmp_path / "integrity_log.jsonl"
    path.write_text(json.dumps(legacy_v1) + "\n", encoding="utf-8")

    integrity_log.append_cross_extractor_to_log(result_v2, path)
    integrity_log.append_cross_extractor_to_log(result_v2, path)

    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 2
    assert records[0].get("checker_version") is None
    assert records[1]["checker_version"] == "2"


def test_cross_extractor_log_allows_unchecked_then_definitive_same_filing(tmp_path):
    unchecked = ce.CrossCheckResult(
        state="UNCHECKED",
        fields=[],
        timestamp="2026-07-03T00:00:00+00:00",
        ticker="AEM",
        fiscal_year="FY2025",
        filing_accession="AEM_FY2025_sedar.json",
        model="gemini-test",
        reason="no_key",
    )
    verified = ce.CrossCheckResult(
        state="VERIFIED",
        fields=[],
        timestamp="2026-07-03T01:00:00+00:00",
        ticker="AEM",
        fiscal_year="FY2025",
        filing_accession="AEM_FY2025_sedar.json",
        model="gemini-test",
    )
    path = tmp_path / "integrity_log.jsonl"

    integrity_log.append_cross_extractor_to_log(unchecked, path)
    integrity_log.append_cross_extractor_to_log(verified, path)
    integrity_log.append_cross_extractor_to_log(verified, path)

    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert [record["state"] for record in records] == ["UNCHECKED", "VERIFIED"]


def test_cross_extractor_records_surface_in_integrity_log_report(tmp_path):
    path = tmp_path / "integrity_log.jsonl"
    records = [
        ce.CrossCheckResult(
            state="VERIFIED",
            fields=[],
            timestamp="2026-07-03T00:00:00+00:00",
            ticker="AEM",
            fiscal_year="FY2025",
            filing_accession="AEM_FY2025_sedar.json",
            model="gemini-test",
        ),
        ce.CrossCheckResult(
            state="PARTIAL",
            fields=[],
            timestamp="2026-07-03T00:01:00+00:00",
            ticker="SLF",
            fiscal_year="FY2025",
            filing_accession="SLF_FY2025_sedar.json",
            model="gemini-test",
        ),
        ce.CrossCheckResult(
            state="FLAGGED",
            fields=[
                ce.CrossExtractorField(
                    canonical_field="revenue",
                    finlens_value=100.0,
                    gemini_value=101.0,
                    status="CONFLICT",
                    finlens_label="Revenue",
                    gemini_label="Revenue",
                    severity="hard",
                )
            ],
            timestamp="2026-07-03T00:02:00+00:00",
            ticker="CNQ",
            fiscal_year="FY2024",
            filing_accession="CNQ_FY2024_sedar.json",
            model="gemini-test",
        ),
        ce.CrossCheckResult(
            state="UNCHECKED",
            fields=[],
            timestamp="2026-07-03T00:03:00+00:00",
            ticker="NFG",
            fiscal_year="FY2024",
            filing_accession="NFG_FY2024_sedar.json",
            model="gemini-test",
            reason="pdf_unresolvable",
        ),
    ]
    path.write_text(
        "\n".join(json.dumps(record.to_dict()) for record in records) + "\n",
        encoding="utf-8",
    )

    report = analyze_log(path)

    assert "GEMINI SECOND-EXTRACTOR SIGNAL" in report
    assert "VERIFIED" in report
    assert "PARTIAL" in report
    assert "FLAGGED" in report
    assert "1 hard / 0 soft / 0 unclassified" in report
    assert "UNCHECKED" in report
    assert "CNQ FY2024 (hard)" in report
    assert "pdf_unresolvable=1" in report


def test_cross_extractor_report_tolerates_legacy_flagged_without_severity(tmp_path):
    path = tmp_path / "integrity_log.jsonl"
    legacy_record = {
        "record_type": "cross_extractor_agreement",
        "timestamp": "2026-07-03T00:02:00+00:00",
        "ticker": "CNQ",
        "fiscal_year": "FY2024",
        "filing_accession": "CNQ_FY2024_sedar.json",
        "state": "FLAGGED",
        "reason": None,
        "model": "gemini-test",
        "cross_extractor_fields": [
            {
                "canonical_field": "revenue",
                "finlens_value": 100.0,
                "gemini_value": 101.0,
                "status": "CONFLICT",
                "finlens_label": "Revenue",
                "gemini_label": "Sales",
            }
        ],
    }
    path.write_text(json.dumps(legacy_record) + "\n", encoding="utf-8")

    report = analyze_log(path)

    assert integrity_analyze._cx_checker_version(legacy_record) == 1
    assert "0 hard / 0 soft / 1 unclassified" in report
    assert "CNQ FY2024 (unclassified)" in report


def test_cross_extractor_report_prefers_latest_definitive_version(tmp_path):
    path = tmp_path / "integrity_log.jsonl"
    legacy_v1 = {
        "record_type": "cross_extractor_agreement",
        "timestamp": "2026-07-03T00:02:00+00:00",
        "ticker": "ATD",
        "fiscal_year": "FY2025",
        "filing_accession": "ATD_FY2025_sedar.json",
        "state": "FLAGGED",
        "reason": None,
        "model": "gemini-test",
        "cross_extractor_fields": [
            {
                "canonical_field": "interest_expense",
                "finlens_value": 690.8,
                "gemini_value": 159.3,
                "status": "CONFLICT",
                "finlens_label": "Financial expenses (Note 9)",
                "gemini_label": "Interest on lease liabilities",
            }
        ],
    }
    v2 = ce.CrossCheckResult(
        state="VERIFIED",
        fields=[],
        timestamp="2026-07-04T00:02:00+00:00",
        ticker="ATD",
        fiscal_year="FY2025",
        filing_accession="ATD_FY2025_sedar.json",
        model="gemini-test",
    )
    path.write_text(
        "\n".join([json.dumps(legacy_v1), json.dumps(v2.to_dict())]) + "\n",
        encoding="utf-8",
    )

    report = analyze_log(path)

    assert "FLAGGED     :    0" in report
    assert "VERIFIED    :    1" in report
    assert "Flagged filings       : (none)" in report


def test_integrity_log_reader_parses_bom_and_reports_bad_lines(tmp_path):
    path = tmp_path / "integrity_log.jsonl"
    valid = {
        "timestamp": "2026-07-04T00:00:00+00:00",
        "ticker": "BOM",
        "fiscal_year": "FY2026",
        "overall_status": "clean",
        "filing_accession": "BOM_FY2026",
        "checks": [],
    }
    path.write_bytes(
        b"\xef\xbb\xbf"
        + json.dumps(valid).encode("utf-8")
        + b"\n"
        + b"{not-json}\n"
    )

    records = integrity_log.read_log(path)
    diagnostics = integrity_log.get_last_read_log_diagnostics()
    report = analyze_log(path)

    assert records == [valid]
    assert diagnostics.physical_lines == 2
    assert diagnostics.records_parsed == 1
    assert diagnostics.unparseable_lines == 1
    assert diagnostics.unparseable_line_numbers == (2,)
    assert "Parsed    : 1 record(s)" in report
    assert "Unparseable JSON lines: 1" in report


def test_cross_extractor_disposition_appears_joined_in_report(tmp_path):
    path = tmp_path / "integrity_log.jsonl"
    agreement = ce.CrossCheckResult(
        state="FLAGGED",
        fields=[
            ce.CrossExtractorField(
                canonical_field="interest_expense",
                finlens_value=690.8,
                gemini_value=159.3,
                status="CONFLICT",
                finlens_label="Financial expenses (Note 9)",
                gemini_label="Interest on lease liabilities",
                severity="soft",
            )
        ],
        timestamp="2026-07-04T00:00:00+00:00",
        ticker="ATD",
        fiscal_year="FY2025",
        filing_accession="ATD_FY2025_sedar.json",
        model="gemini-test",
    )
    path.write_text(json.dumps(agreement.to_dict()) + "\n", encoding="utf-8")

    integrity_log.append_cross_extractor_disposition_to_log(
        filing_accession="ATD_FY2025_sedar.json",
        ticker="ATD",
        fiscal_year="FY2025",
        field="interest_expense",
        checker_version="2",
        disposition="checker_error",
        rationale="Gemini used a note component instead of the statement total.",
        timestamp="2026-07-04T00:01:00+00:00",
        log_path=path,
    )

    report = analyze_log(path)

    assert "Open triage targets    : 0" in report
    assert "DISPOSITIONED checker_error" in report
    assert "Gemini used a note component" in report
    assert "ATD FY2025 v2 interest_expense severity=soft" in report


def test_cross_extractor_disposition_does_not_attach_across_version_bump(tmp_path):
    path = tmp_path / "integrity_log.jsonl"
    v1 = {
        "record_type": "cross_extractor_agreement",
        "timestamp": "2026-07-03T00:00:00+00:00",
        "ticker": "ATD",
        "fiscal_year": "FY2025",
        "filing_accession": "ATD_FY2025_sedar.json",
        "state": "FLAGGED",
        "reason": None,
        "model": "gemini-test",
        "cross_extractor_fields": [
            {
                "canonical_field": "interest_expense",
                "finlens_value": 690.8,
                "gemini_value": 159.3,
                "status": "CONFLICT",
                "finlens_label": "Financial expenses (Note 9)",
                "gemini_label": "Interest on lease liabilities",
            }
        ],
    }
    v2 = ce.CrossCheckResult(
        state="FLAGGED",
        fields=[
            ce.CrossExtractorField(
                canonical_field="interest_expense",
                finlens_value=690.8,
                gemini_value=159.3,
                status="CONFLICT",
                finlens_label="Financial expenses (Note 9)",
                gemini_label="Interest on lease liabilities",
                severity="soft",
            )
        ],
        timestamp="2026-07-04T00:00:00+00:00",
        ticker="ATD",
        fiscal_year="FY2025",
        filing_accession="ATD_FY2025_sedar.json",
        model="gemini-test",
    )
    path.write_text(
        "\n".join([json.dumps(v1), json.dumps(v2.to_dict())]) + "\n",
        encoding="utf-8",
    )
    integrity_log.append_cross_extractor_disposition_to_log(
        filing_accession="ATD_FY2025_sedar.json",
        ticker="ATD",
        fiscal_year="FY2025",
        field="interest_expense",
        checker_version="1",
        disposition="checker_error",
        rationale="Legacy v1 adjudication.",
        timestamp="2026-07-03T00:01:00+00:00",
        log_path=path,
    )

    report = analyze_log(path)

    assert "v2" in report
    assert "interest_expense" in report
    assert "OPEN" in report
    assert "Open triage targets    : 1" in report
    assert "Legacy v1 adjudication" not in report


def test_cross_extractor_disposition_rejects_invalid_target(tmp_path):
    path = tmp_path / "integrity_log.jsonl"
    path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="No matching cross_extractor_agreement"):
        integrity_log.append_cross_extractor_disposition_to_log(
            filing_accession="MISSING",
            ticker="MISS",
            fiscal_year="FY2025",
            field="interest_expense",
            checker_version="2",
            disposition="checker_error",
            rationale="No matching agreement exists.",
            log_path=path,
        )


def test_cross_extractor_duplicate_dispositions_append_and_latest_wins(tmp_path):
    path = tmp_path / "integrity_log.jsonl"
    agreement = ce.CrossCheckResult(
        state="PARTIAL",
        fields=[
            ce.CrossExtractorField(
                canonical_field="insurance_finance_result",
                finlens_value=-6787.0,
                gemini_value=None,
                status="GEMINI_MISSING",
                finlens_label="Insurance finance expenses from contracts issued",
                gemini_label="",
            )
        ],
        timestamp="2026-07-04T00:00:00+00:00",
        ticker="SLF",
        fiscal_year="FY2025",
        filing_accession="SLF_FY2025_sedar.json",
        model="gemini-test",
    )
    path.write_text(json.dumps(agreement.to_dict()) + "\n", encoding="utf-8")

    for disposition, rationale, timestamp in [
        ("structural_absence", "First disposition.", "2026-07-04T00:01:00+00:00"),
        ("gemini_miss_field_present", "Latest disposition.", "2026-07-04T00:02:00+00:00"),
    ]:
        integrity_log.append_cross_extractor_disposition_to_log(
            filing_accession="SLF_FY2025_sedar.json",
            ticker="SLF",
            fiscal_year="FY2025",
            field="insurance_finance_result",
            checker_version="2",
            disposition=disposition,
            rationale=rationale,
            timestamp=timestamp,
            log_path=path,
        )

    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    disposition_records = [
        record
        for record in records
        if record.get("record_type") == "cross_extractor_disposition"
    ]
    report = analyze_log(path)

    assert len(disposition_records) == 2
    assert "Open triage targets    : 0" in report
    assert "DISPOSITIONED gemini_miss_field_present" in report
    assert "Latest disposition." in report
    assert "First disposition." not in report


def test_cross_extractor_compares_native_units_without_fx_or_scale(monkeypatch, tmp_path):
    _patch_pdf_and_log(monkeypatch, tmp_path)
    captured = {}

    def _run(_pdf_path, prompt, _api_key, _model):
        captured["prompt"] = prompt
        return _json([
            {"canonical_field": "revenue", "value": 1000.0, "source_label": "Gemini CAD revenue"},
        ])

    monkeypatch.setattr(ce, "_run_gemini", _run)

    result = ce.cross_check_filing(
        _entry(currency="CAD", scale="thousands"),
        _mapped(revenue=1000.0),
        api_key="key",
        model="gemini-test",
    )

    assert result.state == "VERIFIED"
    assert result.fields[0].finlens_value == 1000.0
    assert result.fields[0].gemini_value == 1000.0
    assert "currency=CAD, scale=thousands" in captured["prompt"]
