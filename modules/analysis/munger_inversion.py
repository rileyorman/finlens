from __future__ import annotations

import json
import os
import re
from typing import Any

from config import ANALYSIS_MODEL
from modules.claude_analyzer import _cache_control, _make_client, _text_content


SYSTEM_PROMPT = """You are a value investor using Charlie Munger's inversion method.

Assume the investment has failed badly 3-5 years from now. Work backward from
the company's actual reported numbers to identify what most plausibly killed
the investment. Be specific, numerate, and conservative. Do not invent metrics
that were not supplied.
"""

USER_PROMPT_TEMPLATE = """Return ONLY valid JSON. No markdown fences, no preamble.

JSON shape:
{
  "thesis_killers": ["up to 3 short phrases"],
  "premortem_narrative": "It's YEAR_PLUS_4. This investment has lost significant value. Here's what happened...",
  "failure_modes": [
    {
      "mode": "specific failure mode",
      "severity": "high|medium|low",
      "grounding": "which real metric/number makes this plausible"
    }
  ],
  "margin_of_safety_note": "where downside protection is thin or absent, value-investor framing",
  "dcf_snapshot": null
}

Company context:
Ticker: __TICKER__
Sector: __SECTOR__

Real fundamentals and mapped filing metrics:
__FUNDAMENTALS_JSON__

DCF valuation snapshot:
__DCF_SNAPSHOT_JSON__

Instructions:
- Use the supplied real numbers as the evidence base.
- If a metric is missing, say that uncertainty weakens the margin-of-safety assessment.
- __DCF_INSTRUCTION__
- Focus on business failure, balance-sheet failure, capital allocation failure, cycle risk, or valuation fragility.
- thesis_killers must contain no more than 3 items.
- failure_modes severity must be one of: high, medium, low.
- Return the exact supplied dcf_snapshot object in the dcf_snapshot key, or null when none was supplied.
"""


def _api_key() -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not found")
    return api_key


def _strip_json_fences(raw: str) -> str:
    text = (raw or "").strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        parsed = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if parsed.is_integer():
        return int(parsed)
    return parsed


def _field_value(financial_data: dict, names: tuple[str, ...]) -> float | int | None:
    if not isinstance(financial_data, dict):
        return None
    for name in names:
        value = _number(financial_data.get(name))
        if value is not None:
            return value
    return None


def _mapped_value(mapping: dict, name: str) -> float | int | None:
    if not isinstance(mapping, dict):
        return None
    mapped = mapping.get("mapped") if isinstance(mapping.get("mapped"), dict) else mapping
    item = mapped.get(name) if isinstance(mapped, dict) else None
    if isinstance(item, dict):
        return _number(item.get("value"))
    return _number(item)


def _ratio(numerator: float | int | None, denominator: float | int | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def _compact_mapping(mapping: dict) -> dict:
    if not isinstance(mapping, dict):
        return {}
    mapped = mapping.get("mapped") if isinstance(mapping.get("mapped"), dict) else mapping
    if not isinstance(mapped, dict):
        return {}
    compact = {}
    for name, item in mapped.items():
        if isinstance(item, dict):
            compact[name] = {
                "value": item.get("value"),
                "source_label": item.get("source_label"),
            }
        else:
            compact[name] = item
    return compact


def _clean_dcf_snapshot(dcf_snapshot: dict | None) -> dict | None:
    if not isinstance(dcf_snapshot, dict):
        return None

    allowed = {
        "intrinsic_value_per_share",
        "current_price",
        "margin_of_safety_pct",
        "is_undervalued",
        "enterprise_value",
        "equity_value",
        "assumptions",
    }
    cleaned = {key: dcf_snapshot.get(key) for key in allowed if key in dcf_snapshot}

    assumptions = cleaned.get("assumptions")
    if isinstance(assumptions, dict):
        allowed_assumptions = {
            "wacc",
            "terminal_growth",
            "terminal_growth_rate",
            "revenue_growth",
            "revenue_growth_rate",
            "forecast_period",
        }
        cleaned["assumptions"] = {
            key: assumptions.get(key)
            for key in allowed_assumptions
            if key in assumptions
        }
    elif "assumptions" in cleaned:
        cleaned.pop("assumptions")

    return cleaned or None


def _has_real_dcf_valuation(dcf_snapshot: dict | None) -> bool:
    if not isinstance(dcf_snapshot, dict):
        return False
    return (
        dcf_snapshot.get("intrinsic_value_per_share") is not None
        and dcf_snapshot.get("margin_of_safety_pct") is not None
    )


def _dcf_instruction(dcf_snapshot: dict | None) -> str:
    if _has_real_dcf_valuation(dcf_snapshot):
        return (
            "A DCF valuation anchor is supplied. Incorporate the quantified margin of safety into "
            "the margin_of_safety_note: intrinsic value per share vs current price, the MoS %, and "
            "how the pre-mortem failure scenario could compress intrinsic value and erode that cushion."
        )
    return (
        "No usable DCF valuation anchor is supplied. Keep margin-of-safety reasoning qualitative "
        "and explicitly note the absence of a valuation anchor. Do not fabricate intrinsic value, "
        "price, or margin-of-safety percentages."
    )


def _fundamentals(financial_data: dict, mapping: dict) -> dict:
    revenue = _field_value(financial_data, ("revenue", "total_revenue"))
    if revenue is None:
        revenue = _mapped_value(mapping, "revenue") or _mapped_value(mapping, "total_revenue")

    net_income = _field_value(financial_data, ("net_income", "netIncome"))
    if net_income is None:
        net_income = _mapped_value(mapping, "net_income")

    gross_profit = _field_value(financial_data, ("gross_profit", "grossProfit"))
    if gross_profit is None:
        gross_profit = _mapped_value(mapping, "gross_profit")

    interest_expense = _field_value(financial_data, ("interest_expense", "interestExpense"))
    if interest_expense is None:
        interest_expense = _mapped_value(mapping, "interest_expense")

    operating_income = _field_value(financial_data, ("operating_income", "operatingIncome", "ebit"))
    if operating_income is None:
        operating_income = _mapped_value(mapping, "operating_income")

    total_debt = _field_value(financial_data, ("total_debt", "debt", "totalDebt"))
    cash = _field_value(financial_data, ("cash", "cash_and_equivalents", "cashAndEquivalents"))
    equity = _field_value(financial_data, ("total_equity", "shareholders_equity", "equity"))

    return {
        "currency": financial_data.get("currency") if isinstance(financial_data, dict) else None,
        "period": financial_data.get("period") if isinstance(financial_data, dict) else None,
        "fiscal_year_end": financial_data.get("fiscal_year_end") if isinstance(financial_data, dict) else None,
        "revenue": revenue,
        "gross_profit": gross_profit,
        "net_income": net_income,
        "operating_income": operating_income,
        "interest_expense": interest_expense,
        "total_debt": total_debt,
        "cash": cash,
        "shareholders_equity": equity,
        "net_margin": _ratio(net_income, revenue),
        "gross_margin": _ratio(gross_profit, revenue),
        "debt_to_equity": _ratio(total_debt, equity),
        "interest_coverage": _ratio(operating_income, abs(interest_expense) if interest_expense else None),
        "mapped_fields": _compact_mapping(mapping),
    }


def _build_prompt(
    financial_data: dict,
    ticker: str,
    sector: str | None,
    mapping: dict,
    dcf_snapshot: dict | None = None,
) -> str:
    payload = _fundamentals(financial_data or {}, mapping or {})
    cleaned_dcf = _clean_dcf_snapshot(dcf_snapshot)
    return (
        USER_PROMPT_TEMPLATE
        .replace("__TICKER__", str(ticker or ""))
        .replace("__SECTOR__", str(sector or "Unknown"))
        .replace("__FUNDAMENTALS_JSON__", json.dumps(payload, indent=2, default=str))
        .replace("__DCF_SNAPSHOT_JSON__", json.dumps(cleaned_dcf, indent=2, default=str))
        .replace("__DCF_INSTRUCTION__", _dcf_instruction(cleaned_dcf))
    )


def _parse_response(raw: str) -> dict:
    return json.loads(_strip_json_fences(raw))


def generate_inversion(financial_data, ticker, sector, mapping, dcf_snapshot=None) -> dict:
    try:
        cleaned_dcf = _clean_dcf_snapshot(dcf_snapshot)
        prompt = _build_prompt(financial_data or {}, ticker or "", sector, mapping or {}, cleaned_dcf)
        client = _make_client(_api_key())
        response = client.messages.create(
            model=ANALYSIS_MODEL,
            max_tokens=1600,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": _cache_control()}],
            messages=[{"role": "user", "content": prompt}],
        )
        parsed = _parse_response(_text_content(response))
        if not isinstance(parsed, dict):
            return {"error": "Munger inversion response was not a JSON object"}
        parsed["dcf_snapshot"] = cleaned_dcf
        return parsed
    except json.JSONDecodeError as exc:
        return {"error": f"Munger inversion response could not be parsed as JSON: {exc}"}
    except Exception as exc:
        return {"error": f"Munger inversion failed: {exc}"}
