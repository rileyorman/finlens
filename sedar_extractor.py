import json
import os
import re
from pathlib import Path
from datetime import datetime
from typing import NotRequired, TypedDict

import pdfplumber
from dotenv import load_dotenv

from config import LIBRARY_DIR
from modules.claude_analyzer import _make_client
from modules.integrity.sedar_mapper import map_line_items, mapper_statement_keys


SEDAR_MODEL = "claude-sonnet-5"
SCHEMA_VERSION = 5
STATEMENT_KEYS = ("balance_sheet", "income_statement", "cash_flow")
COVER_PAGE_INPUT_PAGES = tuple(range(4))


class SedarExtractionError(Exception):
    def __init__(self, message: str, raw_response: str | None = None):
        super().__init__(message)
        self.raw_response = raw_response


class SedarLineItem(TypedDict):
    label: str
    values: dict[str, int | float | None]
    confidence: float


class SedarStatements(TypedDict):
    balance_sheet: list[SedarLineItem]
    income_statement: list[SedarLineItem]
    cash_flow: list[SedarLineItem]


class SedarExtraction(TypedDict):
    source: str
    schema_version: int
    accounting_standard: str
    currency: str
    scale: str
    fiscal_year_end: str
    filing_date: NotRequired[str]
    statements: SedarStatements
    extraction_confidence: float
    pages_used: dict[str, list[int]]
    company_name: NotRequired[str]
    period: NotRequired[str]
    sector_inferred: NotRequired[str]
    mapping: NotRequired[dict]


HEADING_PATTERNS = {
    "balance_sheet": re.compile(
        r"\b(?:condensed\s+)?consolidated\s+statements?\s+of\s+financial\s+position\b"
        r"|\b(?:condensed\s+)?consolidated\s+balance\s+sheets?\b",
        re.IGNORECASE,
    ),
    "income_statement": re.compile(
        r"\b(?:condensed\s+)?consolidated\s+statements?\s+of\s+"
        r"(?:income|operations|earnings|profit\s+or\s+loss|comprehensive\s+income)\b",
        re.IGNORECASE,
    ),
    "cash_flow": re.compile(
        r"\b(?:condensed\s+)?consolidated\s+statements?\s+of\s+cash\s+flows?\b",
        re.IGNORECASE,
    ),
}


SYSTEM_PROMPT = """You are extracting financial statements from Canadian SEDAR+ PDF filings for FinLens.

Respond ONLY with valid JSON. Do not include markdown fences, a preamble, comments, or trailing prose.

Extract only the primary financial statements supplied in the user message: balance sheet/statement of financial position, income statement/statement of operations/earnings/profit or loss/comprehensive income, and statement of cash flows. Do not extract MD&A or notes.

Extract line-item labels exactly as labeled in the filing. Use verbatim labels. Do NOT translate labels into GAAP or FinLens canonical terms; a mapping layer handles that later.

For each line item, return:
{"label": str, "values": {fiscal period: number}, "confidence": float}

Top-level fields required:
{
  "company_name": str or null,
  "accounting_standard": str,
  "currency": str,
  "scale": str,
  "fiscal_year_end": str,
  "filing_date": str or null,
  "sector_inferred": str or null,
  "statements": {
    "balance_sheet": [],
    "income_statement": [],
    "cash_flow": []
  }
}

Rules for company_name:
- Use the issuer's name exactly as printed on the cover page or statement headers (e.g. "The Toronto-Dominion Bank", "RioCan Real Estate Investment Trust").
- Do NOT abbreviate, translate, or normalize the name; do NOT append ticker symbols.
- Return null if no issuer name is visible in the supplied pages. Do NOT guess.

Rules for sector_inferred:
- Infer the primary sector or industry from the filing text (issuer description, segment headings, business overview snippets on the supplied pages).
- Use plain language, e.g. "Banking", "Real Estate (REIT)", "Specialty Retail", "Upstream Oil & Gas", "Software".
- Return null if the supplied pages do not provide enough context to infer the sector confidently.
- Do NOT guess from the ticker or company name alone — only infer from filing content.

Rules for numbers:
- Parse parentheses as negatives.
- Strip thousands separators.
- Use plain JSON numbers, not strings, for numeric values.
- Preserve the filing's stated scale in the top-level "scale" field, such as "thousands" or "millions".
- Do NOT pre-multiply values by the scale. Downstream ingestion normalizes scale.
- Use null only when a value is absent or illegible.

Rules for filing_date:
- Locate the filing/cover date: the date the document was filed, dated, approved, signed, or stated as "dated as of".
- Use the cover page, signature/approval line, or filing/date metadata visible in the supplied pages when present.
- filing_date is NOT the fiscal period end and NOT the fiscal_year_end.
- If no clear filing/cover date is present, return null for filing_date.
- Do NOT guess. Do NOT substitute the period-end date. A wrong filing_date is worse than no filing_date.

Rules for confidence:
- confidence must be a number from 0 to 1.
- Use lower confidence for unclear labels, ambiguous columns, or damaged extraction.
"""


USER_PROMPT_TEMPLATE = """Extract the financial statements from these located SEDAR+ filing pages.

Return exactly this JSON shape:
{
  "accounting_standard": "IFRS or other standard stated in the filing",
  "currency": "currency stated in the filing, e.g. CAD or USD",
  "scale": "scale stated in the filing, e.g. thousands or millions",
  "fiscal_year_end": "period end date or fiscal year end stated in the statements",
  "filing_date": "document filing/cover/approval/signature date in YYYY-MM-DD if clearly present, otherwise null",
  "sector_inferred": "primary sector or industry inferred from filing content, e.g. 'Banking' or 'Real Estate (REIT)', otherwise null",
  "statements": {
    "balance_sheet": [
      {"label": "verbatim label", "values": {"period label": 123}, "confidence": 0.95}
    ],
    "income_statement": [
      {"label": "verbatim label", "values": {"period label": 123}, "confidence": 0.95}
    ],
    "cash_flow": [
      {"label": "verbatim label", "values": {"period label": 123}, "confidence": 0.95}
    ]
  }
}

Pages used:
__PAGES_JSON__

Page text:
__PAGE_TEXT__
"""


def _cache_control() -> dict:
    return {"type": "ephemeral", "ttl": "1h"}


def _sedar_temp_dir() -> Path:
    path = LIBRARY_DIR / "sedar"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _top_quarter_text(page_text: str) -> str:
    lines = [line.strip() for line in (page_text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    cutoff = max(1, (len(lines) + 3) // 4)
    return "\n".join(lines[:cutoff])


def _numeric_token_count(page_text: str) -> int:
    return len(re.findall(r"(?<![A-Za-z])\(?-?\$?\d[\d,]*(?:\.\d+)?\)?%?", page_text or ""))


def _locate_statement_pages_from_texts(page_texts: list[str]) -> dict[str, list[int]]:
    found: dict[str, set[int]] = {key: set() for key in STATEMENT_KEYS}

    for page_num, page_text in enumerate(page_texts):
        if _numeric_token_count(page_text) < 10:
            continue

        top_text = _top_quarter_text(page_text)
        for statement_key, pattern in HEADING_PATTERNS.items():
            if pattern.search(top_text):
                found[statement_key].add(page_num)
                if page_num + 1 < len(page_texts):
                    found[statement_key].add(page_num + 1)

    return {key: sorted(found[key]) for key in STATEMENT_KEYS}


def locate_statement_pages(pdf_path) -> dict[str, list[int]]:
    page_texts: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_texts.append(page.extract_text() or "")

    return _locate_statement_pages_from_texts(page_texts)


def _ordered_unique_pages(pages: dict[str, list[int]]) -> list[int]:
    ordered = []
    seen = set()
    for page_num in COVER_PAGE_INPUT_PAGES:
        ordered.append(page_num)
        seen.add(page_num)
    for key in STATEMENT_KEYS:
        for page_num in pages.get(key, []):
            if isinstance(page_num, int) and page_num >= 0 and page_num not in seen:
                ordered.append(page_num)
                seen.add(page_num)
    return ordered


def _extract_located_page_text(pdf_path, pages: dict[str, list[int]]) -> str:
    selected_pages = _ordered_unique_pages(pages)
    if not selected_pages:
        return ""

    sections = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num in selected_pages:
            if page_num >= len(pdf.pages):
                continue
            text = pdf.pages[page_num].extract_text() or ""
            sections.append(f"\n\n--- PAGE {page_num} ---\n{text}")

    return "".join(sections).strip()


def _response_text(response) -> str:
    return next((block.text for block in response.content if getattr(block, "type", "") == "text"), "")


def _strip_json_fences(raw: str) -> str:
    text = (raw or "").strip()
    # Closing fence optional: a max_tokens truncation eats it, and requiring
    # it left the leading ``` in place — json.loads then failed at char 0
    # (Call 4 bug class, fixed codebase-wide 2026-07-11).
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*(?:```|$)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text


def _parse_number(value):
    if value is None or isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text or text in {"-", "--"}:
        return None

    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    text = text.replace(",", "").replace("$", "").replace("%", "").strip()

    try:
        number = float(text)
    except ValueError:
        return value

    if negative:
        number = -number
    if number.is_integer():
        return int(number)
    return number


def _confidence(value) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, parsed))


def _normalize_sector_inferred(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_filing_date(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    text = value.strip()
    if not text:
        return None

    text = re.sub(r"(?i)\bdated\s+as\s+of\b", "", text).strip(" ,:")
    patterns = (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d %Y",
        "%b %d %Y",
    )
    for pattern in patterns:
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue

    match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if match:
        return match.group(1)
    return None


def _normalize_statement_items(items) -> list[SedarLineItem]:
    normalized = []
    if not isinstance(items, list):
        return normalized

    for item in items:
        if not isinstance(item, dict):
            continue
        values = item.get("values") or {}
        if not isinstance(values, dict):
            values = {}
        normalized.append(
            {
                "label": str(item.get("label") or ""),
                "values": {str(period): _parse_number(value) for period, value in values.items()},
                "confidence": _confidence(item.get("confidence", 0.0)),
            }
        )

    return normalized


def _normalize_extraction_payload(data: dict) -> dict:
    statements = data.get("statements") or {}
    if not isinstance(statements, dict):
        statements = {}

    normalized_statements = {
        "balance_sheet": _normalize_statement_items(statements.get("balance_sheet")),
        "income_statement": _normalize_statement_items(statements.get("income_statement")),
        "cash_flow": _normalize_statement_items(statements.get("cash_flow")),
    }

    # company_name is additive (2026-07-07): absent on all pre-existing
    # cached extractions, and every consumer reads it with .get plus a
    # filename fallback — honest absence, no schema bump (CB-011/012/013
    # reasoning). None (not "") when missing, matching filing_date.
    company_name = str(data.get("company_name") or "").strip() or None

    return {
        "company_name": company_name,
        "accounting_standard": str(data.get("accounting_standard") or ""),
        "currency": str(data.get("currency") or ""),
        "scale": str(data.get("scale") or ""),
        "fiscal_year_end": str(data.get("fiscal_year_end") or ""),
        "filing_date": _normalize_filing_date(data.get("filing_date")),
        "sector_inferred": _normalize_sector_inferred(data.get("sector_inferred")),
        "statements": normalized_statements,
    }


def _parse_extraction_json(raw: str) -> dict:
    return _normalize_extraction_payload(json.loads(_strip_json_fences(raw)))


def _api_key() -> str:
    load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise SedarExtractionError("ANTHROPIC_API_KEY not found — the app was started without secrets injected. There is no .env anymore (SOPS migration 2026-07-08): relaunch with .\run.bat, or run Import-Secrets in PowerShell before streamlit run app.py.")
    return api_key


# Output budget for the extraction response. Bank-scale filings (TD FY2025)
# legitimately need more than the old 8,000-token cap: their statement JSON
# alone exceeded it and the response was truncated mid-string.
MAX_EXTRACTION_OUTPUT_TOKENS = 32_000


def _call_claude(
    client,
    user_prompt: str,
    *,
    system_prompt: str = SYSTEM_PROMPT,
    max_tokens: int = MAX_EXTRACTION_OUTPUT_TOKENS,
):
    # The 32k output budget exceeds the SDK's non-streaming 10-minute request
    # ceiling, so the call streams and returns the accumulated final message —
    # the same Message shape (content, stop_reason, usage) a create() returns.
    # The keyword params (2026-07-11, hedging-note pass) default to the
    # statement-extraction values, so that path's behavior is unchanged.
    with client.messages.stream(
        model=SEDAR_MODEL,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system_prompt, "cache_control": _cache_control()}],
        messages=[{"role": "user", "content": user_prompt}],
        # sonnet-5 emits thinking blocks by default, which would consume the
        # output budget and shift content[0]; extraction needs deterministic
        # text only, so thinking is disabled here (2026-07-08).
        thinking={"type": "disabled"},
    ) as stream:
        return stream.get_final_message()


def _raise_if_truncated(response, *, budget: int = MAX_EXTRACTION_OUTPUT_TOKENS, what: str = "statements") -> None:
    """Fail honestly when the model ran out of output budget.

    A truncated response is not malformed JSON — retrying with the same
    budget can never succeed, so raise the real cause instead of letting
    the JSON parser report a misleading 'unterminated string' error.
    """
    if getattr(response, "stop_reason", None) == "max_tokens":
        raise SedarExtractionError(
            "SEDAR+ extraction response exceeded the model output budget "
            f"({budget} tokens, stop_reason=max_tokens). "
            f"The filing's {what} are larger than one extraction response can hold.",
            _response_text(response),
        )


def extract_statements(pdf_path, pages: dict) -> dict:
    page_text = _extract_located_page_text(pdf_path, pages)
    client = _make_client(_api_key())

    user_prompt = (
        USER_PROMPT_TEMPLATE
        .replace("__PAGES_JSON__", json.dumps(pages, indent=2))
        .replace("__PAGE_TEXT__", page_text)
    )

    response = _call_claude(client, user_prompt)
    _raise_if_truncated(response)
    raw = _response_text(response)

    try:
        return _parse_extraction_json(raw)
    except json.JSONDecodeError:
        fix_prompt = (
            f"{user_prompt}\n\nYour previous response was not valid JSON. "
            "Return the same extraction again as valid JSON only, with no markdown fences or prose."
        )
        retry_response = _call_claude(client, fix_prompt)
        _raise_if_truncated(retry_response)
        retry_raw = _response_text(retry_response)
        try:
            return _parse_extraction_json(retry_raw)
        except json.JSONDecodeError as exc:
            raise SedarExtractionError(f"Claude response could not be parsed as JSON: {exc}", retry_raw) from exc


def _extraction_confidence(statements: SedarStatements) -> float:
    confidences = []
    for items in statements.values():
        for item in items:
            confidences.append(_confidence(item.get("confidence")))
    return min(confidences) if confidences else 0.0


def _first_statement_value(item: dict) -> int | float | None:
    values = item.get("values") or {}
    if not isinstance(values, dict):
        return None

    annual_candidates = []
    for idx, (period, value) in enumerate(values.items()):
        period_text = str(period)
        period_lower = period_text.lower()
        if (
            "year ended" not in period_lower
            and "years ended" not in period_lower
            and not period_lower.startswith("year ")
        ):
            continue
        match = re.search(r"(\d{4})", period_text)
        year = int(match.group(1)) if match else -1
        annual_candidates.append((year, idx, value))
    if annual_candidates:
        return sorted(annual_candidates, key=lambda row: (row[0], -row[1]), reverse=True)[0][2]

    return next(iter(values.values()), None)


def attach_mapping(extraction_result: dict) -> dict:
    statements = extraction_result.get("statements") or {}
    # Single source of truth (shared with the fixture/registry path) for which
    # statements feed the mapper — mining-family + resource include cash flow
    # so operating_cash_flow / capex map (CB-021).
    statement_keys = list(mapper_statement_keys(extraction_result.get("sector_inferred")))

    line_items = []
    if isinstance(statements, dict):
        for statement_key in statement_keys:
            rows = statements.get(statement_key)
            if not isinstance(rows, list):
                continue
            for item in rows:
                if not isinstance(item, dict):
                    continue
                line_items.append({
                    "label": item.get("label"),
                    "value": _first_statement_value(item),
                    "confidence": item.get("confidence"),
                    "statement": statement_key,
                })

    enriched = dict(extraction_result)
    enriched["mapping"] = map_line_items(
        line_items,
        str(extraction_result.get("accounting_standard") or ""),
        sector=extraction_result.get("sector_inferred"),
    )
    return enriched


def extract_sedar_filing(pdf_path) -> SedarExtraction:
    pages = locate_statement_pages(pdf_path)
    extracted = extract_statements(pdf_path, pages)
    statements = extracted["statements"]

    result = {
        "source": "sedar_pdf",
        "schema_version": SCHEMA_VERSION,
        "company_name": extracted.get("company_name"),
        "accounting_standard": extracted.get("accounting_standard", ""),
        "currency": extracted.get("currency", ""),
        "scale": extracted.get("scale", ""),
        "fiscal_year_end": extracted.get("fiscal_year_end", ""),
        "filing_date": extracted.get("filing_date"),
        "sector_inferred": extracted.get("sector_inferred"),
        "statements": statements,
        "extraction_confidence": _extraction_confidence(statements),
        "pages_used": pages,
    }
    return attach_mapping(result)


# ===========================================================================
# HEDGING-BOOK NOTE EXTRACTION (design: docs/HEDGING_BOOK_SPEC.md)
#
# A SEPARATE targeted pass over the derivative/financial-instruments NOTE of
# an already-ingested statement PDF. Deliberately independent of the primary
# statement extraction: the statement SYSTEM_PROMPT forbids notes and MUST
# NOT be touched (Option A cross-filer drift-risk class). Output never
# reaches the statement mapper — it has its own normalized schema.
# ===========================================================================

MAX_HEDGING_OUTPUT_TOKENS = 16_000
# Bound the note-page selection so an over-eager locator (full annual reports
# repeat hedge tables in the MD&A) can't blow up the prompt. Disclosed, not
# silent: extract_hedging_note records dropped pages in the result.
MAX_HEDGING_NOTE_PAGES = 8

# Locator predicate, tuned empirically 2026-07-11 against real filings:
# Peyto FY2025 (note pp. 24-26, exact hit), TOU FY2025 (pp. 64-65, exact),
# CNQ FY2024 ("16. FINANCIAL INSTRUMENTS" p. 17, found unprompted). The
# predicate is recall-biased — full-annual-report shapes (ARX) also pick up
# MD&A risk-management tables, which disclose the same book; the extraction
# prompt filters irrelevant content.
_HEDGING_VOCAB = re.compile(
    r"\b(?:swaps?|collars?|fixed\s+price|notional|call\s+options?|derivative)\b",
    re.IGNORECASE,
)
_HEDGING_TABLE_SIGNALS = re.compile(
    r"(?:daily\s+volume"
    r"|mmbtu/d|bbls?/d"
    r"|volume\s*\((?:gj|mmbtu|bbls?)\)"
    r"|(?:usd|cad)\$?/(?:mmbtu|bbls?|gj|usd)"
    r"|\((?:cad|usd)/(?:gj|mmbtu|bbl|usd)\)"
    r"|rate\s*\(cad/usd\))",
    re.IGNORECASE,
)


def _locate_derivative_note_pages_from_texts(page_texts: list[str]) -> list[int]:
    """Pages that look like derivative/hedging disclosure tables.

    Content-density scan, NOT the top-quarter heading scan the statement
    locator uses — note headings vary too much across filers ("Financial
    instruments", "Risk management", "Derivative financial instruments").
    """
    hits = []
    for page_num, page_text in enumerate(page_texts):
        text = page_text or ""
        if _numeric_token_count(text) < 10:
            continue
        if len(_HEDGING_VOCAB.findall(text)) >= 3 and _HEDGING_TABLE_SIGNALS.search(text):
            hits.append(page_num)
    return hits


def locate_derivative_note_pages(pdf_path) -> list[int]:
    page_texts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_texts.append(page.extract_text() or "")
    return _locate_derivative_note_pages_from_texts(page_texts)


HEDGING_SYSTEM_PROMPT = """You are extracting the derivative/hedging disclosures from the NOTES of a Canadian SEDAR+ financial-statement PDF for FinLens.

Respond ONLY with valid JSON. Do not include markdown fences, a preamble, comments, or trailing prose.

Extract ONLY derivative/hedging positions and related disclosures from the supplied note pages: commodity contracts, foreign-exchange contracts, interest-rate contracts, their fair values, mark-to-market disclosures, price sensitivities, and contracts entered into subsequent to the period end. Ignore any unrelated content on the supplied pages (credit risk, liquidity risk, receivable aging, MD&A prose).

Filers present these tables in two geometries; normalize BOTH into flat position records, one record per (instrument, period):
1. Period-rows: one table per index, rows are quarters/periods with volume and price columns.
2. Instrument-rows x year-columns: rows are instrument types, columns are years, with weighted-average volumes and prices per year and often a fair value per instrument. Emit one record per instrument-year cell that has a volume.

Rules for every position record:
- Keep labels, indices, and period text VERBATIM as printed (e.g. "AECO 7A Monthly", "Q1 2026", "2027", "April 2026 - October 2026").
- instrument must be one of: "fixed_price_swap", "swap", "collar", "call_option", "basis_swap", "forward", "costless_collar", "interest_rate_swap", "other". Use "collar" whenever a price RANGE is printed; put the low bound in price_floor and the high bound in price_ceiling and leave price null. Otherwise put the single price in price and leave floor/ceiling null.
- Parse parentheses as negatives; strip thousands separators and currency symbols from numbers; use plain JSON numbers.
- volume_unit / price_unit / amount_unit verbatim as printed (e.g. "GJ/d", "mmbtu/d", "bbls/d", "CAD/GJ", "USD/MMBtu", "USD (millions)/month").
- fair_value: only when the filing prints a fair value FOR THAT ROW; otherwise null. Report fair values in the filing's stated scale, and state that scale in fair_value_scale.
- source_page: the page number from the "--- PAGE N ---" marker the record came from.
- period_start_year: the first calendar year in the period text as an integer, null if unclear.
- Do NOT guess or interpolate values. A missing value is null. Do NOT invent labels for unlabeled rows; use null and set verbatim_notes to describe the row.

Top-level JSON shape required:
{
  "as_of": "period-end date the positions are stated at, as printed, or null",
  "fair_value_total": number or null,
  "fair_value_scale": "thousands / millions / as-printed scale for fair values, or null",
  "commodity_positions": [
    {"commodity": "natural_gas|oil|propane|other", "index": "verbatim index/benchmark", "instrument": "...",
     "period_label": "verbatim", "period_start_year": 2026, "volume": 240000, "volume_unit": "GJ/d",
     "price": 4.17, "price_floor": null, "price_ceiling": null, "price_unit": "CAD/GJ",
     "fair_value": null, "source_page": 24, "verbatim_notes": null}
  ],
  "fx_positions": [
    {"instrument": "forward|costless_collar|other", "direction": "verbatim, e.g. 'Sold USD Contracts', or null",
     "period_label": "verbatim", "period_start_year": 2026, "amount": 51.7, "amount_unit": "USD millions",
     "rate": 1.3688, "rate_floor": null, "rate_ceiling": null, "rate_unit": "CAD/USD",
     "fair_value": null, "source_page": 25, "verbatim_notes": null}
  ],
  "interest_rate_positions": [
    {"instrument": "interest_rate_swap", "term_label": "verbatim term", "notional": 50, "notional_unit": "CAD millions",
     "fixed_rate_pct": 3.28, "floating_benchmark": "CORRA", "fair_value": null, "source_page": 26, "verbatim_notes": null}
  ],
  "mtm_disclosures": [
    {"scope": "commodity|fx|interest_rate|total", "amount": 123.3, "amount_unit": "CAD millions",
     "verbatim": "the sentence as printed", "source_page": 25}
  ],
  "sensitivities": [
    {"verbatim": "the sensitivity sentence as printed", "source_page": 25}
  ],
  "subsequent_event_positions": [ same record shapes as above, from contracts entered AFTER the period end ],
  "extraction_confidence": 0.0-1.0
}
"""


HEDGING_USER_PROMPT_TEMPLATE = """Extract the derivative/hedging disclosures from these located note pages.

Pages used:
__PAGES_JSON__

Page text:
__PAGE_TEXT__
"""


def _normalize_hedging_records(items, numeric_keys: tuple[str, ...]) -> list[dict]:
    normalized = []
    if not isinstance(items, list):
        return normalized
    for item in items:
        if not isinstance(item, dict):
            continue
        record = {}
        for key, value in item.items():
            record[str(key)] = _parse_number(value) if str(key) in numeric_keys else value
        normalized.append(record)
    return normalized


_COMMODITY_NUMERIC = ("volume", "price", "price_floor", "price_ceiling", "fair_value", "period_start_year", "source_page")
_FX_NUMERIC = ("amount", "rate", "rate_floor", "rate_ceiling", "fair_value", "period_start_year", "source_page")
_IR_NUMERIC = ("notional", "fixed_rate_pct", "fair_value", "source_page")
_MTM_NUMERIC = ("amount", "source_page")


def _normalize_hedging_payload(data: dict) -> dict:
    subsequent = data.get("subsequent_event_positions")
    return {
        "as_of": (str(data.get("as_of")).strip() or None) if data.get("as_of") else None,
        "fair_value_total": _parse_number(data.get("fair_value_total")),
        "fair_value_scale": (str(data.get("fair_value_scale")).strip() or None) if data.get("fair_value_scale") else None,
        "commodity_positions": _normalize_hedging_records(data.get("commodity_positions"), _COMMODITY_NUMERIC),
        "fx_positions": _normalize_hedging_records(data.get("fx_positions"), _FX_NUMERIC),
        "interest_rate_positions": _normalize_hedging_records(data.get("interest_rate_positions"), _IR_NUMERIC),
        "mtm_disclosures": _normalize_hedging_records(data.get("mtm_disclosures"), _MTM_NUMERIC),
        "sensitivities": _normalize_hedging_records(data.get("sensitivities"), ("source_page",)),
        "subsequent_event_positions": _normalize_hedging_records(
            subsequent, _COMMODITY_NUMERIC + _FX_NUMERIC + _IR_NUMERIC
        ),
        "extraction_confidence": _confidence(data.get("extraction_confidence", 0.0)),
    }


def _hedging_figure_presence(hedging_book: dict, note_text: str) -> dict:
    """Deterministic guard: every extracted number must appear in the note text.

    Same concept as Call 1's figure-presence guard — an extracted value that
    is nowhere in the source pages is a fabrication signal. String-normalized
    comparison (commas stripped both sides); fails OPEN into an honest
    'unverified' count the display must surface, never a silent pass.
    """
    haystack = (note_text or "").replace(",", "")
    checked = 0
    missing: list[str] = []

    def _probe(value) -> None:
        nonlocal checked
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return
        checked += 1
        magnitude = abs(value)
        candidates = {f"{magnitude:g}"}
        if float(magnitude).is_integer():
            candidates.add(str(int(magnitude)))
        else:
            candidates.add(f"{magnitude:.2f}")
        if not any(c in haystack for c in candidates):
            missing.append(f"{value}")

    for block in ("commodity_positions", "fx_positions", "interest_rate_positions",
                  "mtm_disclosures", "subsequent_event_positions"):
        for record in hedging_book.get(block) or []:
            for key in ("volume", "price", "price_floor", "price_ceiling", "amount",
                        "rate", "rate_floor", "rate_ceiling", "notional",
                        "fixed_rate_pct", "fair_value"):
                _probe(record.get(key))
    _probe(hedging_book.get("fair_value_total"))

    return {"checked": checked, "missing_count": len(missing), "missing": missing[:20]}


def extract_hedging_note(pdf_path) -> dict:
    """Extract the derivative/hedging note into the normalized hedging_book shape.

    Returns {"status": "no_note_detected", ...} without any API spend when
    the locator finds nothing — itself a finding (an unhedged filer).
    """
    located = locate_derivative_note_pages(pdf_path)
    if not located:
        return {"status": "no_note_detected", "source_pages": [], "dropped_pages": []}

    pages = located[:MAX_HEDGING_NOTE_PAGES]
    dropped = located[MAX_HEDGING_NOTE_PAGES:]

    sections = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num in pages:
            if page_num >= len(pdf.pages):
                continue
            text = pdf.pages[page_num].extract_text() or ""
            sections.append(f"\n\n--- PAGE {page_num} ---\n{text}")
    note_text = "".join(sections).strip()

    client = _make_client(_api_key())
    user_prompt = (
        HEDGING_USER_PROMPT_TEMPLATE
        .replace("__PAGES_JSON__", json.dumps(pages))
        .replace("__PAGE_TEXT__", note_text)
    )

    response = _call_claude(
        client, user_prompt,
        system_prompt=HEDGING_SYSTEM_PROMPT,
        max_tokens=MAX_HEDGING_OUTPUT_TOKENS,
    )
    _raise_if_truncated(response, budget=MAX_HEDGING_OUTPUT_TOKENS, what="hedging disclosures")
    raw = _response_text(response)

    try:
        payload = json.loads(_strip_json_fences(raw))
    except json.JSONDecodeError:
        fix_prompt = (
            f"{user_prompt}\n\nYour previous response was not valid JSON. "
            "Return the same extraction again as valid JSON only, with no markdown fences or prose."
        )
        retry = _call_claude(
            client, fix_prompt,
            system_prompt=HEDGING_SYSTEM_PROMPT,
            max_tokens=MAX_HEDGING_OUTPUT_TOKENS,
        )
        _raise_if_truncated(retry, budget=MAX_HEDGING_OUTPUT_TOKENS, what="hedging disclosures")
        try:
            payload = json.loads(_strip_json_fences(_response_text(retry)))
        except json.JSONDecodeError as exc:
            raise SedarExtractionError(
                f"Hedging-note response could not be parsed as JSON: {exc}", _response_text(retry)
            ) from exc

    hedging_book = _normalize_hedging_payload(payload if isinstance(payload, dict) else {})
    hedging_book["status"] = "extracted"
    hedging_book["source_pages"] = pages
    hedging_book["dropped_pages"] = dropped
    hedging_book["figure_presence"] = _hedging_figure_presence(hedging_book, note_text)
    return hedging_book


# ===========================================================================
# MD&A OPERATIONAL-METRICS PAGE LOCATOR (design: docs/MDA_FETCHER_SPEC.md,
# Stage 1; v1 = the ratified O&G upstream pack)
#
# A SEPARATE targeted pass over the MD&A prose of an already-ingested PDF
# (in-PDF-first sourcing: combined statements+MD&A packs like TOU, full
# annual reports like ARX). Same architecture as the hedging locator above:
# content-density scan, never a heading scan — ARX's MD&A pages don't even
# repeat the "Management's Discussion and Analysis" heading in extracted
# page text, while TOU's repeat it on every page (header artifact), so the
# heading is deliberately NOT a signal. Output will feed extract_mda_metrics
# (Stage 1b) — its own prompt pair and schema; never the statement mapper.
# ===========================================================================

# The O&G MD&A pack spans more disclosure tables than the hedging note
# (volumes + netback + FFO + realized prices), so the cap is wider than
# MAX_HEDGING_NOTE_PAGES. Over-cap pages are dropped by ASCENDING score
# (not document order) and disclosed, never silent.
MAX_MDA_PAGES = 12

# Signal set + weights, tuned empirically 2026-07-12 against the five O&G
# PDFs on disk: TOU FY2025 combined pack (netback tables PDF pp. 31-35,
# volumes pp. 7-8, realized prices p. 11), ARX FY2025 full annual report
# (netback pp. 29-32 + 60-61, FFO pp. 40-43/62, production pp. 21-23), and
# the three statements-only packs (CNQ FY2024, Peyto FY2025, WCP FY2025)
# which must yield ZERO pages so the fetch-fallback lane can fire.
_MDA_NETBACK_RE = re.compile(r"\bnetbacks?\b", re.IGNORECASE)
_MDA_VOLUME_UNITS_RE = re.compile(
    r"\b(?:m?boe/d|mmcf/d|m?bbls?/d|gj/d|boe\s+per\s+day)\b", re.IGNORECASE
)
_MDA_PER_BOE_RE = re.compile(r"(?:\$|per\s)\s*/?\s*boe\b|\bper\s+boe\b", re.IGNORECASE)
_MDA_FUNDS_FLOW_RE = re.compile(
    r"\bfunds\s+(?:flow|from\s+operations)\b|\bfree\s+funds\s+flow\b", re.IGNORECASE
)
_MDA_REALIZED_PRICE_RE = re.compile(
    r"\b(?:average\s+)?realized\s+prices?\b", re.IGNORECASE
)

# A page must carry real tabular density AND a mix of pack signals.
_MDA_MIN_NUMERIC_TOKENS = 15
_MDA_MIN_PAGE_SCORE = 6

# DOCUMENT-LEVEL ANCHOR GATE (the load-bearing negative): the per-boe
# netback table is the O&G MD&A signature — no page with dense netback
# vocabulary means the document has no O&G MD&A operational section, and
# the locator returns nothing so the caller reports no_mda_detected
# honestly (routing statements-only filers to the fetch fallback). Without
# this gate, statements-only packs fire on their notes: WCP's capital-
# management note says "funds flow" 8 times on one page, and hedge notes
# carry volume units (TOU pp. 64-65) — empirically confirmed 2026-07-12.
_MDA_ANCHOR_MIN_NETBACK_HITS = 2
_MDA_ANCHOR_MIN_NUMERIC_TOKENS = 20


def _score_mda_page(page_text: str) -> tuple[int, int, int]:
    """Return (pack_score, numeric_token_count, netback_hits) for one page."""
    text = page_text or ""
    netback = len(_MDA_NETBACK_RE.findall(text))
    score = (
        3 * netback
        + 2 * len(_MDA_VOLUME_UNITS_RE.findall(text))
        + 2 * len(_MDA_PER_BOE_RE.findall(text))
        + 2 * len(_MDA_FUNDS_FLOW_RE.findall(text))
        + 2 * len(_MDA_REALIZED_PRICE_RE.findall(text))
    )
    return score, _numeric_token_count(text), netback


def _locate_mda_pages_from_texts(page_texts: list[str]) -> dict:
    """Pages that look like O&G MD&A operational-disclosure tables.

    Returns {"pages": [...], "dropped_pages": [...]} — both ascending;
    `pages` capped at MAX_MDA_PAGES by keeping the highest-scoring pages,
    `dropped_pages` disclosing the over-cap remainder. Both empty when the
    document has no netback anchor page (no O&G MD&A section present).

    Recall bias accepted (CB-034 mirror): statement-side hedge tables in a
    combined pack can qualify on volume units once the document is anchored;
    the extraction prompt filters non-MD&A content.
    """
    scored = []
    anchored = False
    for page_num, page_text in enumerate(page_texts):
        score, numerics, netback = _score_mda_page(page_text)
        if numerics >= _MDA_ANCHOR_MIN_NUMERIC_TOKENS and netback >= _MDA_ANCHOR_MIN_NETBACK_HITS:
            anchored = True
        if numerics >= _MDA_MIN_NUMERIC_TOKENS and score >= _MDA_MIN_PAGE_SCORE:
            scored.append((score, page_num))

    if not anchored or not scored:
        return {"pages": [], "dropped_pages": []}

    # Keep the strongest MAX_MDA_PAGES pages; emit both lists in page order.
    scored.sort(key=lambda item: (-item[0], item[1]))
    kept = sorted(page_num for _, page_num in scored[:MAX_MDA_PAGES])
    dropped = sorted(page_num for _, page_num in scored[MAX_MDA_PAGES:])
    return {"pages": kept, "dropped_pages": dropped}


def locate_mda_pages(pdf_path) -> dict:
    page_texts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_texts.append(page.extract_text() or "")
    return _locate_mda_pages_from_texts(page_texts)
