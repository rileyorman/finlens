import sys
import ssl
import anthropic
import httpx
import certifi
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
    if sys.platform == "win32":
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.load_verify_locations(certifi.where())
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
