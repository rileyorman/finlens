"""Tests for _sanitize in modules/claude_analyzer.py.

Reference incident (Jul 1 2026, AEM bear case): the old blanket
encode("ascii", "replace") turned em-dashes in Claude prose into "?"
("San Nicolas ? all simultaneously ?") and the mangled text was stored
in the analysis cache permanently. _sanitize must keep its ASCII-only
output guarantee (Windows charmap safety) while mapping typography to
readable equivalents instead of "?".
"""

import pytest

from modules.claude_analyzer import _sanitize


@pytest.mark.parametrize(
    "text, expected",
    [
        # The reference incident: em dashes become "--", not "?"
        (
            "conducting feasibility at San Nicolas — all simultaneously — raising execution risk",
            "conducting feasibility at San Nicolas -- all simultaneously -- raising execution risk",
        ),
        # En dash and unicode minus
        ("FY2024–FY2025 range", "FY2024-FY2025 range"),
        ("a loss of −6,787", "a loss of -6,787"),
        # Curly quotes straighten
        ("management’s “strong” outlook", "management's \"strong\" outlook"),
        # Ellipsis and non-breaking space
        ("growth continues…", "growth continues..."),
        ("55.4 Moz", "55.4 Moz"),
        # Accents drop to base letters, not "?"
        ("San Nicolás café", "San Nicolas cafe"),
        ("Société Générale", "Societe Generale"),
        # Plain ASCII passes through untouched
        ("Net income of $4.5B -- up 135% YoY", "Net income of $4.5B -- up 135% YoY"),
        # Empty/None-ish inputs preserved
        ("", ""),
    ],
)
def test_sanitize_readable_ascii(text, expected):
    assert _sanitize(text) == expected


def test_sanitize_output_is_always_pure_ascii():
    """The charmap-safety contract: output must encode to ASCII cleanly."""
    samples = [
        "em—dash", "quote’s", "café", "naïve", "½ unmappable ₹ symbols",
        "mixed — “typography” … everywhere",
    ]
    for s in samples:
        out = _sanitize(s)
        out.encode("ascii")  # raises if the guarantee is broken


def test_sanitize_unmappable_symbols_fall_back_to_question_mark():
    # Truly unmappable symbols still degrade to "?" rather than crashing.
    assert "?" in _sanitize("price in ₹ rupees")
