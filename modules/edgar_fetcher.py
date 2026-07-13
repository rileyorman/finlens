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
# FMP-zero batch (2026-07-13): per-share and share-count concepts. EPS facts
# carry the "USD/shares" unit; the cover-page share count lives in the dei
# taxonomy under the "shares" unit — both need unit-aware selection (the
# monetary selectors' USD-first rule would pick nothing or the wrong series).
EPS_BASIC_CONCEPTS = ["EarningsPerShareBasic"]
EPS_DILUTED_CONCEPTS = ["EarningsPerShareDiluted"]
DEI_SHARES_CONCEPT = "EntityCommonStockSharesOutstanding"
_MONETARY_UNITS = ("USD",)
_PER_SHARE_UNITS = ("USD/shares",)
_SHARES_UNITS = ("shares",)


def _unit_values(concept_data: dict | None, units: tuple = _MONETARY_UNITS) -> list:
    """Facts in the first matching unit, each annotated with its unit key
    ("_unit") so consumers can DERIVE the filing currency instead of
    hardcoding it — the ENB trap: a dual registrant filing 10-Ks with
    CAD-unit facts renders CAD values under a USD label unless the unit
    travels with the fact. Monetary concepts want USD, share counts want
    'shares', per-share concepts want 'USD/shares'; the final fallback
    (first unit present) preserves the legacy behavior for filers
    reporting in a single non-USD unit."""
    all_units = (concept_data or {}).get("units") or {}
    for unit in units:
        if all_units.get(unit):
            return [{**item, "_unit": unit} for item in all_units[unit]]
    unit, items = next(iter(all_units.items()), (None, []))
    return [{**item, "_unit": unit} for item in items]


def latest_shares_outstanding(facts: dict) -> dict | None:
    """The filer's latest cover-page share count (dei taxonomy),
    restatement-resolved (same end → latest filed). Cover dates TRAIL
    period ends, so the count is served AS-OF its own date with its own
    receipt — never period-matched to a statement column."""
    dei = ((facts or {}).get("facts") or {}).get("dei") or {}
    values = _unit_values(dei.get(DEI_SHARES_CONCEPT), _SHARES_UNITS)
    dated = [item for item in values if item.get("val") is not None and item.get("end")]
    if not dated:
        return None
    by_end: dict[str, dict] = {}
    for item in dated:
        end = item.get("end", "")
        if end not in by_end or (item.get("filed", "") > by_end[end].get("filed", "")):
            by_end[end] = item
    return max(by_end.values(), key=lambda i: (i.get("end", ""), i.get("filed", "")))


def _annual_facts(facts: dict, concept_names: list[str], accession_number: str) -> tuple:
    try:
        us_gaap = facts.get("facts", {}).get("us-gaap", {})
        accession_number = (accession_number or "").strip()
        for concept in concept_names:
            concept_data = us_gaap.get(concept)
            if not concept_data:
                continue
            values = _unit_values(concept_data)
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


def _concept_annual_facts(us_gaap: dict, concept: str, units: tuple = _MONETARY_UNITS) -> list[dict]:
    """One concept's annual facts, restatement-resolved: same filters as
    _annual_facts (10-K, non-null, >=300-day duration via _is_annual_duration),
    then facts sharing an `end` collapse to the latest `filed` (comparative
    re-reports produce 2-5 duplicates per period — probe 2026-07-12), sorted
    newest-first by (end, filed)."""
    concept_data = us_gaap.get(concept)
    if not concept_data:
        return []
    values = _unit_values(concept_data, units)
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


def _competing_annual_facts(
    facts: dict, concept_names: list[str], units: tuple = _MONETARY_UNITS,
) -> tuple[str | None, list[dict]]:
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
        annual = _concept_annual_facts(us_gaap, concept, units)
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
            # Derived from the revenue anchor's unit — never hardcoded (the
            # ENB trap: CAD-unit 10-K facts under a USD label).
            "currency": (revenues_current or {}).get("_unit") or "USD",
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
    unit = fact.get("_unit")
    return (
        f"us-gaap:{concept} · {fact.get('form', '?')} {fact.get('accn', '?')} · "
        f"ended {fact.get('end', '?')}" + (f" · {unit}" if unit else "")
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

        def _field(
            name: str,
            concepts: list[str],
            units: tuple = _MONETARY_UNITS,
            require_unit: str | None = None,
        ) -> list[dict]:
            concept, annual = _competing_annual_facts(facts, concepts, units)
            if require_unit is not None:
                annual = [f for f in annual if f.get("_unit") == require_unit]
            if concept and annual:
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
        # The filing currency is the revenue anchor's unit; every other
        # field must carry the SAME unit or go honest-N/A — never mix, never
        # relabel (the ENB trap: CAD-unit 10-K facts under a hardcoded USD
        # label). Preferring the anchor unit in selection also retires a
        # stale other-currency series automatically (TECK's dual-unit case).
        filing_unit = revenue_facts[0].get("_unit") or "USD"
        _mon = (filing_unit,)
        _ps_unit = f"{filing_unit}/shares"

        cost_facts = _field("cost_of_revenue", COST_OF_REVENUE_CONCEPTS, _mon, filing_unit)
        gross_facts = _field("gross_profit", GROSS_PROFIT_CONCEPTS, _mon, filing_unit)
        oi_facts = _field("operating_income", OPERATING_INCOME_CONCEPTS, _mon, filing_unit)
        ni_facts = _field("net_income", NET_INCOME_CONCEPTS, _mon, filing_unit)
        rd_facts = _field("rd_expense", RD_EXPENSE_CONCEPTS, _mon, filing_unit)
        int_facts = _field("interest_expense", INTEREST_EXPENSE_CONCEPTS, _mon, filing_unit)
        cash_facts = _field("cash", CASH_CONCEPTS, _mon, filing_unit)
        ta_facts = _field("total_assets", TOTAL_ASSETS_CONCEPTS, _mon, filing_unit)
        ca_facts = _field("total_current_assets", CURRENT_ASSETS_CONCEPTS, _mon, filing_unit)
        cl_facts = _field("total_current_liabilities", CURRENT_LIABILITIES_CONCEPTS, _mon, filing_unit)
        ltd_facts = _field("long_term_debt", LONG_TERM_DEBT_CONCEPTS, _mon, filing_unit)
        cd_facts = _field("current_debt", CURRENT_DEBT_CONCEPTS, _mon, filing_unit)
        eq_facts = _field("equity", EQUITY_CONCEPTS, _mon, filing_unit)
        ocf_facts = _field("operating_cash_flow", OPERATING_CASH_FLOW_CONCEPTS, _mon, filing_unit)
        capex_facts = _field("capex", CAPEX_CONCEPTS, _mon, filing_unit)
        div_facts = _field("dividends_paid", DIVIDENDS_PAID_CONCEPTS, _mon, filing_unit)
        # FMP-zero batch: as-filed per-share history (<currency>/shares unit).
        epsb_facts = _field("eps_basic", EPS_BASIC_CONCEPTS, (_ps_unit,), _ps_unit)
        epsd_facts = _field("eps_diluted", EPS_DILUTED_CONCEPTS, (_ps_unit,), _ps_unit)

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
            ("eps_basic", epsb_facts), ("eps_diluted", epsd_facts),
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

        # FMP-zero batch: the cover-page share count (dei taxonomy) — served
        # AS-OF its own date (cover dates trail period ends by design), with
        # a receipt saying so. Retires the aggregator dependency for
        # per-share math on this path.
        shares_fact = latest_shares_outstanding(facts)
        shares_outstanding = shares_fact.get("val") if shares_fact else None
        if shares_fact is not None:
            receipts["shares_outstanding"] = (
                f"dei:{DEI_SHARES_CONCEPT} · {shares_fact.get('form', '?')} "
                f"{shares_fact.get('accn', '?')} · as of {shares_fact.get('end', '?')} "
                f"(cover-page count — not period-matched)"
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
            "currency": filing_unit,   # the revenue anchor's unit, never hardcoded
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
            "eps_basic": _cur(epsb_facts),
            "eps_diluted": _cur(epsd_facts),
            "shares_outstanding": shares_outstanding,
            "dividends_paid": _cur(div_facts),
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
                _fd_row("EPS (Basic)", _cur(epsb_facts), _pri(epsb_facts)),
                _fd_row("EPS (Diluted)", _cur(epsd_facts), _pri(epsd_facts)),
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


# ---------------------------------------------------------------------------
# CB-039 (CB-038 Phase 2): Latest Quarter + TTM from company-facts.
#
# Evidence base (NVDA 10-Q probe, 2026-07-12; spec
# docs/EDGAR_COMPANY_FACTS_SPEC.md Phase-2 section):
# - Operating cash flow is YTD-ONLY in 10-Qs (cash-flow statements are
#   presented year-to-date), so TTM = FY + YTD_current − YTD_prior is the
#   ONLY viable construction — sum-of-4-discrete-quarters is impossible
#   for cash-flow items from raw facts.
# - The `fp` field LIES (the 181-day H1 fact carries fp="Q2"). Period
#   identity comes from date arithmetic ONLY — nothing below reads fp.
# - Discrete flow quarters come from YTD DIFFERENCING (Q1 = YTD1;
#   Qn = YTDn − YTDn−1; Q4 = FY − YTD_Q3), each under a STRICT date-chain
#   gate; any violation → honest N/A with no receipt.
# - Amendments included: {10-Q, 10-Q/A} (+ {10-K, 10-K/A} for FY
#   components) — an amendment is the MOST corrected statement of a
#   period; latest-`filed` prefers it naturally. The v1 ANNUAL path's
#   10-K-only filter is deliberately untouched (its own pins).
# ---------------------------------------------------------------------------

_QUARTERLY_FORMS = ("10-Q", "10-Q/A")
_FY_FORMS = ("10-K", "10-K/A")


def _window_days(item: dict) -> int | None:
    start, end = item.get("start"), item.get("end")
    if not start or not end:
        return None
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return None


def _window_class(days: int | None) -> str | None:
    """CB-039 duration taxonomy — day counts ONLY (the fp field lies):
    discrete quarter 60–120d · H1 150–210d · 9M 240–299d · FY ≥300d
    (the existing _is_annual_duration threshold). Anything outside every
    window is unusable for derivation (honest exclusion)."""
    if days is None:
        return None
    if 60 <= days <= 120:
        return "Q"
    if 150 <= days <= 210:
        return "H1"
    if 240 <= days < 300:
        return "9M"
    if days >= 300:
        return "FY"
    return None


def _day_after(iso: str) -> str | None:
    try:
        return (date.fromisoformat(iso) + timedelta(days=1)).isoformat()
    except ValueError:
        return None


def _days_between(start_iso: str, end_iso: str) -> int | None:
    try:
        return (date.fromisoformat(end_iso) - date.fromisoformat(start_iso)).days
    except ValueError:
        return None


def _concept_window_facts(us_gaap: dict, concept: str, forms: tuple) -> list[dict]:
    """One concept's dated duration facts from the given forms,
    restatement-resolved: facts sharing an exact (start, end) window
    collapse to the latest `filed` — which is how a 10-Q/A amendment
    naturally outranks the 10-Q it corrects. Sorted newest-first."""
    concept_data = us_gaap.get(concept)
    if not concept_data:
        return []
    values = _unit_values(concept_data)
    dated = [
        item for item in values
        if item.get("form") in forms
        and item.get("val") is not None
        and item.get("start") and item.get("end")
    ]
    by_window: dict[tuple, dict] = {}
    for item in dated:
        key = (item.get("start", ""), item.get("end", ""))
        if key not in by_window or (item.get("filed", "") > by_window[key].get("filed", "")):
            by_window[key] = item
    return sorted(by_window.values(), key=lambda i: (i.get("end", ""), i.get("filed", "")), reverse=True)


def _concept_instant_facts(us_gaap: dict, concept: str, forms: tuple) -> list[dict]:
    """One concept's instant (balance-sheet) facts from the given forms,
    same-`end` duplicates resolved to the latest `filed`, newest-first."""
    concept_data = us_gaap.get(concept)
    if not concept_data:
        return []
    values = _unit_values(concept_data)
    instants = [
        item for item in values
        if item.get("form") in forms
        and item.get("val") is not None
        and item.get("end") and not item.get("start")
    ]
    by_end: dict[str, dict] = {}
    for item in instants:
        end = item.get("end", "")
        if end not in by_end or (item.get("filed", "") > by_end[end].get("filed", "")):
            by_end[end] = item
    return sorted(by_end.values(), key=lambda i: (i.get("end", ""), i.get("filed", "")), reverse=True)


def _quarterly_bundle(us_gaap: dict, concept: str) -> dict:
    """A concept's derivation inputs: true YTD/quarter windows from 10-Qs,
    full-year windows from 10-Ks (amendments included in both)."""
    ytd = [
        f for f in _concept_window_facts(us_gaap, concept, _QUARTERLY_FORMS)
        if _window_class(_window_days(f)) in ("Q", "H1", "9M")
    ]
    fy = [
        f for f in _concept_window_facts(us_gaap, concept, _FY_FORMS)
        if _window_class(_window_days(f)) == "FY"
    ]
    return {"ytd": ytd, "fy": fy}


def _competing_quarterly_flow(facts: dict, concept_names: list[str]) -> tuple[str | None, dict | None]:
    """Recency competition (the CB-038 central rule) over the quarterly
    derivation pool: the concept whose latest usable duration fact has the
    most recent (end, filed) wins; ties → earlier-declared concept."""
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    best_key = None
    best: tuple[str | None, dict | None] = (None, None)
    for concept in concept_names:
        bundle = _quarterly_bundle(us_gaap, concept)
        pool = bundle["ytd"] + bundle["fy"]
        if not pool:
            continue
        latest = max(pool, key=lambda i: (i.get("end", ""), i.get("filed", "")))
        key = (latest.get("end", ""), latest.get("filed", ""))
        if best_key is None or key > best_key:
            best_key = key
            best = (concept, bundle)
    return best


def _competing_quarterly_instant(facts: dict, concept_names: list[str]) -> tuple[str | None, list[dict]]:
    """Recency competition over instant (balance-sheet) facts across
    {10-Q, 10-Q/A, 10-K, 10-K/A}."""
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    best_key = None
    best: tuple[str | None, list[dict]] = (None, [])
    for concept in concept_names:
        instants = _concept_instant_facts(us_gaap, concept, _QUARTERLY_FORMS + _FY_FORMS)
        if not instants:
            continue
        latest = instants[0]
        key = (latest.get("end", ""), latest.get("filed", ""))
        if best_key is None or key > best_key:
            best_key = key
            best = (concept, instants)
    return best


def _window_ref(fact: dict) -> str:
    return (
        f"{fact.get('start', '?')}→{fact.get('end', '?')} "
        f"[{fact.get('form', '?')} {fact.get('accn', '?')}]"
    )


def _latest_discrete_quarter(concept: str, bundle: dict) -> dict | None:
    """The latest discrete quarter of a FLOW concept via YTD differencing
    (CB-039 decision 1) under the strict date-chain gate (decision 2).
    Returns {"value", "end", "ordinal", "receipt"} or None (chain
    violation / nothing derivable — honest N/A, never a guess)."""
    ytd, fy = bundle["ytd"], bundle["fy"]
    latest_fy = fy[0] if fy else None
    latest_q_end = ytd[0].get("end", "") if ytd else ""

    # Case B — the newest period on file is the fiscal year itself:
    # Q4 = FY − YTD_Q3, gated on YTD_Q3.start == FY.start and a 60–120 day
    # remainder (no Q4 10-Q exists; this is the only route to Q4).
    if latest_fy and latest_fy.get("end", "") >= latest_q_end:
        fy_start, fy_end = latest_fy.get("start"), latest_fy.get("end")
        for fact in ytd:
            if fact.get("start") != fy_start:
                continue
            gap = _days_between(fact.get("end", ""), fy_end or "")
            if gap is not None and 60 <= gap <= 120:
                return {
                    "value": latest_fy["val"] - fact["val"],
                    "end": fy_end,
                    "ordinal": 4,
                    "unit": latest_fy.get("_unit"),
                    "receipt": (
                        f"derived Q4: FY {_window_ref(latest_fy)} − "
                        f"YTD {_window_ref(fact)} (us-gaap:{concept})"
                    ),
                }
        return None

    if not ytd:
        return None

    # Case A — a post-FY 10-Q window is the newest period. The fiscal-year
    # start is anchored on the prior FY fact (fp is never trusted):
    # year_start = prior FY end + 1 day. Dual-tagged DISCRETE facts start
    # mid-year, so the start filter drops them from the YTD chain.
    year_start = None
    for fy_fact in fy:  # newest-first; first FY ending before the latest 10-Q window
        if fy_fact.get("end", "") < latest_q_end:
            year_start = _day_after(fy_fact.get("end", ""))
            break
    if not year_start:
        return None  # no prior FY on file — the chain cannot be validated
    chain = [f for f in ytd if f.get("start") == year_start]
    if not chain:
        return None
    latest = chain[0]
    cls = _window_class(_window_days(latest))
    if cls == "Q":
        return {
            "value": latest["val"],
            "end": latest["end"],
            "ordinal": 1,
            "unit": latest.get("_unit"),
            "receipt": f"YTD Q1 {_window_ref(latest)} (us-gaap:{concept})",
        }
    ordinal = {"H1": 2, "9M": 3}.get(cls)
    if ordinal is None:
        return None
    for prev in chain[1:]:
        gap = _days_between(prev.get("end", ""), latest.get("end", ""))
        if gap is not None and 60 <= gap <= 120:
            return {
                "value": latest["val"] - prev["val"],
                "end": latest["end"],
                "ordinal": ordinal,
                "unit": latest.get("_unit"),
                "receipt": (
                    f"derived Q{ordinal}: YTD {_window_ref(latest)} − "
                    f"YTD {_window_ref(prev)} (us-gaap:{concept})"
                ),
            }
    return None


def _ttm_flow(concept: str, bundle: dict) -> dict | None:
    """TTM of a FLOW concept: FY + YTD_current − YTD_prior — the only
    viable construction (OCF is YTD-only in 10-Qs). Strict chain: YTD_current
    starts FY.end + 1 day; YTD_prior starts FY.start with a day-count within
    ±7 of YTD_current's (same ordinal without trusting fp). No post-FY 10-Q
    yet → TTM degenerates to FY exactly, receipted as such."""
    ytd, fy = bundle["ytd"], bundle["fy"]
    if not fy:
        return None
    latest_fy = fy[0]
    fy_start, fy_end = latest_fy.get("start"), latest_fy.get("end")
    fy_ref = f"FY {_window_ref(latest_fy)}"
    next_start = _day_after(fy_end or "")
    post = [f for f in ytd if next_start and f.get("start") == next_start]
    if not post:
        return {
            "value": latest_fy["val"],
            "end": fy_end,
            "ordinal": None,
            "unit": latest_fy.get("_unit"),
            "receipt": (
                f"TTM = {fy_ref} — no post-FY quarterly filing yet; "
                f"TTM equals FY exactly (us-gaap:{concept})"
            ),
        }
    ytd_c = post[0]
    days_c = _window_days(ytd_c)
    ytd_p = None
    for fact in ytd:
        if fact.get("start") != fy_start:
            continue
        days_p = _window_days(fact)
        if days_p is not None and days_c is not None and abs(days_p - days_c) <= 7:
            ytd_p = fact
            break
    if ytd_p is None:
        return None  # chain violation — no same-ordinal prior-year YTD
    return {
        "value": latest_fy["val"] + ytd_c["val"] - ytd_p["val"],
        "end": ytd_c["end"],
        "ordinal": None,
        "unit": latest_fy.get("_unit"),
        "receipt": (
            f"TTM = {fy_ref} + YTD {_window_ref(ytd_c)} − "
            f"YTD {_window_ref(ytd_p)} (us-gaap:{concept})"
        ),
    }


def build_quarterly_financial_data_from_edgar_facts(ticker: str, mode: str = "quarter") -> dict | None:
    """As-filed Latest-Quarter / TTM quick financials for a US ticker
    (CB-039 — Phase 2 of CB-038).

    Same output contract as the annual builder: raw dollars (scale=1),
    source="edgar", per-figure receipts (composite for derived values,
    naming every component fact), honest N/A for anything the strict
    date-chain gate rejects. Flow values are anchored on revenue's derived
    window: every emitted figure describes EXACTLY that period (flows by
    window end, balance items by as-of instant); anything else is honest
    N/A. Returns None when no revenue can be derived for the mode — never
    a partial dict without its anchor.
    """
    try:
        if mode not in ("quarter", "ttm"):
            return None
        cik = get_cik(ticker)
        if not cik:
            return None
        facts = _get_companyfacts(cik)
        if not facts:
            return None

        flow_fields = [
            ("revenue", REVENUE_CONCEPTS),
            ("cost_of_revenue", COST_OF_REVENUE_CONCEPTS),
            ("gross_profit", GROSS_PROFIT_CONCEPTS),
            ("operating_income", OPERATING_INCOME_CONCEPTS),
            ("net_income", NET_INCOME_CONCEPTS),
            ("rd_expense", RD_EXPENSE_CONCEPTS),
            ("interest_expense", INTEREST_EXPENSE_CONCEPTS),
            ("operating_cash_flow", OPERATING_CASH_FLOW_CONCEPTS),
            ("capex", CAPEX_CONCEPTS),
            ("dividends_paid", DIVIDENDS_PAID_CONCEPTS),
        ]
        instant_fields = [
            ("cash", CASH_CONCEPTS),
            ("total_assets", TOTAL_ASSETS_CONCEPTS),
            ("total_current_assets", CURRENT_ASSETS_CONCEPTS),
            ("total_current_liabilities", CURRENT_LIABILITIES_CONCEPTS),
            ("long_term_debt", LONG_TERM_DEBT_CONCEPTS),
            ("current_debt", CURRENT_DEBT_CONCEPTS),
            ("equity", EQUITY_CONCEPTS),
        ]

        derive = _latest_discrete_quarter if mode == "quarter" else _ttm_flow

        results: dict[str, dict] = {}
        for name, concepts in flow_fields:
            concept, bundle = _competing_quarterly_flow(facts, concepts)
            if not concept:
                continue
            derived = derive(concept, bundle)
            if derived is not None:
                results[name] = derived

        anchor = results.get("revenue")
        if anchor is None:
            return None  # nothing derivable for this mode — honest refusal
        anchor_end = anchor["end"]
        # The filing currency is the revenue anchor's unit (never hardcoded
        # — the ENB trap); same-currency gate mirrors the annual builder.
        anchor_unit = anchor.get("unit")

        receipts: dict[str, str] = {}
        values: dict[str, float | None] = {}
        # Same-window gate: a flow value whose derived window ends anywhere
        # but the anchor's end describes a DIFFERENT period — honest N/A,
        # no receipt (the CB-038 corollary). Same-currency gate likewise.
        for name, derived in results.items():
            if derived["end"] == anchor_end and derived.get("unit") == anchor_unit:
                values[name] = derived["value"]
                receipts[name] = derived["receipt"]

        # Balance items: the as-of instant must be the anchor period end,
        # in the anchor currency.
        for name, concepts in instant_fields:
            concept, instants = _competing_quarterly_instant(facts, concepts)
            if not concept:
                continue
            for fact in instants:
                if fact.get("end") == anchor_end and fact.get("_unit") == anchor_unit:
                    values[name] = fact.get("val")
                    receipts[name] = _fact_receipt(concept, fact)
                    break

        # FMP-zero batch: cover-page share count, served as-of its own date
        # (same helper + receipt framing as the annual builder). EPS is
        # deliberately ABSENT here: per-share figures cannot be derived by
        # YTD differencing (weighted-average shares make EPS non-additive) —
        # discrete-quarter EPS lift is a separate, later decision.
        shares_fact = latest_shares_outstanding(facts)
        if shares_fact is not None:
            values["shares_outstanding"] = shares_fact.get("val")
            receipts["shares_outstanding"] = (
                f"dei:{DEI_SHARES_CONCEPT} · {shares_fact.get('form', '?')} "
                f"{shares_fact.get('accn', '?')} · as of {shares_fact.get('end', '?')} "
                f"(cover-page count — not period-matched)"
            )

        revenue = values.get("revenue")
        cost_of_revenue = values.get("cost_of_revenue")
        gross_profit = values.get("gross_profit")
        if gross_profit is None and revenue is not None and cost_of_revenue is not None:
            gross_profit = revenue - cost_of_revenue
            receipts["gross_profit"] = (
                "derived: revenue − cost of revenue "
                f"({receipts.get('revenue', '?')} − {receipts.get('cost_of_revenue', '?')})"
            )
        net_income = values.get("net_income")
        operating_cash_flow = values.get("operating_cash_flow")
        capex = values.get("capex")  # XBRL Payments* facts are positive outflows
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

        # CB-022 pair semantics, identical to the annual builder.
        ltd = values.get("long_term_debt")
        current_debt = values.get("current_debt")
        if ltd is None:
            total_debt = None
        else:
            total_debt = ltd + (current_debt or 0)
            receipts["total_debt"] = (
                f"{receipts.get('long_term_debt', '?')}"
                + (f" + {receipts.get('current_debt')}" if current_debt is not None
                   else " (long-term only; no current-portion fact)")
            )

        current_assets = values.get("total_current_assets")
        current_liabilities = values.get("total_current_liabilities")
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

        if mode == "ttm":
            period_label = f"TTM ended {anchor_end}"
        else:
            period_label = f"Q{anchor['ordinal']} ended {anchor_end}"

        def _fd_row(label, value, row_type="data"):
            return {"line_item": label, "value": value, "value_prior": None,
                    "row_type": row_type}

        return {
            "ticker": (ticker or "").upper(),
            "company": facts.get("entityName") or (ticker or "").upper(),
            "company_name": facts.get("entityName") or (ticker or "").upper(),
            "period": period_label,
            "currency": anchor_unit or "USD",  # the anchor's unit, never hardcoded
            "scale": 1,                # raw dollars — the ratified basis
            "_normalized": True,
            "source": "edgar",         # flips all badging to the trusted branch
            "revenue": revenue,
            "revenue_prior": None,
            "gross_profit": gross_profit,
            "operating_income": values.get("operating_income"),
            "net_income": net_income,
            # ebitda: not an XBRL concept — honestly absent, never derived here
            "total_assets": values.get("total_assets"),
            "total_debt": total_debt,
            "cash": values.get("cash"),
            "equity": values.get("equity"),
            "operating_cash_flow": operating_cash_flow,
            "capex": capex,
            "free_cash_flow": free_cash_flow,
            "current_ratio": current_ratio,
            "interest_expense": values.get("interest_expense"),
            "rd_expense": values.get("rd_expense"),
            "gross_margin": gross_margin,
            "shares_outstanding": values.get("shares_outstanding"),
            "fiscal_year": period_label,
            "fiscal_year_prior": "Prior",
            "fmp_period": "quarter",
            "fmp_limit": 4 if mode == "ttm" else 1,
            "period_history": [{
                "label": period_label,
                "revenue": revenue,
                "gross_profit": gross_profit,
                "net_income": net_income,
                "free_cash_flow": free_cash_flow,
                "total_debt": total_debt,
                "cash": values.get("cash"),
            }],
            "receipts": receipts,
            "income_statement": [
                _fd_row("Revenue", revenue, "total"),
                _fd_row("Cost of Revenue", cost_of_revenue),
                _fd_row("Gross Profit", gross_profit, "subtotal"),
                _fd_row("R&D Expenses", values.get("rd_expense")),
                _fd_row("Operating Income", values.get("operating_income"), "subtotal"),
                _fd_row("Interest Expense", values.get("interest_expense")),
                _fd_row("Net Income", net_income, "total"),
            ],
            "balance_sheet": [
                _section("ASSETS"),
                _fd_row("Cash and Cash Equivalents", values.get("cash")),
                _fd_row("Total Current Assets", current_assets, "subtotal"),
                _fd_row("Total Assets", values.get("total_assets"), "total"),
                _section("LIABILITIES"),
                _fd_row("Total Current Liabilities", current_liabilities, "subtotal"),
                _fd_row("Total Debt", total_debt),
                _section("SHAREHOLDERS' EQUITY"),
                _fd_row("Total Stockholders' Equity", values.get("equity"), "total"),
            ],
            "cash_flow_statement": [
                _section("OPERATING ACTIVITIES"),
                _fd_row("Net Cash from Operating Activities", operating_cash_flow, "subtotal"),
                _section("INVESTING ACTIVITIES"),
                _fd_row("Capital Expenditure", capex),
                _fd_row("Free Cash Flow", free_cash_flow, "total"),
                _section("FINANCING ACTIVITIES"),
                _fd_row("Dividends Paid", values.get("dividends_paid")),
            ],
        }
    except Exception:
        return None


