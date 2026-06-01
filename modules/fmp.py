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


def _latest_statement_entry(data):
    if not isinstance(data, list) or not data:
        return None
    return data[0] if isinstance(data[0], dict) else None


def _ratio(numerator, denominator):
    try:
        if numerator is None or not denominator:
            return None
        return float(numerator) / float(denominator)
    except Exception:
        return None


def _get_statement_list(endpoint, ticker, period="annual", limit=1, label="Statement"):
    session = _make_session()
    try:
        url = (
            f"https://financialmodelingprep.com/stable/{endpoint}"
            f"?symbol={ticker}&period={period}&limit={limit}&apikey={FMP_API_KEY}"
        )
        response = session.get(url, timeout=10)
        print(f"{label} Status: {response.status_code}, Body: {response.text[:300]}")
        if response.status_code != 200:
            return None
        data = response.json()
        return data if isinstance(data, list) else None
    except Exception as e:
        print(f"Exception: {e}")
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


def get_income_statement(ticker, period="annual", limit=1):
    try:
        latest = _latest_statement_entry(
            _get_statement_list("income-statement", ticker, period, limit, "Income Statement")
        )
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


def get_balance_sheet(ticker, period="annual", limit=1):
    try:
        latest = _latest_statement_entry(
            _get_statement_list("balance-sheet-statement", ticker, period, limit, "Balance Sheet")
        )
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


def get_cash_flow(ticker, period="annual", limit=1):
    try:
        latest = _latest_statement_entry(
            _get_statement_list("cash-flow-statement", ticker, period, limit, "Cash Flow")
        )
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


def _row(line_item, value, value_prior=None, row_type="data"):
    return {
        "line_item": line_item,
        "value": value,
        "value_prior": value_prior,
        "row_type": row_type,
    }


def _second_statement_entry(data):
    if not isinstance(data, list):
        return None
    rows = [item for item in data if isinstance(item, dict)]
    return rows[1] if len(rows) > 1 else None


def _period_label(item, selected_period="annual"):
    fiscal_year = item.get("fiscalYear")
    period = str(item.get("period") or "").upper()
    if selected_period == "quarter" and period and period != "FY":
        return f"{period} {fiscal_year}" if fiscal_year else period
    return f"FY{fiscal_year}" if fiscal_year else "Current"


def build_financial_data_from_fmp(ticker, period="annual", limit=1):
    """Build app-compatible financial_data from FMP financial statement data."""
    try:
        ticker = (ticker or "").strip().upper()
        if not ticker:
            return None

        profile = get_company_profile(ticker) or {}
        income = get_income_statement(ticker, period, limit)
        balance = get_balance_sheet(ticker, period, limit)
        cashflow = get_cash_flow(ticker, period, limit)
        if not income or not balance or not cashflow:
            return None

        income_history = _get_statement_list("income-statement", ticker, period, limit, "Income Statement History")
        balance_history = _get_statement_list("balance-sheet-statement", ticker, period, limit, "Balance Sheet History")
        cashflow_history = _get_statement_list("cash-flow-statement", ticker, period, limit, "Cash Flow History")
        income_raw = _latest_statement_entry(income_history) or {}
        income_prior = _second_statement_entry(income_history) or {}
        balance_prior = _second_statement_entry(balance_history) or {}
        cashflow_prior = _second_statement_entry(cashflow_history) or {}

        current_assets = balance.get("totalCurrentAssets") or 0
        current_liabilities = balance.get("totalCurrentLiabilities") or 1
        current_ratio = _ratio(current_assets, current_liabilities)
        company_name = profile.get("companyName") or ticker
        fiscal_year = income.get("fiscalYear")
        fiscal_year_prior = income_prior.get("fiscalYear")
        period_label = _period_label(income_raw, period)

        period_history = []
        income_rows = income_history if isinstance(income_history, list) else []
        balance_rows = balance_history if isinstance(balance_history, list) else []
        cashflow_rows = cashflow_history if isinstance(cashflow_history, list) else []
        for idx, income_item in enumerate(income_rows):
            if not isinstance(income_item, dict):
                continue
            balance_item = balance_rows[idx] if idx < len(balance_rows) and isinstance(balance_rows[idx], dict) else {}
            cashflow_item = cashflow_rows[idx] if idx < len(cashflow_rows) and isinstance(cashflow_rows[idx], dict) else {}
            period_history.append({
                "label": _period_label(income_item, period),
                "revenue": income_item.get("revenue"),
                "gross_profit": income_item.get("grossProfit"),
                "net_income": income_item.get("netIncome"),
                "free_cash_flow": cashflow_item.get("freeCashFlow"),
                "total_debt": balance_item.get("totalDebt"),
                "cash": balance_item.get("cashAndCashEquivalents"),
            })

        financial_data = {
            "ticker": ticker,
            "company": company_name,
            "company_name": company_name,
            "period": period_label,
            "currency": profile.get("currency") or "USD",
            "scale": 1,
            "revenue": income.get("revenue"),
            "revenue_prior": income_prior.get("revenue"),
            "gross_profit": income.get("grossProfit"),
            "operating_income": income.get("operatingIncome"),
            "net_income": income.get("netIncome"),
            "ebitda": income.get("ebitda"),
            "total_assets": balance.get("totalAssets"),
            "total_debt": balance.get("totalDebt"),
            "cash": balance.get("cashAndCashEquivalents"),
            "equity": balance.get("totalStockholdersEquity"),
            "operating_cash_flow": cashflow.get("operatingCashFlow"),
            "capex": cashflow.get("capitalExpenditure"),
            "free_cash_flow": cashflow.get("freeCashFlow"),
            "current_ratio": current_ratio,
            "interest_expense": income_raw.get("interestExpense"),
            "rd_expense": income_raw.get("researchAndDevelopmentExpenses"),
            "gross_margin": income.get("grossProfitRatio"),
            "fiscal_year": period_label,
            "fiscal_year_prior": f"FY{fiscal_year_prior}" if fiscal_year_prior else "Prior",
            "fmp_period": period,
            "fmp_limit": limit,
            "period_history": period_history,
            "source": "fmp",
            "income_statement": [
                _row("Revenue", income.get("revenue"), income_prior.get("revenue"), "total"),
                _row("Cost of Revenue", income_raw.get("costOfRevenue"), income_prior.get("costOfRevenue")),
                _row("Gross Profit", income.get("grossProfit"), income_prior.get("grossProfit"), "subtotal"),
                _row("Research and Development Expenses", income_raw.get("researchAndDevelopmentExpenses"), income_prior.get("researchAndDevelopmentExpenses")),
                _row("Operating Income", income.get("operatingIncome"), income_prior.get("operatingIncome"), "subtotal"),
                _row("Interest Expense", income_raw.get("interestExpense"), income_prior.get("interestExpense")),
                _row("EBITDA", income.get("ebitda"), income_prior.get("ebitda")),
                _row("Net Income", income.get("netIncome"), income_prior.get("netIncome"), "total"),
            ],
            "balance_sheet": [
                _row("ASSETS", None, None, "section_header"),
                _row("Cash and Cash Equivalents", balance.get("cashAndCashEquivalents"), balance_prior.get("cashAndCashEquivalents")),
                _row("Total Current Assets", balance.get("totalCurrentAssets"), balance_prior.get("totalCurrentAssets"), "subtotal"),
                _row("Total Assets", balance.get("totalAssets"), balance_prior.get("totalAssets"), "total"),
                _row("LIABILITIES", None, None, "section_header"),
                _row("Total Current Liabilities", balance.get("totalCurrentLiabilities"), balance_prior.get("totalCurrentLiabilities"), "subtotal"),
                _row("Total Debt", balance.get("totalDebt"), balance_prior.get("totalDebt")),
                _row("SHAREHOLDERS' EQUITY", None, None, "section_header"),
                _row("Total Stockholders' Equity", balance.get("totalStockholdersEquity"), balance_prior.get("totalStockholdersEquity"), "total"),
            ],
            "cash_flow_statement": [
                _row("OPERATING ACTIVITIES", None, None, "section_header"),
                _row("Operating Cash Flow", cashflow.get("operatingCashFlow"), cashflow_prior.get("operatingCashFlow"), "subtotal"),
                _row("INVESTING ACTIVITIES", None, None, "section_header"),
                _row("Capital Expenditure", cashflow.get("capitalExpenditure"), cashflow_prior.get("capitalExpenditure")),
                _row("Free Cash Flow", cashflow.get("freeCashFlow"), cashflow_prior.get("freeCashFlow"), "total"),
                _row("FINANCING ACTIVITIES", None, None, "section_header"),
                _row("Dividends Paid", cashflow.get("dividendsPaid"), cashflow_prior.get("netDividendsPaid") or cashflow_prior.get("commonDividendsPaid")),
            ],
        }
        return financial_data
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
