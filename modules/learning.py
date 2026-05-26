LEARNING_CONTENT = {
    "signal": {
        "what": "A composite rating summarising the overall investment quality of the company based on financial health, valuation, and momentum.",
        "equation": None,
        "why": "Gives a fast top-line read before diving into the details — Pass, Investigate, or Decline.",
        "columbia": "Reflects the multi-factor screening frameworks covered in quantitative equity analysis."
    },
    "distress_score": {
        "what": "A measure of financial distress risk based on the Altman Z-Score model.",
        "equation": "Z = 1.2x(Working Capital/Assets) + 1.4x(Retained Earnings/Assets) + 3.3x(EBIT/Assets) + 0.6x(Equity/Debt) + 1.0x(Revenue/Assets)",
        "why": "Predicts probability of bankruptcy. Z > 3.0 = safe zone, Z < 1.8 = distress zone.",
        "columbia": "Altman Z-Score is a foundational model in credit risk and financial distress prediction."
    },
    "quality_score": {
        "what": "A 0-100 score measuring earnings quality, balance sheet strength, and cash flow consistency.",
        "equation": None,
        "why": "Higher quality companies tend to outperform over time with lower drawdown risk.",
        "columbia": "Quality factor investing is a core concept in factor-based portfolio construction."
    },
    "red_flags": {
        "what": "Automated checks for accounting irregularities, leverage concerns, and earnings quality issues.",
        "equation": None,
        "why": "Red flags often precede earnings misses or financial restatements.",
        "columbia": "Forensic accounting and earnings quality analysis are key tools in fundamental research."
    },
    "mda_sentiment": {
        "what": "AI-powered sentiment analysis of the Management Discussion & Analysis section of the filing.",
        "equation": None,
        "why": "Management tone often leads reported financials — cautious language can signal deterioration before numbers show it.",
        "columbia": "Natural language processing applied to financial disclosures is a growing area of quantitative research."
    },
    "scenario_simulator": {
        "what": "A what-if model that adjusts key financial assumptions and shows the impact on distress score and profitability.",
        "equation": "Scenario EBIT = (Base Revenue x (1 + Revenue Growth)) x Gross Margin % - Base OpEx x (1 + OpEx Growth)",
        "why": "Stress testing assumptions is essential for understanding downside risk and margin of safety.",
        "columbia": "Scenario analysis is a core tool in DCF modelling and credit risk assessment."
    },
    "bull_bear": {
        "what": "AI-generated bull and bear cases summarising the key upside and downside arguments for the investment.",
        "equation": None,
        "why": "Forces structured thinking about both sides of the trade before forming a view.",
        "columbia": "Balanced investment thesis construction is fundamental to equity research and portfolio management."
    },
    "lynch_category": {
        "what": "Peter Lynch's company classification system: Slow Grower, Stalwart, Fast Grower, Cyclical, Turnaround, or Asset Play.",
        "equation": None,
        "why": "Each category implies a different valuation approach and holding strategy.",
        "columbia": "Lynch's framework from One Up on Wall Street remains a widely taught qualitative classification tool."
    },
}


def info_tooltip(key: str) -> str:
    """Return a formatted markdown string explaining the given analysis section."""
    entry = LEARNING_CONTENT.get(key)
    if not entry:
        return f"No methodology entry found for '{key}'."
    lines = [
        f"**What it is:** {entry['what']}",
        f"**Why it matters:** {entry['why']}",
        f"**Columbia connection:** {entry['columbia']}",
    ]
    if entry.get("equation"):
        lines.insert(1, f"**Equation:** {entry['equation']}")
    return "\n\n".join(lines)
