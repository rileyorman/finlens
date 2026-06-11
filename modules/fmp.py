import os
import platform

import requests
import urllib3


FMP_API_KEY = os.environ.get("FMP_API_KEY", "").strip()
FMP_FETCH_SUCCESS = "success"
FMP_PREMIUM_BLOCKED = "fmp_premium_blocked"
FMP_TRANSIENT_FAILURE = "transient_failure"


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


def _scale_money(value, scale=1_000_000):
    try:
        if value is None:
            return None
        return float(value) / scale
    except (TypeError, ValueError):
        return None


def _sum_values(*values):
    numeric = []
    for value in values:
        if value is None:
            continue
        try:
            numeric.append(float(value))
        except (TypeError, ValueError):
            continue
    if not numeric:
        return None
    return sum(numeric)


def _sum_field(rows, field):
    if not isinstance(rows, list):
        return None
    values = []
    for row in rows:
        if not isinstance(row, dict) or row.get(field) is None:
            continue
        try:
            values.append(float(row.get(field)))
        except (TypeError, ValueError):
            continue
    return sum(values) if values else None


def _get_statement_list_with_reason(endpoint, ticker, period="annual", limit=1, label="Statement"):
    session = _make_session()
    try:
        url = (
            f"https://financialmodelingprep.com/stable/{endpoint}"
            f"?symbol={ticker}&period={period}&limit={limit}&apikey={FMP_API_KEY}"
        )
        response = session.get(url, timeout=10)
        if response.status_code == 402:
            return None, FMP_PREMIUM_BLOCKED
        if response.status_code != 200:
            return None, FMP_TRANSIENT_FAILURE
        data = response.json()
        if isinstance(data, list) and data:
            return data, FMP_FETCH_SUCCESS
        return None, FMP_TRANSIENT_FAILURE
    except Exception as e:
        print(f"Exception: {e}")
        return None, FMP_TRANSIENT_FAILURE


def _get_statement_list(endpoint, ticker, period="annual", limit=1, label="Statement"):
    data, _reason = _get_statement_list_with_reason(endpoint, ticker, period, limit, label)
    return data


def get_company_profile(ticker):
    """Get company profile - price, market cap, beta, volume."""
    session = _make_session()
    try:
        url = f"https://financialmodelingprep.com/stable/profile?symbol={ticker}&apikey={FMP_API_KEY}"
        response = session.get(url, timeout=10)
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
        total_current_assets = latest.get("totalCurrentAssets")
        if total_current_assets is None:
            total_current_assets = latest.get("currentAssets")

        total_current_liabilities = latest.get("totalCurrentLiabilities")
        if total_current_liabilities is None:
            total_current_liabilities = latest.get("currentLiabilities")

        total_debt = latest.get("totalDebt")
        if total_debt is None:
            total_debt = _sum_values(latest.get("longTermDebt"), latest.get("shortTermDebt"))

        total_stockholders_equity = latest.get("totalStockholdersEquity")
        if total_stockholders_equity is None:
            total_stockholders_equity = latest.get("stockholdersEquity")

        return {
            "cashAndCashEquivalents": latest.get("cashAndCashEquivalents"),
            "totalCurrentAssets": total_current_assets,
            "totalAssets": latest.get("totalAssets"),
            "totalCurrentLiabilities": total_current_liabilities,
            "totalDebt": total_debt,
            "totalStockholdersEquity": total_stockholders_equity,
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


def _balance_field(item, key):
    if not isinstance(item, dict):
        return None
    if key == "totalCurrentAssets":
        return item.get("totalCurrentAssets") if item.get("totalCurrentAssets") is not None else item.get("currentAssets")
    if key == "totalCurrentLiabilities":
        value = item.get("totalCurrentLiabilities")
        return value if value is not None else item.get("currentLiabilities")
    if key == "totalDebt":
        value = item.get("totalDebt")
        return value if value is not None else _sum_values(item.get("longTermDebt"), item.get("shortTermDebt"))
    if key == "totalStockholdersEquity":
        value = item.get("totalStockholdersEquity")
        return value if value is not None else item.get("stockholdersEquity")
    return item.get(key)


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
        income_prior = _second_statement_entry(income_history) if limit > 1 else None
        balance_prior = _second_statement_entry(balance_history) if limit > 1 else None
        cashflow_prior = _second_statement_entry(cashflow_history) if limit > 1 else None
        income_prior = income_prior or {}
        balance_prior = balance_prior or {}
        cashflow_prior = cashflow_prior or {}
        is_ttm = period == "quarter" and limit == 4

        if is_ttm:
            revenue = _sum_field(income_history, "revenue")
            gross_profit = _sum_field(income_history, "grossProfit")
            operating_income = _sum_field(income_history, "operatingIncome")
            net_income = _sum_field(income_history, "netIncome")
            income = {
                "revenue": revenue,
                "grossProfit": gross_profit,
                "operatingIncome": operating_income,
                "netIncome": net_income,
                "ebitda": _sum_field(income_history, "ebitda"),
                "grossProfitRatio": _ratio(gross_profit, revenue),
                "operatingIncomeRatio": _ratio(operating_income, revenue),
                "netIncomeRatio": _ratio(net_income, revenue),
                "fiscalYear": "TTM",
            }
            cashflow = {
                "operatingCashFlow": _sum_field(cashflow_history, "operatingCashFlow"),
                "capitalExpenditure": _sum_field(cashflow_history, "capitalExpenditure"),
                "freeCashFlow": _sum_field(cashflow_history, "freeCashFlow"),
                "dividendsPaid": _sum_field(cashflow_history, "dividendsPaid"),
                "fiscalYear": "TTM",
            }
            income_raw = {
                "costOfRevenue": _sum_field(income_history, "costOfRevenue"),
                "researchAndDevelopmentExpenses": _sum_field(income_history, "researchAndDevelopmentExpenses"),
                "interestExpense": _sum_field(income_history, "interestExpense"),
            }
            income_prior = {}
            balance_prior = {}
            cashflow_prior = {}

        current_assets = balance.get("totalCurrentAssets") or 0
        current_liabilities = balance.get("totalCurrentLiabilities") or 1
        current_ratio = _ratio(current_assets, current_liabilities)
        company_name = profile.get("companyName") or ticker
        fiscal_year = income.get("fiscalYear")
        fiscal_year_prior = income_prior.get("fiscalYear")
        period_label = "TTM" if is_ttm else _period_label(income_raw, period)

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
                "revenue": _scale_money(income_item.get("revenue")),
                "gross_profit": _scale_money(income_item.get("grossProfit")),
                "net_income": _scale_money(income_item.get("netIncome")),
                "free_cash_flow": _scale_money(cashflow_item.get("freeCashFlow")),
                "total_debt": _scale_money(_balance_field(balance_item, "totalDebt")),
                "cash": _scale_money(balance_item.get("cashAndCashEquivalents")),
            })

        financial_data = {
            "ticker": ticker,
            "company": company_name,
            "company_name": company_name,
            "period": period_label,
            "currency": profile.get("currency") or "USD",
            "scale": 1_000_000,
            "revenue": _scale_money(income.get("revenue")),
            "revenue_prior": _scale_money(income_prior.get("revenue")),
            "gross_profit": _scale_money(income.get("grossProfit")),
            "operating_income": _scale_money(income.get("operatingIncome")),
            "net_income": _scale_money(income.get("netIncome")),
            "ebitda": _scale_money(income.get("ebitda")),
            "total_assets": _scale_money(balance.get("totalAssets")),
            "total_debt": _scale_money(balance.get("totalDebt")),
            "cash": _scale_money(balance.get("cashAndCashEquivalents")),
            "equity": _scale_money(balance.get("totalStockholdersEquity")),
            "operating_cash_flow": _scale_money(cashflow.get("operatingCashFlow")),
            "capex": _scale_money(cashflow.get("capitalExpenditure")),
            "free_cash_flow": _scale_money(cashflow.get("freeCashFlow")),
            "current_ratio": current_ratio,
            "interest_expense": _scale_money(income_raw.get("interestExpense")),
            "rd_expense": _scale_money(income_raw.get("researchAndDevelopmentExpenses")),
            "gross_margin": income.get("grossProfitRatio"),
            "fiscal_year": period_label,
            "fiscal_year_prior": f"FY{fiscal_year_prior}" if fiscal_year_prior else "Prior",
            "fmp_period": period,
            "fmp_limit": limit,
            "period_history": period_history,
            "source": "fmp",
            "income_statement": [
                _row("Revenue", _scale_money(income.get("revenue")), _scale_money(income_prior.get("revenue")), "total"),
                _row("Cost of Revenue", _scale_money(income_raw.get("costOfRevenue")), _scale_money(income_prior.get("costOfRevenue"))),
                _row("Gross Profit", _scale_money(income.get("grossProfit")), _scale_money(income_prior.get("grossProfit")), "subtotal"),
                _row("Research and Development Expenses", _scale_money(income_raw.get("researchAndDevelopmentExpenses")), _scale_money(income_prior.get("researchAndDevelopmentExpenses"))),
                _row("Operating Income", _scale_money(income.get("operatingIncome")), _scale_money(income_prior.get("operatingIncome")), "subtotal"),
                _row("Interest Expense", _scale_money(income_raw.get("interestExpense")), _scale_money(income_prior.get("interestExpense"))),
                _row("EBITDA", _scale_money(income.get("ebitda")), _scale_money(income_prior.get("ebitda"))),
                _row("Net Income", _scale_money(income.get("netIncome")), _scale_money(income_prior.get("netIncome")), "total"),
            ],
            "balance_sheet": [
                _row("ASSETS", None, None, "section_header"),
                _row("Cash and Cash Equivalents", _scale_money(balance.get("cashAndCashEquivalents")), _scale_money(balance_prior.get("cashAndCashEquivalents"))),
                _row("Total Current Assets", _scale_money(balance.get("totalCurrentAssets")), _scale_money(_balance_field(balance_prior, "totalCurrentAssets")), "subtotal"),
                _row("Total Assets", _scale_money(balance.get("totalAssets")), _scale_money(balance_prior.get("totalAssets")), "total"),
                _row("LIABILITIES", None, None, "section_header"),
                _row("Total Current Liabilities", _scale_money(balance.get("totalCurrentLiabilities")), _scale_money(_balance_field(balance_prior, "totalCurrentLiabilities")), "subtotal"),
                _row("Total Debt", _scale_money(balance.get("totalDebt")), _scale_money(_balance_field(balance_prior, "totalDebt"))),
                _row("SHAREHOLDERS' EQUITY", None, None, "section_header"),
                _row("Total Stockholders' Equity", _scale_money(balance.get("totalStockholdersEquity")), _scale_money(_balance_field(balance_prior, "totalStockholdersEquity")), "total"),
            ],
            "cash_flow_statement": [
                _row("OPERATING ACTIVITIES", None, None, "section_header"),
                _row("Net Cash from Operating Activities", _scale_money(cashflow.get("operatingCashFlow")), _scale_money(cashflow_prior.get("operatingCashFlow")), "subtotal"),
                _row("INVESTING ACTIVITIES", None, None, "section_header"),
                _row("Capital Expenditure", _scale_money(cashflow.get("capitalExpenditure")), _scale_money(cashflow_prior.get("capitalExpenditure"))),
                _row("Free Cash Flow", _scale_money(cashflow.get("freeCashFlow")), _scale_money(cashflow_prior.get("freeCashFlow")), "total"),
                _row("FINANCING ACTIVITIES", None, None, "section_header"),
                _row("Dividends Paid", _scale_money(cashflow.get("dividendsPaid")), _scale_money(cashflow_prior.get("netDividendsPaid") or cashflow_prior.get("commonDividendsPaid"))),
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
