import json

from modules.integrity import cross_extractor as ce
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


def test_cross_extractor_verified_when_all_fields_agree(monkeypatch, tmp_path):
    _patch_pdf_and_log(monkeypatch, tmp_path)
    monkeypatch.setattr(ce, "_run_gemini", lambda *_args: _json([
        {"canonical_field": "revenue", "value": 100.0, "source_label": "Gemini revenue"},
        {"canonical_field": "net_income", "value": 10.0, "source_label": "Gemini net income"},
    ]))

    result = ce.cross_check_filing(_entry(), _mapped(), api_key="key", model="gemini-test")

    assert result.state == "VERIFIED"
    assert [field.status for field in result.fields] == ["AGREE", "AGREE"]


def test_cross_extractor_flagged_when_any_field_conflicts(monkeypatch, tmp_path):
    _patch_pdf_and_log(monkeypatch, tmp_path)
    monkeypatch.setattr(ce, "_run_gemini", lambda *_args: _json([
        {"canonical_field": "revenue", "value": 101.0, "source_label": "Gemini revenue"},
        {"canonical_field": "net_income", "value": 10.0, "source_label": "Gemini net income"},
    ]))

    result = ce.cross_check_filing(_entry(), _mapped(), api_key="key", model="gemini-test")

    assert result.state == "FLAGGED"
    assert {field.canonical_field: field.status for field in result.fields}["revenue"] == "CONFLICT"


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


def test_cross_extractor_log_writer_is_idempotent_by_filing_accession(tmp_path):
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
    assert json.loads(lines[0])["record_type"] == "cross_extractor_agreement"


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
            fields=[],
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
    assert "UNCHECKED" in report
    assert "CNQ FY2024" in report
    assert "pdf_unresolvable=1" in report


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
