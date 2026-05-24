"""Red Flag Detector — deterministic ratio-based distress screening.

Scores _calc_summary_metrics() output against defined thresholds and returns
flags ('red' | 'yellow') plus an optional signal override.

Override rules:
  2+ red flags    → DECLINE
  1 red flag      → INVESTIGATE
  3+ yellow flags → INVESTIGATE
  Otherwise       → None
"""

from modules.excel_exporter import _calc_summary_metrics, _lookup


_OI_KEYWORDS = [
    "income (loss) from operations", "income from operations",
    "operating income", "operating profit", "operating earnings",
    "earnings from operations", "operating loss", "loss from operations",
]


def detect_flags(financial_data: dict) -> dict:
    """Run threshold checks against financial_data.

    Returns:
        flags:           list of {"label", "detail", "severity": "red"|"yellow"}
        red_count:       int
        yellow_count:    int
        signal_override: "DECLINE" | "INVESTIGATE" | None
    """
    m       = _calc_summary_metrics(financial_data)
    is_rows = financial_data.get("income_statement", [])

    # Operating income is used inside _calc_summary_metrics but not returned
    oi_c = _lookup(is_rows, _OI_KEYWORDS, "value")

    flags = []

    def _red(label: str, detail: str) -> None:
        flags.append({"label": label, "detail": detail, "severity": "red"})

    def _yellow(label: str, detail: str) -> None:
        flags.append({"label": label, "detail": detail, "severity": "yellow"})

    # ── Revenue growth ────────────────────────────────────────────────────────
    yoy = m.get("yoy_rev")
    if yoy is not None:
        if yoy < -10.0:
            _red("Revenue declining sharply",
                 f"Revenue fell {yoy:.1f}% year-over-year.")
        elif yoy < 0.0:
            _yellow("Revenue declining",
                    f"Revenue fell {yoy:.1f}% year-over-year.")

    # ── Gross margin ──────────────────────────────────────────────────────────
    gp_margin = m.get("gp_margin")
    if gp_margin is not None:
        if gp_margin < 0.0:
            _red("Negative gross margin",
                 f"Gross margin is {gp_margin:.1f}% — cost of sales exceeds revenue.")
        elif gp_margin < 20.0:
            _yellow("Thin gross margin",
                    f"Gross margin is {gp_margin:.1f}%, leaving limited room for operating expenses.")

    # ── Operating income ──────────────────────────────────────────────────────
    if oi_c is not None and oi_c < 0:
        _red("Negative operating income",
             f"Operating income is {oi_c:,.0f} — core operations are loss-making.")

    # ── Net income ────────────────────────────────────────────────────────────
    ni_c = m.get("ni_c")
    if ni_c is not None and ni_c < 0:
        _yellow("Negative net income",
                f"Net income is {ni_c:,.0f}.")

    # ── Free cash flow ────────────────────────────────────────────────────────
    fcf_c = m.get("fcf_c")
    if fcf_c is not None and fcf_c < 0:
        _yellow("Negative free cash flow",
                f"FCF is {fcf_c:,.0f} — cash outflows exceed operating cash generation.")

    # ── Liquidity ─────────────────────────────────────────────────────────────
    cr = m.get("current_ratio")
    if cr is not None:
        if cr < 1.0:
            _red("Poor liquidity",
                 f"Current ratio is {cr:.2f}x — current liabilities exceed current assets.")
        elif cr < 1.5:
            _yellow("Tight liquidity",
                    f"Current ratio is {cr:.2f}x — limited short-term buffer.")

    # ── Leverage ──────────────────────────────────────────────────────────────
    nd_ebitda = m.get("nd_ebitda")
    if nd_ebitda is not None:
        if nd_ebitda > 5.0:
            _red("High leverage",
                 f"Net Debt / EBITDA is {nd_ebitda:.2f}x — elevated debt burden.")
        elif nd_ebitda > 3.0:
            _yellow("Elevated leverage",
                    f"Net Debt / EBITDA is {nd_ebitda:.2f}x — above comfortable range.")

    # ── Interest coverage ─────────────────────────────────────────────────────
    ic = m.get("int_cover")
    if ic is not None:
        if ic < 1.5:
            _red("Weak interest coverage",
                 f"Interest coverage is {ic:.2f}x — earnings barely cover interest expense.")
        elif ic < 3.0:
            _yellow("Low interest coverage",
                    f"Interest coverage is {ic:.2f}x — limited cushion above debt service.")

    # ── Signal override ───────────────────────────────────────────────────────
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
    }
