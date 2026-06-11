from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import edgar_fetcher


class _FakeResponse:
    def __init__(self, payload: dict | None = None, ok: bool = True):
        self._payload = payload or {}
        self.ok = ok
        self.content = b""

    def json(self) -> dict:
        return self._payload


class _FakeSession:
    def __init__(self):
        self.urls: list[str] = []

    def get(self, url, headers=None, timeout=None):
        self.urls.append(url)
        if "search-index" in url:
            if "%22Chubb%22" in url:
                return _FakeResponse(
                    {
                        "hits": [
                            {"entity": ["THE CHUBB CORP (CIK 0000020171)"]},
                            {"entity": ["CHUBB LIMITED (CIK 0000896159)"]},
                        ]
                    }
                )
            if "%22Apple%22" in url:
                return _FakeResponse({"hits": [{"entity": ["APPLE INC (CIK 0000320193)"]}]})
            if "%22Markel%22" in url:
                return _FakeResponse({"hits": [{"entity": ["MARKEL GROUP INC. (CIK 0001096343)"]}]})
        if "CIK0000896159.json" in url:
            return _FakeResponse({"filings": {"recent": {"filingDate": ["2026-02-28", "2025-11-03"]}}})
        if "CIK0000020171.json" in url:
            return _FakeResponse({"filings": {"recent": {"filingDate": ["2015-11-12", "2015-08-06"]}}})
        if "CIK0000320193.json" in url:
            return _FakeResponse({"filings": {"recent": {"filingDate": ["2025-10-31"]}}})
        if "CIK0001096343.json" in url:
            return _FakeResponse({"filings": {"recent": {"filingDate": ["2026-02-25"]}}})
        return _FakeResponse(ok=False)


def _install_fake_session(monkeypatch) -> _FakeSession:
    fake = _FakeSession()
    monkeypatch.setattr(edgar_fetcher, "_SESSION", fake)
    monkeypatch.setattr(edgar_fetcher, "_SUBMISSIONS_CACHE", {})
    return fake


def test_chubb_name_search_sorts_live_company_above_defunct_entity(monkeypatch):
    _install_fake_session(monkeypatch)

    matches = edgar_fetcher.search_companies("Chubb")

    assert [match["cik"] for match in matches[:2]] == ["0000896159", "0000020171"]
    assert matches[0]["name"] == "CHUBB LIMITED"
    assert matches[0]["last_filed"] == "2026-02-28"
    assert "possibly defunct" not in matches[0]["label"]
    assert matches[1]["name"] == "THE CHUBB CORP"
    assert matches[1]["last_filed"] == "2015-11-12"
    assert matches[1]["possibly_defunct"] is True
    assert matches[1]["label"].endswith("[possibly defunct]")


def test_apple_name_search_returns_current_apple_cik(monkeypatch):
    _install_fake_session(monkeypatch)

    matches = edgar_fetcher.search_companies("Apple")

    assert matches[0]["name"] == "APPLE INC"
    assert matches[0]["cik"] == "0000320193"
    assert matches[0]["label"] == "APPLE INC (CIK 0000320193) — last filed 2025-10-31"


def test_markel_name_search_returns_current_markel_cik(monkeypatch):
    _install_fake_session(monkeypatch)

    matches = edgar_fetcher.search_companies("Markel")

    assert matches[0]["name"] == "MARKEL GROUP INC."
    assert matches[0]["cik"] == "0001096343"
    assert matches[0]["label"] == "MARKEL GROUP INC. (CIK 0001096343) — last filed 2026-02-25"
