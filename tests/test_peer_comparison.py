"""Peer-comparison pins — sector auto-suggestion + WCSB peer groups (2026-07-10).

Reference incident: an ARX (ARC Resources, "Upstream Oil & Gas") analysis
rendered the Peer Comparison panel defaulted to "Technology" with
AAPL/MSFT/GOOGL/META/AMZN — the filing's inferred sector never reached
financial_data top-level, and the empty-hint fallback landed on peer_map's
first key with no caption. The fixes: sector_inferred is copied at the SEDAR
boundary (app.py _sedar_extraction_to_financial_data), the filing hint now
outranks the yfinance session auto_sector, an honest "pick one" caption always
renders when nothing matched, and SEDAR energy filers steer to the WCSB
Canadian peer set (Riley's WCSB framework: Integrated Majors / Mid-Cap /
Unconventional; netback, RLI, and production-mix comparisons stay deferred on
AIF/MD&A data — Net Debt/CF is the WCSB metric computable today).
"""

from modules.peer_comparison import (
    _net_debt_to_cash_flow,
    _ticker_root,
    peer_map,
    suggest_sector,
)


# ---------------------------------------------------------------------------
# suggest_sector — filing sector text -> peer bucket
# ---------------------------------------------------------------------------

def test_upstream_oil_and_gas_maps_to_energy():
    assert suggest_sector("Upstream Oil & Gas") == "Energy"


def test_sedar_energy_filer_steers_to_wcsb_bucket():
    # The canadian flag is passed for SEDAR filings: a WCSB gas producer's
    # comparables are Canadian issuers, not US supermajors.
    assert suggest_sector("Upstream Oil & Gas", canadian=True) == "Energy — Canada (WCSB)"


def test_canadian_flag_only_affects_buckets_with_a_variant():
    # No Canadian variant is defined for Metals & Mining — the flag must not
    # invent one.
    assert suggest_sector("Gold Mining", canadian=True) == "Metals & Mining"


def test_empty_hint_returns_none_never_a_default():
    # None means "no suggestion" — the caller renders an honest pick-one
    # caption instead of silently defaulting to the first bucket.
    assert suggest_sector("") is None
    assert suggest_sector(None) is None
    assert suggest_sector("   ", canadian=True) is None


# ---------------------------------------------------------------------------
# WCSB peer groups (Riley's framework, 2026-07-10)
# ---------------------------------------------------------------------------

def test_wcsb_buckets_exist_with_expected_names():
    combined = peer_map["Energy — Canada (WCSB)"]
    assert combined == ["CNQ", "SU", "CVE", "TOU.TO", "OVV", "ARX.TO"]
    assert peer_map["WCSB — Integrated Majors"] == ["CNQ", "SU", "IMO"]
    assert peer_map["WCSB — Mid-Cap Producers"] == ["CVE", "TOU.TO", "ARX.TO"]
    assert peer_map["WCSB — Unconventional Drillers"] == ["OVV", "TOU.TO", "ARX.TO"]


def test_generic_energy_bucket_unchanged():
    # The US supermajor bucket stays for EDGAR/US filers.
    assert peer_map["Energy"] == ["XOM", "CVX", "COP", "SLB", "EOG"]


# ---------------------------------------------------------------------------
# Same-issuer dedup — the analyzed company must not appear as its own peer
# even when the bucket carries a different listing (ARX vs ARX.TO)
# ---------------------------------------------------------------------------

def test_ticker_root_strips_exchange_suffix():
    assert _ticker_root("TOU.TO") == "TOU"
    assert _ticker_root("arx.to") == "ARX"
    assert _ticker_root("TECK.B") == "TECK"
    assert _ticker_root("CNQ") == "CNQ"
    assert _ticker_root("") == ""


# ---------------------------------------------------------------------------
# Net Debt / Operating Cash Flow — the WCSB leverage metric
# ---------------------------------------------------------------------------

def test_net_debt_cf_from_yfinance_shape():
    # ARX-like numbers: (2,878.1 debt − 7.0 cash) / 3,093.5 OCF ≈ 0.93×
    value = _net_debt_to_cash_flow(
        {"totalDebt": 2878.1, "totalCash": 7.0, "operatingCashflow": 3093.5}
    )
    assert value is not None
    assert abs(value - 0.9282) < 0.001


def test_net_debt_cf_honest_none_on_missing_or_negative_ocf():
    # Negative or missing OCF makes the ratio meaningless — honest None,
    # never a sign-flipped number.
    assert _net_debt_to_cash_flow({"totalDebt": 100.0, "operatingCashflow": -50.0}) is None
    assert _net_debt_to_cash_flow({"totalDebt": 100.0}) is None
    assert _net_debt_to_cash_flow({"operatingCashflow": 500.0}) is None
    assert _net_debt_to_cash_flow({}) is None
