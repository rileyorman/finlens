import sys
import ssl
import anthropic
import httpx
import json
import re

from config import EXTRACTION_MODEL, ANALYSIS_MODEL, BEAR_BULL_MODEL, MAX_FILING_CHARS, MAX_EXTRACTION_FRONT, MAX_EXTRACTION_BACK

# Model alias for the dashboard insights call (same tier as analysis)
DASHBOARD_MODEL = ANALYSIS_MODEL


def _sanitize(text: str) -> str:
    """Replace non-ASCII characters with '?' — prevents charmap errors on Windows."""
    if not text:
        return text
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
    if sys.platform == "win32":
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.load_default_certs()  # Windows system cert store includes Avast CA
        ssl_ctx.check_hostname = True
        return anthropic.Anthropic(
            api_key=api_key,
            http_client=httpx.Client(verify=ssl_ctx, trust_env=False),
        )
    return anthropic.Anthropic(api_key=api_key)


# ===========================================================================
# CALL 1 — EXTRACTION
# Model: claude-haiku (fast, cheap, structured extraction only)
# SYSTEM_PROMPT defines Claude's role and the exact JSON shape to return.
# USER_PROMPT_TEMPLATE injects the raw PDF text at runtime.
# ===========================================================================

SYSTEM_PROMPT = """You are a financial analyst assistant. Extract financial statements
from raw document text and return them as a single JSON object.

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
"""

USER_PROMPT_TEMPLATE = """Extract the financial statements from the following document:

{document_text}
"""


def analyze_financials(document_text: str, api_key: str) -> dict:
    """Call 1: extract structured financial data from PDF text using Claude Haiku."""
    client = _make_client(api_key)
    # Front+back slice: captures business context at the top and financial
    # statements at the end, which large filings (e.g. Walgreens 10-K) place
    # well past the 150K character mark if front-only truncation is used.
    document_text = document_text[:MAX_EXTRACTION_FRONT] + document_text[-MAX_EXTRACTION_BACK:]

    response = client.messages.create(
        model=EXTRACTION_MODEL,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.format(document_text=document_text),
            }
        ],
    )

    raw = response.content[0].text

    # Strip markdown code fences if Claude wraps the JSON in them
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if match:
        raw = match.group(1)

    return json.loads(raw)


# ===========================================================================
# CALL 2 — SUMMARY ANALYSIS
# Model: ANALYSIS_MODEL (Sonnet for dev, Opus for demo — set in config.py)
# Reads the full filing text (including MD&A, risk factors, management
# commentary) plus the structured financials from Call 1, and returns a
# structured investment signal with thesis, catalysts, and risks.
# Do not modify SUMMARY_SYSTEM_PROMPT without design review.
# ===========================================================================

SUMMARY_SYSTEM_PROMPT = """You are a principal investor and fund manager with 20+ years deploying capital across public equities, private credit, and venture. You review financial filings to make allocation decisions — not to summarise, not to present options, but to form a view and act on it. You have seen hundreds of filings. You know what matters and what doesn't.

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

SUMMARY_USER_PROMPT_TEMPLATE = """Analyse the following financial filing and return your investment signal.

EXTRACTED FINANCIALS (from structured parsing — use as a cross-reference):
{extracted_financials}

FULL FILING TEXT (read this for MD&A, risk factors, and management commentary):
{filing_text}
"""


def analyze_summary(filing_text: str, extracted_financials: dict, api_key: str) -> dict:
    """Call 2: send filing text + Call 1 financials to Claude and return investment signal."""
    client = _make_client(api_key)
    filing_text = filing_text[:MAX_FILING_CHARS]

    user_message = SUMMARY_USER_PROMPT_TEMPLATE.format(
        extracted_financials=json.dumps(extracted_financials, indent=2),
        filing_text=filing_text,
    )

    response = client.messages.create(
        model=ANALYSIS_MODEL,
        max_tokens=1024,
        system=[{"type": "text", "text": SUMMARY_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text

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

BEAR_BULL_SYSTEM_PROMPT = """You are a principal investor writing a structured bull and bear case for a financial filing.

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

BEAR_BULL_USER_PROMPT_TEMPLATE = """Generate the bull and bear case for this financial filing:

{filing_text}
"""


def analyze_bear_bull(filing_text: str, api_key: str) -> dict:
    """Call 3: generate 3-point bull and bear cases from filing text using Claude Sonnet."""
    client = _make_client(api_key)
    filing_text = filing_text[:MAX_FILING_CHARS]

    user_message = BEAR_BULL_USER_PROMPT_TEMPLATE.format(filing_text=filing_text)

    response = client.messages.create(
        model=BEAR_BULL_MODEL,
        max_tokens=1024,
        system=[{"type": "text", "text": BEAR_BULL_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text

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

DASHBOARD_SYSTEM_PROMPT = """You are a financial analyst generating framework-based insights for a fund manager dashboard.

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

DASHBOARD_USER_PROMPT_TEMPLATE = """Generate dashboard insights for this financial filing.

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
) -> dict:
    """Call 4: generate Dalio/Lynch/Marks framework insights for the dashboard.

    Always returns a dict — never raises. Errors are returned as {"error": "..."}.
    filing_text may be empty string when called from the Filing Library load path
    (raw text not stored); the model generates insights from structured data alone.
    """
    raw = ""
    try:
        client      = _make_client(api_key)
        filing_text = filing_text[:MAX_FILING_CHARS]

        user_message = DASHBOARD_USER_PROMPT_TEMPLATE.format(
            summary_json   = json.dumps(summary_data or {}, indent=2),
            financials_json= json.dumps(financial_data,     indent=2),
            filing_text    = filing_text,
        )

        response = client.messages.create(
            model     = DASHBOARD_MODEL,
            max_tokens= 1200,
            system    = [{"type": "text", "text": DASHBOARD_SYSTEM_PROMPT,
                          "cache_control": {"type": "ephemeral"}}],
            messages  = [{"role": "user", "content": user_message}],
        )

        raw = response.content[0].text

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
