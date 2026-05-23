import sys
import ssl
import anthropic
import httpx
import json
import re


# ===========================================================================
# PROMPT — refine this section to improve extraction accuracy.
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
    """Send extracted PDF text to Claude and return structured financial data."""
    # Windows SSL fix: load system cert store so Avast HTTPS
    # inspection CA is trusted. certifi bundle alone won't work
    # on machines with Avast installed.
    if sys.platform == "win32":
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.load_default_certs()  # includes Avast CA
        ssl_ctx.check_hostname = True
        client = anthropic.Anthropic(
            api_key=api_key,
            http_client=httpx.Client(verify=ssl_ctx, trust_env=False),
        )
    else:
        client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model="claude-sonnet-4-6",
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
# Model: claude-opus-4-7
# Reads the full filing text (including MD&A, risk factors, management
# commentary) plus the structured financials from Call 1, and returns a
# structured investment signal with thesis, catalysts, and risk.
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
    """Call 2: send full filing text + Call 1 financials to Claude Opus and return investment signal."""
    # Windows SSL fix: load system cert store so Avast HTTPS
    # inspection CA is trusted. certifi bundle alone won't work
    # on machines with Avast installed.
    if sys.platform == "win32":
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.load_default_certs()  # includes Avast CA
        ssl_ctx.check_hostname = True
        client = anthropic.Anthropic(
            api_key=api_key,
            http_client=httpx.Client(verify=ssl_ctx, trust_env=False),
        )
    else:
        client = anthropic.Anthropic(api_key=api_key)

    user_message = SUMMARY_USER_PROMPT_TEMPLATE.format(
        extracted_financials=json.dumps(extracted_financials, indent=2),
        filing_text=filing_text,
    )

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system=SUMMARY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text

    # Strip markdown code fences if Claude wraps the JSON in them
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if match:
        raw = match.group(1)

    try:
        return json.loads(raw)
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
