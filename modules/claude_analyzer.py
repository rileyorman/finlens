import platform
import ssl
import anthropic
import httpx
import json
import logging
import re
import unicodedata

from config import ANALYSIS_MODEL, MAX_FILING_CHARS, MAX_EXTRACTION_FRONT, MAX_EXTRACTION_BACK

# Model alias for the dashboard insights call (same tier as analysis)
DASHBOARD_MODEL = ANALYSIS_MODEL
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
OPUS_48_MODEL = "claude-opus-4-8"
MAX_CACHED_FILING_CHARS = 450_000
_LOGGER = logging.getLogger(__name__)
_UNIT_SCALE_WORDS = ("thousand", "million", "billion")


def _detect_unit_scale(currency: str) -> int:
    """Return multiplier to convert stored values to raw dollars."""
    if not isinstance(currency, str):
        return 1
    cur = (currency or "").lower()
    if _UNIT_SCALE_WORDS[0] in cur:
        return 1_000
    if _UNIT_SCALE_WORDS[1] in cur:
        return 1_000_000
    if _UNIT_SCALE_WORDS[2] in cur:
        return 1_000_000_000
    return 1


def _has_unit_scale_word(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.lower()
    return any(word in text for word in _UNIT_SCALE_WORDS)


def is_truncated_excerpt(text: str | None) -> bool:
    """True when stored filing text is almost certainly a truncated excerpt.

    Library entries and legacy text caches were historically written as
    text[:MAX_FILING_CHARS], so a stored document of exactly that length is a
    truncation signature, not a real document size. Excerpts that size were
    cut for the analysis calls (2-4) and usually end mid-document with no
    financial statements — feeding one to extraction (Call 1) yields either an
    honest FabricatedExtractionError or, pre-guard, fabricated numbers
    (reference incident: NVDA FY2026 re-analyse, 2026-07-03). A genuine
    document of exactly MAX_FILING_CHARS chars is astronomically unlikely; the
    cost of a false positive is only a PDF re-extraction or an honest error.
    """
    return text is not None and len(text) == MAX_FILING_CHARS


def is_legacy_scaled_financial_data_stale(
    financial_data: dict,
    schema_version: object,
    current_schema_version: int,
) -> bool:
    """Return True when reload cannot distinguish raw vs unscaled legacy values."""
    if not isinstance(financial_data, dict):
        return False
    if financial_data.get("_normalized") is True:
        return False
    if not (
        _has_unit_scale_word(financial_data.get("scale"))
        or _has_unit_scale_word(financial_data.get("currency"))
    ):
        return False
    try:
        stored_schema = int(schema_version)
    except (TypeError, ValueError):
        return True
    return stored_schema < current_schema_version


# Per-share line items (EPS, dividends per share, book value per share) are
# NOT expressed in the filing's unit scale: a "USD in thousands" filing still
# reports EPS as raw dollars-per-share. They must be exempt from unit scaling,
# and from K/M/B abbreviation on display.
# Matches per-share line items: "per share", "per common share", "per diluted
# share", "earnings per share", "dividends per common share", and "EPS". The
# qualifier window allows words like "common"/"diluted" between "per" and
# "share" so variants are not missed (a missed exemption 1000x-scales the value).
_PER_SHARE_RE = re.compile(r"\bper\b[\w\s\-,]{0,24}?\bshares?\b|\beps\b")

# Bank statements print an "Earnings per share (Canadian dollars)" HEADER with
# bare "Basic" / "Diluted" sub-rows; extraction stores the bare sub-labels, so
# the regex alone misses them (TD FY2025 cold slot: $11.57 basic EPS scaled
# x1M and rendered "$11.6M"). Exact-match only — longer labels such as "basic
# weighted average number of shares" are deliberately NOT exempted here.
_BARE_EPS_LABELS = {"basic", "diluted", "basic and diluted"}


def is_per_share_line_item(label) -> bool:
    """Return True when a statement line item is a per-share figure (EPS, DPS)."""
    text = str(label or "").lower()
    if _PER_SHARE_RE.search(text):
        return True
    return re.sub(r"[\s.,;:]+$", "", text).strip() in _BARE_EPS_LABELS


# Top-level scalar fields that carry the filing's unit scale and must be scaled
# to raw dollars at this boundary (see the "Normalize at the Boundary" principle
# in CLAUDE.md). app.py promotes EVERY mapped SEDAR canonical field to a
# top-level financial_data key, so the canonical portion below MUST stay in sync
# with the canonical fields in modules/integrity/sedar_aliases.json. That sync is
# machine-enforced by tests/test_sedar_scaling_whitelist.py -- do not hand-manage
# this from memory when adding a sector field.

# Market/derived scalars -- not SEDAR canonical fields (sourced from FMP/yfinance).
_MARKET_DERIVED_SCALE_FIELDS = frozenset({
    "free_cash_flow",
    "fcf",
    "market_cap",
    "shares_outstanding",
    "total_debt",
})

# SEDAR canonical fields that are dollar magnitudes -- scaled by the unit factor.
_CANONICAL_SCALE_FIELDS = frozenset({
    "capitalized_exploration_additions",
    "cash",
    "cost_of_revenue",
    "depletion_depreciation_amortization",
    "ebitda",
    "exploration_expense",
    "gross_profit",
    "insurance_finance_result",
    "insurance_revenue",
    "insurance_service_expenses",
    "interest_expense",
    "investment_property_fair_value_delta",
    "mine_development_amortization",
    "net_cash_used_in_operating_activities",
    "net_income",
    "net_insurance_service_result",
    "net_interest_income",
    "net_investment_result",
    "net_loss",
    "net_operating_income",
    "operating_expense",
    "operating_income",
    "operating_loss",
    "production_costs",
    "property_operating_costs",
    "provision_for_credit_losses",
    "rd_expense",
    "rental_revenue",
    "revenue",
    "royalties",
    "total_assets",
    "total_equity",
    "total_liabilities",
    "total_revenue_bank",
})

# SEDAR canonical fields that are NOT dollar magnitudes (ratios/margins) and must
# never be unit-scaled. Kept explicit so the sync test forces a deliberate
# scale/no-scale decision for every canonical field rather than defaulting.
_NON_SCALED_CANONICAL_FIELDS = frozenset({
    "gross_margin",  # ratio, not a currency magnitude
})

_TOP_LEVEL_SCALE_FIELDS = _MARKET_DERIVED_SCALE_FIELDS | _CANONICAL_SCALE_FIELDS


def normalize_financial_data(financial_data: dict) -> dict:
    """Scale financial_data values to raw dollars based on the currency unit.

    Returns the same dict mutated in place. Idempotent when _normalized is set.
    Currency labels are preserved; this performs unit scaling only, not FX.
    """
    if not isinstance(financial_data, dict):
        return financial_data

    if financial_data.get("_normalized") is True:
        return financial_data

    currency = financial_data.get("currency", "")
    scale_label = financial_data.get("scale") or currency
    scale = _detect_unit_scale(scale_label)

    if scale == 1:
        financial_data["_normalized"] = True
        return financial_data

    for section_key in ("income_statement", "balance_sheet", "cash_flow_statement"):
        rows = financial_data.get(section_key, [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            # Per-share figures are already raw dollars-per-share, not in the
            # filing's unit scale -- scaling them would 1000x the EPS.
            if is_per_share_line_item(row.get("line_item")):
                continue
            for value_key in ("value", "value_prior"):
                v = row.get(value_key)
                if isinstance(v, (int, float)):
                    row[value_key] = v * scale

    # Exporters and downstream consumers read these top-level scalars directly,
    # so scaling them here keeps Excel/memo/scenario/DCF outputs and every
    # promoted SEDAR canonical field on the same raw-dollar basis without
    # per-consumer scaling logic.
    for key in _TOP_LEVEL_SCALE_FIELDS:
        v = financial_data.get(key)
        if isinstance(v, (int, float)):
            financial_data[key] = v * scale

    financial_data["_normalized"] = True
    return financial_data


def normalize_and_validate(
    financial_data: dict,
    ticker: str,
    sector: str | None = None,
    filing_metadata: dict | None = None,
) -> dict:
    """
    Normalize financial_data to raw dollars, then run integrity checks.

    Attaches the validation result as financial_data["_integrity"] — a dict
    that callers and the UI can read.  The underlying data is never altered or
    suppressed; _integrity is purely additive metadata.

    This is the wiring point.  Replace direct calls to normalize_financial_data()
    with this function wherever ticker/filing context is available.

    Parameters
    ----------
    financial_data   Mutable dict returned by get_financial_data() or the
                     Claude extraction path.
    ticker           Ticker symbol, e.g. "MSFT".
    sector           Company sector string.  Pass None if unknown.
    filing_metadata  Dict with optional keys: filing_date, accession, source.
    """
    normalize_financial_data(financial_data)

    try:
        from modules.integrity import validate_filing, append_to_log
        result = validate_filing(financial_data, ticker, sector, filing_metadata or {})
        append_to_log(result)
        financial_data["_integrity"] = result.to_dict()
    except Exception:
        _LOGGER.exception("Data Integrity Engine failed for %s", ticker)

    return financial_data


def _cache_control() -> dict:
    return {"type": "ephemeral", "ttl": "1h"}


def _text_content(response) -> str:
    return next((b.text for b in response.content if b.type == "text"), "")


# Typography that Claude emits in prose, mapped to readable ASCII equivalents.
# Do not revert _sanitize to a blanket '?' replace: em-dashes in analyst text
# were stored as "?" and displayed that way permanently (cache holds the result).
_TYPOGRAPHY_ASCII = str.maketrans({
    "—": "--",   # em dash
    "–": "-",    # en dash
    "−": "-",    # unicode minus
    "‘": "'",    # left single quote
    "’": "'",    # right single quote / apostrophe
    "“": '"',    # left double quote
    "”": '"',    # right double quote
    "…": "...",  # ellipsis
    " ": " ",    # non-breaking space
})


def _sanitize(text: str) -> str:
    """Convert model text to readable ASCII — keeps the Windows charmap-safety
    guarantee (output is pure ASCII) without destroying typography: em dashes
    become '--', curly quotes straighten, accents drop (é -> e). '?' remains
    only for genuinely unmappable symbols."""
    if not text:
        return text
    text = text.translate(_TYPOGRAPHY_ASCII)
    # NFKD splits accented letters into base + combining mark; drop the marks
    # so "é" becomes "e" (not "e?").
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.encode("ascii", "replace").decode("ascii")


def _strip_latex(text: str) -> str:
    """Remove LaTeX math formatting from Claude prose output.

    Claude occasionally wraps numbers in inline math ($-0.61$) or uses
    backslash escapes (\\-). Streamlit renders $...$ as LaTeX, collapsing
    spaces and producing garbled strings like "$\\-0.61lossin2023to$".
    """
    if not text:
        return text
    # Display math $$...$$ → inner content
    text = re.sub(r'\$\$(.+?)\$\$', r'\1', text, flags=re.DOTALL)
    # Inline math containing a LaTeX command (backslash = definite math mode)
    text = re.sub(r'\$([^$\n]*\\[^$\n]*)\$', r'\1', text)
    # Inline math wrapping a plain number or percentage: $-0.61$ → -0.61
    text = re.sub(r'\$([+-]?[\d,]+\.?\d*%?)\$', r'\1', text)
    # LaTeX soft hyphen / negative sign: \- → -
    text = re.sub(r'\\-', '-', text)
    # LaTeX thin/medium/negative spacing commands → remove
    text = re.sub(r'\\[,;:!]', '', text)
    # LaTeX text formatting commands: \textbf{x} \textit{x} \text{x} → x
    text = re.sub(r'\\text\w*\{([^}]*)\}', r'\1', text)
    # Any remaining \word sequences (e.g. \alpha, \times) → remove
    text = re.sub(r'\\\w+', '', text)
    # Collapse double-spaces left behind after stripping
    text = re.sub(r' {2,}', ' ', text).strip()
    return text


def _make_client(api_key: str):
    """Build an Anthropic client with Windows SSL fix for Avast HTTPS inspection.
    Avast presents its own CA cert which is in the Windows system store but not
    in the certifi bundle, so we load system certs instead of using certifi.
    """
    if platform.system() == "Windows":
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.load_default_certs()  # Windows system cert store includes Avast CA
        ssl_ctx.check_hostname = True
        return anthropic.Anthropic(
            api_key=api_key,
            http_client=httpx.Client(verify=ssl_ctx, trust_env=False),
        )
    return anthropic.Anthropic(api_key=api_key)


def build_filing_context(filing_text: str) -> list:
    filing_text = filing_text[:MAX_CACHED_FILING_CHARS]
    return [
        {
            "type": "text",
            "text": filing_text,
            "cache_control": _cache_control(),
        }
    ]


def log_cache_usage(call_name: str, usage) -> dict:
    log = {
        "call": call_name,
        "cache_read": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        "cache_write": int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
    }
    return log


def _render_template(template: str, **values) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


# ===========================================================================
# CALL 1 — EXTRACTION
# Model: claude-haiku (fast, cheap, structured extraction only)
# SYSTEM_PROMPT defines Claude's shared role across all analyzer calls.
# USER_PROMPT_TEMPLATE injects call-specific instructions at runtime.
# ===========================================================================

SYSTEM_PROMPT = """You are a senior financial analyst analyzing SEC filings, public-company financial statements, management commentary, and investor-relevant disclosures for a fund manager workflow. Treat the filing as primary evidence. Your role is to read carefully, reason from the text and numbers that are actually present, and produce decision-useful structured analysis when the user asks for it.

You operate like an experienced analyst who has reviewed hundreds of 10-Ks, 10-Qs, annual reports, MD&A sections, risk factors, segment footnotes, cash flow statements, and management disclosures. You understand that filings are legal documents as well as business narratives. You look for what changed, what matters, what is recurring, what is temporary, and what management is emphasizing or avoiding. You distinguish accounting presentation from economic substance. You are attentive to revenue quality, margin structure, working capital, liquidity, leverage, free cash flow conversion, capital allocation, dilution, buybacks, dividends, restructuring charges, impairments, one-time gains or losses, tax effects, stock-based compensation, deferred revenue, inventory, receivables, debt maturities, covenants, operating leases, and contingent liabilities.

Anchor every conclusion in the supplied filing context. Do not invent facts, figures, dates, tickers, segments, products, markets, management quotes, or forward guidance. If a requested field cannot be supported by the filing, use the fallback requested by the user prompt, such as null, an empty array, or a concise error field. When the user provides extracted financials in addition to filing text, use the extracted financials as a cross-reference, not as a substitute for reading the filing. If the filing text and extracted financials conflict, prefer the filing text when it is explicit and note ambiguity only if the requested output format allows it.

Keep your analysis investment-grade and concrete. Avoid generic sector commentary unless the filing itself makes the sector issue material. Prefer named line items, disclosed metrics, management statements, dates, period labels, and numerical changes over vague language. When evaluating quality, consider the full context: growth alongside margin pressure, profitability alongside cash burn, improving income alongside working-capital strain, strong liquidity alongside refinancing risk, and management optimism alongside risk-factor language. Do not overreact to a single metric if the broader filing gives a clearer picture.

Read MD&A, risk factors, footnotes, business description, segment disclosures, liquidity and capital resources, contractual obligations, subsequent events, and financial statement notes when they are present. Recognize common filing structures and terminology. A cash flow statement may be labeled consolidated, condensed consolidated, combined, statement of cash flows, or similar. Equity may be labeled shareholders' equity, stockholders' equity, members' equity, or deficit. Negative numbers may appear with parentheses. Currency and scale may appear in headings, captions, or table notes. Fiscal year labels and period end dates may be embedded in table headers rather than prose.

When the user requests JSON, return only valid JSON with no markdown fences, no prose preamble, and no trailing commentary. Match the exact field names, enum values, array lengths, and data types requested in the user prompt. Do not add fields unless explicitly requested. Use plain numbers for numeric values. Do not include commas, currency symbols, or parentheses in numeric fields. Use null only when the requested value is genuinely absent or cannot be inferred reliably. Preserve original line-item names when extraction is requested. Sanitize prose for downstream display: use straight quotes, avoid special punctuation when requested, and keep wording concise.

When the user asks for an investment signal, bear/bull case, dashboard insight, or sentiment score, make a judgment from the evidence rather than summarizing mechanically. Be decisive when the evidence supports a view, but do not fabricate certainty. A useful answer should help a portfolio manager decide what to investigate, pass on, or monitor. A weak answer lists obvious facts; a strong answer identifies the central driver, the evidence that matters, and the risk that would invalidate the view.

When the user asks for financial extraction, focus on reliable structured capture. Identify the most recent comparable period, prior period, fiscal labels, currency, and scale. Include section headers and totals where they clarify the statement structure. Keep current and prior values aligned to the correct columns. If quarterly and year-to-date figures both appear, follow the specific instruction in the user prompt. Do not blend periods or infer missing numbers from unrelated tables unless the prompt explicitly asks you to calculate.

When the user asks for qualitative sentiment, assess tone from management's actual language. Separate confident, specific, accountable language from promotional boilerplate. Separate prudent risk disclosure from pervasive hedging. Look for forward guidance, stated priorities, explanations of underperformance, language around demand, pricing, costs, supply chain, capital spending, liquidity, and competition. Choose representative phrases that are specific and meaningful.

Maintain an institutional standard of evidence. Treat tables, prose disclosures, and footnotes as complementary sources. A filing may present strong headline results while revealing weaker unit economics, shrinking backlog, adverse mix shift, higher customer concentration, deteriorating credit quality, or aggressive accounting in the notes. A filing may also present weak headline earnings while revealing nonrecurring charges, temporary working-capital usage, improving order trends, or management actions that make the business more resilient. Your job is to reconcile those signals without flattening them into generic commentary.

Think across time. Compare current-period figures with prior-period figures when available. Consider whether growth is organic or acquisition-driven, whether margin changes reflect price, volume, input costs, mix, restructuring, impairment, or operating leverage, and whether cash flow supports or contradicts earnings. Evaluate the balance sheet in relation to the business model: cash needs, debt maturity profile, interest expense, covenant pressure, capital intensity, inventory cycles, receivables collection, customer prepayments, and off-balance-sheet commitments. When disclosures mention subsequent events, litigation, regulatory matters, or going-concern language, treat them as potentially material even if they do not flow through the primary statements.

Think like a capital allocator. Ask whether management is investing, harvesting, defending, or repairing the business. Buybacks can be accretive or wasteful depending on valuation, leverage, and reinvestment needs. Dividends can signal durability or capital scarcity. Acquisitions can create strategic value or mask organic weakness. Capex can be growth investment or maintenance burden. Stock-based compensation can be acceptable in a high-growth company or a persistent drag on shareholder returns. Do not judge these items in isolation; connect them to the company's financial trajectory and stated strategy.

Be precise about uncertainty. If evidence is mixed, identify the specific unresolved issue rather than writing vague balance. If a number is unavailable, do not backfill it from memory. If a metric is not directly reported but can be calculated from disclosed values, calculate it only when the requested output allows calculations and keep the result consistent with the filing's scale and currency. If a filing is partial, synthetic, or generated from structured SEC data rather than a full narrative filing, adjust the depth of qualitative conclusions to the available evidence.

Maintain consistency across calls for the same filing. The same filing context may be reused for extraction, summary, bull/bear analysis, dashboard frameworks, and MD&A sentiment. Treat that context as stable. Call-specific instructions, schemas, and output constraints are supplied in the user message; follow those instructions exactly while keeping this shared analyst role unchanged."""

USER_PROMPT_TEMPLATE = """Extract the financial statements from the cached filing context or document text and return them as a single JSON object.

Required structure:
{
  "company_name": "string",
  "period": "string — the most recent period, e.g. 'Year ended December 31, 2024'",
  "fiscal_year": "string — short label for the current year column, e.g. 'FY2024'",
  "fiscal_year_prior": "string — short label for the prior year column, e.g. 'FY2023'",
  "currency": "string — e.g. 'USD, in thousands'",
  "income_statement": [ <row objects> ],
  "balance_sheet": [ <row objects> ],
  "cash_flow_statement": [ <row objects> ]
}

Each row object:
  {
    "line_item": "string — label from the document",
    "value": number or null,        — current year figure
    "value_prior": number or null,  — prior year comparative figure
    "row_type": "data" | "section_header" | "subtotal" | "total"
  }

row_type rules:
- "section_header": a major section label. Both value and value_prior must be null.
    Balance sheet MUST include: "ASSETS", "LIABILITIES", "SHAREHOLDERS' EQUITY" (or equivalent).
    Cash flow MUST include: "OPERATING ACTIVITIES", "INVESTING ACTIVITIES", "FINANCING ACTIVITIES" (or equivalent).
    The cash flow statement may be labelled any of the following — look for all variants:
    - CONSOLIDATED STATEMENTS OF CASH FLOWS
    - CONDENSED CONSOLIDATED STATEMENTS OF CASH FLOWS
    - STATEMENTS OF CASH FLOWS
    - COMBINED STATEMENTS OF CASH FLOWS
    Include YTD figures if quarterly periods are presented.
    Income statement: include section headers only if clearly labelled in the source document.
- "subtotal": an intermediate total within a section (e.g. Total current assets, Gross profit).
- "total": a final total for the whole statement (e.g. Total assets, Net income, Net change in cash).
- "data": all other line items.

Statement extraction rules:
- Extract EVERY material line item that appears in the issuer's actual income statement, balance sheet, and cash flow statement. Do not force a retail, SaaS, or manufacturing template onto companies in other industries.
- Use the issuer's exact line_item labels from the filing. Do not rename insurance, bank, REIT, utility, or other specialized financial statement captions into generic technology/retail captions.
- For income statements, always include the total/top-line revenue or equivalent, operating income or equivalent when reported, net income, and all material revenue, expense, gain/loss, provision, and subtotal lines shown in the statement.
- Industry examples are guidance only, not required labels:
    - Tech/Retail: Revenue, Cost of Revenue, Gross Profit, Operating Expenses, R&D, SG&A, Operating Income, Net Income.
    - Insurance: Premiums earned, Net investment income, Net investment gains, Losses and loss adjustment expenses, Amortization of deferred policy acquisition costs, Underwriting and other operating expenses, Operating Income, Net Income.
    - Banks: Net interest income, Provision for credit losses, Noninterest income, Noninterest expense, Income before taxes, Net Income.
    - REITs: Rental revenue, Property operating expenses, Depreciation and amortization, Gains or losses on property sales, Operating Income, Net Income.
    - Utilities: Operating revenues, Fuel or purchased power, Operations and maintenance, Depreciation and amortization, Interest expense, Net Income.
- For balance sheets, extract the actual asset, liability, and equity captions presented by the issuer, including industry-specific captions such as investments, loans, loss reserves, policyholder liabilities, deposits, real estate investments, regulatory assets, and accumulated depreciation when present.
- For cash flow statements, extract the actual operating, investing, and financing activity lines presented by the issuer, including industry-specific adjustments and cash movements. Do not replace them with a generic capex/depreciation/free-cash-flow template.

Additional rules:
- Most SEC filings show two years side by side. Extract BOTH columns.
  "value" is the more recent (current) year. "value_prior" is the comparative (prior) year.
- Values must be plain numbers — no commas, no currency symbols, no parentheses.
- Negative numbers use a minus sign (e.g. -500). Do NOT use parentheses for negatives.
- Zero values should be included as 0, not omitted.
- Use null only when a figure is genuinely absent from the document.
- Preserve the original line item names exactly as they appear in the document.
- If a statement is not found in the document, return an empty array.
- Return only the JSON object. No explanation, no markdown fences.

{document_text}
"""


# ---------------------------------------------------------------------------
# Figure-presence guard.
# A number that appears NOWHERE in the source text cannot have been read from
# it — it was recalled from training or invented. Reference incident
# (2026-07-03): re-analysing NVDA from text truncated before the statements
# produced a complete fabricated extraction that passed every downstream
# check (Quality 100/100, zero integrity flags). This guard makes that
# failure loud instead of silent.
# ---------------------------------------------------------------------------

FIGURE_PRESENCE_MIN_ROWS = 5     # below this, too few rows to judge
FIGURE_PRESENCE_MIN_RATIO = 0.2  # reject when fewer than 20% of values appear


class FabricatedExtractionError(ValueError):
    """Extracted figures do not appear in the source text."""


def _number_in_text(number: float, text: str) -> bool:
    """True if the number appears in the text in any common filing format."""
    candidates = set()
    if float(number) == int(number):
        whole = int(number)
        candidates.add(f"{whole:,}")   # 130,497
        candidates.add(str(whole))     # 130497
    else:
        candidates.add(f"{number:,.2f}")  # 1,234.56
        candidates.add(f"{number:.2f}")   # 1234.56
        candidates.add(f"{number:g}")     # 2.5 (no trailing zero)
    return any(candidate in text for candidate in candidates)


def _figure_presence(financial_data: dict, source_text: str) -> dict:
    """Share of extracted statement values that literally appear in the text."""
    checked = 0
    found = 0
    rows: list[dict] = []
    for section in ("income_statement", "balance_sheet", "cash_flow_statement"):
        for row in financial_data.get(section, []) or []:
            value = row.get("value")
            if value is None:
                continue
            try:
                number = abs(float(value))
            except (TypeError, ValueError):
                continue
            checked += 1
            row_found = _number_in_text(number, source_text)
            if row_found:
                found += 1
            rows.append({
                "section": section,
                "line_item": row.get("line_item", ""),
                "found": row_found,
            })
    ratio = (found / checked) if checked else None
    return {"checked": checked, "found": found, "ratio": ratio, "rows": rows}


def _check_figure_presence(financial_data: dict, source_text: str, model: str) -> dict:
    """Run the guard, append its verdict to the integrity log, and raise on
    fabrication. Returns the presence dict so callers can attach it."""
    presence = _figure_presence(financial_data, source_text)
    fabricated = (
        presence["checked"] >= FIGURE_PRESENCE_MIN_ROWS
        and presence["ratio"] is not None
        and presence["ratio"] < FIGURE_PRESENCE_MIN_RATIO
    )
    presence["verdict"] = "FABRICATED" if fabricated else "PASS"

    try:
        # Lazy import: the integrity package must never depend on this module.
        from modules.integrity.log import append_figure_presence_to_log
        missing_all = [
            r["section"] + ":" + r["line_item"]
            for r in presence["rows"]
            if not r["found"]
        ]
        missing_count = len(missing_all)
        missing_rows = missing_all[:20]
        append_figure_presence_to_log(
            company=str(financial_data.get("company_name") or "Unknown"),
            model=model,
            checked=presence["checked"],
            found=presence["found"],
            ratio=presence["ratio"],
            verdict=presence["verdict"],
            source_chars=len(source_text),
            missing_rows=missing_rows,
            missing_count=missing_count,
        )
    except Exception:
        logging.getLogger(__name__).exception("figure-presence log append failed")

    if fabricated:
        raise FabricatedExtractionError(
            f"Extraction rejected: only {presence['found']} of "
            f"{presence['checked']} extracted figures appear in the source "
            f"text ({len(source_text):,} characters). The text likely does "
            f"not contain the financial statements (truncated or wrong "
            f"document) and the model filled in numbers from memory. "
            f"No analysis was saved."
        )
    return presence


def analyze_financials(
    document_text: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    filing_context: list = None,
) -> dict:
    """Call 1: extract structured financial data from PDF text using Claude Haiku."""
    client = _make_client(api_key)
    if filing_context is not None:
        user_message = [
            *filing_context,
            {
                "type": "text",
                "text": _render_template(
                    USER_PROMPT_TEMPLATE,
                    document_text="Filing text provided above as cached context."
                ),
            },
        ]
        # The text Claude actually sees lives in the context blocks — the
        # figure-presence guard must check against exactly that.
        guard_text = "".join(
            block.get("text", "")
            for block in filing_context
            if isinstance(block, dict)
        )
    else:
        # Front+back slice: captures business context at the top and financial
        # statements at the end, which large filings (e.g. Walgreens 10-K) place
        # well past the 150K character mark if front-only truncation is used.
        document_text = document_text[:MAX_EXTRACTION_FRONT] + document_text[-MAX_EXTRACTION_BACK:]
        user_message = _render_template(USER_PROMPT_TEMPLATE, document_text=document_text)
        guard_text = document_text

    response = client.messages.create(
        model=model,
        max_tokens=8192,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": _cache_control()}],
        messages=[
            {
                "role": "user",
                "content": user_message,
            }
        ],
    )

    print(log_cache_usage("analyze_financials", response.usage))
    raw = response.content[0].text

    # Strip markdown code fences if Claude wraps the JSON in them
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if match:
        raw = match.group(1)

    financial_data = json.loads(raw)

    # Figure-presence guard: values are still in filing units here (before
    # normalization), which is exactly how they appear in the source text.
    # Raises FabricatedExtractionError when the numbers aren't in the text.
    financial_data["figure_presence"] = _check_figure_presence(
        financial_data, guard_text, model
    )

    return normalize_financial_data(financial_data)


# ===========================================================================
# CALL 2 — SUMMARY ANALYSIS
# Model: ANALYSIS_MODEL (Sonnet for dev, Opus for demo — set in config.py)
# Reads the full filing text (including MD&A, risk factors, management
# commentary) plus the structured financials from Call 1, and returns a
# structured investment signal with thesis, catalysts, and risks.
# ===========================================================================

SUMMARY_INSTRUCTIONS = """You are a principal investor and fund manager with 20+ years deploying capital across public equities, private credit, and venture. You review financial filings to make allocation decisions — not to summarise, not to present options, but to form a view and act on it. You have seen hundreds of filings. You know what matters and what doesn't.

Your job is to read the full filing — including the financial statements, MD&A, management commentary, risk factors, and any forward guidance — and produce a structured investment signal with supporting analysis.

You are not summarising the filing. You are making a call.

---

WHAT TO READ

Do not limit your analysis to the financial tables. You must read and draw on:
- Management Discussion & Analysis (MD&A)
- Risk Factors section
- CEO/CFO commentary and forward guidance
- Footnotes or disclosures that affect reported figures (off-balance-sheet items, restatements, one-time charges)
- Any segment or geographic breakdown that reveals underlying business quality

If these sections are absent or sparse (e.g. a partial or non-standard filing), note that in your thesis and weight the signal accordingly.

---

HOW TO FORM YOUR VIEW

Start by identifying the single most important thing an analyst needs to know about this company's financial position and trajectory. Your signal and thesis must follow from that observation — do not assign a signal first and then justify it. Think like a principal who has built $200M+ across investments and operating businesses — not like someone writing a report for a committee.

Do not hedge or present balanced views. Commit to a position based on the evidence in the filing. If the data is genuinely ambiguous, say so in one sentence and classify as PASS.

Use these classifications:

INVESTIGATE — The filing reveals a financially sound or improving business with one or more identifiable upside catalysts. The risk/reward profile warrants deeper due diligence. Revenue trajectory, margin structure, FCF generation, and management commentary are broadly constructive. INVESTIGATE also applies where the business is undervalued relative to identifiable recovery catalysts, even if current fundamentals are under pressure.

PASS — The business is stable but unremarkable, or the filing contains genuinely conflicting signals that do not resolve clearly in either direction. Not compelling enough to act on at this stage.

DECLINE — The filing reveals deteriorating fundamentals, material balance sheet risk, concerning management commentary, or a risk profile that is difficult to underwrite. Capital would be better deployed elsewhere.

---

CATALYST AND RISK FRAMING

For catalysts: identify specific, near-term events or structural advantages visible in the filing that could drive upside. Do not list generic sector tailwinds.

For the risk bullet: answer the question "what would make this thesis wrong?" — not "what are the risks to the company." The risk must directly challenge your stated thesis. If your thesis is that margins are expanding, the risk bullet must address what would reverse margin expansion, not a general comment about competition or macro.

---

OUTPUT FORMAT

Respond with a single JSON object only. No markdown fences, no explanation, no preamble.

{
  "signal": "INVESTIGATE" | "PASS" | "DECLINE",
  "thesis": "2 sentences maximum. If you cannot state your view in 2 sentences, sharpen it until you can. No hedging. One clear view.",
  "catalysts": [
    { "type": "opportunity", "text": "Specific catalyst visible in the filing." },
    { "type": "opportunity", "text": "Second catalyst if present — omit this object if only one exists." }
  ],
  "risks": [
    { "type": "risk", "text": "What would make this thesis wrong — not a general company risk." }
  ],
  "sector_inferred": "Primary sector or industry inferred from the filing (e.g. 'Enterprise SaaS', 'Specialty Retail', 'Upstream Oil & Gas').",
  "filing_date": "Most recent period end date or filing date found in the document, formatted YYYY-MM-DD. Null if not found.",
  "ticker": "Exchange ticker if present in the document. Null if not found."
}

The catalysts array must contain 1 or 2 objects. The risks array must contain exactly 1 object. Do not add fields. Do not omit fields."""

SUMMARY_USER_PROMPT_TEMPLATE = SUMMARY_INSTRUCTIONS + """

Analyse the following financial filing and return your investment signal.

EXTRACTED FINANCIALS (from structured parsing — use as a cross-reference):
{extracted_financials}

FULL FILING TEXT (read this for MD&A, risk factors, and management commentary):
{filing_text}
"""


def analyze_summary(
    filing_text: str,
    extracted_financials: dict,
    api_key: str,
    model: str = DEFAULT_MODEL,
    filing_context: list = None,
) -> dict:
    """Call 2: send filing text + Call 1 financials to Claude and return investment signal."""
    client = _make_client(api_key)

    if filing_context is not None:
        question_text = _render_template(
            SUMMARY_USER_PROMPT_TEMPLATE,
            extracted_financials=json.dumps(extracted_financials, indent=2),
            filing_text="Filing text provided above as cached context.",
        )
        user_message = [
            *filing_context,
            {"type": "text", "text": question_text},
        ]
    else:
        filing_text = filing_text[:MAX_FILING_CHARS]
        user_message = _render_template(
            SUMMARY_USER_PROMPT_TEMPLATE,
            extracted_financials=json.dumps(extracted_financials, indent=2),
            filing_text=filing_text,
        )

    if model == OPUS_48_MODEL:
        response = client.messages.create(
            model=model,
            max_tokens=8000,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": _cache_control()}],
            messages=[{"role": "user", "content": user_message}],
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
        )
    else:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": _cache_control()}],
            messages=[{"role": "user", "content": user_message}],
        )

    print(log_cache_usage("analyze_summary", response.usage))
    raw = _text_content(response)

    # Strip markdown code fences if Claude wraps the JSON in them
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if match:
        raw = match.group(1)

    try:
        data = json.loads(raw)
        data["thesis"] = _sanitize(data.get("thesis") or "")
        data["sector_inferred"] = _sanitize(data.get("sector_inferred") or "")
        for item in data.get("catalysts", []):
            item["text"] = _sanitize(item.get("text") or "")
        for item in data.get("risks", []):
            item["text"] = _sanitize(item.get("text") or "")
        return data
    except json.JSONDecodeError as e:
        return {
            "error": f"Call 2 response could not be parsed as JSON: {e}",
            "raw_response": raw,
            "signal": None,
            "thesis": None,
            "catalysts": [],
            "risks": [],
            "sector_inferred": None,
            "filing_date": None,
            "ticker": None,
        }


# ===========================================================================
# CALL 3 — BULL / BEAR CASE
# Model: BEAR_BULL_MODEL (Sonnet)
# Generates 3 specific bull points and 3 specific bear points grounded in
# evidence from the filing. Each point has a short title + 1-2 sentence detail.
# Prompt-cached so repeat runs within 5 minutes cost only input tokens.
# ===========================================================================

BEAR_BULL_INSTRUCTIONS = """You are a principal investor writing a structured bull and bear case for a financial filing.

Read the filing carefully and identify the 3 strongest arguments FOR investing (bull case) and the 3 strongest arguments AGAINST investing (bear case). Ground every point in specific data, trends, or disclosures from this filing — not generic sector commentary or obvious macro risks.

Return a single JSON object only. No markdown fences, no preamble.

{
  "bull_case": [
    {"title": "5-word max title", "detail": "1-2 sentences grounded in specific filing evidence."},
    {"title": "...", "detail": "..."},
    {"title": "...", "detail": "..."}
  ],
  "bear_case": [
    {"title": "5-word max title", "detail": "1-2 sentences grounded in specific filing evidence."},
    {"title": "...", "detail": "..."},
    {"title": "...", "detail": "..."}
  ]
}

Rules:
- Exactly 3 objects in each array. No more, no fewer.
- Titles: 5 words or fewer, punchy and specific — not generic labels like "Strong Revenue Growth".
- Details: reference actual numbers, named trends, or specific disclosures from the filing.
- Bull points: catalysts, competitive advantages, improving metrics, or underappreciated assets visible in the data.
- Bear points: specific risks, deteriorating trends, concerning disclosures, or valuation concerns grounded in the filing.
- These points should complement — not repeat — the top-level investment signal thesis."""

BEAR_BULL_USER_PROMPT_TEMPLATE = BEAR_BULL_INSTRUCTIONS + """

Generate the bull and bear case for this financial filing:

{filing_text}
"""


def analyze_bear_bull(
    filing_text: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    filing_context: list = None,
) -> dict:
    """Call 3: generate 3-point bull and bear cases from filing text using Claude Sonnet."""
    client = _make_client(api_key)

    if filing_context is not None:
        question_text = _render_template(
            BEAR_BULL_USER_PROMPT_TEMPLATE,
            filing_text="Filing text provided above as cached context."
        )
        user_message = [
            *filing_context,
            {"type": "text", "text": question_text},
        ]
    else:
        filing_text = filing_text[:MAX_FILING_CHARS]
        user_message = _render_template(BEAR_BULL_USER_PROMPT_TEMPLATE, filing_text=filing_text)

    if model == OPUS_48_MODEL:
        response = client.messages.create(
            model=model,
            max_tokens=8000,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": _cache_control()}],
            messages=[{"role": "user", "content": user_message}],
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
        )
    else:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": _cache_control()}],
            messages=[{"role": "user", "content": user_message}],
        )

    print(log_cache_usage("analyze_bear_bull", response.usage))
    raw = _text_content(response)

    # Strip markdown code fences if Claude wraps the JSON in them
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if match:
        raw = match.group(1)

    try:
        data = json.loads(raw)
        for item in data.get("bull_case", []):
            item["title"]  = _sanitize(_strip_latex(item.get("title") or ""))
            item["detail"] = _sanitize(_strip_latex(item.get("detail") or ""))
        for item in data.get("bear_case", []):
            item["title"]  = _sanitize(_strip_latex(item.get("title") or ""))
            item["detail"] = _sanitize(_strip_latex(item.get("detail") or ""))
        return data
    except json.JSONDecodeError as e:
        return {
            "error": f"Call 3 response could not be parsed as JSON: {e}",
            "bull_case": [],
            "bear_case": [],
        }


# ===========================================================================
# CALL 4 — DASHBOARD INSIGHTS
# Model: DASHBOARD_MODEL (Sonnet)
# Framework-based insights for the fund manager dashboard: Dalio (macro/cycle),
# Lynch (story/growth), Marks (value/risk), capital allocation, sentiment.
# ===========================================================================

DASHBOARD_INSTRUCTIONS = """You are a financial analyst generating framework-based insights for a fund manager dashboard.

Given a company's financial filing and investment signal, produce structured insights in the style of three legendary investors.

DALIO: Ray Dalio's macro/credit cycle framework — where is this company in the debt/productivity cycle?
LYNCH: Peter Lynch's story framework — categorise the business, apply the story test.
MARKS: Howard Marks's risk/return framework — second-level thinking, what does the crowd miss?

Return a single JSON object only. No markdown fences, no preamble.

{
  "dalio_view": "2 sentences on macro/debt cycle positioning from Dalio's perspective. Reference specific filing data.",
  "lynch_category": "Exactly one of: Fast Grower | Stalwart | Slow Grower | Turnaround | Asset Play | Cyclical",
  "lynch_story": "3 sentences — plain English investment story a non-expert can follow. Reference the actual business.",
  "marks_view": "2 sentences of genuine second-level thinking. What does the crowd believe vs. what is actually true?",
  "capital_allocation": [
    {"label": "Buybacks",        "value": "One-line assessment referencing filing data."},
    {"label": "Dividends",       "value": "One-line assessment."},
    {"label": "M&A",             "value": "One-line assessment."},
    {"label": "Cash Position",   "value": "One-line assessment referencing balance sheet."},
    {"label": "Capex Intensity", "value": "One-line assessment referencing cash flow data."}
  ],
  "crowd_thinks": "1 sentence — the market consensus view on this company right now.",
  "marks_question": "1 sentence — the specific second-level question Marks would ask about this investment."
}

Rules:
- Reference specific numbers, trends, or disclosures from the filing wherever possible
- lynch_category must be exactly one of the 6 values listed above, nothing else
- capital_allocation must have exactly 5 entries in the order shown
- marks_view must show genuine contrarian or second-level insight — not generic risk commentary
- Important: never use em dashes (—) or special unicode punctuation. Use regular hyphens (-) or double hyphens (--) instead. Use straight quotes only."""

DASHBOARD_USER_PROMPT_TEMPLATE = DASHBOARD_INSTRUCTIONS + """

Generate dashboard insights for this financial filing.

INVESTMENT SIGNAL (from prior analysis):
{summary_json}

EXTRACTED FINANCIALS:
{financials_json}

FILING TEXT (for capital allocation and management commentary context):
{filing_text}
"""


def analyze_dashboard_insights(
    filing_text: str,
    summary_data: dict,
    financial_data: dict,
    api_key: str,
    model: str = DEFAULT_MODEL,
    filing_context: list = None,
) -> dict:
    """Call 4: generate Dalio/Lynch/Marks framework insights for the dashboard.

    Always returns a dict — never raises. Errors are returned as {"error": "..."}.
    filing_text may be empty string when called from the Filing Library load path
    (raw text not stored); the model generates insights from structured data alone.
    """
    raw = ""
    try:
        client      = _make_client(api_key)

        if filing_context is not None:
            question_text = _render_template(
                DASHBOARD_USER_PROMPT_TEMPLATE,
                summary_json   = json.dumps(summary_data or {}, indent=2),
                financials_json= json.dumps(financial_data,     indent=2),
                filing_text    = "Filing text provided above as cached context.",
            )
            user_message = [
                *filing_context,
                {"type": "text", "text": question_text},
            ]
        else:
            filing_text = filing_text[:MAX_FILING_CHARS]
            user_message = _render_template(
                DASHBOARD_USER_PROMPT_TEMPLATE,
                summary_json   = json.dumps(summary_data or {}, indent=2),
                financials_json= json.dumps(financial_data,     indent=2),
                filing_text    = filing_text,
            )

        if model == OPUS_48_MODEL:
            response = client.messages.create(
                model     = model,
                max_tokens= 8000,
                system    = [{"type": "text", "text": SYSTEM_PROMPT,
                              "cache_control": _cache_control()}],
                messages  = [{"role": "user", "content": user_message}],
                thinking  = {"type": "adaptive"},
                output_config = {"effort": "high"},
            )
        else:
            response = client.messages.create(
                model     = model,
                max_tokens= 1200,
                system    = [{"type": "text", "text": SYSTEM_PROMPT,
                              "cache_control": _cache_control()}],
                messages  = [{"role": "user", "content": user_message}],
            )

        print(log_cache_usage("analyze_dashboard_insights", response.usage))
        raw = _text_content(response)

        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
        if m:
            raw = m.group(1)

        data = json.loads(raw)
        for key in ("dalio_view", "lynch_category", "lynch_story", "marks_view",
                    "crowd_thinks", "marks_question"):
            if key in data:
                data[key] = _sanitize(data.get(key) or "")
        for item in (data.get("capital_allocation") or []):
            item["label"] = _sanitize(item.get("label") or "")
            item["value"] = _sanitize(item.get("value") or "")
        return data

    except Exception as e:
        return {
            "error":              f"Call 4 failed ({type(e).__name__}): {e}",
            "raw_response":       raw,
            "dalio_view":         "",
            "lynch_category":     "",
            "lynch_story":        "",
            "marks_view":         "",
            "capital_allocation": [],
            "crowd_thinks":       "",
            "marks_question":     "",
        }


# ===========================================================================
# CALL 5 — MD&A SENTIMENT
# Model: Haiku by default. Haiku prompt cache is model-scoped and separate from
# the Sonnet cache written/read by the other analyzer calls.
# ===========================================================================

MDA_INSTRUCTIONS = """Your task: locate the Management Discussion & Analysis (MD&A) section in the filing text provided, then score its sentiment. If no distinct MD&A section exists, analyse whatever management commentary and forward-looking statements are present.

Return ONLY a valid JSON object — no markdown fences, no preamble, no explanation:

{
  "overall_tone": "Positive" | "Cautious" | "Negative",
  "scores": {
    "forward_outlook": <integer 1-5>,
    "risk_language_density": <integer 1-5>,
    "management_confidence": <integer 1-5>
  },
  "key_phrases": ["phrase 1", "phrase 2"],
  "error": null
}

Scoring scale — 5 = most positive for the investor on every dimension:

overall_tone:
  Positive  — management is confident, highlights achievements, uses constructive forward language
  Cautious  — balanced language, hedging, uncertainty acknowledged alongside positives
  Negative  — emphasis on challenges, deterioration, or defensive/apologetic framing

forward_outlook (1=very bearish guidance, 5=very bullish guidance):
  Based on forward guidance language, growth projections, and stated confidence in future performance.

risk_language_density (1=pervasive hedging and risk warnings, 5=minimal risk language):
  Based on frequency and weight of cautionary language, qualifiers, and risk disclosures.
  A score of 5 means management writes plainly and with conviction; 1 means every sentence is hedged.

management_confidence (1=very defensive or evasive, 5=very direct and confident):
  Based on ownership of results, directness of statements, and proactive vs. reactive framing.

key_phrases: exactly 2–3 verbatim phrases (one sentence maximum each) that most strongly influenced your overall_tone score. Choose phrases that are specific and representative — not generic boilerplate.

Rules:
- All score fields must be integers 1–5. Do not use null for scores.
- key_phrases must have 2 or 3 entries.
- Return ONLY the JSON object."""

MDA_USER_PROMPT_TEMPLATE = MDA_INSTRUCTIONS + """

Analyse the MD&A sentiment in this financial filing:

{filing_text}"""


def _safe_json(raw: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
    return {"error": f"Could not parse response: {raw[:200]}"}


_EMPTY_MDA = {
    "overall_tone": None,
    "scores": {
        "forward_outlook":       None,
        "risk_language_density": None,
        "management_confidence": None,
    },
    "key_phrases": [],
    "error": None,
}


def analyze_mda_sentiment(
    raw_text: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    filing_context: list = None,
) -> dict:
    """Call 5: score MD&A sentiment from filing text using Claude Haiku."""
    try:
        client = _make_client(api_key)

        if filing_context is not None:
            user_message = [
                *filing_context,
                {
                    "type": "text",
                    "text": _render_template(
                        MDA_USER_PROMPT_TEMPLATE,
                        filing_text="Filing text provided above as cached context."
                    ),
                },
            ]
        else:
            text = (raw_text or "")[:MAX_FILING_CHARS]
            user_message = _render_template(MDA_USER_PROMPT_TEMPLATE, filing_text=text)

        if model == OPUS_48_MODEL:
            response = client.messages.create(
                model=model,
                max_tokens=8000,
                system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": _cache_control()}],
                messages=[{"role": "user", "content": user_message}],
                thinking={"type": "adaptive"},
                output_config={"effort": "high"},
            )
        else:
            response = client.messages.create(
                model=model,
                max_tokens=512,
                system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": _cache_control()}],
                messages=[{"role": "user", "content": user_message}],
            )

        print(log_cache_usage("analyze_mda_sentiment", response.usage))
        data = _safe_json(_text_content(response))
        if data.get("error"):
            result = {k: v for k, v in _EMPTY_MDA.items()}
            result["error"] = data["error"]
            return result

        for key in ("forward_outlook", "risk_language_density", "management_confidence"):
            v = (data.get("scores") or {}).get(key)
            if isinstance(v, (int, float)):
                data.setdefault("scores", {})[key] = max(1, min(5, int(v)))
            else:
                data.setdefault("scores", {})[key] = None

        data.setdefault("overall_tone", None)
        data.setdefault("key_phrases", [])
        data["error"] = None
        return data

    except Exception as exc:
        result = {k: v for k, v in _EMPTY_MDA.items()}
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
