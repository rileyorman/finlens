import platform
import ssl

import anthropic
import httpx

from modules.excel_exporter import _calc_summary_metrics, _lookup, _lookup2

DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def _make_client(api_key: str):
    if platform.system() == "Windows":
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.load_default_certs()
        ssl_ctx.check_hostname = True
        return anthropic.Anthropic(
            api_key=api_key,
            http_client=httpx.Client(verify=ssl_ctx, trust_env=False),
        )
    return anthropic.Anthropic(api_key=api_key)


def _altman_distress(
    rev, ebit, total_assets,
    working_capital=None, retained_earnings=None,
    equity=None, total_debt=None,
) -> float | None:
    """Altman Z-Score proxy scaled to 0-100 where higher = more distress.

    Z >= 3.0 → 0 (safe), Z <= 1.0 → 100 (distress). Linear in between.
    Missing inputs default to conservative neutral values rather than failing.
    """
    if not total_assets:
        return None

    x1 = (working_capital / total_assets) if working_capital is not None else 0.0
    x2 = (retained_earnings / total_assets) if retained_earnings is not None else 0.0
    x3 = (ebit / total_assets) if ebit is not None else 0.0
    x4 = (equity / total_debt) if (equity is not None and total_debt and total_debt != 0) else 0.5
    x5 = (rev / total_assets) if rev is not None else 0.0

    z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5

    if z >= 3.0:
        return 0.0
    if z <= 1.0:
        return 100.0
    return round((3.0 - z) / 2.0 * 100, 1)


def _extract_base(financial_data: dict) -> dict:
    """Pull all base values needed for scenario math."""
    metrics = _calc_summary_metrics(financial_data)

    is_rows = financial_data.get("income_statement", [])
    bs_rows = financial_data.get("balance_sheet", [])

    # Operating income (EBIT proxy) — not in _calc_summary_metrics return dict
    oi_c = _lookup(is_rows, [
        "income (loss) from operations", "income from operations",
        "operating income", "operating profit", "operating earnings",
        "earnings from operations",
    ], "value")

    # Interest expense
    int_raw = _lookup(is_rows, ["interest expense"], "value")
    int_exp_c = abs(int_raw) if int_raw is not None else None

    # Balance sheet extras for Altman
    ta_c  = _lookup2(bs_rows, ["total assets"], "value")
    ca_c  = _lookup2(bs_rows, ["total current assets"], "value")
    cl_c  = _lookup2(bs_rows, ["total current liabilities"], "value")
    eq_c  = _lookup2(bs_rows, [
        "total shareholders' equity", "total stockholders' equity",
        "shareholders' equity", "total owner", "total equity",
    ], "value")
    re_c  = _lookup(bs_rows, [
        "retained earnings", "accumulated deficit",
        "retained earnings (accumulated deficit)",
    ], "value")
    ltd_c = _lookup(bs_rows, [
        "long-term debt", "long-term notes payable",
        "long-term borrowings", "senior notes", "term loan",
    ], "value") or 0
    std_c = _lookup(bs_rows, [
        "short-term debt", "current portion of long-term debt",
        "current maturities of long-term debt", "commercial paper",
    ], "value") or 0
    total_debt = ltd_c + std_c if (ltd_c or std_c) else None

    wc_c = (ca_c - cl_c) if (ca_c is not None and cl_c is not None) else None

    return {
        "rev_c":        metrics.get("rev_c"),
        "gp_c":         metrics.get("gp_c"),
        "gp_margin":    metrics.get("gp_margin"),
        "ni_c":         metrics.get("ni_c"),
        "oi_c":         oi_c,
        "int_exp_c":    int_exp_c,
        "total_assets": ta_c,
        "working_capital": wc_c,
        "retained_earnings": re_c,
        "equity":       eq_c,
        "total_debt":   total_debt,
    }


_NARRATIVE_PROMPT = """You are a concise financial analyst. A user has run a what-if scenario on a company's financials.

Base metrics:
{base_summary}

Scenario inputs applied:
{scenario_inputs}

Scenario output:
{scenario_output}

Write 2-3 sentences (maximum) explaining what this scenario means for the investment thesis — be specific about the key driver of change and whether it improves or worsens the risk/reward profile. No headers, no bullet points, plain prose only."""


def run_scenario(
    base_financials: dict,
    scenario_inputs: dict,
    api_key: str,
    model: str = DEFAULT_MODEL,
) -> dict:
    """Run a what-if scenario on base_financials. Always returns dict, never raises."""
    result = {
        "scenario_revenue":       None,
        "scenario_gross_profit":  None,
        "scenario_ebit":          None,
        "scenario_net_income":    None,
        "base_distress_score":    None,
        "scenario_distress_score": None,
        "distress_delta":         None,
        "implied_pe":             None,
        "narrative":              None,
        "error":                  None,
    }

    try:
        base = _extract_base(base_financials)

        rev   = base["rev_c"]
        gp    = base["gp_c"]
        oi    = base["oi_c"]
        ni    = base["ni_c"]
        int_e = base["int_exp_c"]

        rev_growth_pct         = float(scenario_inputs.get("revenue_growth_pct",      0))
        gross_margin_pct       = float(scenario_inputs.get("gross_margin_pct",        50))
        opex_growth_pct        = float(scenario_inputs.get("opex_growth_pct",         0))
        interest_rate_change   = float(scenario_inputs.get("interest_rate_change_bps", 0))

        # Scenario revenue
        s_rev = (rev * (1 + rev_growth_pct / 100)) if rev is not None else None

        # Scenario gross profit
        s_gp = (s_rev * (gross_margin_pct / 100)) if s_rev is not None else None

        # Base opex = gross_profit - operating_income (SG&A + R&D, below gross profit line)
        # Falls back to 0 if either is missing so scenario still runs
        base_opex = ((gp or 0) - (oi or 0)) if (gp is not None or oi is not None) else None
        s_opex    = (base_opex * (1 + opex_growth_pct / 100)) if base_opex is not None else 0

        # Scenario EBIT
        s_ebit = ((s_gp or 0) - (s_opex or 0)) if s_gp is not None else None

        # Scenario interest expense
        s_int = (int_e * (1 + interest_rate_change / 10000)) if int_e is not None else (int_e or 0)

        # Scenario net income (simplified — no tax adjustment)
        s_ni = ((s_ebit or 0) - (s_int or 0)) if s_ebit is not None else None

        result["scenario_revenue"]      = round(s_rev, 2) if s_rev is not None else None
        result["scenario_gross_profit"] = round(s_gp, 2)  if s_gp  is not None else None
        result["scenario_ebit"]         = round(s_ebit, 2) if s_ebit is not None else None
        result["scenario_net_income"]   = round(s_ni, 2)   if s_ni  is not None else None

        # Distress scores
        ta = base["total_assets"]
        wc = base["working_capital"]
        re = base["retained_earnings"]
        eq = base["equity"]
        td = base["total_debt"]

        base_ds = _altman_distress(rev, oi, ta, wc, re, eq, td)
        scen_ds = _altman_distress(s_rev, s_ebit, ta, wc, re, eq, td)

        result["base_distress_score"]     = base_ds
        result["scenario_distress_score"] = scen_ds
        result["distress_delta"] = (
            round(scen_ds - base_ds, 1)
            if (base_ds is not None and scen_ds is not None) else None
        )

        # Narrative call
        client = _make_client(api_key)

        def _fmt(v, suffix=""):
            return f"{v:,.0f}{suffix}" if v is not None else "N/A"

        base_summary = (
            f"Revenue: {_fmt(rev)}, Gross Profit: {_fmt(gp)}, "
            f"EBIT: {_fmt(oi)}, Net Income: {_fmt(ni)}"
        )
        scen_summary = (
            f"Revenue: {_fmt(s_rev)}, Gross Profit: {_fmt(s_gp)}, "
            f"EBIT: {_fmt(s_ebit)}, Net Income: {_fmt(s_ni)}"
        )
        inputs_summary = (
            f"Revenue growth: {rev_growth_pct:+.1f}%, "
            f"Gross margin: {gross_margin_pct:.1f}%, "
            f"OpEx growth: {opex_growth_pct:+.1f}%, "
            f"Interest rate change: {interest_rate_change:+.0f}bps"
        )

        response = client.messages.create(
            model      = model,
            max_tokens = 256,
            messages   = [{
                "role": "user",
                "content": _NARRATIVE_PROMPT.format(
                    base_summary    = base_summary,
                    scenario_inputs = inputs_summary,
                    scenario_output = scen_summary,
                ),
            }],
        )
        result["narrative"] = response.content[0].text.strip()

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result
