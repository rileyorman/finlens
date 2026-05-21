import anthropic
import json
import re


# ===========================================================================
# PROMPT — refine this section to improve extraction accuracy.
# SYSTEM_PROMPT defines Claude's role and the exact JSON shape to return.
# USER_PROMPT_TEMPLATE injects the raw PDF text at runtime.
# ===========================================================================

SYSTEM_PROMPT = """You are a financial analyst assistant. Extract financial statements
from raw document text and return them as a single JSON object with this exact structure:

{
  "company_name": "string",
  "period": "string — e.g. 'Year ended December 31, 2024'",
  "fiscal_year": "string — short column label, e.g. 'FY2024' or 'Dec 31, 2024'",
  "currency": "string — e.g. 'USD, in thousands'",
  "income_statement": [ <row objects> ],
  "balance_sheet": [ <row objects> ],
  "cash_flow_statement": [ <row objects> ]
}

Each row object has three fields:
  {"line_item": "string", "value": number or null, "row_type": "data" | "section_header" | "subtotal" | "total"}

row_type rules:
- "section_header": a major section label. Value must be null.
    Balance sheet MUST include headers: "ASSETS", "LIABILITIES", "SHAREHOLDERS' EQUITY" (or equivalent wording).
    Cash flow MUST include headers: "OPERATING ACTIVITIES", "INVESTING ACTIVITIES", "FINANCING ACTIVITIES" (or equivalent).
    Income statement: include section headers only if clearly labelled in the source document.
- "subtotal": an intermediate total within a section (e.g. Total current assets, Gross profit, Net cash from operating activities).
- "total": a final total for the whole statement (e.g. Total assets, Total liabilities and equity, Net income, Net change in cash).
- "data": all other line items.

Additional rules:
- Values must be plain numbers — no commas, currency symbols, or parentheses.
- Negative numbers use a minus sign (e.g. -500). Do NOT use parentheses for negatives.
- Zero values should be included as 0, not omitted.
- Preserve the original line item names exactly as they appear in the document.
- If a statement is not found in the document, return an empty array.
- Return only the JSON object. No explanation, no markdown fences.
"""

USER_PROMPT_TEMPLATE = """Extract the financial statements from the following document:

{document_text}
"""


def analyze_financials(document_text: str, api_key: str) -> dict:
    """Send extracted PDF text to Claude and return structured financial data."""
    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
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
