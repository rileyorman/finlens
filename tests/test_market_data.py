"""Market-data ticker-resolution pins — the wrong-issuer guard (2026-07-10).

Reference collision: an ARX (ARC Resources Ltd., TSX-only) SEDAR analysis
fetched market data for bare 'ARX', which on yfinance is Accelerant Holdings —
a US insurance broker. The app then showed Accelerant's sector ("Financial
Services") in Valuation Inputs and would have used its $2.7B market cap in
place of ARC's $17.5B: a confident wrong number, the exact class the cold-load
gate forbids. Guard: Canadian filings try .TO/.V listings first, and any
candidate whose listing name disagrees with the filing's company name is
REJECTED (honest absence beats wrong-issuer data).
"""

from modules.market_data import (
    _candidate_symbols,
    _names_agree,
    _normalize_company_name,
    _to_yfinance_ticker,
)


# ---------------------------------------------------------------------------
# _to_yfinance_ticker — existing translation behavior stays pinned
# ---------------------------------------------------------------------------

def test_dot_format_tsx_tickers_translate():
    assert _to_yfinance_ticker("REI.UN") == "REI-UN.TO"
    assert _to_yfinance_ticker("TECK.B") == "TECK-B.TO"


def test_override_and_suffixed_tickers_pass_through():
    assert _to_yfinance_ticker("NFG") == "NFG.V"  # campaign-scoped override
    assert _to_yfinance_ticker("TOU.TO") == "TOU.TO"
    assert _to_yfinance_ticker("AAPL") == "AAPL"


# ---------------------------------------------------------------------------
# _candidate_symbols — Canadian filings try TSX/TSXV before the bare symbol
# ---------------------------------------------------------------------------

def test_bare_ticker_on_canadian_filing_tries_tsx_first():
    assert _candidate_symbols("ARX", prefer_canadian=True) == ["ARX.TO", "ARX.V", "ARX"]


def test_bare_ticker_without_canadian_preference_unchanged():
    # EDGAR/US paths keep the historical single-candidate behavior.
    assert _candidate_symbols("ARX") == ["ARX"]
    assert _candidate_symbols("AAPL", prefer_canadian=False) == ["AAPL"]


def test_already_suffixed_or_translated_tickers_do_not_expand():
    assert _candidate_symbols("REI.UN", prefer_canadian=True) == ["REI-UN.TO"]
    assert _candidate_symbols("TOU.TO", prefer_canadian=True) == ["TOU.TO"]
    assert _candidate_symbols("NFG", prefer_canadian=True) == ["NFG.V"]


def test_empty_ticker_yields_no_candidates():
    assert _candidate_symbols("", prefer_canadian=True) == []


# ---------------------------------------------------------------------------
# _names_agree — the wrong-issuer guard
# ---------------------------------------------------------------------------

def test_reference_collision_rejected():
    # Bare 'ARX' resolves to Accelerant Holdings — must NOT pass as ARC.
    assert _names_agree("ARC Resources Ltd.", "Accelerant Holdings") is False


def test_true_issuer_accepted_across_legal_forms():
    assert _names_agree("ARC Resources Ltd.", "ARC Resources Ltd.") is True
    assert _names_agree("ARC Resources Ltd.", "Arc Resources") is True
    assert _names_agree("Tourmaline Oil Corp.", "Tourmaline Oil Corporation") is True
    assert _names_agree(
        "RioCan Real Estate Investment Trust",
        "RioCan Real Estate Investment Trust",
    ) is True


def test_containment_counts_as_agreement():
    # Listing names often extend the filing name (class suffixes etc.).
    assert _names_agree("Teck Resources", "Teck Resources Limited Class B") is True


def test_missing_names_never_agree():
    assert _names_agree("", "Accelerant Holdings") is False
    assert _names_agree("ARC Resources Ltd.", "") is False
    assert _names_agree(None, None) is False


def test_normalize_strips_legal_words_and_punctuation():
    assert _normalize_company_name("ARC Resources Ltd.") == "arc resources"
    assert _normalize_company_name("Tourmaline Oil Corp.") == "tourmaline oil"
    assert _normalize_company_name("The Toronto-Dominion Bank") == "toronto dominion bank"
