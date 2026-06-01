import os
import platform

import requests
import urllib3


FMP_API_KEY = os.environ.get("FMP_API_KEY", "").strip()


def _make_session():
    session = requests.Session()
    session.trust_env = False
    if platform.system() == "Windows":
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        session.verify = False
    return session


def _latest_annual_entry(data):
    if not isinstance(data, list) or not data:
        return None
    annual = [
        item for item in data
        if isinstance(item, dict) and str(item.get("period") or "").upper() == "FY"
    ]
    return (annual or data)[0] if isinstance((annual or data)[0], dict) else None


def _ratio(numerator, denominator):
    try:
        if numerator is None or not denominator:
            return None
        return float(numerator) / float(denominator)
    except Exception:
        return None


def get_company_profile(ticker):
    """Get company profile - price, market cap, beta, volume."""
    session = _make_session()
    try:
        url = f"https://financialmodelingprep.com/stable/profile?symbol={ticker}&apikey={FMP_API_KEY}"
        response = session.get(url, timeout=10)
        print(f"Company Profile Status: {response.status_code}, Body: {response.text[:300]}")
        if response.status_code != 200:
            return None
        data = response.json()
        if isinstance(data, list) and data:
            return data[0]
        return None
    except Exception as e:
        print(f"Exception: {e}")
        return None


def get_earnings_calendar(ticker, limit=8):
    """Get earnings history with EPS and revenue actuals vs estimates."""
    session = _make_session()
    try:
        url = (
            "https://financialmodelingprep.com/stable/earnings-calendar"
            f"?symbol={ticker}&limit={limit}&apikey={FMP_API_KEY}"
        )
        response = session.get(url, timeout=10)
        print(f"Earnings Calendar Status: {response.status_code}, Body: {response.text[:300]}")
        if response.status_code != 200:
            return []
        data = response.json()
        if not isinstance(data, list):
            return []
        symbol = (ticker or "").upper()
        results = []
        for item in data:
            if not isinstance(item, dict) or item.get("symbol") != symbol:
                continue
            results.append({
                "date": item.get("date"),
                "epsActual": item.get("epsActual"),
                "epsEstimated": item.get("epsEstimated"),
                "revenueActual": item.get("revenueActual"),
                "revenueEstimated": item.get("revenueEstimated"),
            })
            if len(results) >= limit:
                break
        return results
    except Exception as e:
        print(f"Exception: {e}")
        return []


def get_income_statement(ticker, limit=4):
    session = _make_session()
    try:
        url = f"https://financialmodelingprep.com/stable/income-statement?symbol={ticker}&limit={limit}&apikey={FMP_API_KEY}"
        response = session.get(url, timeout=10)
        print(f"Income Statement Status: {response.status_code}, Body: {response.text[:300]}")
        if response.status_code != 200:
            return None
        latest = _latest_annual_entry(response.json())
        if not latest:
            return None
        revenue = latest.get("revenue")
        gross_profit = latest.get("grossProfit")
        operating_income = latest.get("operatingIncome")
        net_income = latest.get("netIncome")
        return {
            "revenue": revenue,
            "grossProfit": gross_profit,
            "operatingIncome": operating_income,
            "netIncome": net_income,
            "ebitda": latest.get("ebitda"),
            "grossProfitRatio": latest.get("grossProfitRatio") or _ratio(gross_profit, revenue),
            "operatingIncomeRatio": latest.get("operatingIncomeRatio") or _ratio(operating_income, revenue),
            "netIncomeRatio": latest.get("netIncomeRatio") or _ratio(net_income, revenue),
            "fiscalYear": latest.get("fiscalYear"),
        }
    except Exception as e:
        print(f"Exception: {e}")
        return None


def get_balance_sheet(ticker, limit=4):
    session = _make_session()
    try:
        url = f"https://financialmodelingprep.com/stable/balance-sheet-statement?symbol={ticker}&limit={limit}&apikey={FMP_API_KEY}"
        response = session.get(url, timeout=10)
        print(f"Balance Sheet Status: {response.status_code}, Body: {response.text[:300]}")
        if response.status_code != 200:
            return None
        latest = _latest_annual_entry(response.json())
        if not latest:
            return None
        return {
            "cashAndCashEquivalents": latest.get("cashAndCashEquivalents"),
            "totalCurrentAssets": latest.get("totalCurrentAssets"),
            "totalAssets": latest.get("totalAssets"),
            "totalCurrentLiabilities": latest.get("totalCurrentLiabilities"),
            "totalDebt": latest.get("totalDebt"),
            "totalStockholdersEquity": latest.get("totalStockholdersEquity"),
            "fiscalYear": latest.get("fiscalYear"),
        }
    except Exception as e:
        print(f"Exception: {e}")
        return None


def get_cash_flow(ticker, limit=4):
    session = _make_session()
    try:
        url = f"https://financialmodelingprep.com/stable/cash-flow-statement?symbol={ticker}&limit={limit}&apikey={FMP_API_KEY}"
        response = session.get(url, timeout=10)
        print(f"Cash Flow Status: {response.status_code}, Body: {response.text[:300]}")
        if response.status_code != 200:
            return None
        latest = _latest_annual_entry(response.json())
        if not latest:
            return None
        return {
            "operatingCashFlow": latest.get("operatingCashFlow"),
            "capitalExpenditure": latest.get("capitalExpenditure"),
            "freeCashFlow": latest.get("freeCashFlow"),
            "dividendsPaid": latest.get("dividendsPaid") or latest.get("netDividendsPaid") or latest.get("commonDividendsPaid"),
            "fiscalYear": latest.get("fiscalYear"),
        }
    except Exception as e:
        print(f"Exception: {e}")
        return None


if __name__ == "__main__":
    import json

    print("Testing FMP API...")
    income_statement = get_income_statement("NVDA")
    print("Income Statement:", json.dumps(income_statement, indent=2) if income_statement else "None")
    balance_sheet = get_balance_sheet("NVDA")
    print("Balance Sheet:", json.dumps(balance_sheet, indent=2) if balance_sheet else "None")
    cash_flow = get_cash_flow("NVDA")
    print("Cash Flow:", json.dumps(cash_flow, indent=2) if cash_flow else "None")
