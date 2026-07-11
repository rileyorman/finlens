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


def _call_claude(client, user_prompt: str):
    # The 32k output budget exceeds the SDK's non-streaming 10-minute request
    # ceiling, so the call streams and returns the accumulated final message —
    # the same Message shape (content, stop_reason, usage) a create() returns.
    with client.messages.stream(
        model=SEDAR_MODEL,
        max_tokens=MAX_EXTRACTION_OUTPUT_TOKENS,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": _cache_control()}],
        messages=[{"role": "user", "content": user_prompt}],
        # sonnet-5 emits thinking blocks by default, which would consume the
        # output budget and shift content[0]; extraction needs deterministic
        # text only, so thinking is disabled here (2026-07-08).
        thinking={"type": "disabled"},
    ) as stream:
        return stream.get_final_message()


def _raise_if_truncated(response) -> None:
    """Fail honestly when the model ran out of output budget.

    A truncated response is not malformed JSON — retrying with the same
    budget can never succeed, so raise the real cause instead of letting
    the JSON parser report a misleading 'unterminated string' error.
    """
    if getattr(response, "stop_reason", None) == "max_tokens":
        raise SedarExtractionError(
            "SEDAR+ extraction response exceeded the model output budget "
            f"({MAX_EXTRACTION_OUTPUT_TOKENS} tokens, stop_reason=max_tokens). "
            "The filing's statements are larger than one extraction response can hold.",
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
