import re
from urllib.parse import quote
from xml.etree import ElementTree

import requests


HEADERS = {"User-Agent": "FinLens 264511560+rileyorman@users.noreply.github.com"}


def _fmt(value):
    if value is None:
        return None
    try:
        v = float(value)
        if abs(v) >= 1_000_000_000:
            return f"${v/1_000_000_000:.1f}B"
        elif abs(v) >= 1_000_000:
            return f"${v/1_000_000:.1f}M"
        elif abs(v) >= 1_000:
            return f"${v/1_000:.1f}K"
        else:
            return f"${v:.0f}"
    except:
        return None


def _zero_pad_cik(cik) -> str | None:
    try:
        digits = re.sub(r"\D", "", str(cik))
        if not digits:
            return None
        return digits.zfill(10)
    except Exception:
        return None


def get_cik(ticker: str) -> str | None:
    try:
        ticker = (ticker or "").strip().upper()
        if not ticker:
            return None

        search_url = (
            "https://efts.sec.gov/LATEST/search-index"
            f"?q={quote(f'\"{ticker}\"')}&dateRange=custom&startdt=2020-01-01&forms=10-K"
        )
        try:
            response = requests.get(search_url, headers=HEADERS, timeout=15)
            if response.ok:
                payload = response.json()
                hits = payload.get("hits", {}).get("hits", [])
                for hit in hits:
                    source = hit.get("_source", {}) if isinstance(hit, dict) else {}
                    cik = (
                        source.get("ciks")
                        or source.get("cik")
                        or source.get("cikNumber")
                        or source.get("adsh")
                    )
                    if isinstance(cik, list):
                        cik = cik[0] if cik else None
                    padded = _zero_pad_cik(cik)
                    if padded:
                        return padded
        except Exception:
            pass

        atom_url = (
            "https://www.sec.gov/cgi-bin/browse-edgar"
            f"?action=getcompany&ticker={quote(ticker)}&type=10-K&dateb=&owner=include"
            "&count=10&search_text=&output=atom"
        )
        response = requests.get(atom_url, headers=HEADERS, timeout=15)
        if not response.ok:
            return None
        root = ElementTree.fromstring(response.content)
        for elem in root.iter():
            text = elem.text or ""
            match = re.search(r"CIK=(\d+)", text)
            if match:
                return _zero_pad_cik(match.group(1))
            if elem.tag.lower().endswith("cik"):
                padded = _zero_pad_cik(text)
                if padded:
                    return padded
        match = re.search(rb"CIK=(\d+)", response.content)
        if match:
            return _zero_pad_cik(match.group(1).decode("ascii"))
        return None
    except Exception:
        return None


def get_recent_filings(cik: str, form_type: str = "10-K", count: int = 5) -> list[dict]:
    try:
        cik = _zero_pad_cik(cik)
        if not cik:
            return []
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        response = requests.get(url, headers=HEADERS, timeout=15)
        if not response.ok:
            return []
        recent = response.json().get("filings", {}).get("recent", {})
        rows = []
        forms = recent.get("form", [])
        for i, form in enumerate(forms):
            if form != form_type:
                continue
            rows.append({
                "accessionNumber": recent.get("accessionNumber", [])[i],
                "filingDate": recent.get("filingDate", [])[i],
                "form": form,
                "reportDate": recent.get("reportDate", [])[i],
            })
            if len(rows) >= count:
                break
        return rows
    except Exception:
        return []


def _annual_facts(facts: dict, concept_names: list[str], accession_number: str) -> tuple:
    try:
        us_gaap = facts.get("facts", {}).get("us-gaap", {})
        accession_number = (accession_number or "").strip()
        for concept in concept_names:
            concept_data = us_gaap.get(concept)
            if not concept_data:
                continue
            units = concept_data.get("units", {})
            values = units.get("USD") or next(iter(units.values()), [])
            annual = [
                item for item in values
                if item.get("form") == "10-K" and item.get("val") is not None
            ]
            if not annual:
                continue

            annual.sort(key=lambda item: (item.get("end", ""), item.get("filed", "")), reverse=True)
            selected_idx = 0
            if accession_number:
                for i, item in enumerate(annual):
                    if item.get("accn") == accession_number:
                        selected_idx = i
                        break

            current = annual[selected_idx] if selected_idx < len(annual) else None
            prior = annual[selected_idx + 1] if selected_idx + 1 < len(annual) else None
            if current:
                return current, prior
        return None, None
    except Exception:
        return None, None


def _row(facts: dict, label: str, concepts: list[str], accession_number: str, row_type: str = "data") -> dict:
    current, prior = _annual_facts(facts, concepts, accession_number)
    return {
        "line_item": label,
        "value": current.get("val") if current else None,
        "value_prior": prior.get("val") if prior else None,
        "row_type": row_type,
    }


def _section(label: str) -> dict:
    return {"line_item": label, "value": None, "value_prior": None, "row_type": "section_header"}


def get_financial_data(cik: str, accession_number: str) -> dict:
    try:
        cik = _zero_pad_cik(cik)
        if not cik or not accession_number:
            return {}
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        response = requests.get(url, headers=HEADERS, timeout=20)
        if not response.ok:
            return {}
        facts = response.json()

        revenues_current, revenues_prior = _annual_facts(
            facts,
            ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
            accession_number,
        )
        report_end = (revenues_current or {}).get("end", "")
        prior_end = (revenues_prior or {}).get("end", "")
        fiscal_year = f"FY{report_end[:4]}" if report_end else "Current Year"
        fiscal_year_prior = f"FY{prior_end[:4]}" if prior_end else "Prior Year"

        return {
            "company_name": facts.get("entityName", "Company"),
            "period": f"Year ended {report_end}" if report_end else "",
            "fiscal_year": fiscal_year,
            "fiscal_year_prior": fiscal_year_prior,
            "currency": "USD",
            "income_statement": [
                _row(facts, "Revenues", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"], accession_number, "total"),
                _row(facts, "Cost of Revenue", ["CostOfRevenue", "CostOfGoodsAndServicesSold"], accession_number),
                _row(facts, "Gross Profit", ["GrossProfit"], accession_number, "subtotal"),
                _row(facts, "Operating Expenses", ["OperatingExpenses"], accession_number, "subtotal"),
                _row(facts, "Research and Development Expense", ["ResearchAndDevelopmentExpense"], accession_number),
                _row(facts, "Selling, General and Administrative Expense", ["SellingGeneralAndAdministrativeExpense"], accession_number),
                _row(facts, "Operating Income", ["OperatingIncomeLoss"], accession_number, "total"),
                _row(facts, "Net Income", ["NetIncomeLoss"], accession_number, "total"),
            ],
            "balance_sheet": [
                _section("ASSETS"),
                _row(facts, "Cash and Cash Equivalents", ["CashAndCashEquivalentsAtCarryingValue"], accession_number),
                _row(facts, "Accounts Receivable, Net", ["AccountsReceivableNetCurrent"], accession_number),
                _row(facts, "Assets", ["Assets"], accession_number, "total"),
                _section("LIABILITIES"),
                _row(facts, "Liabilities", ["Liabilities"], accession_number, "total"),
                _row(facts, "Long-Term Debt", ["LongTermDebt"], accession_number),
                _section("SHAREHOLDERS' EQUITY"),
                _row(facts, "Stockholders' Equity", ["StockholdersEquity"], accession_number, "total"),
                _row(facts, "Retained Earnings", ["RetainedEarningsAccumulatedDeficit"], accession_number),
            ],
            "cash_flow_statement": [
                _section("OPERATING ACTIVITIES"),
                _row(facts, "Net Cash Provided by Operating Activities", ["NetCashProvidedByUsedInOperatingActivities"], accession_number, "total"),
                _section("INVESTING ACTIVITIES"),
                _row(facts, "Capital Expenditures", ["PaymentsToAcquirePropertyPlantAndEquipment", "CapitalExpenditureDiscontinuedOperations"], accession_number),
                _row(facts, "Net Cash Provided by Investing Activities", ["NetCashProvidedByUsedInInvestingActivities"], accession_number, "total"),
                _section("FINANCING ACTIVITIES"),
                _row(facts, "Net Cash Provided by Financing Activities", ["NetCashProvidedByUsedInFinancingActivities"], accession_number, "total"),
            ],
        }
    except Exception:
        return {}
