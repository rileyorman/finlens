"""Red Flag Detector — deterministic ratio-based distress screening.

Scores _calc_summary_metrics() output against defined thresholds and returns
flags ('red' | 'yellow') plus an optional signal override.

Override rules:
  2+ red flags    → DECLINE
  1 red flag      → INVESTIGATE
  3+ yellow flags → INVESTIGATE
  Otherwise       → None

CB-019: sector-aware suppression is additive.  Suppressed flags never count
toward the override and are returned in a separate ``suppressed`` list.
"""

from modules.excel_exporter import _calc_summary_metrics, _lookup


_OI_KEYWORDS = [
    "income (loss) from operations", "income from operations",
    "operating income", "operating profit", "operating earnings",
    "earnings from operations", "operating loss", "loss from operations",
]

# ── CB-019: sector-aware flag suppression ─────────────────────────────────────

CHECK_IDS = (
    "revenue_growth_yoy", "gross_margin", "operating_income",
    "net_income", "free_cash_flow", "current_ratio",
    "net_debt_to_ebitda", "interest_coverage",
    "derivative_gains_concentration",
)

SECTOR_FLAG_RULES: dict[str, dict[str, dict]] = {
    "mining_exploration_sector": {
        "operating_income": {
            "action": "suppress",
            "reason_code": "sector_expected_shape",
            "rationale": (
                "Negative operating income is the expected shape of a "
                "pre-revenue explorer (NGEx cold-load finding #3, 2026-06-17)."
            ),
        },
        "net_income": {
            "action": "suppress",
            "reason_code": "sector_expected_shape",
            "rationale": (
                "Negative net income is the expected shape of a "
                "pre-revenue explorer (NGEx cold-load finding #3, 2026-06-17)."
            ),
        },
        "free_cash_flow": {
            "action": "suppress",
            "reason_code": "sector_expected_shape",
            "rationale": (
                "Negative free cash flow is the expected shape of a "
                "pre-revenue explorer (NGEx cold-load finding #3, 2026-06-17)."
            ),
        },
    },
}


def _resolve_sector_profile(financial_data: dict):
    """Safe nested read of financial_data['mapping']['meta']['sector_profile'].

    Returns None when ``mapping`` is absent entirely (EDGAR path), when
    ``meta`` is absent, or when the value itself is None.  Never raises
    KeyError.  A profile string with no entry in SECTOR_FLAG_RULES resolves
    normally but yields no rules — default behavior.
    """
    mapping = financial_data.get("mapping")
    if not isinstance(mapping, dict):
        return None
    meta = mapping.get("meta")
    if not isinstance(meta, dict):
        return None
    return meta.get("sector_profile")


def detect_flags(financial_data: dict) -> dict:
    """Run threshold checks against financial_data.

    Returns:
        flags:           list of {"label", "detail", "severity": "red"|"yellow"}
        red_count:       int
        yellow_count:    int
        signal_override: "DECLINE" | "INVESTIGATE" | None
        suppressed:      list of suppression records (always present; [] when none)
        sector_profile:  resolved sector profile string or None
    """
    m       = _calc_summary_metrics(financial_data)
    is_rows = financial_data.get("income_statement", [])

    # Operating income is used inside _calc_summary_metrics but not returned.
    oi_c = _lookup(is_rows, _OI_KEYWORDS, "value")

    # ── Step 1: evaluate all eight checks; collect raw fired flags ────────────
    # Each entry: {check_id, label, detail, severity, metric_value, threshold}
    _raw_flags: list[dict] = []

    def _fire(check_id: str, severity: str, label: str, detail: str,
              metric_value, threshold: str) -> None:
        _raw_flags.append({
            "check_id":     check_id,
            "label":        label,
            "detail":       detail,
            "severity":     severity,
            "metric_value": metric_value,
            "threshold":    threshold,
        })

    def _red(check_id, label, detail, metric_value, threshold):
        _fire(check_id, "red", label, detail, metric_value, threshold)

    def _yellow(check_id, label, detail, metric_value, threshold):
        _fire(check_id, "yellow", label, detail, metric_value, threshold)

    # ── Revenue growth ────────────────────────────────────────────────────────
    yoy = m.get("yoy_rev")
    if yoy is not None:
        if yoy < -10.0:
            _red("revenue_growth_yoy",
                 "Revenue declining sharply",
                 f"Revenue fell {yoy:.1f}% year-over-year.",
                 yoy, "< -10%")
        elif yoy < 0.0:
            _yellow("revenue_growth_yoy",
                    "Revenue declining",
                    f"Revenue fell {yoy:.1f}% year-over-year.",
                    yoy, "< 0%")

    # ── Gross margin ──────────────────────────────────────────────────────────
    gp_margin = m.get("gp_margin")
    if gp_margin is not None:
        if gp_margin < 0.0:
            _red("gross_margin",
                 "Negative gross margin",
                 f"Gross margin is {gp_margin:.1f}% — cost of sales exceeds revenue.",
                 gp_margin, "< 0%")
        elif gp_margin < 20.0:
            _yellow("gross_margin",
                    "Thin gross margin",
                    f"Gross margin is {gp_margin:.1f}%, leaving limited room for operating expenses.",
                    gp_margin, "< 20%")

    # ── Operating income ──────────────────────────────────────────────────────
    if oi_c is not None and oi_c < 0:
        _red("operating_income",
             "Negative operating income",
             f"Operating income is {oi_c:,.0f} — core operations are loss-making.",
             oi_c, "< 0")

    # ── Net income ────────────────────────────────────────────────────────────
    ni_c = m.get("ni_c")
    if ni_c is not None and ni_c < 0:
        _yellow("net_income",
                "Negative net income",
                f"Net income is {ni_c:,.0f}.",
                ni_c, "< 0")

    # ── Free cash flow ────────────────────────────────────────────────────────
    fcf_c = m.get("fcf_c")
    if fcf_c is not None and fcf_c < 0:
        _yellow("free_cash_flow",
                "Negative free cash flow",
                f"FCF is {fcf_c:,.0f} — cash outflows exceed operating cash generation.",
                fcf_c, "< 0")

    # ── Liquidity ─────────────────────────────────────────────────────────────
    cr = m.get("current_ratio")
    if cr is not None:
        if cr < 1.0:
            _red("current_ratio",
                 "Poor liquidity",
                 f"Current ratio is {cr:.2f}x — current liabilities exceed current assets.",
                 cr, "< 1.0")
        elif cr < 1.5:
            _yellow("current_ratio",
                    "Tight liquidity",
                    f"Current ratio is {cr:.2f}x — limited short-term buffer.",
                    cr, "< 1.5")

    # ── Leverage ──────────────────────────────────────────────────────────────
    nd_ebitda = m.get("nd_ebitda")
    if nd_ebitda is not None:
        if nd_ebitda > 5.0:
            _red("net_debt_to_ebitda",
                 "High leverage",
                 f"Net Debt / EBITDA is {nd_ebitda:.2f}x — elevated debt burden.",
                 nd_ebitda, "> 5.0")
        elif nd_ebitda > 3.0:
            _yellow("net_debt_to_ebitda",
                    "Elevated leverage",
                    f"Net Debt / EBITDA is {nd_ebitda:.2f}x — above comfortable range.",
                    nd_ebitda, "> 3.0")

    # ── Interest coverage ─────────────────────────────────────────────────────
    ic = m.get("int_cover")
    if ic is not None:
        if ic < 1.5:
            _red("interest_coverage",
                 "Weak interest coverage",
                 f"Interest coverage is {ic:.2f}x — earnings barely cover interest expense.",
                 ic, "< 1.5")
        elif ic < 3.0:
            _yellow("interest_coverage",
                    "Low interest coverage",
                    f"Interest coverage is {ic:.2f}x — limited cushion above debt service.",
                    ic, "< 3.0")

    # ── Derivative gains concentration (CB-034) ───────────────────────────────
    # Earnings-quality check: realized derivative gains as a share of pre-tax
    # earnings. Both inputs are mapped SEDAR canonical fields promoted to
    # top-level keys — the check honestly skips when either is unmapped.
    # Reference: Peyto FY2025, 248,737 / 535,822 = 46% (the cold-load drill
    # finding that motivated the hedging-book session).
    _rdg = financial_data.get("realized_derivative_gains")
    _ptx = financial_data.get("pretax_income")
    if isinstance(_rdg, (int, float)) and isinstance(_ptx, (int, float)) and _ptx > 0:
        _conc = abs(_rdg) / _ptx * 100.0
        if _conc >= 50.0:
            _red("derivative_gains_concentration",
                 "Earnings dominated by derivative gains",
                 f"Realized derivative gains are {_conc:.0f}% of pre-tax earnings — "
                 "run-rate profitability depends heavily on the hedge book, which "
                 "rolls off at market prices.",
                 _conc, ">= 50%")
        elif _conc >= 25.0:
            _yellow("derivative_gains_concentration",
                    "Significant derivative-gains reliance",
                    f"Realized derivative gains are {_conc:.0f}% of pre-tax earnings — "
                    "check what earnings look like once current hedges expire.",
                    _conc, ">= 25%")

    # ── Step 2: resolve sector profile ────────────────────────────────────────
    profile      = _resolve_sector_profile(financial_data)
    sector_rules = SECTOR_FLAG_RULES.get(profile, {}) if profile is not None else {}

    # ── Step 3: post-evaluation suppression pass ──────────────────────────────
    # A fired flag is either suppressed (moved to suppressed[]) or survives
    # into flags[].  skip ≠ suppress: a None metric never reaches this pass.
    flags: list[dict]      = []
    suppressed: list[dict] = []

    for raw in _raw_flags:
        rule = sector_rules.get(raw["check_id"])
        if rule is not None and rule.get("action") == "suppress":
            suppressed.append({
                "check":              raw["check_id"],
                "severity_suppressed": raw["severity"],
                "metric_value":       raw["metric_value"],
                "threshold":          raw["threshold"],
                "sector_profile":     profile,
                "action":             rule["action"],
                "reason_code":        rule["reason_code"],
                "rationale":          rule["rationale"],
            })
        else:
            flags.append({
                "label":    raw["label"],
                "detail":   raw["detail"],
                "severity": raw["severity"],
            })

    # ── Step 4: signal override from surviving flags only ─────────────────────
    red_count    = sum(1 for f in flags if f["severity"] == "red")
    yellow_count = sum(1 for f in flags if f["severity"] == "yellow")

    if red_count >= 2:
        signal_override = "DECLINE"
    elif red_count >= 1 or yellow_count >= 3:
        signal_override = "INVESTIGATE"
    else:
        signal_override = None

    return {
        "flags":           flags,
        "red_count":       red_count,
        "yellow_count":    yellow_count,
        "signal_override": signal_override,
        "suppressed":      suppressed,
        "sector_profile":  profile,
    }
