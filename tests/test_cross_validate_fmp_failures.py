import json

from modules.integrity import cross_validate as cv


def _normalized_data():
    return {
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


def test_successful_cross_validation_writes_reason_to_cache(monkeypatch, tmp_path):
    cache_file = tmp_path / "cv_cache.json"
    monkeypatch.setattr(cv, "_CV_CACHE_FILE", cache_file)
    monkeypatch.setattr(cv, "_fetch_fmp_raw", lambda _ticker, _year: (
        {
            "revenue": 100.0,
            "net_income": 10.0,
            "total_assets": 500.0,
            "operating_cash_flow": 40.0,
        },
        True,
        cv.FMP_FETCH_SUCCESS,
    ))
    monkeypatch.setattr("modules.integrity.log.append_cv_to_log", lambda _result: None)

    result = cv.cross_validate_filing(_normalized_data(), "TEST", "FY2025")

    assert result.fmp_fetch_success is True
    assert result.fmp_fetch_reason == cv.FMP_FETCH_SUCCESS
    assert result.overall_status == "all_agree"
    cache = json.loads(cache_file.read_text(encoding="utf-8"))
    assert cache["TEST|2025"]["fmp_fetch_reason"] == cv.FMP_FETCH_SUCCESS


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
                "fmp_vals": {"revenue": 1.0},
                "fmp_fetch_success": True,
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(cv, "_CV_CACHE_FILE", cache_file)

    cache = cv._load_cv_cache()

    assert "COST|2025" not in cache
    assert cache["NVDA|2026"]["fmp_fetch_reason"] == cv.FMP_FETCH_SUCCESS
