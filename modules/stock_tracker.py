import os

import yfinance as yf
import pandas as pd

from config import YFINANCE_CACHE_DIR
from modules.market_data import _to_yfinance_ticker


NYSE_TICKERS = {
    "ABBV", "ABT", "ACN", "AMD", "AMT", "AXP", "BA", "BAC", "BABA", "BRK-B",
    "CAT", "CRM", "CVX", "DE", "DIS", "F", "GE", "GM", "GS", "HD", "IBM",
    "JNJ", "JPM", "KO", "LLY", "MA", "MCD", "MRK", "NKE", "NVO", "ORCL",
    "PFE", "PG", "PLTR", "SHOP", "SNOW", "T", "TSM", "UBER", "UNH", "V",
    "VZ", "WFC", "WMT", "XOM",
}


def _fiscal_ai_exchange_for_ticker(ticker: str) -> str:
    symbol = (ticker or "").strip().upper()
    if symbol.endswith(".TO") or symbol.endswith(".V"):
        return "TSX"
    return "NYSE" if symbol in NYSE_TICKERS else "NASDAQ"


def _fmt_segment_value(value):
    if value is None:
        return ""
    value = float(value)
    if abs(value) >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.2f}T"
    if abs(value) >= 1_000_000_000:
        return f"${value / 1_000_000_000:.1f}B"
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    return f"${value:,.0f}"


def render_business_segments_card(ticker: str, exchange: str | None = None) -> bool:
    """Render the Fiscal AI business segments card. Returns True if rendered."""
    try:
        import plotly.graph_objects as go
        import streamlit as st

        from modules.fiscal_ai import get_segments_with_values

        symbol = (ticker or "").strip().upper()
        if not symbol:
            return False

        exchange = exchange or _fiscal_ai_exchange_for_ticker(symbol)
        segments = get_segments_with_values(symbol, exchange)
        if not segments:
            return False

        chart_segments = sorted(segments, key=lambda row: row["value"])
        labels = [row["name"] for row in chart_segments]
        values = [row["value"] for row in chart_segments]
        text = [_fmt_segment_value(row["value"]) for row in chart_segments]

        st.markdown("#### Business Segments")
        fig = go.Figure(
            go.Bar(
                x=values,
                y=labels,
                orientation="h",
                text=text,
                textposition="auto",
                marker=dict(color="#378ADD"),
                hovertemplate="%{y}<br>%{text}<extra></extra>",
            )
        )
        fig.update_layout(
            height=max(260, 42 * len(chart_segments)),
            margin=dict(l=8, r=8, t=8, b=8),
            xaxis_title=None,
            yaxis_title=None,
            showlegend=False,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#CBD5E1"),
        )
        fig.update_xaxes(showgrid=True, gridcolor="rgba(148,163,184,0.18)")
        fig.update_yaxes(showgrid=False)
        st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})
        period = segments[0].get("period")
        period_text = f" · {period}" if period else ""
        st.markdown(
            f'<div style="color:#94A3B8;font-size:12px;margin-top:-0.5rem">'
            f'Source: Fiscal AI{period_text}</div>',
            unsafe_allow_html=True,
        )
        return True
    except Exception:
        return False


def get_fiscal_ai_ratios(ticker, exchange="NASDAQ") -> dict:
    try:
        from modules.fiscal_ai import get_ratios_with_values

        ratios = get_ratios_with_values(ticker, exchange)
        if not ratios:
            return {}

        friendly_map = {
            "P/E Ratio": "pe_ratio",
            "EV/EBITDA": "ev_ebitda",
            "P/B Ratio": "price_to_book",
            "P/S Ratio": "price_to_sales",
            "Gross Margin": "gross_margin",
            "Operating Margin": "operating_margin",
            "Net Margin": "net_margin",
        }
        return {
            label: ratios[key]
            for label, key in friendly_map.items()
            if key in ratios
        }
    except Exception:
        return {}


def _calc_rsi(hist, period=14):
    delta = hist["Close"].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def _next_earnings_date(t):
    """Return next upcoming earnings date as YYYY-MM-DD string, or None."""
    # Try earnings_dates DataFrame (yfinance >= 0.2)
    try:
        ed = t.earnings_dates
        if ed is not None and not ed.empty and "Reported EPS" in ed.columns:
            future = ed[ed["Reported EPS"].isna()]
            if not future.empty:
                return str(future.index.min())[:10]
    except Exception:
        pass
    # Fallback: calendar
    try:
        cal = t.calendar
        if cal is None:
            return None
        if isinstance(cal, pd.DataFrame) and not cal.empty:
            if "Earnings Date" in cal.index:
                raw = cal.loc["Earnings Date"].iloc[0]
                return str(raw)[:10]
        elif isinstance(cal, dict):
            ed_val = cal.get("Earnings Date")
            if ed_val:
                if isinstance(ed_val, list) and ed_val:
                    return str(ed_val[0])[:10]
                return str(ed_val)[:10]
    except Exception:
        pass
    return None


def _earnings_surprise(t):
    """Return last quarter EPS surprise as a percentage, or None."""
    try:
        ed = t.earnings_dates
        if ed is None or ed.empty:
            return None
        if "Reported EPS" not in ed.columns or "EPS Estimate" not in ed.columns:
            return None
        past = ed[ed["Reported EPS"].notna()].copy()
        if past.empty:
            return None
        last = past.iloc[0]
        est = last.get("EPS Estimate")
        act = last.get("Reported EPS")
        if est is not None and act is not None and float(est) != 0:
            return float((act - est) / abs(est) * 100)
    except Exception:
        pass
    return None


def get_stock_data(ticker: str) -> dict:
    """Fetch comprehensive stock data for a ticker via yfinance.

    Returns a nested dict with sections: price, momentum, analyst, earnings,
    valuation, company, and error. All fields default to None if unavailable.
    Never raises exceptions.
    """
    result = {
        "price": {
            "current": None, "previous_close": None, "day_change_pct": None,
            "week_52_high": None, "week_52_low": None,
            "pct_from_52_high": None, "pct_from_52_low": None,
        },
        "momentum": {
            "ma_50": None, "ma_200": None,
            "above_50ma": None, "above_200ma": None,
            "golden_cross": None, "rsi_14": None,
        },
        "analyst": {
            "recommendation": None, "target_price": None,
            "num_analysts": None, "upside_pct": None,
        },
        "earnings": {
            "next_earnings_date": None, "eps_estimate": None,
            "eps_actual_last": None, "revenue_estimate": None,
            "earnings_surprise_pct": None,
        },
        "valuation": {
            "pe_trailing": None, "pe_forward": None, "peg_ratio": None,
            "ev_ebitda": None, "price_to_book": None, "price_to_sales": None,
        },
        "company": {
            "name": None, "sector": None, "industry": None,
            "market_cap": None, "description": None,
        },
        "hist":  None,
        "error": None,
    }

    try:
        YFINANCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        os.environ["YFINANCE_CACHE_DIR"] = str(YFINANCE_CACHE_DIR)

        t    = yf.Ticker(_to_yfinance_ticker(ticker))
        info = t.info
        hist = t.history(period="1y")

        current = info.get("currentPrice") or info.get("regularMarketPrice")
        if not current:
            result["error"] = (
                f"No data found for '{ticker}'. "
                "Verify the symbol is correct and try again."
            )
            return result

        # --- Price ---
        prev  = info.get("previousClose") or info.get("regularMarketPreviousClose")
        hi52  = info.get("fiftyTwoWeekHigh")
        lo52  = info.get("fiftyTwoWeekLow")

        result["price"] = {
            "current":          current,
            "previous_close":   prev,
            "day_change_pct":   round((current - prev) / prev * 100, 2)
                                if prev and prev > 0 else None,
            "week_52_high":     hi52,
            "week_52_low":      lo52,
            "pct_from_52_high": round((current - hi52) / hi52 * 100, 2)
                                if hi52 and hi52 > 0 else None,
            "pct_from_52_low":  round((current - lo52) / lo52 * 100, 2)
                                if lo52 and lo52 > 0 else None,
        }

        # --- Momentum ---
        ma_50 = ma_200 = above_50 = above_200 = golden = rsi_14 = None
        if not hist.empty and len(hist) >= 15:
            closes = hist["Close"]
            if len(closes) >= 50:
                ma_50    = round(float(closes.rolling(50).mean().iloc[-1]), 2)
                above_50 = bool(current > ma_50)
            if len(closes) >= 200:
                ma_200    = round(float(closes.rolling(200).mean().iloc[-1]), 2)
                above_200 = bool(current > ma_200)
            if ma_50 and ma_200:
                golden = bool(ma_50 > ma_200)
            try:
                rsi_14 = round(float(_calc_rsi(hist)), 2)
            except Exception:
                pass

        result["momentum"] = {
            "ma_50": ma_50, "ma_200": ma_200,
            "above_50ma": above_50, "above_200ma": above_200,
            "golden_cross": golden, "rsi_14": rsi_14,
        }

        # --- Analyst ---
        target = info.get("targetMeanPrice")
        result["analyst"] = {
            "recommendation": info.get("recommendationKey"),
            "target_price":   target,
            "num_analysts":   info.get("numberOfAnalystOpinions"),
            "upside_pct":     round((target - current) / current * 100, 1)
                              if target and current > 0 else None,
        }

        # --- Earnings ---
        result["earnings"] = {
            "next_earnings_date":    _next_earnings_date(t),
            "eps_estimate":          info.get("forwardEps"),
            "eps_actual_last":       info.get("trailingEps"),
            "revenue_estimate":      info.get("totalRevenue"),
            "earnings_surprise_pct": _earnings_surprise(t),
        }

        # --- Valuation ---
        result["valuation"] = {
            "pe_trailing":    info.get("trailingPE"),
            "pe_forward":     info.get("forwardPE"),
            "peg_ratio":      info.get("pegRatio"),
            "ev_ebitda":      info.get("enterpriseToEbitda"),
            "price_to_book":  info.get("priceToBook"),
            "price_to_sales": info.get("priceToSalesTrailing12Months"),
        }

        # --- Company ---
        raw_mc   = info.get("marketCap")
        desc_raw = info.get("longBusinessSummary") or ""
        result["company"] = {
            "name":        info.get("longName") or info.get("shortName"),
            "sector":      info.get("sector"),
            "industry":    info.get("industry"),
            "market_cap":  round(raw_mc / 1_000_000, 2) if raw_mc else None,
            "description": desc_raw[:300] + ("..." if len(desc_raw) > 300 else ""),
        }

        result["hist"] = hist

    except Exception as e:
        result["error"] = f"Failed to fetch data for '{ticker}': {e}"

    return result


# ---------------------------------------------------------------------------
# Sector quote-basis notes (2026-07-13, from the docs/research/ coverage-gap
# reports). The five-times-confirmed finding: the headline number the market
# quotes per sector is a company-defined non-GAAP measure living OUTSIDE the
# statements (funds flow, DCF payout, FFO/AFFO, AISC, adjusted EPS/ROTE) —
# so the tracker's generalist ratios (P/E, PEG, statements-FCF) mislead by
# omission on those sectors. These notes DISCLOSE the quote basis; they never
# serve non-GAAP values (that is the Arc 3 packs' job, CB-036-gated).
# Classification is deliberately conservative: unknown sector → None → no note.
# ---------------------------------------------------------------------------

_SECTOR_QUOTE_NOTES = {
    "og_upstream": {
        "valuation": (
            "E&Ps are quoted on EV/DACF, P/CF, and NAV rather than P/E — "
            "earnings are commodity-price-driven and P/E misleads here."
        ),
        "cashflow": (
            "O&G issuers quote FUNDS FLOW (issuer-defined non-GAAP, excludes "
            "working-capital swings), not statements-basis FCF — the two "
            "differ materially in single quarters."
        ),
    },
    "og_midstream": {
        "valuation": (
            "Midstream names are quoted on EV/EBITDA and distributable-cash-"
            "flow (DCF) payout, not P/E."
        ),
        "cashflow": (
            "Distributable cash flow is the quoted measure — issuer-defined "
            "non-GAAP, reconciled in the MD&A, not the statements-basis FCF "
            "shown here."
        ),
    },
    "og_downstream": {
        "valuation": (
            "Refiners are quoted on EV/EBITDA against crack-spread cycles; "
            "single-period P/E is cycle-distorted."
        ),
        "cashflow": None,
    },
    "reit": {
        "valuation": (
            "REITs are quoted on P/FFO and P/AFFO — net-income-based P/E "
            "misleads (depreciation dominates). NAREIT and REALPAC define "
            "FFO differently; AFFO varies by issuer."
        ),
        "cashflow": (
            "FFO/AFFO are the quoted cash measures — issuer-defined non-GAAP "
            "from the MD&A, not statements-basis FCF."
        ),
    },
    "bank": {
        "valuation": (
            "Banks are quoted on P/B, P/TBV, ROE/ROTE, and adjusted "
            "(\"cash\") EPS — EV-based multiples are not meaningful for "
            "banks (deposits are not debt in the EV sense)."
        ),
        "cashflow": None,
    },
    "miner": {
        "valuation": (
            "Miners are quoted on AISC margins, EV/oz of reserves, and "
            "P/NAV; cash-cost basis varies by issuer (by-product vs "
            "co-product), so cross-miner comparisons need the definitions."
        ),
        "cashflow": (
            "AISC is the quoted cost measure — issuer-defined non-GAAP from "
            "the MD&A, not derivable from the statements."
        ),
    },
}

_MINER_INDUSTRY_TOKENS = ("gold", "silver", "copper", "mining", "metals", "uranium", "coal")


def sector_quote_note(sector, industry) -> dict | None:
    """The quote-basis note for a yfinance (sector, industry) pair, or None.

    Returns {"valuation": str, "cashflow": str | None}. Conservative:
    anything unrecognized gets no note rather than a guessed one.
    """
    sec = (sector or "").strip().lower()
    ind = (industry or "").strip().lower()
    if not sec and not ind:
        return None
    if "oil & gas midstream" in ind:
        return _SECTOR_QUOTE_NOTES["og_midstream"]
    if "oil & gas refining" in ind:
        return _SECTOR_QUOTE_NOTES["og_downstream"]
    if "oil & gas" in ind and ("e&p" in ind or "integrated" in ind or "drilling" in ind):
        return _SECTOR_QUOTE_NOTES["og_upstream"]
    if ind.startswith("reit") or "reit -" in ind or "reit—" in ind:
        return _SECTOR_QUOTE_NOTES["reit"]
    if "banks" in ind:
        return _SECTOR_QUOTE_NOTES["bank"]
    if sec == "basic materials" and any(tok in ind for tok in _MINER_INDUSTRY_TOKENS):
        return _SECTOR_QUOTE_NOTES["miner"]
    return None
