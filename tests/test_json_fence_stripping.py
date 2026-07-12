"""
JSON fence stripping must survive a max_tokens truncation.

Pins the Call 4 bug fix (2026-07-11): claude-sonnet-5's dashboard-insights
JSON hit the max_tokens=1200 cap mid-output on six corpus filers
(WCP/AP.UN/SU/CNQ/REI.UN/PLD library entries + ARX live). When the model
had opened a ```json fence, the truncation ate the closing fence, and the
old both-fences-required regex left the leading ``` in place — json.loads
then failed with the misleading "Expecting value: line 1 column 1 (char 0)"
signature that looked like an empty response.

The fix (besides raising the token budgets) makes the closing fence
OPTIONAL at every fence-strip site: modules/claude_analyzer._strip_json_fences
(Calls 1-4), sedar_extractor._strip_json_fences, and
modules/analysis/munger_inversion._strip_json_fences.
"""

import json

import pytest

from modules.claude_analyzer import _strip_json_fences as _strip_analyzer
from modules.analysis.munger_inversion import _strip_json_fences as _strip_munger
from sedar_extractor import _strip_json_fences as _strip_sedar

COMPLETE_JSON = '{"signal": "BUY", "thesis": "Strong netbacks."}'
FENCED = f"```json\n{COMPLETE_JSON}\n```"
FENCED_UPPER = f"```JSON\n{COMPLETE_JSON}\n```"
TRUNCATED_FENCED = f"```json\n{COMPLETE_JSON}"  # closing fence eaten by max_tokens
PROSE_WRAPPED = f"Here is the JSON you asked for:\n\n```json\n{COMPLETE_JSON}\n```\nHope this helps."

ALL_STRIPPERS = [_strip_analyzer, _strip_sedar, _strip_munger]


@pytest.mark.parametrize("strip", ALL_STRIPPERS)
def test_complete_fenced_json_parses(strip):
    assert json.loads(strip(FENCED)) == json.loads(COMPLETE_JSON)


@pytest.mark.parametrize("strip", ALL_STRIPPERS)
def test_truncated_fence_is_salvaged(strip):
    # THE bug: truncation eats the closing fence. The stripped result must
    # still be the JSON body, not a string starting with a backtick.
    assert json.loads(strip(TRUNCATED_FENCED)) == json.loads(COMPLETE_JSON)


@pytest.mark.parametrize("strip", ALL_STRIPPERS)
def test_bare_json_passes_through(strip):
    assert json.loads(strip(COMPLETE_JSON)) == json.loads(COMPLETE_JSON)


@pytest.mark.parametrize("strip", ALL_STRIPPERS)
def test_uppercase_fence_tag(strip):
    assert json.loads(strip(FENCED_UPPER)) == json.loads(COMPLETE_JSON)


@pytest.mark.parametrize("strip", ALL_STRIPPERS)
def test_prose_wrapped_fence(strip):
    assert json.loads(strip(PROSE_WRAPPED)) == json.loads(COMPLETE_JSON)


def test_truncated_mid_string_still_fails_honestly():
    # A truncation that lands mid-JSON cannot be salvaged by fence stripping;
    # the parse must still fail (the raised token budget is the real fix; the
    # error handler reports "truncated at max_tokens" for this case).
    truncated_body = '```json\n{"signal": "BUY", "thesis": "cut off mid-sent'
    stripped = _strip_analyzer(truncated_body)
    assert stripped.startswith('{"signal"')  # fence gone — honest parse error next
    with pytest.raises(json.JSONDecodeError):
        json.loads(stripped)
