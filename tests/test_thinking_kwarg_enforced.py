"""
Every Anthropic API call must set an explicit `thinking` kwarg.

Machine-enforces the CLAUDE.md sonnet-5 gotcha (verified 2026-07-08):
claude-sonnet-5 intermittently emits thinking content blocks BY DEFAULT,
which (1) shift content[0] so bare content[0].text breaks, and (2) consume
the output budget, truncating small-max_tokens JSON responses. The
convention — non-Opus calls pass thinking={"type": "disabled"}, Opus
branches deliberately pass {"type": "adaptive"} — previously lived only in
CLAUDE.md prose, and the 2026-07-11 token-limit audit found two modules it
never reached (mda_sentiment.py and filing_comparison.py both ran sonnet-5
with default thinking and 512/2048-token caps: the Call 4 truncation bug
class, live in the Filing Comparison feature).

This test scans the source of every LLM-calling module: each
`messages.create(` / `messages.stream(` call must contain a `thinking`
kwarg somewhere in its argument list. Either value passes — the rule is
that the choice must be EXPLICIT, never the model default.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Every module that calls the Anthropic messages API. A new LLM-calling
# module must be added here (the test below also fails if a listed file
# stops containing any API calls, so the list can't silently rot).
LLM_MODULES = [
    "modules/claude_analyzer.py",
    "modules/mda_sentiment.py",
    "modules/filing_comparison.py",
    "modules/analysis/munger_inversion.py",
    "modules/scenario_simulator.py",
    "sedar_extractor.py",
]

_CALL_RE = re.compile(r"\.messages\.(?:create|stream)\(")


def _call_spans(source: str):
    """Yield (line_number, argument_text) for each messages.create/stream call."""
    for match in _CALL_RE.finditer(source):
        start = match.end() - 1  # the opening paren
        depth = 0
        for i in range(start, len(source)):
            if source[i] == "(":
                depth += 1
            elif source[i] == ")":
                depth -= 1
                if depth == 0:
                    line = source.count("\n", 0, match.start()) + 1
                    yield line, source[start : i + 1]
                    break


@pytest.mark.parametrize("rel_path", LLM_MODULES)
def test_every_api_call_sets_thinking_explicitly(rel_path):
    source = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    spans = list(_call_spans(source))
    assert spans, (
        f"{rel_path} is listed as an LLM-calling module but contains no "
        "messages.create/stream calls — update LLM_MODULES if it stopped calling the API."
    )
    missing = [line for line, args in spans if not re.search(r"\bthinking\b", args)]
    assert not missing, (
        f"{rel_path}: messages.create/stream call(s) at line(s) {missing} do not set "
        'an explicit `thinking` kwarg. Non-Opus calls need {"type": "disabled"} '
        "(sonnet-5 emits thinking blocks by default, eating the output budget "
        'and shifting content[0]); Opus branches pass {"type": "adaptive"}. '
        "See the sonnet-5 gotcha in CLAUDE.md."
    )
