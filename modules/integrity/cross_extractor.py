"""
Gemini second-extractor cross-check for campaign filings.

V1 is fail-closed and non-blocking: every failure returns an explicit
UNCHECKED result, and successful runs write a typed integrity-log signal.
"""
from __future__ import annotations

import json
import platform
import re
import ssl
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx

from modules.campaign_pdf import resolve_campaign_pdf


DEFAULT_MODEL = "gemini-3.5-flash"
CROSS_EXTRACTOR_VERSION = "2"
UNCHECKED_PDF_UNRESOLVABLE = "pdf_unresolvable"
UNCHECKED_NO_KEY = "no_key"
UNCHECKED_NO_MAPPED_FIELDS = "no_mapped_fields"
UNCHECKED_GEMINI_ERROR = "gemini_error"
UNCHECKED_PARSE_ERROR = "parse_error"

FlagSeverity = Literal["hard", "soft"]

_NOTE_REFERENCE_RE = re.compile(r"\(\s*note\s*\d+\s*\)", flags=re.IGNORECASE)
_TRAILING_FOOTNOTE_REFERENCE_RE = re.compile(
    r"\s*\(\s*(?:[ivxlcdm]{1,6}|[a-z]|\d{1,2})\s*\)\s*$",
    flags=re.IGNORECASE,
)
_LEADING_TOTAL_RE = re.compile(r"^total\s+")
_TRAILING_TOTAL_RE = re.compile(r"\s+total$")
_WHITESPACE_RE = re.compile(r"\s+")

FIELD_DESCRIPTIONS = {
    "cost_of_revenue": "Costs directly attributable to revenue, cost of sales, or equivalent.",
    "depletion_depreciation_amortization": "Resource-sector depletion, depreciation, and amortization expense.",
    "exploration_expense": "Mining or resource exploration expense.",
    "gross_profit": "Gross profit, or revenue less cost of revenue if clearly derivable.",
    "insurance_finance_result": "Net insurance finance income or expense under IFRS 17.",
    "insurance_revenue": "IFRS 17 insurance revenue.",
    "insurance_service_expenses": "IFRS 17 insurance service expenses.",
    "interest_expense": "Interest, finance costs, financial expenses, or equivalent expense.",
    "investment_property_fair_value_delta": "Fair value gain or loss on investment properties.",
    "mine_development_amortization": "Mining property, plant, mine development, or related amortization.",
    "net_income": "Net income, net earnings, profit, or loss attributable to the consolidated entity.",
    "net_insurance_service_result": "Insurance net service result under IFRS 17.",
    "net_interest_income": "Banking net interest income.",
    "net_investment_result": "Insurance net investment return or result.",
    "net_operating_income": "REIT net operating income or net rental income.",
    "operating_expense": "Resource-sector production or operating expense.",
    "operating_income": "Operating income, income from operations, or equivalent.",
    "production_costs": "Mining production costs.",
    "property_operating_costs": "REIT property operating costs or investment property operating expenses.",
    "provision_for_credit_losses": "Banking provision for credit losses.",
    "rental_revenue": "REIT rental revenue, investment property revenue, or equivalent.",
    "revenue": (
        "Total revenue, revenues, sales, or equivalent top-line revenue. "
        "For resource-sector filers: GROSS product sales before royalty deductions."
    ),
    "royalties": "Resource-sector royalties.",
    "total_assets": "Total assets from the consolidated balance sheet or statement of financial position.",
}


def normalize_source_label(label: str | None) -> str:
    text = "" if label is None else str(label)
    text = text.casefold()
    text = _NOTE_REFERENCE_RE.sub(" ", text)
    text = _TRAILING_FOOTNOTE_REFERENCE_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    text = _LEADING_TOTAL_RE.sub("", text)
    text = _TRAILING_TOTAL_RE.sub("", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def classify_flag_severity(finlens_label: str, gemini_label: str) -> FlagSeverity:
    if not str(gemini_label or "").strip():
        return "soft"
    if normalize_source_label(finlens_label) == normalize_source_label(gemini_label):
        return "hard"
    return "soft"


@dataclass
class CrossExtractorField:
    canonical_field: str
    finlens_value: float | None
    gemini_value: float | None
    status: str
    finlens_label: str
    gemini_label: str
    severity: FlagSeverity | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.severity is None:
            data.pop("severity")
        return data


@dataclass
class CrossCheckResult:
    state: str
    fields: list[CrossExtractorField]
    timestamp: str
    ticker: str
    fiscal_year: str
    filing_accession: str
    model: str
    checker_version: str = CROSS_EXTRACTOR_VERSION
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": "cross_extractor_agreement",
            "timestamp": self.timestamp,
            "ticker": self.ticker,
            "fiscal_year": self.fiscal_year,
            "filing_accession": self.filing_accession,
            "state": self.state,
            "reason": self.reason,
            "model": self.model,
            "checker_version": self.checker_version,
            "cross_extractor_fields": [field.to_dict() for field in self.fields],
        }


def _filing_accession(registry_entry: dict[str, Any] | None) -> str:
    entry = registry_entry or {}
    for key in ("filing_accession", "accession"):
        value = entry.get(key)
        if value:
            return str(value)
    fixture_path = entry.get("fixture_path")
    if fixture_path:
        return Path(str(fixture_path)).name
    ticker = entry.get("ticker") or "UNKNOWN"
    fiscal_year = entry.get("fiscal_year") or entry.get("period") or "UNKNOWN"
    return f"{ticker}|{fiscal_year}"


def _result_base(registry_entry: dict[str, Any] | None, model: str) -> dict[str, Any]:
    entry = registry_entry or {}
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ticker": str(entry.get("ticker") or ""),
        "fiscal_year": str(entry.get("fiscal_year") or entry.get("period") or ""),
        "filing_accession": _filing_accession(entry),
        "model": model,
        "checker_version": CROSS_EXTRACTOR_VERSION,
    }


def _unchecked_result(
    registry_entry: dict[str, Any] | None,
    model: str,
    reason: str,
) -> CrossCheckResult:
    return CrossCheckResult(
        state="UNCHECKED",
        fields=[],
        reason=reason,
        **_result_base(registry_entry, model),
    )


def _finalize_result(result: CrossCheckResult) -> CrossCheckResult:
    try:
        from .log import append_cross_extractor_to_log

        append_cross_extractor_to_log(result)
    except Exception:
        pass
    return result


def _field_lines(fields: dict[str, dict[str, Any]]) -> str:
    lines = []
    for field in fields:
        description = FIELD_DESCRIPTIONS.get(field, "FinLens canonical mapped field from the stored fixture.")
        lines.append(f"- {field}: {description}")
    return "\n".join(lines)


def _prompt(
    registry_entry: dict[str, Any] | None,
    fields: dict[str, dict[str, Any]],
) -> str:
    entry = registry_entry or {}
    company = entry.get("company_name") or entry.get("ticker") or "the filing"
    fiscal_year = entry.get("fiscal_year") or entry.get("fiscal_year_end") or ""
    currency = entry.get("currency") or "the filing currency"
    scale = entry.get("scale") or "the filing native scale"
    field_names = ", ".join(fields)
    return f"""
You are independently validating FinLens extraction for {company} {fiscal_year}.

Read the whole attached PDF and extract values only from primary consolidated
financial statement lines. Consolidated-statement-level lines are acceptable;
note-only components, note breakdown rows, roll-forwards, and component
subtotals from the notes are never acceptable substitutes. If a canonical field
is available only in the notes, or only as a note component, omit that field.
Return JSON ONLY, with no prose and no markdown fences, in
this exact shape:
{{"fields": [{{"canonical_field": "...", "value": <number>, "source_label": "...", "page": <int>}}]}}

Canonical fields to extract: {field_names}.

Field descriptions:
{_field_lines(fields)}

Use the filing's native units: currency={currency}, scale={scale}. Preserve
sign conventions. Use consolidated income, operations, earnings, or profit/loss
statements for income-statement fields; use the consolidated balance sheet or
statement of financial position for balance-sheet fields such as total_assets.
If a gross_profit value is not explicitly shown but is directly derivable from
displayed revenue and cost of revenue lines, return the derived value and use a
source_label that says it is derived. Omit any field you cannot find rather than
guessing.
""".strip()


def _gemini_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text:
        return str(text)
    return str(response)


def _strip_json_response(raw: str) -> str:
    text = raw.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end >= start:
        return text[start : end + 1]
    return text


def _parse_gemini_json(raw: str) -> dict[str, Any]:
    cleaned = _strip_json_response(raw)
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("fields"), list):
        raise ValueError("Gemini JSON must be an object with a fields list")
    return parsed


def _normalize_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)

    text = str(value).strip()
    if not text or text in {"-", "--", "n/a", "N/A"}:
        return None

    negative = text.startswith("(") and text.endswith(")")
    cleaned = text.replace(",", "")
    cleaned = re.sub(
        r"(?i)\b(cad|c\$|usd|us\$|dollars?|millions?|million|mn|thousands?|thousand|bn|billion)\b",
        "",
        cleaned,
    )
    cleaned = cleaned.replace("$", "").replace("(", "").replace(")", "")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None

    number = float(match.group(0))
    return -abs(number) if negative else number


def _same_sign(left: float, right: float) -> bool:
    return (left >= 0 and right >= 0) or (left < 0 and right < 0)


def _status(claude_value: float | None, gemini_value: float | None) -> str:
    if gemini_value is None:
        return "GEMINI_MISSING"
    if claude_value is None:
        return "CONFLICT"
    denominator = max(abs(claude_value), 1.0)
    relative_diff = abs(claude_value - gemini_value) / denominator
    if relative_diff <= 0.005 and _same_sign(claude_value, gemini_value):
        return "AGREE"
    return "CONFLICT"


def _gemini_fields_by_name(parsed: dict[str, Any], expected_fields: set[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in parsed.get("fields", []):
        if not isinstance(item, dict):
            continue
        field = item.get("canonical_field")
        if field in expected_fields:
            result[str(field)] = item
    return result


def _field_results(
    claude_fields: dict[str, dict[str, Any]],
    gemini_fields: dict[str, dict[str, Any]],
) -> list[CrossExtractorField]:
    results: list[CrossExtractorField] = []
    for field, claude in claude_fields.items():
        gemini = gemini_fields.get(field)
        finlens_label = str(claude.get("source_label", ""))
        gemini_label = str(gemini.get("source_label", "")) if gemini else ""
        finlens_value = _normalize_number(claude.get("value"))
        gemini_value = _normalize_number(gemini.get("value")) if gemini else None
        status = _status(finlens_value, gemini_value)
        severity = (
            classify_flag_severity(finlens_label, gemini_label)
            if status == "CONFLICT"
            else None
        )
        results.append(
            CrossExtractorField(
                canonical_field=field,
                finlens_value=finlens_value,
                gemini_value=gemini_value,
                status=status,
                finlens_label=finlens_label,
                gemini_label=gemini_label,
                severity=severity,
            )
        )
    return results


def _aggregate_state(fields: list[CrossExtractorField]) -> str:
    statuses = {field.status for field in fields}
    if "CONFLICT" in statuses:
        return "FLAGGED"
    if "GEMINI_MISSING" in statuses:
        return "PARTIAL"
    return "VERIFIED"


def _make_httpx_client() -> httpx.Client:
    if platform.system() == "Windows":
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.load_default_certs()
        ssl_ctx.check_hostname = True
        return httpx.Client(verify=ssl_ctx, trust_env=False)
    return httpx.Client(trust_env=False)


def _run_gemini(pdf_path: Path, prompt: str, api_key: str, model: str) -> str:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is not installed. Install it with: "
            r".\venv\Scripts\python.exe -m pip install google-genai"
        ) from exc

    http_client = _make_httpx_client()
    try:
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(httpx_client=http_client),
        )
        pdf_part = types.Part.from_bytes(
            data=pdf_path.read_bytes(),
            mime_type="application/pdf",
        )
        response = client.models.generate_content(
            model=model,
            contents=[prompt, pdf_part],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        return _gemini_text(response)
    finally:
        http_client.close()


def cross_check_filing(
    registry_entry: dict[str, Any] | None,
    mapped: dict[str, dict[str, Any]],
    *,
    api_key: str | None,
    model: str,
) -> CrossCheckResult:
    pdf_path = resolve_campaign_pdf(registry_entry)
    if pdf_path is None:
        return _finalize_result(
            _unchecked_result(registry_entry, model, UNCHECKED_PDF_UNRESOLVABLE)
        )

    if not api_key:
        return _finalize_result(
            _unchecked_result(registry_entry, model, UNCHECKED_NO_KEY)
        )

    fields = mapped or {}
    if not fields:
        return _finalize_result(
            _unchecked_result(registry_entry, model, UNCHECKED_NO_MAPPED_FIELDS)
        )

    prompt = _prompt(registry_entry, fields)
    try:
        raw = _run_gemini(pdf_path, prompt, api_key, model)
    except Exception:
        return _finalize_result(
            _unchecked_result(registry_entry, model, UNCHECKED_GEMINI_ERROR)
        )

    try:
        parsed = _parse_gemini_json(raw)
    except (json.JSONDecodeError, ValueError):
        return _finalize_result(
            _unchecked_result(registry_entry, model, UNCHECKED_PARSE_ERROR)
        )

    gemini_fields = _gemini_fields_by_name(parsed, set(fields))
    field_results = _field_results(fields, gemini_fields)
    result = CrossCheckResult(
        state=_aggregate_state(field_results),
        fields=field_results,
        reason=None,
        **_result_base(registry_entry, model),
    )
    return _finalize_result(result)
