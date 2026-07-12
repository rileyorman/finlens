"""Machine enforcement: every json.loads on LLM output must pass strict=False.

Reference incident (2026-07-12, TOU dashboard): Call 4 failed with
"Invalid control character at ... char 1217" — sonnet-5 emitted a raw
control character (literal newline/tab) inside a JSON string value, which
Python's strict-mode parser rejects. strict=False accepts control chars
INSIDE strings while still rejecting structurally invalid JSON — the right
tolerance for model-generated JSON, and a distinct defect class from the
max_tokens truncation fixed in c73c976.

Scope: the seven modules that parse LLM (Claude/Gemini/agent) responses.
In these files EVERY json.loads is an LLM-output parse (verified by audit
2026-07-12), so the rule is total per file. Fixture/log/registry/HTTP
parses elsewhere stay strict — control characters there are corruption
signals, not model quirks.

Same enforcement pattern as tests/test_thinking_kwarg_enforced.py.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

LLM_PARSING_FILES = [
    "modules/claude_analyzer.py",
    "sedar_extractor.py",
    "modules/analysis/munger_inversion.py",
    "modules/filing_comparison.py",
    "modules/mda_sentiment.py",
    "modules/integrity/cross_extractor.py",
    "modules/agent_fetch.py",
]

_LOADS_RE = re.compile(r"json\.loads\([^\n]*")


@pytest.mark.parametrize("rel_path", LLM_PARSING_FILES)
def test_every_llm_json_loads_is_tolerant(rel_path):
    source = (ROOT / rel_path).read_text(encoding="utf-8")
    offenders = []
    for line_num, line in enumerate(source.splitlines(), start=1):
        for match in _LOADS_RE.finditer(line):
            if "strict=False" not in match.group(0):
                offenders.append(f"{rel_path}:{line_num}: {line.strip()}")
    assert not offenders, (
        "json.loads on LLM output without strict=False (raw control chars "
        "inside model-emitted strings raise JSONDecodeError in strict mode):\n"
        + "\n".join(offenders)
    )


def test_strict_false_actually_tolerates_control_chars():
    """The behavior the enforcement buys: a literal newline inside a JSON
    string parses under strict=False and fails under the default."""
    import json

    payload = '{"dalio_view": "line one\nline two"}'
    with pytest.raises(json.JSONDecodeError):
        json.loads(payload)
    assert json.loads(payload, strict=False)["dalio_view"] == "line one\nline two"
