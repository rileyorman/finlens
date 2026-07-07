import os
import platform

import requests
import urllib3


FISCAL_AI_KEY = os.environ.get("FISCAL_AI_KEY", "").strip()


def _company_key(ticker, exchange="NASDAQ"):
    """Build the fiscal.ai companyKey: EXCHANGE_SYMBOL with the bare symbol.

    fiscal.ai's catalog keys TSX names on the bare symbol (TSX_RY), not the
    yfinance-style suffixed form: TSX_RY.TO returns 404 "data not yet
    available" while TSX_RY resolves (403 plan-gated on the free tier).
    Verified live 2026-07-07 against /v2/company/logo. Suffixed tickers are
    what the app carries everywhere (yfinance convention), so the strip
    happens here at the boundary — callers keep passing tickers as-is.
    """
    symbol = str(ticker or "").strip().upper()
    if symbol.endswith(".TO") or symbol.endswith(".V"):
        symbol = symbol.rsplit(".", 1)[0]
    return f"{exchange}_{symbol}"


def _make_session():
    session = requests.Session()
    session.trust_env = False
    if platform.system() == "Windows":
        # Avast/corporate SSL inspection workaround - Windows only
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        session.verify = False
    return session


def _get_json(url):
    session = _make_session()
    response = session.get(url, timeout=10)
    if response.status_code == 200:
        return response.json()
    return None


def _test_url(label, url):
    try:
        session = _make_session()
        session.get(url, timeout=10)
    except Exception as e:
        print(f"{label}: Exception: {e}")


def get_company_profile(ticker, exchange="NASDAQ"):
    try:
        api_key = FISCAL_AI_KEY
        if not api_key:
            return None

        company_key = _company_key(ticker, exchange)
        url = (
            "https://api.fiscal.ai/v1/company/profile"
            f"?companyKey={company_key}&apiKey={api_key}"
        )
        return _get_json(url)
    except Exception as e:
        print(f"Exception: {e}")
        return None


def get_shares_outstanding(ticker, exchange="NASDAQ"):
    try:
        api_key = FISCAL_AI_KEY
        if not api_key:
            return None

        company_key = _company_key(ticker, exchange)
        url = (
            "https://api.fiscal.ai/v1/company/shares-outstanding"
            f"?companyKey={company_key}&apiKey={api_key}"
        )
        session = _make_session()
        response = session.get(url, timeout=10)
        if response.status_code != 200:
            return None

        data = response.json()
        if not isinstance(data, list) or not data:
            return None

        latest = max(data, key=lambda row: row.get("date") or "")
        shares = latest.get("totalSharesOutstanding")
        if not isinstance(shares, (int, float)):
            return None

        share_classes = latest.get("shareClasses") or []
        main_class = next(
            (row for row in share_classes if row.get("isMainShareClass")),
            share_classes[0] if share_classes else {},
        )
        return {
            "date": latest.get("date"),
            "shares_outstanding": shares,
            "share_class": main_class.get("shareClass"),
        }
    except Exception as e:
        print(f"Exception: {e}")
        return None


def get_company_logo(ticker, exchange="NASDAQ"):
    try:
        api_key = FISCAL_AI_KEY
        if not api_key:
            return None

        company_key = _company_key(ticker, exchange)
        session = _make_session()
        urls = [
            (
                "https://api.fiscal.ai/v2/company/logo"
                f"?companyKey={company_key}&apiKey={api_key}&variant=icon"
            ),
            (
                "https://api.fiscal.ai/v2/company/logo"
                f"?companyKey={company_key}&apiKey={api_key}"
            ),
        ]
        for url in urls:
            response = session.get(url, timeout=10)
            if response.status_code == 200 and response.content:
                return response.content
        return None
    except Exception:
        return None


def get_earnings_calendar(ticker, exchange="NASDAQ"):
    try:
        api_key = FISCAL_AI_KEY
        if not api_key:
            return None

        company_key = _company_key(ticker, exchange)
        session = _make_session()
        urls = [
            (
                "https://api.fiscal.ai/v1/company/earnings-calendar"
                f"?companyKey={company_key}&apiKey={api_key}"
            ),
            (
                "https://api.fiscal.ai/v2/company/earnings-calendar"
                f"?companyKey={company_key}&apiKey={api_key}"
            ),
        ]
        for url in urls:
            response = session.get(url, timeout=10)
            if response.status_code == 200:
                return response.json()
        return None
    except Exception as e:
        print(f"Exception: {e}")
        return None


def get_company_news(ticker, exchange="NASDAQ", limit=5):
    try:
        api_key = FISCAL_AI_KEY
        if not api_key:
            return []

        company_key = _company_key(ticker, exchange)
        url = (
            "https://api.fiscal.ai/v1/company/news"
            f"?companyKey={company_key}&apiKey={api_key}&limit={limit}"
        )
        data = _get_json(url)
        if not isinstance(data, list):
            return []

        news_items = []
        for item in data:
            if not isinstance(item, dict):
                continue
            title = item.get("title") or ""
            url = item.get("sourceUrl") or item.get("url") or ""
            if not title or not url:
                continue
            news_items.append({
                "title": title,
                "date": item.get("date") or item.get("collectedAt") or "",
                "url": url,
                "category": item.get("eventType") or item.get("category") or "",
                "summary": item.get("summary") or item.get("description") or "",
            })
        return news_items[:limit]
    except Exception:
        return []


def get_company_filings(ticker, exchange="NASDAQ", limit=5):
    try:
        api_key = FISCAL_AI_KEY
        if not api_key:
            return []

        company_key = _company_key(ticker, exchange)
        url = (
            "https://api.fiscal.ai/v2/company/filings"
            f"?companyKey={company_key}&apiKey={api_key}&limit={limit}"
        )
        session = _make_session()
        response = session.get(url, timeout=10)
        if response.status_code != 200:
            return []

        data = response.json()
        if not isinstance(data, list):
            return []

        filings = []
        for item in data:
            if not isinstance(item, dict):
                continue
            filing_type = (
                item.get("type")
                or item.get("form")
                or item.get("formType")
                or item.get("filingType")
                or item.get("secFormType")
                or ""
            )
            date = item.get("date") or item.get("filingDate") or item.get("filedAt") or ""
            description = (
                item.get("description")
                or item.get("title")
                or item.get("documentType")
                or filing_type
            )
            filing_url = (
                item.get("url")
                or item.get("sourceUrl")
                or item.get("filingUrl")
                or item.get("pdfUrl")
                or ""
            )
            if not filing_type and not description:
                continue
            filings.append({
                "type": filing_type,
                "date": date,
                "description": description,
                "url": filing_url,
            })
        return filings[:limit]
    except Exception as e:
        print(f"Exception: {e}")
        return []


def get_income_statement(ticker, exchange="NASDAQ"):
    """Get income statement"""
    try:
        api_key = FISCAL_AI_KEY
        if not api_key:
            return None

        company_key = _company_key(ticker, exchange)
        url = (
            "https://api.fiscal.ai/v1/company/income-statement"
            f"?companyKey={company_key}&apiKey={api_key}"
        )
        return _get_json(url)
    except Exception as e:
        print(f"Exception: {e}")
        return None


def get_balance_sheet(ticker, exchange="NASDAQ"):
    """Get balance sheet"""
    try:
        api_key = FISCAL_AI_KEY
        if not api_key:
            return None

        company_key = _company_key(ticker, exchange)
        url = (
            "https://api.fiscal.ai/v1/company/balance-sheet"
            f"?companyKey={company_key}&apiKey={api_key}"
        )
        return _get_json(url)
    except Exception as e:
        print(f"Exception: {e}")
        return None


def get_cash_flow(ticker, exchange="NASDAQ"):
    """Get cash flow statement"""
    try:
        api_key = FISCAL_AI_KEY
        if not api_key:
            return None

        company_key = _company_key(ticker, exchange)
        url = (
            "https://api.fiscal.ai/v1/company/cash-flow-statement"
            f"?companyKey={company_key}&apiKey={api_key}"
        )
        return _get_json(url)
    except Exception as e:
        print(f"Exception: {e}")
        return None


def get_ratios(ticker, exchange="NASDAQ"):
    """Get P/E, EV/EBITDA, margins, etc"""
    try:
        api_key = FISCAL_AI_KEY
        if not api_key:
            return None

        company_key = _company_key(ticker, exchange)
        url = (
            "https://api.fiscal.ai/v1/company/ratios"
            f"?companyKey={company_key}&apiKey={api_key}"
        )
        return _get_json(url)
    except Exception as e:
        print(f"Exception: {e}")
        return None


def get_ratios_with_values(ticker, exchange="NASDAQ"):
    """Return selected most recent Fiscal AI ratio values."""
    ratio_id_map = {
        "pe_ratio": "ratio_price_to_earnings",
        "ev_ebitda": "ratio_ev_to_ebitda",
        "price_to_book": "ratio_price_to_book",
        "price_to_sales": "ratio_price_to_sales",
        "ev_revenue": "ratio_ev_to_sales",
        "gross_margin": "ratio_gross_profit_margin",
        "operating_margin": "ratio_operating_margin",
        "net_margin": "ratio_net_profit_margin",
    }
    try:
        api_key = FISCAL_AI_KEY
        if not api_key:
            return {}

        company_key = _company_key(ticker, exchange)
        url = (
            "https://api.fiscal.ai/v1/company/ratios"
            f"?companyKey={company_key}&apiKey={api_key}&includeValues=true&period=latest"
        )
        data = _get_json(url)
        if not isinstance(data, dict):
            return {}

        periods = data.get("data") or []
        if not periods:
            return {}

        latest = periods[0]
        values = latest.get("metricValues") or latest.get("metricsValues") or {}
        result = {}
        for friendly_id, fiscal_id in ratio_id_map.items():
            value = values.get(fiscal_id)
            if isinstance(value, (int, float)):
                result[friendly_id] = value
        return result
    except Exception:
        return {}


def get_segments_and_kpis(ticker, exchange="NASDAQ"):
    """Get business segment revenue breakdown"""
    try:
        api_key = FISCAL_AI_KEY
        if not api_key:
            return None

        company_key = _company_key(ticker, exchange)
        url = (
            "https://api.fiscal.ai/v2/company/segments-and-kpis"
            f"?companyKey={company_key}&apiKey={api_key}"
        )
        return _get_json(url)
    except Exception as e:
        print(f"Exception: {e}")
        return None


def get_segments_with_values(ticker, exchange="NASDAQ"):
    """Return most recent annual business segment values from Fiscal AI."""
    try:
        api_key = FISCAL_AI_KEY
        if not api_key:
            return []

        metadata = get_segments_and_kpis(ticker, exchange)
        if not isinstance(metadata, dict):
            return []

        metrics_by_id = {
            metric.get("metricId"): metric
            for metric in metadata.get("metrics", [])
            if metric.get("metricId")
        }
        revenue_segment_ids = []
        for group in metadata.get("segmentGroups", []) or []:
            if group.get("title") != "Revenue":
                continue
            for metric in group.get("metrics", []) or []:
                metric_id = metric.get("metricId")
                if metric_id and not metric.get("isRollup"):
                    revenue_segment_ids.append(metric_id)

        segment_metrics = {}
        for metric_id in revenue_segment_ids:
            metric = metrics_by_id.get(metric_id) or {}
            if metric.get("metricType") == "Segment" and metric.get("metricName"):
                segment_metrics[metric_id] = metric["metricName"]

        if not segment_metrics:
            segment_metrics = {
                metric.get("metricId"): metric.get("metricName")
                for metric in metadata.get("metrics", [])
                if metric.get("metricType") == "Segment"
                and metric.get("metricId")
                and metric.get("metricName")
            }
        if not segment_metrics:
            return []

        company_key = _company_key(ticker, exchange)
        url = (
            "https://api.fiscal.ai/v2/company/segments-and-kpis"
            f"?companyKey={company_key}&apiKey={api_key}&period=annual&includeValues=true"
        )
        data = _get_json(url)
        if not isinstance(data, dict):
            return []

        annual_periods = [
            row for row in data.get("data", [])
            if isinstance(row, dict) and row.get("periodType") == "Annual"
        ]
        if not annual_periods:
            return []

        latest = max(
            annual_periods,
            key=lambda row: (
                row.get("fiscalYear") or 0,
                row.get("reportDate") or "",
            ),
        )
        metric_values = latest.get("metricsValues") or latest.get("metricValues") or {}
        fiscal_year = latest.get("fiscalYear")
        period = f"FY{fiscal_year}" if fiscal_year else latest.get("periodId", "")

        segments = []
        for metric_id, name in segment_metrics.items():
            value = metric_values.get(metric_id)
            if isinstance(value, (int, float)):
                segments.append({"name": name, "value": value, "period": period})

        return sorted(segments, key=lambda row: row["value"], reverse=True)
    except Exception:
        return []


def get_adjusted_metrics(ticker, exchange="NASDAQ"):
    """Get adjusted EPS, Revenue, EBITDA, FCF"""
    try:
        api_key = FISCAL_AI_KEY
        if not api_key:
            return None

        company_key = _company_key(ticker, exchange)
        url = (
            "https://api.fiscal.ai/v1/company/adjusted-metrics"
            f"?companyKey={company_key}&apiKey={api_key}"
        )
        return _get_json(url)
    except Exception as e:
        print(f"Exception: {e}")
        return None


def get_adjusted_metrics_with_values(ticker, exchange="NASDAQ"):
    """Return selected most recent annual adjusted metrics from Fiscal AI."""
    metric_map = {
        "Adjusted Revenue": "adjusted_revenue",
        "Adjusted Gross Profit": "adjusted_gross_profit",
        "Adjusted EBITDA": "adjusted_ebitda",
        "Adjusted EBIT": "adjusted_ebit",
        "Adjusted Net Income": "adjusted_net_income",
        "Adjusted EPS": "adjusted_eps",
        "Adjusted FCF": "adjusted_free_cash_flow",
        "Adjusted Gross Margin": "adjusted_gross_margin",
        "Adjusted Operating Margin": "adjusted_ebit_margin",
        "Adjusted Net Margin": "adjusted_net_income_margin",
    }
    try:
        api_key = FISCAL_AI_KEY
        if not api_key:
            return {}

        company_key = _company_key(ticker, exchange)
        url = (
            "https://api.fiscal.ai/v1/company/adjusted-metrics"
            f"?companyKey={company_key}&apiKey={api_key}&includeValues=true&period=annual"
        )
        data = _get_json(url)
        if not isinstance(data, dict):
            return {}

        annual_periods = [
            row for row in data.get("data", [])
            if isinstance(row, dict) and row.get("periodType") == "Annual"
        ]
        if not annual_periods:
            return {}

        latest = max(
            annual_periods,
            key=lambda row: (
                row.get("fiscalYear") or 0,
                row.get("reportDate") or "",
            ),
        )
        metric_values = latest.get("metricValues") or latest.get("metricsValues") or {}

        result = {}
        for label, metric_id in metric_map.items():
            metric_value = metric_values.get(metric_id)
            value = metric_value.get("value") if isinstance(metric_value, dict) else metric_value
            if isinstance(value, (int, float)):
                result[label] = value
        return result
    except Exception:
        return {}


if __name__ == "__main__":
    _api_key = FISCAL_AI_KEY
    _company_key = "NASDAQ_NVDA"
    print("Alternative Financial Statement URLs")
    _test_url(
        "Test 1",
        f"https://api.fiscal.ai/v1/company/standardized-financials?companyKey={_company_key}&apiKey={_api_key}",
    )
    _test_url(
        "Test 2",
        f"https://api.fiscal.ai/v1/company/financials/income-statement?companyKey={_company_key}&apiKey={_api_key}",
    )
    _test_url(
        "Test 3",
        f"https://api.fiscal.ai/v1/company/financial-statements?companyKey={_company_key}&apiKey={_api_key}",
    )
    _test_url(
        "Test 4",
        f"https://api.fiscal.ai/v2/company/financials?companyKey={_company_key}&apiKey={_api_key}",
    )
    _test_url(
        "Test 5",
        f"https://api.fiscal.ai/v1/financials?companyKey={_company_key}&apiKey={_api_key}",
    )
    print("Income Statement")
    get_income_statement("NVDA", "NASDAQ")
    print("Balance Sheet")
    get_balance_sheet("NVDA", "NASDAQ")
    print("Cash Flow")
    get_cash_flow("NVDA", "NASDAQ")
    print("Ratios")
    get_ratios("NVDA", "NASDAQ")
    print("Segments and KPIs")
    get_segments_and_kpis("NVDA", "NASDAQ")
    print("Adjusted Metrics")
    get_adjusted_metrics("NVDA", "NASDAQ")
