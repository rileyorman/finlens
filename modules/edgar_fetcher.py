import platform
import re
import ssl
from datetime import date, timedelta
from urllib.parse import quote
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter


class _WindowsCertAdapter(HTTPAdapter):
    """Load the Windows system cert store so Avast HTTPS inspection is trusted.
    Avast's CA is in the Windows store but not in certifi's bundle.
    """
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_default_certs()
        ctx.check_hostname = True
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


def _make_session():
    session = requests.Session()
    session.trust_env = False
    if platform.system() == "Windows":
        session.mount("https://", _WindowsCertAdapter())
    return session


_SESSION = _make_session()
HEADERS = {"User-Agent": "FinLens riley@finlens.ai"}
_SUBMISSIONS_CACHE: dict[str, dict] = {}


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
    except Exception:
        return None


def _zero_pad_cik(cik) -> str | None:
    try:
        digits = re.sub(r"\D", "", str(cik))
        if not digits:
            return None
        return digits.zfill(10)
    except Exception:
        return None


def _company_match_key(cik: str | None, name: str | None) -> tuple[str, str]:
    return (_zero_pad_cik(cik) or "", re.sub(r"\s+", " ", str(name or "")).strip().upper())


def _add_company_match(matches: list[dict], seen: set, cik, name: str, ticker: str = "") -> None:
    padded = _zero_pad_cik(cik)
    if not padded:
        return
    company = re.sub(r"\s+", " ", str(name or "")).strip() or padded
    key = _company_match_key(padded, company)
    if key in seen:
        return
    matches.append({"cik": padded, "name": company, "ticker": ticker.upper()})
    seen.add(key)


def _get_submissions(cik: str) -> dict:
    padded = _zero_pad_cik(cik)
    if not padded:
        return {}
    if padded in _SUBMISSIONS_CACHE:
        return _SUBMISSIONS_CACHE[padded]
    url = f"https://data.sec.gov/submissions/CIK{padded}.json"
    response = _SESSION.get(url, headers=HEADERS, timeout=15)
    if not response.ok:
        _SUBMISSIONS_CACHE[padded] = {}
        return {}
    payload = response.json()
    _SUBMISSIONS_CACHE[padded] = payload if isinstance(payload, dict) else {}
    return _SUBMISSIONS_CACHE[padded]


def _latest_filing_date(submissions: dict) -> str:
    recent = (submissions or {}).get("filings", {}).get("recent", {})
    filing_dates = recent.get("filingDate", []) if isinstance(recent, dict) else []
    if not isinstance(filing_dates, list):
        return ""
    return max((str(value) for value in filing_dates if value), default="")


def _is_possibly_defunct(last_filed: str) -> bool:
    try:
        filed = date.fromisoformat(last_filed)
    except Exception:
        return False
    return filed < (date.today() - timedelta(days=3 * 365))


def _enrich_company_matches(matches: list[dict]) -> list[dict]:
    enriched = []
    seen_ciks = set()
    for match in matches:
        cik = _zero_pad_cik(match.get("cik"))
        if not cik or cik in seen_ciks:
            continue
        seen_ciks.add(cik)
        row = dict(match)
        row["cik"] = cik
        submissions = _get_submissions(cik)
        submission_name = re.sub(r"\s+", " ", str(submissions.get("name") or "")).strip()
        current_name = re.sub(r"\s+", " ", str(row.get("name") or "")).strip()
        if submission_name and (not current_name or len(current_name) < len(submission_name)):
            row["name"] = submission_name
        row["last_filed"] = _latest_filing_date(submissions)
        label = f"{row.get('name') or 'Unknown company'} (CIK {cik}) — last filed {row['last_filed'] or 'unknown'}"
        if _is_possibly_defunct(row["last_filed"]):
            row["possibly_defunct"] = True
            label += " [possibly defunct]"
        else:
            row["possibly_defunct"] = False
        row["label"] = label
        enriched.append(row)
    enriched.sort(key=lambda row: row.get("last_filed") or "", reverse=True)
    return enriched


def _filter_company_name_matches(query: str, matches: list[dict]) -> list[dict]:
    normalized_query = re.sub(r"[^a-z0-9]+", " ", str(query or "").lower()).strip()
    if not normalized_query:
        return matches
    filtered = []
    for match in matches:
        normalized_name = re.sub(r"[^a-z0-9]+", " ", str(match.get("name") or "").lower()).strip()
        if normalized_query in normalized_name:
            filtered.append(match)
    return filtered or matches


def _candidate_from_entity_text(entity: str) -> tuple[str | None, str | None]:
    text = re.sub(r"\s+", " ", str(entity or "")).strip()
    match = re.search(r"\bCIK[:\s]+(\d+)\b|\((\d{10})\)", text, re.I)
    cik = next((group for group in (match.groups() if match else []) if group), None)
    name = re.sub(r"\s+\(.*?CIK.*?\)\s*$", "", text, flags=re.I).strip()
    name = re.sub(r"\s+CIK[:\s]+\d+\b.*$", "", name, flags=re.I).strip()
    return cik, name or None


def _company_name_from_atom_title(title: str, fallback: str) -> str:
    name = re.sub(r"^\s*10-K(?:/A)?\s*-\s*", "", title or "", flags=re.I)
    name = re.sub(r"\s+\(.*?(?:CIK|Filer|\d{10}).*?\)\s*", " ", name, flags=re.I)
    return re.sub(r"\s+", " ", name).strip(" -") or fallback


def _append_atom_company_matches(content: bytes, query: str, matches: list[dict], seen: set, ticker: str = "") -> None:
    try:
        root = ElementTree.fromstring(content)
    except Exception:
        return
    for entry in root.iter():
        if not entry.tag.lower().endswith("entry"):
            continue
        title = ""
        cik = None
        for child in entry:
            tag = child.tag.lower()
            text = child.text or ""
            if tag.endswith("title"):
                title = text.strip()
            attr_text = " ".join(str(v) for v in child.attrib.values())
            match = re.search(r"CIK=(\d+)|/CIK(\d+)|\((\d{10})\)", f"{text} {attr_text}", re.I)
            if match:
                cik = next((group for group in match.groups() if group), None)
        if not cik:
            for descendant in entry.iter():
                if descendant.tag.lower().endswith("cik"):
                    cik = descendant.text
                    break
        name = _company_name_from_atom_title(title, query)
        _add_company_match(matches, seen, cik, name, ticker)


def search_companies(company_name: str, count: int = 10) -> list[dict]:
    try:
        query = (company_name or "").strip()
        if not query:
            return []

        matches = []
        seen = set()

        if re.fullmatch(r"[A-Za-z]{1,4}", query):
            atom_url = (
                "https://www.sec.gov/cgi-bin/browse-edgar"
                f"?action=getcompany&company=&CIK={quote(query)}&type=10-K"
                "&dateb=&owner=include&count=10&search_text=&output=atom"
            )
            response = _SESSION.get(atom_url, headers=HEADERS, timeout=15)
            if response.ok:
                _append_atom_company_matches(response.content, query, matches, seen, ticker=query)
                if matches:
                    return _filter_company_name_matches(query, _enrich_company_matches(matches))[:count]

        quoted_query = quote(f'"{query}"')
        search_url = (
            "https://efts.sec.gov/LATEST/search-index"
            f"?q={quoted_query}&dateRange=custom"
            "&startdt=2020-01-01&enddt=2026-12-31&forms=10-K"
        )
        response = _SESSION.get(search_url, headers=HEADERS, timeout=15)
        if response.ok:
            payload = response.json()
            hits = payload.get("hits", [])
            if isinstance(hits, dict):
                hits = hits.get("hits", [])
            for hit in hits:
                hit = hit if isinstance(hit, dict) else {}
                source = hit.get("_source", {}) if isinstance(hit.get("_source"), dict) else {}
                entities = hit.get("entity") or source.get("entity")
                cik = (
                    hit.get("cik")
                    or hit.get("ciks")
                    or source.get("ciks")
                    or source.get("cik")
                    or source.get("cikNumber")
                    or source.get("cik_number")
                )
                if isinstance(cik, list):
                    cik = cik[0] if cik else None
                if isinstance(entities, list):
                    for entity in entities:
                        entity_cik, entity_name = _candidate_from_entity_text(entity)
                        if entity_cik:
                            _add_company_match(matches, seen, entity_cik, entity_name or query)
                if not cik and isinstance(entities, list):
                    for entity in entities:
                        entity_cik, _ = _candidate_from_entity_text(entity)
                        if entity_cik:
                            cik = entity_cik
                            break
                padded = _zero_pad_cik(cik)
                if not padded:
                    continue
                company = (
                    entities
                    or source.get("display_names")
                    or source.get("entity_name")
                    or source.get("entityName")
                    or source.get("companyName")
                    or source.get("displayNames")
                    or source.get("name")
                    or query
                )
                if isinstance(company, list):
                    company = company[0] if company else query
                company = re.sub(r"\s+\(.*?CIK.*?\)\s*$", "", str(company)).strip()
                ticker = source.get("tickers") or source.get("ticker") or source.get("tickerSymbol")
                if isinstance(ticker, list):
                    ticker = ticker[0] if ticker else ""
                _add_company_match(matches, seen, padded, company, str(ticker or "").strip().upper())
        atom_url = (
            "https://www.sec.gov/cgi-bin/browse-edgar"
            f"?company={quote(query)}&CIK=&type=10-K&dateb=&owner=include"
            "&count=10&search_text=&action=getcompany&output=atom"
        )
        response = _SESSION.get(atom_url, headers=HEADERS, timeout=15)
        if response.ok:
            _append_atom_company_matches(response.content, query, matches, seen)
        return _filter_company_name_matches(query, _enrich_company_matches(matches))[:count]
    except Exception:
        return []


def get_cik(ticker: str) -> str | None:
    try:
        ticker = (ticker or "").strip().upper()
        if not ticker:
            return None

        try:
            ticker_response = _SESSION.get("https://www.sec.gov/files/company_tickers.json", headers=HEADERS, timeout=15)
            if ticker_response.ok:
                for company in ticker_response.json().values():
                    if str(company.get("ticker", "")).strip().upper() == ticker:
                        return _zero_pad_cik(company.get("cik_str"))
        except Exception:
            pass

        quoted_ticker = quote(f'"{ticker}"')
        search_url = (
            "https://efts.sec.gov/LATEST/search-index"
            f"?q={quoted_ticker}&dateRange=custom&startdt=2020-01-01&forms=10-K"
        )
        try:
            response = _SESSION.get(search_url, headers=HEADERS, timeout=15)
            if response.ok:
                payload = response.json()
                hits = payload.get("hits", {}).get("hits", [])
                for hit in hits:
                    source = hit.get("_source", {}) if isinstance(hit, dict) else {}
                    cik = (
                        source.get("ciks")
                        or source.get("cik")
                        or source.get("cikNumber")
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
        response = _SESSION.get(atom_url, headers=HEADERS, timeout=15)
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


def get_ticker_for_cik(cik: str) -> str | None:
    """Resolve a CIK to the issuer's primary ticker symbol via SEC's company_tickers.json."""
    try:
        cik_int = int(str(cik).lstrip("0") or "0")
        if cik_int <= 0:
            return None
        url = "https://www.sec.gov/files/company_tickers.json"
        response = _SESSION.get(url, headers=HEADERS, timeout=15)
        if not response.ok:
            return None
        data = response.json()
        for row in data.values():
            if int(row.get("cik_str", 0)) == cik_int:
                return str(row.get("ticker", "")).upper() or None
        return None
    except Exception:
        return None


def get_recent_filings(cik: str, form_type: str = "10-K", count: int = 5) -> list[dict]:
    try:
        cik = _zero_pad_cik(cik)
        if not cik:
            return []
        count = max(int(count), 0)
        if count == 0:
            return []
        submissions = _get_submissions(cik)
        if not submissions:
            return []
        filings = submissions.get("filings", {})
        recent = filings.get("recent", {})
        rows = []
        seen = set()

        def _append_matching_rows(filing_page: dict) -> None:
            forms = filing_page.get("form", [])
            accessions = filing_page.get("accessionNumber", [])
            filing_dates = filing_page.get("filingDate", [])
            report_dates = filing_page.get("reportDate", [])
            for i, form in enumerate(forms):
                if form != form_type:
                    continue
                accession = accessions[i] if i < len(accessions) else ""
                if accession in seen:
                    continue
                seen.add(accession)
                rows.append({
                    "accessionNumber": accession,
                    "filingDate": filing_dates[i] if i < len(filing_dates) else "",
                    "form": form,
                    "reportDate": report_dates[i] if i < len(report_dates) else "",
                })

        _append_matching_rows(recent)

        archive_files = filings.get("files", [])
        for archive in archive_files[:5]:
            if len(rows) >= count:
                break
            name = archive.get("name") if isinstance(archive, dict) else None
            if not name:
                continue
            try:
                archive_url = f"https://data.sec.gov/submissions/{name}"
                archive_response = _SESSION.get(archive_url, headers=HEADERS, timeout=15)
                if not archive_response.ok:
                    continue
                _append_matching_rows(archive_response.json())
            except Exception:
                continue

        rows.sort(key=lambda row: row.get("filingDate", ""), reverse=True)
        return rows[:count]
    except Exception:
        return []


def _is_annual_duration(item: dict) -> bool:
    """True if a companyfacts item covers a full-year period (or is an instant fact).

    A 10-K's XBRL data can include QUARTERLY duration facts (e.g. Prologis
    tags its "Selected Quarterly Financial Data" note), and those carry
    form="10-K" and fp="FY" just like the annual facts — so neither field
    distinguishes them. A Q4 fact shares its end date with the annual fact,
    ties on the (end, filed) sort, and gets picked as "prior year"
    (PLD FY2025 bug: fiscal_year_prior == fiscal_year, prior revenue = Q4).
    Duration is the only reliable discriminator: quarters run ~90 days,
    years ~364-371 (52/53-week calendars included).

    Balance-sheet facts are point-in-time (no "start") — always kept.
    """
    start, end = item.get("start"), item.get("end")
    if not start or not end:
        return True  # instant fact (balance sheet) — no duration to check
    try:
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return True  # unparseable dates — keep, matching old behavior
    return days >= 300


# ---------------------------------------------------------------------------
# Shared XBRL concept chains (CB-038): BOTH the accession-pinned filing path
# (get_financial_data) and the quick company-facts path
# (build_financial_data_from_edgar_facts) consume these — the NVDA-hardened
# capex chain must never fork. Order matters only as a tiebreak on the quick
# path (recency competition decides first) and as the fallback order on the
# accession-pinned path (unchanged semantics, pinned by
# tests/test_edgar_annual_facts.py).
# ---------------------------------------------------------------------------
REVENUE_CONCEPTS = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"]
COST_OF_REVENUE_CONCEPTS = ["CostOfRevenue", "CostOfGoodsAndServicesSold"]
GROSS_PROFIT_CONCEPTS = ["GrossProfit"]
OPERATING_INCOME_CONCEPTS = ["OperatingIncomeLoss"]
NET_INCOME_CONCEPTS = ["NetIncomeLoss"]
RD_EXPENSE_CONCEPTS = ["ResearchAndDevelopmentExpense"]
INTEREST_EXPENSE_CONCEPTS = ["InterestExpense"]
CASH_CONCEPTS = ["CashAndCashEquivalentsAtCarryingValue"]
TOTAL_ASSETS_CONCEPTS = ["Assets"]
CURRENT_ASSETS_CONCEPTS = ["AssetsCurrent"]
CURRENT_LIABILITIES_CONCEPTS = ["LiabilitiesCurrent"]
LONG_TERM_DEBT_CONCEPTS = ["LongTermDebtNoncurrent", "LongTermDebt"]
CURRENT_DEBT_CONCEPTS = ["LongTermDebtCurrent", "DebtCurrent"]
# CB-013 semantics for the quick path's `equity`: the grand total INCLUDING
# NCI outranks the attributable-only subtotal (declared order is the
# recency-competition tiebreak). The accession-pinned filing path keeps its
# original StockholdersEquity row (its own pinned contract).
EQUITY_CONCEPTS = [
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    "StockholdersEquity",
]
OPERATING_CASH_FLOW_CONCEPTS = ["NetCashProvidedByUsedInOperatingActivities"]
# PaymentsToAcquireProductiveAssets: combined PP&E + intangibles purchases —
# NVDA's capex line. Ordered last: PP&E-tagging filers (e.g. PLD) match
# earlier on the accession-pinned path; on the quick path recency
# competition retires NVDA's stale PP&E tag (facts end 2012) automatically.
CAPEX_CONCEPTS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "CapitalExpenditureDiscontinuedOperations",
    "PaymentsToAcquireProductiveAssets",
]
DIVIDENDS_PAID_CONCEPTS = ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"]


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
                if item.get("form") == "10-K"
                and item.get("val") is not None
                and _is_annual_duration(item)
            ]
            if not annual:
                continue

            annual.sort(key=lambda item: (item.get("end", ""), item.get("filed", "")), reverse=True)
            selected_idx = None
            if accession_number:
                for i, item in enumerate(annual):
                    if item.get("accn") == accession_number:
                        selected_idx = i
                        break
                if selected_idx is None:
                    continue   # accession not present in this concept — try next concept
            else:
                selected_idx = 0

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


def _concept_annual_facts(us_gaap: dict, concept: str) -> list[dict]:
    """One concept's annual facts, restatement-resolved: same filters as
    _annual_facts (10-K, non-null, >=300-day duration via _is_annual_duration),
    then facts sharing an `end` collapse to the latest `filed` (comparative
    re-reports produce 2-5 duplicates per period — probe 2026-07-12), sorted
    newest-first by (end, filed)."""
    concept_data = us_gaap.get(concept)
    if not concept_data:
        return []
    units = concept_data.get("units", {})
    values = units.get("USD") or next(iter(units.values()), [])
    annual = [
        item for item in values
        if item.get("form") == "10-K"
        and item.get("val") is not None
        and _is_annual_duration(item)
    ]
    by_end: dict[str, dict] = {}
    for item in annual:
        end = item.get("end", "")
        if end not in by_end or (item.get("filed", "") > by_end[end].get("filed", "")):
            by_end[end] = item
    return sorted(by_end.values(), key=lambda item: (item.get("end", ""), item.get("filed", "")), reverse=True)


def _competing_annual_facts(facts: dict, concept_names: list[str]) -> tuple[str | None, list[dict]]:
    """CB-038 quick-path selection: concept candidates COMPETE ON RECENCY.

    The accession-pinned path is safe with first-concept-with-facts because a
    concept lacking the chosen filing's facts is skipped. With NO accession,
    that rule resurrects the NVDA phantom: the stale
    PaymentsToAcquirePropertyPlantAndEquipment tag HAS annual facts — ending
    in 2012 ($138.7M) — and would beat today's
    PaymentsToAcquireProductiveAssets ($6.04B FY2026). So here the concept
    whose LATEST fact has the most recent (end, filed) wins the field; ties
    resolve to the earlier-declared concept. A tag the filer stopped feeding
    loses automatically, for every filer, forever.
    """
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    best_key = None
    best: tuple[str | None, list[dict]] = (None, [])
    for concept in concept_names:
        annual = _concept_annual_facts(us_gaap, concept)
        if not annual:
            continue
        latest = annual[0]
        key = (latest.get("end", ""), latest.get("filed", ""))
        if best_key is None or key > best_key:
            best_key = key
            best = (concept, annual)
    return best


def get_earnings_press_release(cik: str, limit: int = 5) -> dict | None:
    """
    Fetch the most recent earnings press release 8-K from SEC EDGAR.

    Returns a dict with:
        text         - full extracted text of the 8-K exhibit
        filing_date  - e.g. "2025-01-29"
        report_date  - period of report
        accession    - accession number
        url          - direct URL to filing index
    Or None if not found.
    """
    try:
        cik_padded = _zero_pad_cik(cik)
        if not cik_padded:
            return None

        # Fetch recent submissions from the EDGAR submissions endpoint
        sub_url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
        sub_resp = _SESSION.get(sub_url, headers=HEADERS, timeout=10)
        if not sub_resp.ok:
            return None

        recent = sub_resp.json().get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accession_numbers = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])
        items_list = recent.get("items", [])

        # Collect 8-K filings that report Results of Operations (item 2.02).
        # Item 2.02 is the SEC-defined item for earnings/results disclosures,
        # which reliably identifies earnings press releases without needing
        # keyword matching on exhibit descriptions (which are often just "EX-99.1").
        earnings_filings = []
        for i, form in enumerate(forms):
            if form != "8-K":
                continue
            items_val = items_list[i] if i < len(items_list) else ""
            if "2.02" not in str(items_val):
                continue
            earnings_filings.append({
                "accession": accession_numbers[i],
                "filing_date": filing_dates[i],
                "report_date": report_dates[i],
            })
            if len(earnings_filings) >= limit:
                break

        if not earnings_filings:
            return None

        earnings_keywords = (
            "press release",
            "earnings",
            "results of operations",
            "financial results",
            "quarterly results",
        )

        # URL path requires CIK without leading zeros
        cik_int = str(int(cik_padded))

        for filing in earnings_filings:
            accession = filing["accession"]
            accession_nodash = accession.replace("-", "")
            index_url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik_int}"
                f"/{accession_nodash}/{accession}-index.htm"
            )

            # Parse the HTML filing index to enumerate documents and exhibits
            index_resp = _SESSION.get(index_url, headers=HEADERS, timeout=10)
            if not index_resp.ok:
                continue

            index_soup = BeautifulSoup(index_resp.text, "html.parser")
            table = index_soup.find("table", class_="tableFile")
            if not table:
                continue

            for row in table.find_all("tr"):
                cols = row.find_all("td")
                if len(cols) < 4:
                    continue

                description = cols[1].get_text(strip=True).lower()
                link_tag = cols[2].find("a")
                doc_type = cols[3].get_text(strip=True).upper()

                if not link_tag:
                    continue

                href = link_tag.get("href", "")

                # Strip the inline XBRL viewer prefix when present
                if href.startswith("/ix?doc="):
                    href = href[len("/ix?doc="):]

                ext = href.lower()

                # Only inspect exhibits, not the 8-K form body itself
                if not doc_type.startswith("EX"):
                    continue

                # Match by description keyword (e.g. "press release", "earnings")
                # or by the standard EX-99.1 type used for press releases.
                # Companies vary — many omit a meaningful description and rely on the type.
                desc_match = any(kw in description for kw in earnings_keywords)
                type_match = doc_type in ("EX-99.1", "EX-99")
                if not (desc_match or type_match):
                    continue

                # Prefer HTML or plain text — skip binary or XBRL-only files
                if not (ext.endswith(".htm") or ext.endswith(".html") or ext.endswith(".txt")):
                    continue

                exhibit_url = (
                    f"https://www.sec.gov{href}"
                    if href.startswith("/")
                    else href
                )
                exhibit_resp = _SESSION.get(exhibit_url, headers=HEADERS, timeout=10)
                if not exhibit_resp.ok:
                    continue

                raw = exhibit_resp.text
                if ext.endswith(".htm") or ext.endswith(".html"):
                    exhibit_soup = BeautifulSoup(raw, "html.parser")
                    text = exhibit_soup.get_text(separator="\n")
                else:
                    text = raw

                # Collapse runs of blank lines left after HTML stripping
                text = re.sub(r"\n{3,}", "\n\n", text).strip()

                return {
                    "text": text,
                    "filing_date": filing["filing_date"],
                    "report_date": filing["report_date"],
                    "accession": accession,
                    "url": index_url,
                }

        return None
    except Exception:
        return None


def get_filing_text(cik: str, form_type: str = "10-K", limit: int = 5) -> dict | None:
    """
    Fetch the most recent 10-K or 10-Q filing text from SEC EDGAR.

    Args:
        cik: Company CIK (10-digit padded or unpadded)
        form_type: "10-K" or "10-Q" (default "10-K")
        limit: Max recent filings to check before giving up (default 5)

    Returns dict with:
        text         - full extracted text of the primary filing document
        filing_date  - e.g. "2025-09-27"
        report_date  - period of report
        accession    - accession number
        url          - direct URL to filing index
        form_type    - "10-K" or "10-Q" (echoed back)
    Or None if not found.
    """
    try:
        form_type = str(form_type).upper()
        if form_type not in ("10-K", "10-Q"):
            return None

        cik_padded = _zero_pad_cik(cik)
        if not cik_padded:
            return None

        sub_url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
        sub_resp = _SESSION.get(sub_url, headers=HEADERS, timeout=10)
        if not sub_resp.ok:
            return None

        recent = sub_resp.json().get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accession_numbers = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])

        filings = []
        for i, form in enumerate(forms):
            if form != form_type:
                continue
            filings.append({
                "accession": accession_numbers[i] if i < len(accession_numbers) else "",
                "filing_date": filing_dates[i] if i < len(filing_dates) else "",
                "report_date": report_dates[i] if i < len(report_dates) else "",
            })
            if len(filings) >= limit:
                break

        filings.sort(key=lambda f: f.get("filing_date", ""), reverse=True)

        if not filings:
            return None

        cik_int = str(int(cik_padded))

        for filing in filings:
            accession = filing["accession"]
            if not accession:
                continue

            accession_nodash = accession.replace("-", "")
            index_url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik_int}"
                f"/{accession_nodash}/{accession}-index.htm"
            )

            index_resp = _SESSION.get(index_url, headers=HEADERS, timeout=10)
            if not index_resp.ok:
                continue

            index_soup = BeautifulSoup(index_resp.text, "html.parser")
            table = index_soup.find("table", class_="tableFile")
            if not table:
                continue

            primary_href = None
            first_html_href = None
            for row in table.find_all("tr"):
                cols = row.find_all("td")
                if len(cols) < 4:
                    continue

                link_tag = cols[2].find("a")
                doc_type = cols[3].get_text(strip=True).upper()
                if not link_tag:
                    continue

                href = link_tag.get("href", "")
                if href.startswith("/ix?doc="):
                    href = href[len("/ix?doc="):]

                ext = href.lower()
                if not (ext.endswith(".htm") or ext.endswith(".html")):
                    continue

                if first_html_href is None:
                    first_html_href = href

                if doc_type == form_type:
                    primary_href = href
                    break

            href = primary_href or first_html_href
            if not href:
                continue

            filing_url = f"https://www.sec.gov{href}" if href.startswith("/") else href
            filing_resp = _SESSION.get(filing_url, headers=HEADERS, timeout=10)
            if not filing_resp.ok:
                continue

            filing_soup = BeautifulSoup(filing_resp.text, "html.parser")
            text = filing_soup.get_text(separator="\n")
            text = re.sub(r"\n{3,}", "\n\n", text).strip()

            if len(text) > 500_000:
                text = text[:150_000] + text[-350_000:]

            return {
                "text": text,
                "filing_date": filing["filing_date"],
                "report_date": filing["report_date"],
                "accession": accession,
                "url": index_url,
                "form_type": form_type,
            }

        return None
    except Exception:
        return None


def get_financial_data(cik: str, accession_number: str) -> dict:
    try:
        cik = _zero_pad_cik(cik)
        if not cik or not accession_number:
            return {}
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        response = _SESSION.get(url, headers=HEADERS, timeout=20)
        if not response.ok:
            return {}
        facts = response.json()

        revenues_current, revenues_prior = _annual_facts(
            facts,
            REVENUE_CONCEPTS,
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
                _row(facts, "Revenues", REVENUE_CONCEPTS, accession_number, "total"),
                _row(facts, "Cost of Revenue", COST_OF_REVENUE_CONCEPTS, accession_number),
                _row(facts, "Gross Profit", GROSS_PROFIT_CONCEPTS, accession_number, "subtotal"),
                _row(facts, "Operating Expenses", ["OperatingExpenses"], accession_number, "subtotal"),
                _row(facts, "Research and Development Expense", RD_EXPENSE_CONCEPTS, accession_number),
                _row(facts, "Selling, General and Administrative Expense", ["SellingGeneralAndAdministrativeExpense"], accession_number),
                _row(facts, "Operating Income", OPERATING_INCOME_CONCEPTS, accession_number, "total"),
                _row(facts, "Net Income", NET_INCOME_CONCEPTS, accession_number, "total"),
            ],
            "balance_sheet": [
                _section("ASSETS"),
                _row(facts, "Cash and Cash Equivalents", CASH_CONCEPTS, accession_number),
                _row(facts, "Accounts Receivable, Net", ["AccountsReceivableNetCurrent"], accession_number),
                _row(facts, "Assets", TOTAL_ASSETS_CONCEPTS, accession_number, "total"),
                _section("LIABILITIES"),
                _row(facts, "Liabilities", ["Liabilities"], accession_number, "total"),
                # This path's Long-Term Debt row deliberately keeps the single
                # combined tag (its own pinned contract); the quick path's
                # total_debt uses the CB-022 pair semantics instead.
                _row(facts, "Long-Term Debt", ["LongTermDebt"], accession_number),
                _section("SHAREHOLDERS' EQUITY"),
                _row(facts, "Stockholders' Equity", ["StockholdersEquity"], accession_number, "total"),
                _row(facts, "Retained Earnings", ["RetainedEarningsAccumulatedDeficit"], accession_number),
            ],
            "cash_flow_statement": [
                _section("OPERATING ACTIVITIES"),
                _row(facts, "Net Cash Provided by Operating Activities", OPERATING_CASH_FLOW_CONCEPTS, accession_number, "total"),
                _section("INVESTING ACTIVITIES"),
                # CAPEX_CONCEPTS carries the NVDA phantom-capex fix — see the
                # shared-chain block near _annual_facts.
                _row(facts, "Capital Expenditures", CAPEX_CONCEPTS, accession_number),
                _row(facts, "Net Cash Provided by Investing Activities", ["NetCashProvidedByUsedInInvestingActivities"], accession_number, "total"),
                _section("FINANCING ACTIVITIES"),
                _row(facts, "Net Cash Provided by Financing Activities", ["NetCashProvidedByUsedInFinancingActivities"], accession_number, "total"),
            ],
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Quick Financials from company-facts (CB-038, docs/EDGAR_COMPANY_FACTS_SPEC.md)
# As-filed XBRL replaces FMP for the ANNUAL quick options. Raw dollars,
# per-figure receipts, honest N/A on unmatched tags, recency-competition
# concept selection (see _competing_annual_facts).
# ---------------------------------------------------------------------------

_COMPANYFACTS_CACHE: dict[str, dict] = {}


def _get_companyfacts(cik: str) -> dict | None:
    """Fetch (and memoize per process) a filer's full company-facts payload."""
    cik = _zero_pad_cik(cik)
    if not cik:
        return None
    if cik in _COMPANYFACTS_CACHE:
        return _COMPANYFACTS_CACHE[cik]
    try:
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        response = _SESSION.get(url, headers=HEADERS, timeout=20)
        if not response.ok:
            return None
        facts = response.json()
    except Exception:
        return None
    _COMPANYFACTS_CACHE[cik] = facts
    return facts


def _fact_receipt(concept: str, fact: dict) -> str:
    return (
        f"us-gaap:{concept} · {fact.get('form', '?')} {fact.get('accn', '?')} · "
        f"ended {fact.get('end', '?')}"
    )


def build_financial_data_from_edgar_facts(ticker: str, limit: int = 1) -> dict | None:
    """As-filed annual quick financials for a US ticker (CB-038).

    Drop-in for build_financial_data_from_fmp's ANNUAL shapes, with the
    ratified differences: raw dollars (scale=1), source="edgar" (flips all
    badging to the trusted branch), a `receipts` dict carrying each figure's
    XBRL tag + accession + form + period end, and honest N/A for any field
    with no matching fact (CB-021 discipline: derived fields require ALL
    components). Returns None when the ticker/CIK/revenue anchor is
    unavailable — never a partial dict without its anchor.
    """
    try:
        limit = max(int(limit or 1), 1)
        cik = get_cik(ticker)
        if not cik:
            return None
        facts = _get_companyfacts(cik)
        if not facts:
            return None

        receipts: dict[str, str] = {}
        field_concepts: dict[str, str] = {}

        def _field(name: str, concepts: list[str]) -> list[dict]:
            concept, annual = _competing_annual_facts(facts, concepts)
            if concept:
                field_concepts[name] = concept
            return annual

        def _val_at(annual: list[dict], end: str):
            for fact in annual:
                if fact.get("end") == end:
                    return fact.get("val")
            return None

        revenue_facts = _field("revenue", REVENUE_CONCEPTS)
        if not revenue_facts:
            return None  # no revenue anchor — honest refusal, never a shell
        period_ends = [f.get("end", "") for f in revenue_facts[:limit]]

        cost_facts = _field("cost_of_revenue", COST_OF_REVENUE_CONCEPTS)
        gross_facts = _field("gross_profit", GROSS_PROFIT_CONCEPTS)
        oi_facts = _field("operating_income", OPERATING_INCOME_CONCEPTS)
        ni_facts = _field("net_income", NET_INCOME_CONCEPTS)
        rd_facts = _field("rd_expense", RD_EXPENSE_CONCEPTS)
        int_facts = _field("interest_expense", INTEREST_EXPENSE_CONCEPTS)
        cash_facts = _field("cash", CASH_CONCEPTS)
        ta_facts = _field("total_assets", TOTAL_ASSETS_CONCEPTS)
        ca_facts = _field("total_current_assets", CURRENT_ASSETS_CONCEPTS)
        cl_facts = _field("total_current_liabilities", CURRENT_LIABILITIES_CONCEPTS)
        ltd_facts = _field("long_term_debt", LONG_TERM_DEBT_CONCEPTS)
        cd_facts = _field("current_debt", CURRENT_DEBT_CONCEPTS)
        eq_facts = _field("equity", EQUITY_CONCEPTS)
        ocf_facts = _field("operating_cash_flow", OPERATING_CASH_FLOW_CONCEPTS)
        capex_facts = _field("capex", CAPEX_CONCEPTS)
        div_facts = _field("dividends_paid", DIVIDENDS_PAID_CONCEPTS)

        current_end = period_ends[0]
        prior_end = period_ends[1] if len(period_ends) > 1 else None

        # A receipt cites ONLY the exact fact emitted as the current value —
        # a concept whose facts stopped before the current period end emits
        # None (honest absence) and gets NO receipt. Found on the first live
        # run: NVDA stopped filing InterestExpense after FY2024; the value
        # was honestly None but a stale 2024 receipt had been recorded.
        for name, annual in (
            ("revenue", revenue_facts), ("cost_of_revenue", cost_facts),
            ("gross_profit", gross_facts), ("operating_income", oi_facts),
            ("net_income", ni_facts), ("rd_expense", rd_facts),
            ("interest_expense", int_facts), ("cash", cash_facts),
            ("total_assets", ta_facts), ("total_current_assets", ca_facts),
            ("total_current_liabilities", cl_facts),
            ("long_term_debt", ltd_facts), ("current_debt", cd_facts),
            ("equity", eq_facts), ("operating_cash_flow", ocf_facts),
            ("capex", capex_facts), ("dividends_paid", div_facts),
        ):
            for fact in annual:
                if fact.get("end") == current_end and name in field_concepts:
                    receipts[name] = _fact_receipt(field_concepts[name], fact)
                    break

        def _cur(annual):
            return _val_at(annual, current_end)

        def _pri(annual):
            return _val_at(annual, prior_end) if prior_end else None

        revenue = _cur(revenue_facts)
        cost_of_revenue = _cur(cost_facts)
        gross_profit = _cur(gross_facts)
        if gross_profit is None and revenue is not None and cost_of_revenue is not None:
            gross_profit = revenue - cost_of_revenue
            receipts["gross_profit"] = (
                "derived: revenue − cost of revenue "
                f"({receipts.get('revenue', '?')} − {receipts.get('cost_of_revenue', '?')})"
            )
        net_income = _cur(ni_facts)
        operating_cash_flow = _cur(ocf_facts)
        capex = _cur(capex_facts)  # XBRL Payments* facts are positive outflows
        free_cash_flow = (
            operating_cash_flow - capex
            if operating_cash_flow is not None and capex is not None
            else None
        )
        if free_cash_flow is not None:
            receipts["free_cash_flow"] = (
                "derived: operating cash flow − capital expenditure "
                f"({receipts.get('operating_cash_flow', '?')} − {receipts.get('capex', '?')})"
            )

        # CB-022 pair semantics: total debt = long-term + current portion;
        # missing LTD → honest None (a current-portion-only total would
        # understate); missing current portion → LTD alone, disclosed.
        ltd = _cur(ltd_facts)
        current_debt = _cur(cd_facts)
        if ltd is None:
            total_debt = None
        else:
            total_debt = ltd + (current_debt or 0)
            receipts["total_debt"] = (
                f"{receipts.get('long_term_debt', '?')}"
                + (f" + {receipts.get('current_debt')}" if current_debt is not None
                   else " (long-term only; no current-portion fact)")
            )

        current_assets = _cur(ca_facts)
        current_liabilities = _cur(cl_facts)
        current_ratio = (
            current_assets / current_liabilities
            if current_assets is not None and current_liabilities not in (None, 0)
            else None
        )
        gross_margin = (
            gross_profit / revenue
            if gross_profit is not None and revenue not in (None, 0)
            else None
        )

        fiscal_year = f"FY{current_end[:4]}" if current_end else "Current Year"
        fiscal_year_prior = f"FY{prior_end[:4]}" if prior_end else "Prior"

        period_history = []
        for end in period_ends:
            period_history.append({
                "label": f"FY{end[:4]}" if end else "?",
                "revenue": _val_at(revenue_facts, end),
                "gross_profit": _val_at(gross_facts, end),
                "net_income": _val_at(ni_facts, end),
                "free_cash_flow": (
                    _val_at(ocf_facts, end) - _val_at(capex_facts, end)
                    if _val_at(ocf_facts, end) is not None and _val_at(capex_facts, end) is not None
                    else None
                ),
                "total_debt": (
                    _val_at(ltd_facts, end) + (_val_at(cd_facts, end) or 0)
                    if _val_at(ltd_facts, end) is not None else None
                ),
                "cash": _val_at(cash_facts, end),
            })

        def _fd_row(label, value, prior, row_type="data"):
            return {"line_item": label, "value": value, "value_prior": prior,
                    "row_type": row_type}

        return {
            "ticker": (ticker or "").upper(),
            "company": facts.get("entityName") or (ticker or "").upper(),
            "company_name": facts.get("entityName") or (ticker or "").upper(),
            "period": fiscal_year,
            "currency": "USD",
            "scale": 1,                # raw dollars — the ratified basis
            "_normalized": True,
            "source": "edgar",         # flips all badging to the trusted branch
            "revenue": revenue,
            "revenue_prior": _pri(revenue_facts),
            "gross_profit": gross_profit,
            "operating_income": _cur(oi_facts),
            "net_income": net_income,
            # ebitda: not an XBRL concept — honestly absent, never derived here
            "total_assets": _cur(ta_facts),
            "total_debt": total_debt,
            "cash": _cur(cash_facts),
            "equity": _cur(eq_facts),
            "operating_cash_flow": operating_cash_flow,
            "capex": capex,
            "free_cash_flow": free_cash_flow,
            "current_ratio": current_ratio,
            "interest_expense": _cur(int_facts),
            "rd_expense": _cur(rd_facts),
            "gross_margin": gross_margin,
            "fiscal_year": fiscal_year,
            "fiscal_year_prior": fiscal_year_prior,
            "fmp_period": "annual",
            "fmp_limit": limit,
            "period_history": period_history,
            "receipts": receipts,
            "income_statement": [
                _fd_row("Revenue", revenue, _pri(revenue_facts), "total"),
                _fd_row("Cost of Revenue", cost_of_revenue, _pri(cost_facts)),
                _fd_row("Gross Profit", gross_profit, _pri(gross_facts), "subtotal"),
                _fd_row("R&D Expenses", _cur(rd_facts), _pri(rd_facts)),
                _fd_row("Operating Income", _cur(oi_facts), _pri(oi_facts), "subtotal"),
                _fd_row("Interest Expense", _cur(int_facts), _pri(int_facts)),
                _fd_row("Net Income", net_income, _pri(ni_facts), "total"),
            ],
            "balance_sheet": [
                _section("ASSETS"),
                _fd_row("Cash and Cash Equivalents", _cur(cash_facts), _pri(cash_facts)),
                _fd_row("Total Current Assets", current_assets, _pri(ca_facts), "subtotal"),
                _fd_row("Total Assets", _cur(ta_facts), _pri(ta_facts), "total"),
                _section("LIABILITIES"),
                _fd_row("Total Current Liabilities", current_liabilities, _pri(cl_facts), "subtotal"),
                _fd_row("Total Debt", total_debt, None),
                _section("SHAREHOLDERS' EQUITY"),
                _fd_row("Total Stockholders' Equity", _cur(eq_facts), _pri(eq_facts), "total"),
            ],
            "cash_flow_statement": [
                _section("OPERATING ACTIVITIES"),
                _fd_row("Net Cash from Operating Activities", operating_cash_flow,
                        _pri(ocf_facts), "subtotal"),
                _section("INVESTING ACTIVITIES"),
                _fd_row("Capital Expenditure", capex, _pri(capex_facts)),
                _fd_row("Free Cash Flow", free_cash_flow, None, "total"),
                _section("FINANCING ACTIVITIES"),
                _fd_row("Dividends Paid", _cur(div_facts), _pri(div_facts)),
            ],
        }
    except Exception:
        return None


