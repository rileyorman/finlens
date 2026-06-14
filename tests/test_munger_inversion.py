from __future__ import annotations

import json
from types import SimpleNamespace

from modules import analysis_cache
from modules.analysis import inversion_store, munger_inversion


class _FakeMessages:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.response_text)]
        )


class _FakeClient:
    def __init__(self, response_text: str):
        self.messages = _FakeMessages(response_text)


def _sample_financial_data() -> dict:
    return {
        "currency": "CAD millions",
        "period": "FY2025",
        "fiscal_year_end": "2025-12-31",
        "revenue": 10_756,
        "net_income": 1_072,
        "gross_profit": 2_657,
        "operating_income": 2_248,
        "interest_expense": -912,
        "total_debt": 8_000,
        "cash": 5_012,
        "shareholders_equity": 20_000,
    }


def _sample_mapping() -> dict:
    return {
        "mapped": {
            "revenue": {"value": 10_756, "source_label": "Revenue (Note 6)"},
            "net_income": {"value": 1_072, "source_label": "Profit for the year"},
            "gross_profit": {"value": 2_657, "source_label": "Gross profit"},
        }
    }


def test_generate_inversion_builds_prompt_from_fundamentals_and_parses_json(monkeypatch):
    response_payload = {
        "thesis_killers": ["cycle turns before debt falls", "margin compression"],
        "premortem_narrative": "It's 2029. Lower copper prices exposed thin coverage.",
        "failure_modes": [
            {
                "mode": "commodity cycle reversal",
                "severity": "high",
                "grounding": "Revenue was 10756 and interest expense was -912.",
            }
        ],
        "margin_of_safety_note": "Debt and cyclicality leave little room for error.",
    }
    fake_client = _FakeClient(json.dumps(response_payload))

    monkeypatch.setattr(munger_inversion, "_api_key", lambda: "test-key")
    monkeypatch.setattr(munger_inversion, "_make_client", lambda api_key: fake_client)

    result = munger_inversion.generate_inversion(
        _sample_financial_data(),
        "TECK.B",
        "Diversified Mining (Copper)",
        _sample_mapping(),
    )

    assert result == response_payload
    call = fake_client.messages.calls[0]
    assert call["model"] == munger_inversion.ANALYSIS_MODEL
    prompt = call["messages"][0]["content"]
    assert "TECK.B" in prompt
    assert "Diversified Mining (Copper)" in prompt
    assert '"revenue": 10756' in prompt
    assert '"net_margin":' in prompt
    assert "Revenue (Note 6)" in prompt


def test_generate_inversion_returns_error_for_malformed_json(monkeypatch):
    fake_client = _FakeClient("not json")
    monkeypatch.setattr(munger_inversion, "_api_key", lambda: "test-key")
    monkeypatch.setattr(munger_inversion, "_make_client", lambda api_key: fake_client)

    result = munger_inversion.generate_inversion(
        _sample_financial_data(),
        "TECK.B",
        "Diversified Mining (Copper)",
        _sample_mapping(),
    )

    assert "error" in result
    assert "could not be parsed" in result["error"]


def test_inversion_store_round_trips_with_sanitized_filename_and_schema(monkeypatch, tmp_path):
    store_dir = tmp_path / "inversions"
    monkeypatch.setattr(inversion_store, "_STORE_DIR", store_dir)

    payload = {
        "thesis_killers": ["rent reset risk"],
        "premortem_narrative": "It's 2029. The thesis broke.",
        "failure_modes": [],
        "margin_of_safety_note": "Thin.",
    }

    assert inversion_store.save_inversion("TECK.B", "FY2025", payload)
    assert inversion_store.inversion_exists("TECK.B", "FY2025")

    path = inversion_store.inversion_path("TECK.B", "FY2025")
    assert path.name == "TECK_B_FY2025.json"
    loaded = inversion_store.load_inversion("TECK.B", "FY2025")
    assert loaded["schema_version"] == inversion_store.SCHEMA_VERSION
    assert loaded["thesis_killers"] == ["rent reset risk"]

    assert inversion_store.save_inversion("REI.UN", "FY2025", payload)
    assert inversion_store.inversion_path("REI.UN", "FY2025").name == "REI_UN_FY2025.json"


def test_inversion_store_is_separate_from_analysis_cache(monkeypatch, tmp_path):
    inversion_dir = tmp_path / "inversions"
    analysis_dir = tmp_path / "analysis"
    monkeypatch.setattr(inversion_store, "_STORE_DIR", inversion_dir)
    monkeypatch.setattr(analysis_cache, "_CACHE_DIR", analysis_dir)

    assert inversion_store.save_inversion(
        "TECK.B",
        "FY2025",
        {
            "thesis_killers": [],
            "premortem_narrative": "",
            "failure_modes": [],
            "margin_of_safety_note": "",
        },
    )

    assert inversion_store.inversion_path("TECK.B", "FY2025").exists()
    assert not analysis_dir.exists()
    assert not analysis_cache.analysis_exists("TECK.B", "FY2025")
