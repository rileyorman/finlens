from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "diagnose_label_blind_agree.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("diagnose_label_blind_agree", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_diagnostic_uses_production_label_normalizer_and_counts_agree_rows():
    script = _load_script_module()
    records = [
        {
            "record_type": "cross_extractor_agreement",
            "checker_version": "2",
            "timestamp": "2026-07-03T00:00:00+00:00",
            "ticker": "ATD",
            "fiscal_year": "FY2025",
            "filing_accession": "atd",
            "state": "VERIFIED",
            "cross_extractor_fields": [
                {
                    "canonical_field": "revenue",
                    "status": "AGREE",
                    "finlens_label": "Revenue (Note 1)",
                    "gemini_label": "revenue",
                    "finlens_value": 100.0,
                    "gemini_value": 100.0,
                },
                {
                    "canonical_field": "net_income",
                    "status": "AGREE",
                    "finlens_label": "Net earnings",
                    "gemini_label": "Net earnings attributable to shareholders",
                    "finlens_value": 2592.4,
                    "gemini_value": 2580.4,
                },
                {
                    "canonical_field": "interest_expense",
                    "status": "CONFLICT",
                    "finlens_label": "Financial expenses (Note 9)",
                    "gemini_label": "Interest on lease liabilities",
                    "finlens_value": 690.8,
                    "gemini_value": 159.3,
                },
            ],
        },
        {
            "record_type": "cross_extractor_agreement",
            "checker_version": "1",
            "timestamp": "2026-07-02T00:00:00+00:00",
            "ticker": "ATD",
            "fiscal_year": "FY2025",
            "filing_accession": "atd",
            "state": "VERIFIED",
            "cross_extractor_fields": [],
        },
    ]

    latest = script._latest_cross_extractor_records(records, "2")
    rows = script._agree_label_rows(latest)

    assert len(latest) == 1
    assert len(rows) == 2
    assert rows[0]["labels_match"] is True
    assert rows[0]["finlens_normalized"] == "revenue"
    assert rows[1]["labels_match"] is False
    assert rows[1]["relative_delta_pct"] > 0
