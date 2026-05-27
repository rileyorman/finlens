from modules.excel_exporter import _calc_summary_metrics


def _find(rows, keywords):
    """Return the first value whose line_item contains any of the keywords (case-insensitive)."""
    for row in rows:
        name = (row.get("line_item") or "").lower().strip()
        for kw in keywords:
            if kw in name:
                v = row.get("value")
                return float(v) if v is not None else None
    return None


def _currency_scale(financial_data):
    cur = (financial_data.get("currency") or "").lower()
    if "billion" in cur:
        return 1_000_000_000
    if "million" in cur:
        return 1_000_000
    if "thousand" in cur:
        return 1_000
    return 1


def calculate_dcf(financial_data: dict, inputs: dict) -> dict:
    """Calculate intrinsic value per share using a multi-stage DCF model.

    inputs:
        wacc (float)                — discount rate in % (e.g. 10.0)
        terminal_growth_rate (float)— terminal growth in % (e.g. 3.0)
        forecast_period (int)       — 5 or 10 years
        revenue_growth_rate (float) — FCF growth rate in % (e.g. 15.0)
        shares_outstanding (float)  — shares in millions, or None
        current_price (float)       — current market price per share, or None

    Returns a result dict. All monetary values are in raw dollars. Never raises.
    """
    result = {
        "base_fcf":                 None,
        "pv_forecast":              None,
        "pv_terminal":              None,
        "enterprise_value":         None,
        "equity_value":             None,
        "intrinsic_value_per_share": None,
        "current_price":            inputs.get("current_price"),
        "margin_of_safety_pct":     None,
        "is_undervalued":           None,
        "forecast_table":           [],
        "error":                    None,
    }

    try:
        wacc      = inputs["wacc"] / 100
        tgr       = inputs["terminal_growth_rate"] / 100
        n         = int(inputs["forecast_period"])
        gr        = inputs["revenue_growth_rate"] / 100
        shares_m  = inputs.get("shares_outstanding")
        cur_price = inputs.get("current_price")

        if wacc <= tgr:
            result["error"] = "WACC must be greater than terminal growth rate."
            return result

        scale = _currency_scale(financial_data)

        # --- Base FCF (from reporting units → raw dollars) ---
        metrics = _calc_summary_metrics(financial_data)
        fcf_rep = metrics.get("fcf_c")

        if fcf_rep is None:
            result["error"] = (
                "FCF not available — ensure operating cash flow and capex "
                "are present in the filing."
            )
            return result

        fcf_raw = fcf_rep * scale

        if fcf_raw <= 0:
            result["error"] = (
                "FCF not available or negative — DCF not applicable "
                "for companies with negative free cash flow."
            )
            return result

        result["base_fcf"] = fcf_raw

        # --- Cash and debt for equity bridge (reporting units → raw dollars) ---
        bs_rows  = financial_data.get("balance_sheet", [])
        cash_rep = _find(bs_rows, ["cash and cash equivalents",
                                   "cash and equivalents",
                                   "cash, cash equivalents"])
        ltd_rep  = _find(bs_rows, ["long-term debt",
                                   "long-term notes payable",
                                   "long-term borrowings",
                                   "senior notes"])
        std_rep  = _find(bs_rows, ["short-term debt",
                                   "current portion of long-term debt",
                                   "current maturities of long-term debt"])

        cash_raw = (cash_rep or 0.0) * scale
        debt_raw = ((ltd_rep or 0.0) + (std_rep or 0.0)) * scale

        # --- Project and discount FCFs ---
        # pv_yr = FCF_year / (1 + wacc)^year  — exponent must increment each year.
        # When revenue_growth_rate == wacc the (1+g)^t terms cancel and every
        # discounted FCF equals base_fcf (mathematically correct but visually
        # misleading), so defaults are kept WACC > growth_rate to avoid this.
        forecast_table = []
        pv_sum = 0.0

        for yr in range(1, n + 1):
            fcf_yr          = fcf_raw * (1 + gr) ** yr
            discount_factor = (1 + wacc) ** yr          # grows with each year
            pv_yr           = fcf_yr / discount_factor
            pv_sum         += pv_yr
            forecast_table.append({
                "year":           yr,
                "fcf":            fcf_yr,
                "discounted_fcf": pv_yr,
            })

        # --- Terminal value (Gordon Growth Model) ---
        fcf_terminal = fcf_raw * ((1 + gr) ** n) * (1 + tgr)
        pv_terminal  = (fcf_terminal / (wacc - tgr)) / ((1 + wacc) ** n)

        # --- Enterprise → Equity → Per Share ---
        ev      = pv_sum + pv_terminal
        eq_val  = ev + cash_raw - debt_raw

        result["pv_forecast"]    = pv_sum
        result["pv_terminal"]    = pv_terminal
        result["enterprise_value"] = ev
        result["equity_value"]   = eq_val
        result["forecast_table"] = forecast_table

        if shares_m and shares_m > 0:
            iv = eq_val / (shares_m * 1_000_000)
            result["intrinsic_value_per_share"] = iv

            if cur_price and cur_price > 0 and iv > 0:
                mos = (iv - cur_price) / iv * 100
                result["margin_of_safety_pct"] = round(mos, 1)
                result["is_undervalued"]        = mos > 0

    except Exception as e:
        result["error"] = f"DCF calculation failed: {e}"

    return result
