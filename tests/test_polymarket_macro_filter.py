"""Pins for the Polymarket macro-feed fixes (found live 2026-07-13 during
the Stock Tracker tab walk): (1) keyword matching is word-boundary, never
substring — "World Cup: Golden Boot Winner" topped the "macro" feed because
"golden" contains "gold"; (2) a probability is served ONLY for a true
binary (Yes/No) market — Polymarket events hold multiple binary sub-markets,
and outcomePrices[0] of a sub-market shown against the EVENT title produced
"How many Fed rate cuts in 2026? 78% Yes".
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import polymarket as pm


def test_keyword_match_is_word_boundary_not_substring():
    assert pm._is_macro_event({"title": "Will the Fed cut rates in September?"})
    assert pm._is_macro_event({"title": "Gold above $4,000 at year end?"})
    # The live escapes: substring hits inside unrelated words must NOT match.
    assert not pm._is_macro_event({"title": "World Cup: Golden Boot Winner"})
    assert not pm._is_macro_event({"title": "Political turmoil in parliament?"})
    assert not pm._is_macro_event({"title": "Arcade game of the year"})


def test_probability_only_for_true_binary_markets():
    binary = {"outcomes": '["Yes", "No"]', "outcomePrices": '["0.76", "0.24"]'}
    assert pm._yes_probability(binary) == 0.76
    # Multi-outcome / non-Yes-No markets serve NO probability.
    multi = {"outcomes": '["0 cuts", "1 cut", "2 cuts"]', "outcomePrices": '["0.1", "0.3", "0.6"]'}
    assert pm._yes_probability(multi) is None
    assert pm._yes_probability({"outcomePrices": '["0.5", "0.5"]'}) is None


def test_multi_market_event_displays_the_sub_market_question(monkeypatch):
    """The probability belongs to one sub-market; the shown question must be
    that market's, not the event's non-binary umbrella title."""
    event = {
        "title": "How many Fed rate cuts in 2026?",
        "slug": "fed-cuts-2026",
        "volume": 1000,
        "markets": [
            {"question": "Will there be exactly 2 Fed rate cuts in 2026?",
             "outcomes": '["Yes", "No"]', "outcomePrices": '["0.30", "0.70"]',
             "volumeNum": 900},
            {"question": "Will there be exactly 3 Fed rate cuts in 2026?",
             "outcomes": '["Yes", "No"]', "outcomePrices": '["0.20", "0.80"]',
             "volumeNum": 100},
        ],
    }

    class _FakeResponse:
        def raise_for_status(self):
            pass
        def json(self):
            return [event]

    class _FakeSession:
        def get(self, *a, **k):
            return _FakeResponse()

    monkeypatch.setattr(pm, "_make_session", lambda: _FakeSession())
    results = pm.get_macro_markets()
    # One event returned per offset page (deduped by content here is fine —
    # the pin is the QUESTION selection, not the pagination).
    assert results, "expected the macro event to pass the filter"
    assert results[0]["question"] == "Will there be exactly 2 Fed rate cuts in 2026?"
    assert results[0]["probability"] == 0.30
