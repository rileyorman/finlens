import os

import requests
import urllib3


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


FISCAL_AI_KEY = os.environ.get("FISCAL_AI_KEY", "").strip()


def _make_session():
    session = requests.Session()
    session.trust_env = False
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
        response = session.get(url, timeout=10)
        print(f"{label}: Status {response.status_code}, Body: {response.text[:200]}")
    except Exception as e:
        print(f"{label}: Exception: {e}")


def get_company_profile(ticker, exchange="NASDAQ"):
    try:
        api_key = FISCAL_AI_KEY
        if not api_key:
            return None

        company_key = f"{exchange}_{ticker}"
        url = (
            "https://api.fiscal.ai/v1/company/profile"
            f"?companyKey={company_key}&apiKey={api_key}"
        )
        return _get_json(url)
    except Exception as e:
        print(f"Exception: {e}")
        return None


def get_company_logo(ticker, exchange="NASDAQ"):
    try:
        api_key = FISCAL_AI_KEY
        if not api_key:
            return None

        company_key = f"{exchange}_{ticker}"
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


def get_income_statement(ticker, exchange="NASDAQ"):
    """Get income statement"""
    try:
        api_key = FISCAL_AI_KEY
        if not api_key:
            return None

        company_key = f"{exchange}_{ticker}"
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

        company_key = f"{exchange}_{ticker}"
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

        company_key = f"{exchange}_{ticker}"
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

        company_key = f"{exchange}_{ticker}"
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

        company_key = f"{exchange}_{ticker}"
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

        company_key = f"{exchange}_{ticker}"
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

        company_key = f"{exchange}_{ticker}"
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

        company_key = f"{exchange}_{ticker}"
        url = (
            "https://api.fiscal.ai/v1/company/adjusted-metrics"
            f"?companyKey={company_key}&apiKey={api_key}"
        )
        return _get_json(url)
    except Exception as e:
        print(f"Exception: {e}")
        return None


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
