"""CB-019 — Sector-aware red-flag suppression: acceptance tests T1–T11.

Covers the post-evaluation suppression path introduced in SPEC §2 of
docs/design_sessions/2026-07-07-sector-aware-red-flags__fable.md.

Fixture convention
------------------
All financial_data dicts are built inline from minimal rows; no JSON
fixtures are loaded.  Row dicts use only the fields _lookup/_lookup2 need:
``line_item`` (str), ``value`` (float|int).  ``row_type`` is omitted so
_lookup2's subtotal pass misses them and the fallback pass picks them up —
identical behavior to real SEDAR rows that lack a ``row_type``.

The ``net_income`` top-level key takes priority in _calc_summary_metrics
over IS-row scanning (CB-017 canonical-first rule), so NI is set there
instead of adding a duplicate IS row.
"""

import copy

from modules.red_flag_detector import (
    SECTOR_FLAG_RULES,
    detect_flags,
    _resolve_sector_profile,
)

# ── Fixture helpers ────────────────────────────────────────────────────────────

_MINING_PROFILE = "mining_exploration_sector"


def _row(label: str, value) -> dict:
    return {"line_item": label, "value": value}


def _explorer_fd(
    *,
    current_ratio: float = 3.2,
    add_interest_expense: bool = False,
    fcf_none: bool = False,
    ni_none: bool = False,
    oi_none: bool = False,
    all_positive: bool = False,
) -> dict:
    """Base fixture for a mining_exploration_sector filer.

    Defaults produce the T1 NGEx shape:
      - operating income  < 0  (red if not suppressed)
      - net income        < 0  (yellow if not suppressed)
      - free cash flow    < 0  (yellow if not suppressed)
      - revenue           None (pre-revenue explorer)
      - current ratio     3.2x (healthy)
      - debt metrics      None

    Keyword overrides tweak individual axes for other tests.
    """
    is_rows = []
    cf_rows = []
    bs_rows = [
        _row("total current assets",      int(current_ratio * 1_000_000)),
        _row("total current liabilities", 1_000_000),
    ]

    if all_positive:
        # T8: healthy explorer — nothing fires
        is_rows.append(_row("operating income", 5_000_000))
        cf_rows.extend([
            _row("net cash provided by operating activities", 8_000_000),
            _row("capital expenditures",                     -2_000_000),
        ])
        fd = {
            "mapping":             {"meta": {"sector_profile": _MINING_PROFILE}},
            "income_statement":    is_rows,
            "net_income":          4_000_000,
            "balance_sheet":       bs_rows,
            "cash_flow_statement": cf_rows,
        }
        return fd

    if not oi_none:
        is_rows.append(_row("operating income", -5_000_000))

    if add_interest_expense:
        # Produces interest coverage < 1.5 (red) when oi_c = -5_000_000.
        # int_cover = oi_c / abs(int_exp) = -5_000_000 / 1_000_000 = -5.0 < 1.5.
        is_rows.append(_row("interest expense", -1_000_000))

    if not fcf_none:
        # ocf=2M, capex=5M (abs) → fcf = 2M – 5M = –3M  (< 0, yellow)
        cf_rows.extend([
            _row("net cash provided by operating activities", 2_000_000),
            _row("capital expenditures",                     -5_000_000),
        ])
    else:
        # No capex row → fcf_c = None (honest skip)
        cf_rows.append(_row("net cash provided by operating activities", 2_000_000))

    fd: dict = {
        "mapping":             {"meta": {"sector_profile": _MINING_PROFILE}},
        "income_statement":    is_rows,
        "balance_sheet":       bs_rows,
        "cash_flow_statement": cf_rows,
    }
    if not ni_none:
        fd["net_income"] = -3_000_000
    return fd


# ── T1 — NGEx shape (the motivating case) ─────────────────────────────────────

def test_t1_ngex_shape_suppresses_three_no_override():
    """Profile mining_exploration_sector; OI<0, NI<0, FCF<0; healthy liquidity.

    Spec: red flags=0, yellow flags=0, suppressed=3 (all with reason_code
    'sector_expected_shape'), override=None.
    This is the correction of the false INVESTIGATE the blind detector produced.
    """
    fd  = _explorer_fd()
    out = detect_flags(fd)

    assert out["red_count"]    == 0,    "no surviving reds"
    assert out["yellow_count"] == 0,    "no surviving yellows"
    assert out["signal_override"] is None

    sup = out["suppressed"]
    assert len(sup) == 3, f"expected 3 suppressed, got {len(sup)}"

    checks = {s["check"] for s in sup}
    assert checks == {"operating_income", "net_income", "free_cash_flow"}

    for s in sup:
        assert s["reason_code"]    == "sector_expected_shape"
        assert s["sector_profile"] == _MINING_PROFILE
        assert s["action"]         == "suppress"
        assert "rationale"         in s and s["rationale"]

    # Severity sanity: op-income is red, the other two are yellow
    by_check = {s["check"]: s for s in sup}
    assert by_check["operating_income"]["severity_suppressed"] == "red"
    assert by_check["net_income"]["severity_suppressed"]       == "yellow"
    assert by_check["free_cash_flow"]["severity_suppressed"]   == "yellow"

    assert out["sector_profile"] == _MINING_PROFILE


# ── T2 — Explorer with a real liquidity problem ────────────────────────────────

def test_t2_explorer_real_liquidity_problem():
    """As T1 but current ratio 0.4x.

    Spec: current_ratio red survives; suppressed still 3; override INVESTIGATE.
    """
    fd  = _explorer_fd(current_ratio=0.4)
    out = detect_flags(fd)

    assert out["red_count"]    == 1
    assert out["signal_override"] == "INVESTIGATE"

    surviving_labels = [f["label"] for f in out["flags"]]
    assert any("liquidity" in lbl.lower() for lbl in surviving_labels), (
        "current_ratio red flag must survive"
    )
    assert len(out["suppressed"]) == 3


# ── T3 — Explorer near insolvency ─────────────────────────────────────────────

def test_t3_explorer_near_insolvency():
    """As T1 but current ratio 0.4x and interest coverage also fires red.

    Spec: 2 surviving reds → DECLINE; suppressed records do not count.
    """
    fd  = _explorer_fd(current_ratio=0.4, add_interest_expense=True)
    out = detect_flags(fd)

    assert out["red_count"]       == 2
    assert out["signal_override"] == "DECLINE"
    assert len(out["suppressed"]) == 3

    surviving_check_labels = {f["label"] for f in out["flags"]}
    assert any("liquidity"  in lbl.lower() for lbl in surviving_check_labels)
    assert any("interest"   in lbl.lower() or "coverage" in lbl.lower()
               for lbl in surviving_check_labels)


# ── T4 — Allied (REIT, unchanged behavior) ────────────────────────────────────

def test_t4_allied_reit_unchanged():
    """Profile reit_sector has no rules in v1 — all flags fire normally.

    Spec: net-income yellow, current-ratio red, interest-coverage yellow;
    suppressed=[]; override=INVESTIGATE (1 red).
    """
    fd = {
        "mapping": {"meta": {"sector_profile": "reit_sector"}},
        "income_statement": [
            _row("operating income", 2_340_000),
            _row("interest expense", -1_000_000),
        ],
        "net_income": -1_327_532_000,
        "balance_sheet": [
            _row("total current assets",      530_000),
            _row("total current liabilities", 1_000_000),
        ],
        "cash_flow_statement": [],
    }
    out = detect_flags(fd)

    assert out["suppressed"]      == []
    assert out["sector_profile"]  == "reit_sector"
    assert out["red_count"]       == 1,  "current_ratio red"
    assert out["signal_override"] == "INVESTIGATE"

    labels = [f["label"] for f in out["flags"]]
    assert any("net income" in lbl.lower()  for lbl in labels), "NI yellow present"
    assert any("liquidity"  in lbl.lower()  for lbl in labels), "CR red present"
    assert any("interest"   in lbl.lower() or "coverage" in lbl.lower()
               for lbl in labels), "IC yellow present"


# ── T5 — TD (bank, None-skip unchanged) ───────────────────────────────────────

def test_t5_td_bank_clean_no_suppression():
    """Profile financial_sector; liquidity/leverage metrics all None; healthy profits.

    Spec: CLEAN; suppressed=[]; None-skips are not suppression records.
    """
    fd = {
        "mapping": {"meta": {"sector_profile": "financial_sector"}},
        "income_statement": [
            _row("operating income", 10_000_000),
        ],
        "net_income":          8_000_000,
        "balance_sheet":       [],   # no CA/CL → current_ratio = None → skip
        "cash_flow_statement": [],   # no OCF/capex → fcf_c = None → skip
    }
    out = detect_flags(fd)

    assert out["suppressed"]      == []
    assert out["sector_profile"]  == "financial_sector"
    assert out["red_count"]       == 0
    assert out["yellow_count"]    == 0
    assert out["signal_override"] is None


# ── T6 — EDGAR filer, no mapping key ──────────────────────────────────────────

def test_t6_edgar_no_mapping_key():
    """financial_data has no 'mapping' key at all (EDGAR path).

    Spec: no exception; gross-margin yellow fires as today; suppressed=[];
    sector_profile=None.
    """
    fd = {
        # deliberate absence of 'mapping'
        "income_statement": [
            _row("revenue",      100_000),
            _row("gross profit",  12_000),
        ],
        "balance_sheet":       [],
        "cash_flow_statement": [],
    }
    out = detect_flags(fd)

    assert out["suppressed"]     == []
    assert out["sector_profile"] is None

    labels = [f["label"] for f in out["flags"]]
    assert any("gross margin" in lbl.lower() for lbl in labels), (
        "thin gross-margin yellow must fire"
    )


# ── T7 — skip ≠ suppress ──────────────────────────────────────────────────────

def test_t7_skip_is_not_suppression():
    """Profile mining_exploration_sector; FCF=None (no capex row); NI<0.

    Spec: suppressed contains exactly 1 record (net_income); FCF is absent
    entirely — not in flags, not in suppressed.
    """
    fd = _explorer_fd(fcf_none=True, oi_none=True)
    out = detect_flags(fd)

    sup_checks = [s["check"] for s in out["suppressed"]]
    assert sup_checks == ["net_income"], (
        f"expected [net_income] only, got {sup_checks}"
    )
    # FCF must not appear anywhere
    all_flag_details = [f["label"] for f in out["flags"]]
    assert "free_cash_flow" not in sup_checks or True  # already asserted above
    assert not any("free cash flow" in lbl.lower() for lbl in all_flag_details), (
        "FCF must not appear as a surviving flag either"
    )


# ── T8 — Healthy explorer ─────────────────────────────────────────────────────

def test_t8_healthy_explorer_clean():
    """Profile mining_exploration_sector; all metrics positive/healthy.

    Spec: CLEAN; suppressed=[].
    """
    fd  = _explorer_fd(all_positive=True)
    out = detect_flags(fd)

    assert out["flags"]           == []
    assert out["suppressed"]      == []
    assert out["signal_override"] is None
    assert out["sector_profile"]  == _MINING_PROFILE


# ── T9 — Unknown future profile string ────────────────────────────────────────

def test_t9_unknown_profile_default_behavior():
    """sector_profile='utilities_sector' is not in SECTOR_FLAG_RULES v1.

    Spec: operating-income red fires (default); sector_profile echoed;
    suppressed=[].
    """
    fd = {
        "mapping": {"meta": {"sector_profile": "utilities_sector"}},
        "income_statement": [
            _row("operating income", -3_000_000),
        ],
        "balance_sheet":       [],
        "cash_flow_statement": [],
    }
    out = detect_flags(fd)

    assert out["suppressed"]     == []
    assert out["sector_profile"] == "utilities_sector"
    assert out["red_count"]      >= 1

    labels = [f["label"] for f in out["flags"]]
    assert any("operating income" in lbl.lower() for lbl in labels), (
        "operating-income red must survive for unknown profile"
    )


# ── T10 — Determinism ─────────────────────────────────────────────────────────

def test_t10_determinism():
    """Two identical calls on the T1 fixture must produce byte-identical output."""
    fd  = _explorer_fd()
    r1  = detect_flags(fd)
    r2  = detect_flags(copy.deepcopy(fd))

    assert r1 == r2, "detect_flags must be deterministic"


# ── T11 — Backward-compat shape ───────────────────────────────────────────────

_PRE_EXISTING_KEYS = {"flags", "red_count", "yellow_count", "signal_override"}
_ADDITIVE_KEYS     = {"suppressed", "sector_profile"}


def _assert_backward_compat(out: dict) -> None:
    """All pre-existing keys present; only additive keys are new."""
    for key in _PRE_EXISTING_KEYS:
        assert key in out, f"pre-existing key '{key}' missing from output"
    assert isinstance(out["flags"],        list)
    assert isinstance(out["red_count"],    int)
    assert isinstance(out["yellow_count"], int)
    # signal_override: None | str
    assert out["signal_override"] is None or isinstance(out["signal_override"], str)
    for key in _ADDITIVE_KEYS:
        assert key in out, f"additive key '{key}' missing from output"


def test_t11_backward_compat_t4():
    """T4 (Allied REIT): pre-existing keys unchanged; two additive keys present."""
    fd = {
        "mapping": {"meta": {"sector_profile": "reit_sector"}},
        "income_statement": [
            _row("operating income", 2_340_000),
            _row("interest expense", -1_000_000),
        ],
        "net_income": -1_327_532_000,
        "balance_sheet": [
            _row("total current assets",      530_000),
            _row("total current liabilities", 1_000_000),
        ],
        "cash_flow_statement": [],
    }
    _assert_backward_compat(detect_flags(fd))


def test_t11_backward_compat_t5():
    """T5 (TD bank): pre-existing keys unchanged; two additive keys present."""
    fd = {
        "mapping": {"meta": {"sector_profile": "financial_sector"}},
        "income_statement": [_row("operating income", 10_000_000)],
        "net_income":          8_000_000,
        "balance_sheet":       [],
        "cash_flow_statement": [],
    }
    _assert_backward_compat(detect_flags(fd))


def test_t11_backward_compat_t6():
    """T6 (EDGAR, no mapping): pre-existing keys unchanged; additive keys present."""
    fd = {
        "income_statement": [
            _row("revenue",      100_000),
            _row("gross profit",  12_000),
        ],
        "balance_sheet":       [],
        "cash_flow_statement": [],
    }
    _assert_backward_compat(detect_flags(fd))


# ── Extra: _resolve_sector_profile edge cases ─────────────────────────────────

def test_resolve_profile_no_mapping_key():
    assert _resolve_sector_profile({}) is None


def test_resolve_profile_mapping_is_none():
    assert _resolve_sector_profile({"mapping": None}) is None


def test_resolve_profile_no_meta():
    assert _resolve_sector_profile({"mapping": {}}) is None


def test_resolve_profile_meta_is_none():
    assert _resolve_sector_profile({"mapping": {"meta": None}}) is None


def test_resolve_profile_sector_profile_is_none():
    assert _resolve_sector_profile({"mapping": {"meta": {"sector_profile": None}}}) is None


def test_resolve_profile_returns_string():
    fd = {"mapping": {"meta": {"sector_profile": "mining_exploration_sector"}}}
    assert _resolve_sector_profile(fd) == "mining_exploration_sector"


# ── Structural: SECTOR_FLAG_RULES table integrity ─────────────────────────────

def test_sector_flag_rules_structure():
    """SECTOR_FLAG_RULES must have exactly the three v1 suppressed checks."""
    rules = SECTOR_FLAG_RULES.get("mining_exploration_sector", {})
    assert set(rules) == {"operating_income", "net_income", "free_cash_flow"}
    for check_id, rule in rules.items():
        assert rule["action"]      == "suppress",               check_id
        assert rule["reason_code"] == "sector_expected_shape",  check_id
        assert rule["rationale"],                                check_id
