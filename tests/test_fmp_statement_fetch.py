from modules import fmp


class _Response:
    def __init__(self, status_code, payload=None, raises=False):
        self.status_code = status_code
        self._payload = payload
        self._raises = raises

    def json(self):
        if self._raises:
            raise ValueError("bad json")
        return self._payload


class _Session:
    def __init__(self, response):
        self.response = response

    def get(self, _url, timeout):
        return self.response


def test_statement_fetch_classifies_402_as_premium_blocked(monkeypatch):
    monkeypatch.setattr(fmp, "_make_session", lambda: _Session(_Response(402)))

    data, reason = fmp._get_statement_list_with_reason("income-statement", "O")

    assert data is None
    assert reason == fmp.FMP_PREMIUM_BLOCKED


def test_statement_fetch_classifies_valid_200_as_success(monkeypatch):
    monkeypatch.setattr(fmp, "_make_session", lambda: _Session(_Response(200, [{"revenue": 1}])))

    data, reason = fmp._get_statement_list_with_reason("income-statement", "NVDA")

    assert data == [{"revenue": 1}]
    assert reason == fmp.FMP_FETCH_SUCCESS


def test_statement_fetch_classifies_empty_or_parse_error_as_transient(monkeypatch):
    monkeypatch.setattr(fmp, "_make_session", lambda: _Session(_Response(200, [])))

    data, reason = fmp._get_statement_list_with_reason("income-statement", "COST")

    assert data is None
    assert reason == fmp.FMP_TRANSIENT_FAILURE

    monkeypatch.setattr(fmp, "_make_session", lambda: _Session(_Response(200, raises=True)))
    data, reason = fmp._get_statement_list_with_reason("income-statement", "COST")
    assert data is None
    assert reason == fmp.FMP_TRANSIENT_FAILURE
