from __future__ import annotations

from xml.etree import ElementTree
from urllib.parse import quote

import requests


BASE_URL = "https://www.sedarplus.ca"
API_BASE_URL = "https://api.sedarplus.ca"
HEADERS = {"User-Agent": "FinLens 264511560+rileyorman@users.noreply.github.com"}

_FILING_CACHE: dict[str, dict] = {}


def _as_list(payload) -> list:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("data", "results", "items", "companies", "filings", "documents"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _as_list(value)
            if nested:
                return nested
    return []


def _first_value(row: dict, keys: list[str], default: str = ""):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return default


def _manual_search_url(query: str = "") -> str:
    return (
        f"{BASE_URL}/csa-party/service/create.html"
        f"?_locale=en&service=searchDocuments&targetAppCode=csa-party"
        f"&profileName={quote(query or '')}"
    )


def _document_url(row: dict) -> str:
    url = _first_value(
        row,
        [
            "document_url", "documentUrl", "downloadUrl", "download_url",
            "url", "href", "documentLink", "document_link",
        ],
    )
    if not url:
        document_id = _first_value(row, ["documentId", "document_id", "id"])
        if document_id:
            url = f"{BASE_URL}/csa-party/records/document.html?id={document_id}"
    if isinstance(url, str) and url.startswith("/"):
        return f"{BASE_URL}{url}"
    return str(url or "")


def _absolute_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("/"):
        return f"{BASE_URL}{url}"
    return url


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].split(":", 1)[-1]


def _numeric_text(text: str):
    try:
        cleaned = str(text or "").replace(",", "").strip()
        if not cleaned:
            return None
        return float(cleaned)
    except Exception:
        return None


def _xbrl_value(values: dict[str, list[float]], concepts: list[str], index: int):
    for concept in concepts:
        concept_values = values.get(concept, [])
        if len(concept_values) > index:
            return concept_values[index]
    return None


def _xbrl_row(values: dict[str, list[float]], label: str, concepts: list[str], row_type: str = "data") -> dict:
    return {
        "line_item": label,
        "value": _xbrl_value(values, concepts, 0),
        "value_prior": _xbrl_value(values, concepts, 1),
        "row_type": row_type,
    }


def _section(label: str) -> dict:
    return {"line_item": label, "value": None, "value_prior": None, "row_type": "section_header"}


def _extract_xbrl_financials(xbrl_url: str, company_name: str = "Company") -> dict:
    try:
        xbrl_url = _absolute_url(xbrl_url)
        if not xbrl_url:
            return {}
        response = requests.get(xbrl_url, headers=HEADERS, timeout=20)
        if not response.ok:
            return {}
        root = ElementTree.fromstring(response.content)

        concepts = {
            "Revenue": ["Revenue", "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "ifrs-full_Revenue"],
            "Cost of Revenue": ["CostOfRevenue", "CostOfSales", "ifrs-full_CostOfSales"],
            "Gross Profit": ["GrossProfit", "GrossProfitLoss", "ifrs-full_GrossProfit"],
            "Operating Income": ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities", "ifrs-full_ProfitLossFromOperatingActivities"],
            "Net Income": ["NetIncomeLoss", "ProfitLoss", "ifrs-full_ProfitLoss"],
            "Cash and Cash Equivalents": ["CashAndCashEquivalentsAtCarryingValue", "CashAndCashEquivalents", "ifrs-full_CashAndCashEquivalents"],
            "Assets": ["Assets", "ifrs-full_Assets"],
            "Liabilities": ["Liabilities", "ifrs-full_Liabilities"],
            "Equity": ["StockholdersEquity", "Equity", "ifrs-full_Equity"],
            "Retained Earnings": ["RetainedEarningsAccumulatedDeficit", "RetainedEarnings", "ifrs-full_RetainedEarnings"],
            "Operating Cash Flow": ["NetCashProvidedByUsedInOperatingActivities", "CashFlowsFromUsedInOperatingActivities", "ifrs-full_CashFlowsFromUsedInOperatingActivities"],
            "Capital Expenditures": ["PaymentsToAcquirePropertyPlantAndEquipment", "PurchaseOfPropertyPlantAndEquipment", "ifrs-full_PurchaseOfPropertyPlantAndEquipment"],
            "Investing Cash Flow": ["NetCashProvidedByUsedInInvestingActivities", "CashFlowsFromUsedInInvestingActivities", "ifrs-full_CashFlowsFromUsedInInvestingActivities"],
            "Financing Cash Flow": ["NetCashProvidedByUsedInFinancingActivities", "CashFlowsFromUsedInFinancingActivities", "ifrs-full_CashFlowsFromUsedInFinancingActivities"],
        }
        wanted_names = {name for names in concepts.values() for name in names}
        values: dict[str, list[float]] = {}

        for elem in root.iter():
            name = _local_name(elem.tag)
            if name not in wanted_names:
                continue
            value = _numeric_text(elem.text)
            if value is None:
                continue
            values.setdefault(name, []).append(value)

        if not values:
            return {}

        return {
            "company_name": company_name,
            "period": "",
            "fiscal_year": "Current Year",
            "fiscal_year_prior": "Prior Year",
            "currency": "CAD",
            "income_statement": [
                _xbrl_row(values, "Revenues", concepts["Revenue"], "total"),
                _xbrl_row(values, "Cost of Revenue", concepts["Cost of Revenue"]),
                _xbrl_row(values, "Gross Profit", concepts["Gross Profit"], "subtotal"),
                _xbrl_row(values, "Operating Income", concepts["Operating Income"], "total"),
                _xbrl_row(values, "Net Income", concepts["Net Income"], "total"),
            ],
            "balance_sheet": [
                _section("ASSETS"),
                _xbrl_row(values, "Cash and Cash Equivalents", concepts["Cash and Cash Equivalents"]),
                _xbrl_row(values, "Assets", concepts["Assets"], "total"),
                _section("LIABILITIES"),
                _xbrl_row(values, "Liabilities", concepts["Liabilities"], "total"),
                _section("SHAREHOLDERS' EQUITY"),
                _xbrl_row(values, "Stockholders' Equity", concepts["Equity"], "total"),
                _xbrl_row(values, "Retained Earnings", concepts["Retained Earnings"]),
            ],
            "cash_flow_statement": [
                _section("OPERATING ACTIVITIES"),
                _xbrl_row(values, "Net Cash Provided by Operating Activities", concepts["Operating Cash Flow"], "total"),
                _section("INVESTING ACTIVITIES"),
                _xbrl_row(values, "Capital Expenditures", concepts["Capital Expenditures"]),
                _xbrl_row(values, "Net Cash Provided by Investing Activities", concepts["Investing Cash Flow"], "total"),
                _section("FINANCING ACTIVITIES"),
                _xbrl_row(values, "Net Cash Provided by Financing Activities", concepts["Financing Cash Flow"], "total"),
            ],
            "xbrl_available": True,
            "xbrl_url": xbrl_url,
        }
    except Exception:
        return {}


def search_company(query: str) -> list[dict]:
    try:
        query = (query or "").strip()
        if not query:
            return []

        url = f"{API_BASE_URL}/csa/api/v1/company/search?query={quote(query)}"
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.ok:
            rows = []
            for row in _as_list(response.json()):
                if not isinstance(row, dict):
                    continue
                issuer_no = _first_value(row, ["issuer_no", "issuerNo", "issuerNumber", "profileNo", "profileNumber", "id"])
                name = _first_value(row, ["name", "issuerName", "companyName", "profileName", "legalName"])
                if not issuer_no and not name:
                    continue
                rows.append({
                    "issuer_no": str(issuer_no or ""),
                    "name": str(name or query),
                    "jurisdiction": str(_first_value(row, ["jurisdiction", "principalJurisdiction", "province"])),
                    "ticker": str(_first_value(row, ["ticker", "symbol", "stockSymbol", "tsxSymbol"])),
                })
            if rows:
                return rows

        return [{
            "issuer_no": "",
            "name": query,
            "jurisdiction": "",
            "ticker": "",
            "search_url": _manual_search_url(query),
        }]
    except Exception:
        if query:
            return [{
                "issuer_no": "",
                "name": query,
                "jurisdiction": "",
                "ticker": "",
                "search_url": _manual_search_url(query),
            }]
        return []


def get_filings(issuer_no: str, filing_type: str = "Annual", count: int = 5) -> list[dict]:
    try:
        issuer_no = (issuer_no or "").strip()
        filing_type = (filing_type or "Annual").strip()
        count = max(1, int(count or 5))

        if issuer_no:
            url = (
                f"{API_BASE_URL}/csa/api/v1/company/{quote(issuer_no)}/filings"
                f"?category={quote(filing_type)}&count={count}"
            )
            response = requests.get(url, headers=HEADERS, timeout=15)
            if response.ok:
                filings = []
                for row in _as_list(response.json()):
                    if not isinstance(row, dict):
                        continue
                    filing_id = str(_first_value(row, ["filing_id", "filingId", "id", "accessionNumber"]))
                    if not filing_id:
                        continue
                    filing = {
                        "filing_id": filing_id,
                        "filing_date": str(_first_value(row, ["filing_date", "filingDate", "dateFiled", "filedDate"])),
                        "filing_type": str(_first_value(row, ["filing_type", "filingType", "documentType", "type"], filing_type)),
                        "period_end": str(_first_value(row, ["period_end", "periodEnd", "reportDate", "periodOfReport"])),
                        "document_url": _document_url(row),
                    }
                    _FILING_CACHE[filing_id] = filing
                    filings.append(filing)
                    if len(filings) >= count:
                        break
                if filings:
                    return filings

        manual_url = _manual_search_url(issuer_no)
        filing = {
            "filing_id": "manual_sedar_search",
            "filing_date": "",
            "filing_type": f"{filing_type} filings search",
            "period_end": "",
            "document_url": manual_url,
        }
        _FILING_CACHE[filing["filing_id"]] = filing
        return [filing]
    except Exception:
        if issuer_no:
            filing = {
                "filing_id": "manual_sedar_search",
                "filing_date": "",
                "filing_type": f"{filing_type} filings search",
                "period_end": "",
                "document_url": _manual_search_url(issuer_no),
            }
            _FILING_CACHE[filing["filing_id"]] = filing
            return [filing]
        return []


def get_financial_data(issuer_no: str, filing_id: str) -> dict:
    try:
        issuer_no = (issuer_no or "").strip()
        filing_id = (filing_id or "").strip()
        if not filing_id:
            return {}

        filing = _FILING_CACHE.get(filing_id, {})
        document_url = filing.get("document_url", "")

        if issuer_no and filing_id != "manual_sedar_search":
            detail_url = f"{API_BASE_URL}/csa/api/v1/company/{quote(issuer_no)}/filings/{quote(filing_id)}"
            response = requests.get(detail_url, headers=HEADERS, timeout=15)
            if response.ok:
                detail = response.json()
                if isinstance(detail, dict):
                    document_url = document_url or _document_url(detail)
                    xbrl_url = _first_value(detail, ["xbrl_url", "xbrlUrl", "xbrlDownloadUrl", "structuredDataUrl"])
                    if xbrl_url:
                        company_name = str(_first_value(detail, ["issuerName", "companyName", "name"], "Company"))
                        financial_data = _extract_xbrl_financials(str(xbrl_url), company_name)
                        if financial_data:
                            financial_data["period"] = str(_first_value(detail, ["periodEnd", "period_end", "reportDate"], financial_data.get("period", "")))
                            financial_data["fiscal_year"] = str(_first_value(detail, ["fiscalYear", "fiscal_year"], financial_data.get("fiscal_year", "Current Year")))
                            financial_data["currency"] = str(_first_value(detail, ["currency"], financial_data.get("currency", "CAD")))
                            financial_data["pdf_url"] = str(document_url or "")
                            return financial_data

        return {
            "pdf_url": str(document_url or _manual_search_url(issuer_no)),
            "xbrl_available": False,
            "error": "PDF only — upload manually",
        }
    except Exception:
        return {}
