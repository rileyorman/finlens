import json

from modules.integrity import cross_validate as cv
from modules.integrity import log as integrity_log


def _normalized_data(currency="USD"):
    data = {
        "income_statement": [
            {"line_item": "Revenue", "value": 100.0},
            {"line_item": "Net Income", "value": 10.0},
        ],
        "balance_sheet": [
            {"line_item": "Total Assets", "value": 500.0},
        ],
        "cash_flow_statement": [
            {"line_item": "Net Cash from Operating Activities", "value": 40.0},
        ],
    }
    if currency is not None:
        data["currency"] = currency
    return data


def _fmp_values(
    *,
    reported_currency="USD",
    revenue=100.0,
    net_income=10.0,
    total_assets=500.0,
    operating_cash_flow=40.0,
):
    return {
        cv.FMP_REPORTED_CURRENCY_KEY: reported_currency,
        "revenue": revenue,
        "net_income": net_income,
        "total_assets": total_assets,
        "operating_cash_flow": operating_cash_flow,
    }


def test_successful_cross_validation_writes_reason_to_cache(monkeypatch, tmp_path):
    cache_file = tmp_path / "cv_cache.json"
    monkeypatch.setattr(cv, "_CV_CACHE_FILE", cache_file)
    monkeypatch.setattr(cv, "_fetch_fmp_raw", lambda _ticker, _year: (
        _fmp_values(),
        True,
        cv.FMP_FETCH_SUCCESS,
    ))
    monkeypatch.setattr("modules.integrity.log.append_cv_to_log", lambda _result: None)

    result = cv.cross_validate_filing(_normalized_data(), "TEST", "FY2025")

    assert result.fmp_fetch_success is True
    assert result.fmp_fetch_reason == cv.FMP_FETCH_SUCCESS
    assert result.overall_status == "all_agree"
    assert result.filing_currency == "USD"
    assert result.fmp_reported_currency == "USD"
    assert result.abstention_reason is None
    assert all(field.status == "AGREE" for field in result.fields)
    assert all("severity" not in field.to_dict() for field in result.fields)
    cache = json.loads(cache_file.read_text(encoding="utf-8"))
    assert cache["TEST|2025"]["fmp_fetch_reason"] == cv.FMP_FETCH_SUCCESS
    assert cache["TEST|2025"]["fmp_reported_currency"] == "USD"


def test_sedar_top_level_values_fill_cv_record_when_statement_labels_are_ifrs(monkeypatch, tmp_path):
    cache_file = tmp_path / "cv_cache.json"
    monkeypatch.setattr(cv, "_CV_CACHE_FILE", cache_file)
    monkeypatch.setattr(cv, "_fetch_fmp_raw", lambda _ticker, _year: (
        _fmp_values(
            reported_currency="CAD",
            revenue=72856.8,
            net_income=2592.4,
            total_assets=32367.2,
            operating_cash_flow=6621.7,
        ),
        True,
        cv.FMP_FETCH_SUCCESS,
    ))
    monkeypatch.setattr("modules.integrity.log.append_cv_to_log", lambda _result: None)
    sedar_data = {
        "source": "sedar_pdf",
        "currency": "CAD, in ones",
        "revenue": 72856.8,
        "net_income": 2592.4,
        "total_assets": 32367.2,
        "operating_cash_flow": 6621.7,
        "income_statement": [
            {"line_item": "Rental revenue", "value": 71300.0},
            {"line_item": "Residential inventory sales", "value": 1556.8},
            {"line_item": "Net earnings", "value": 2592.4},
        ],
        "balance_sheet": [
            {"line_item": "Total assets", "value": 32367.2},
        ],
        "cash_flow_statement": [
            {"line_item": "Cash provided by operating activities", "value": 6621.7},
        ],
    }

    result = cv.cross_validate_filing(sedar_data, "ATD", "FY2025")

    finlens_values = {field.field: field.finlens_value for field in result.fields}
    assert finlens_values["revenue"] == sedar_data["revenue"]
    assert finlens_values["revenue"] not in {71300.0, 1556.8}
    assert finlens_values == {
        "revenue": 72856.8,
        "net_income": 2592.4,
        "total_assets": 32367.2,
        "operating_cash_flow": 6621.7,
    }


def test_field_stays_null_when_absent_from_rows_and_top_level():
    data = {"income_statement": [], "balance_sheet": [], "cash_flow_statement": []}

    values = cv._extract_finlens_values(data)

    assert values["revenue"] is None
    assert values["total_assets"] is None


def test_edgar_rows_take_precedence_over_top_level_fallback():
    data = _normalized_data()
    data["revenue"] = 999.0

    values = cv._extract_finlens_values(data)

    assert values["revenue"] == 100.0


def test_premium_block_is_cacheable_with_reason(monkeypatch, tmp_path):
    cache_file = tmp_path / "cv_cache.json"
    monkeypatch.setattr(cv, "_CV_CACHE_FILE", cache_file)
    monkeypatch.setattr(cv, "_fetch_fmp_raw", lambda _ticker, _year: (
        None,
        False,
        cv.FMP_PREMIUM_BLOCKED,
    ))
    monkeypatch.setattr("modules.integrity.log.append_cv_to_log", lambda _result: None)

    result = cv.cross_validate_filing(_normalized_data(), "O", "FY2025")

    assert result.fmp_fetch_success is False
    assert result.fmp_fetch_reason == cv.FMP_PREMIUM_BLOCKED
    cache = json.loads(cache_file.read_text(encoding="utf-8"))
    assert cache["O|2025"]["fmp_fetch_success"] is False
    assert cache["O|2025"]["fmp_fetch_reason"] == cv.FMP_PREMIUM_BLOCKED


def test_transient_failure_is_not_written_to_cache(monkeypatch, tmp_path):
    cache_file = tmp_path / "cv_cache.json"
    monkeypatch.setattr(cv, "_CV_CACHE_FILE", cache_file)
    monkeypatch.setattr(cv, "_fetch_fmp_raw", lambda _ticker, _year: (
        None,
        False,
        cv.FMP_TRANSIENT_FAILURE,
    ))
    monkeypatch.setattr("modules.integrity.log.append_cv_to_log", lambda _result: None)

    result = cv.cross_validate_filing(_normalized_data(), "FAIL", "FY2025")

    assert result.fmp_fetch_success is False
    assert result.fmp_fetch_reason == cv.FMP_TRANSIENT_FAILURE
    assert not cache_file.exists()


def test_legacy_failed_cache_entries_are_repaired(monkeypatch, tmp_path):
    cache_file = tmp_path / "cv_cache.json"
    cache_file.write_text(
        json.dumps({
            "COST|2025": {"fmp_vals": None, "fmp_fetch_success": False},
            "NVDA|2026": {
                "fmp_vals": {
                    cv.FMP_REPORTED_CURRENCY_KEY: "USD",
                    "revenue": 1.0,
                },
                "fmp_fetch_success": True,
                "fmp_reported_currency": "USD",
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(cv, "_CV_CACHE_FILE", cache_file)

    cache = cv._load_cv_cache()

    assert "COST|2025" not in cache
    assert cache["NVDA|2026"]["fmp_fetch_reason"] == cv.FMP_FETCH_SUCCESS


def test_currency_mismatch_writes_abstention_reason_and_does_not_flag(monkeypatch, tmp_path):
    cache_file = tmp_path / "cv_cache.json"
    captured = []
    monkeypatch.setattr(cv, "_CV_CACHE_FILE", cache_file)
    monkeypatch.setattr(cv, "_fetch_fmp_raw", lambda _ticker, _year: (
        _fmp_values(reported_currency="USD", revenue=140.0),
        True,
        cv.FMP_FETCH_SUCCESS,
    ))
    monkeypatch.setattr("modules.integrity.log.append_cv_to_log", lambda result: captured.append(result.to_dict()))

    result = cv.cross_validate_filing(_normalized_data(currency="CAD"), "TEST", "FY2025")
    record = captured[0]

    assert result.overall_status == "partial_unmatched"
    assert result.abstention_reason == cv.CV_ABSTAIN_CURRENCY_MISMATCH
    assert record["abstention_reason"] == cv.CV_ABSTAIN_CURRENCY_MISMATCH
    assert record["filing_currency"] == "CAD"
    assert record["fmp_reported_currency"] == "USD"
    assert all(field["status"] == "UNMATCHED" for field in record["cv_fields"])
    assert all(field["pct_diff"] is None for field in record["cv_fields"])
    assert all(field.get("abstention_reason") == cv.CV_ABSTAIN_CURRENCY_MISMATCH for field in record["cv_fields"])
    assert all("severity" not in field for field in record["cv_fields"])


def test_unknown_currency_writes_abstention_reason(monkeypatch, tmp_path):
    cache_file = tmp_path / "cv_cache.json"
    monkeypatch.setattr(cv, "_CV_CACHE_FILE", cache_file)
    monkeypatch.setattr(cv, "_fetch_fmp_raw", lambda _ticker, _year: (
        _fmp_values(reported_currency="USD", revenue=140.0),
        True,
        cv.FMP_FETCH_SUCCESS,
    ))
    monkeypatch.setattr("modules.integrity.log.append_cv_to_log", lambda _result: None)

    result = cv.cross_validate_filing(_normalized_data(currency=None), "TEST", "FY2025")
    record = result.to_dict()

    assert result.overall_status == "partial_unmatched"
    assert result.filing_currency is None
    assert result.abstention_reason == cv.CV_ABSTAIN_CURRENCY_UNKNOWN
    assert all(field["status"] == "UNMATCHED" for field in record["cv_fields"])
    assert all(field.get("abstention_reason") == cv.CV_ABSTAIN_CURRENCY_UNKNOWN for field in record["cv_fields"])
    assert all("severity" not in field for field in record["cv_fields"])


def test_matching_currency_value_mismatch_is_advisory_never_failure(monkeypatch, tmp_path):
    cache_file = tmp_path / "cv_cache.json"
    monkeypatch.setattr(cv, "_CV_CACHE_FILE", cache_file)
    monkeypatch.setattr(cv, "_fetch_fmp_raw", lambda _ticker, _year: (
        _fmp_values(reported_currency="USD", revenue=140.0),
        True,
        cv.FMP_FETCH_SUCCESS,
    ))
    monkeypatch.setattr("modules.integrity.log.append_cv_to_log", lambda _result: None)

    result = cv.cross_validate_filing(_normalized_data(currency="USD"), "TEST", "FY2025")
    revenue = next(field for field in result.fields if field.field == "revenue")
    revenue_record = next(field for field in result.to_dict()["cv_fields"] if field["field"] == "revenue")

    assert result.overall_status == "disagreement"
    assert result.abstention_reason is None
    assert revenue.status == "DISAGREE"
    assert revenue.severity == cv.CV_SEVERITY_ADVISORY
    assert revenue_record["severity"] == cv.CV_SEVERITY_ADVISORY
    assert revenue_record["severity"] != "failure"


def test_matching_currency_value_match_preserves_pass_shape(monkeypatch, tmp_path):
    cache_file = tmp_path / "cv_cache.json"
    monkeypatch.setattr(cv, "_CV_CACHE_FILE", cache_file)
    monkeypatch.setattr(cv, "_fetch_fmp_raw", lambda _ticker, _year: (
        _fmp_values(reported_currency="USD"),
        True,
        cv.FMP_FETCH_SUCCESS,
    ))
    monkeypatch.setattr("modules.integrity.log.append_cv_to_log", lambda _result: None)

    result = cv.cross_validate_filing(_normalized_data(currency="USD"), "TEST", "FY2025")
    record = result.to_dict()

    assert result.overall_status == "all_agree"
    assert result.abstention_reason is None
    assert all(field["status"] == "AGREE" for field in record["cv_fields"])
    assert all(field["pct_diff"] == 0.0 for field in record["cv_fields"])
    assert all("severity" not in field for field in record["cv_fields"])
    assert all("abstention_reason" not in field for field in record["cv_fields"])


def test_append_v2_cv_record_does_not_mutate_pre_existing_log_record(tmp_path):
    path = tmp_path / "integrity_log.jsonl"
    legacy_record = {
        "record_type": "cross_validation",
        "timestamp": "2026-07-02T00:00:00+00:00",
        "ticker": "TEST",
        "fiscal_year": "FY2025",
        "filing_accession": "legacy",
        "overall_status": "disagreement",
        "fmp_fetch_success": True,
        "fmp_fetch_reason": cv.FMP_FETCH_SUCCESS,
        "cv_fields": [
            {
                "field": "revenue",
                "finlens_value": 100.0,
                "fmp_value": 140.0,
                "pct_diff": 28.57,
                "status": "DISAGREE",
            }
        ],
    }
    path.write_text(json.dumps(legacy_record) + "\n", encoding="utf-8")
    before = path.read_text(encoding="utf-8")

    result = cv.CrossValidationResult(
        overall_status="all_agree",
        fields=[
            cv.FieldResult(
                field="revenue",
                finlens_value=100.0,
                fmp_value=100.0,
                pct_diff=0.0,
                status="AGREE",
            )
        ],
        timestamp="2026-07-03T00:00:00+00:00",
        ticker="TEST",
        fiscal_year="FY2025",
        filing_accession="v2",
        fmp_fetch_success=True,
        fmp_fetch_reason=cv.FMP_FETCH_SUCCESS,
        filing_currency="USD",
        fmp_reported_currency="USD",
    )

    integrity_log.append_cv_to_log(result, path)
    integrity_log.append_cv_to_log(result, path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert before.splitlines()[0] == lines[0]
    assert json.loads(lines[0]) == legacy_record
    assert len(lines) == 2
    appended = json.loads(lines[1])
    assert appended["checker_version"] == cv.CROSS_VALIDATE_VERSION
    assert appended["filing_currency"] == "USD"
    assert appended["fmp_reported_currency"] == "USD"
