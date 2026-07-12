"""Bare-ticker collision guard — fetch-path extension pins (2026-07-12).

The wrong-issuer guard (name-agreement + prefer-Canadian, built for the
ARX/Accelerant incident, commit 12c99c4) protected the analysis paths but
NOT the watchlist/portfolio/quick-financials fetch paths (queue item
tracked since 12c99c4's message). These pins freeze the extension:

- Portfolio display fetch arms the guard from the LIBRARY entry (the
  filing's company name + prefer-Canadian for SEDAR filers).
- Tickers with no library context keep the bare fetch (the user chose the
  listing symbol; the add-time receipt names the resolved listing).

The Stock Tracker path was audited and needs no change: it renders the
resolved company name as the page header (the receipt already exists).
Quick Financials and the EDGAR path arm the guard inline in app.py
(FMP profile name / EDGAR-authoritative name) — exercised via app flows,
not unit-pinned here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import portfolio_manager as pm


def _library(tmp_path, entries):
    lib = tmp_path / "filing_library.json"
    lib.write_text(json.dumps({"entries": entries}), encoding="utf-8")
    return str(lib)


def test_portfolio_fetch_arms_guard_from_library_entry(tmp_path, monkeypatch):
    calls = []

    def fake_get_market_data(ticker, company_name=None, prefer_canadian=False):
        calls.append({"ticker": ticker, "company_name": company_name,
                      "prefer_canadian": prefer_canadian})
        return {}

    monkeypatch.setattr(pm, "get_market_data", fake_get_market_data)
    lib_path = _library(tmp_path, [{
        "ticker": "ARX",
        "financial_data": {"company_name": "ARC Resources Ltd.",
                           "source": "sedar_pdf"},
        "summary_data": {},
    }])

    pm.get_portfolio_display_data(["ARX"], filing_library_path=lib_path)

    assert calls == [{"ticker": "ARX",
                      "company_name": "ARC Resources Ltd.",
                      "prefer_canadian": True}]


def test_portfolio_fetch_bare_without_library_context(tmp_path, monkeypatch):
    calls = []

    def fake_get_market_data(ticker, company_name=None, prefer_canadian=False):
        calls.append({"ticker": ticker, "company_name": company_name,
                      "prefer_canadian": prefer_canadian})
        return {}

    monkeypatch.setattr(pm, "get_market_data", fake_get_market_data)
    lib_path = _library(tmp_path, [])

    pm.get_portfolio_display_data(["AAPL"], filing_library_path=lib_path)

    assert calls == [{"ticker": "AAPL", "company_name": None,
                      "prefer_canadian": False}]


def test_portfolio_fetch_non_sedar_entry_arms_name_only(tmp_path, monkeypatch):
    """EDGAR/manual library entries arm the name check but not the
    Canadian-listing preference."""
    calls = []

    def fake_get_market_data(ticker, company_name=None, prefer_canadian=False):
        calls.append({"company_name": company_name,
                      "prefer_canadian": prefer_canadian})
        return {}

    monkeypatch.setattr(pm, "get_market_data", fake_get_market_data)
    lib_path = _library(tmp_path, [{
        "ticker": "NVDA",
        "financial_data": {"company_name": "NVIDIA Corporation",
                           "source": "edgar"},
        "summary_data": {},
    }])

    pm.get_portfolio_display_data(["NVDA"], filing_library_path=lib_path)

    assert calls == [{"company_name": "NVIDIA Corporation",
                      "prefer_canadian": False}]
