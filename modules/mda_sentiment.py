import sys
import ssl
import json
import re

import anthropic
import httpx

from config import EXTRACTION_MODEL, MAX_FILING_CHARS


def _make_client(api_key: str):
    """Anthropic client with Windows SSL fix (mirrors claude_analyzer._make_client)."""
    if sys.platform == "win32":
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.load_default_certs()
        ssl_ctx.check_hostname = True
        return anthropic.Anthropic(
            api_key=api_key,
            http_client=httpx.Client(verify=ssl_ctx, trust_env=False),
        )
    return anthropic.Anthropic(api_key=api_key)


_SYSTEM_PROMPT = """You are a financial analyst specialising in qualitative text analysis.

Your task: locate the Management Discussion & Analysis (MD&A) section in the filing text provided, then score its sentiment. If no distinct MD&A section exists, analyse whatever management commentary and forward-looking statements are present.

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

_USER_TEMPLATE = """Analyse the MD&A sentiment in this financial filing:

{filing_text}"""


def _safe_json(raw: str) -> dict:
    import re
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


_EMPTY = {
    "overall_tone": None,
    "scores": {
        "forward_outlook":       None,
        "risk_language_density": None,
        "management_confidence": None,
    },
    "key_phrases": [],
    "error": None,
}


def analyze_mda_sentiment(raw_text: str, api_key: str) -> dict:
    """Call 5: score MD&A sentiment from filing text using Claude Haiku.

    Always returns a dict — never raises. On failure, error field is populated
    and scores are None.
    """
    try:
        client  = _make_client(api_key)
        text    = (raw_text or "")[:MAX_FILING_CHARS]

        response = client.messages.create(
            model      = EXTRACTION_MODEL,
            max_tokens = 512,
            system     = [{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages   = [{"role": "user", "content": _USER_TEMPLATE.format(filing_text=text)}],
        )

        raw = response.content[0].text

        data = _safe_json(raw)
        if data.get("error"):
            result = {k: v for k, v in _EMPTY.items()}
            result["error"] = data["error"]
            return result

        # Clamp scores to valid range; treat missing as None
        for key in ("forward_outlook", "risk_language_density", "management_confidence"):
            v = (data.get("scores") or {}).get(key)
            if isinstance(v, (int, float)):
                data.setdefault("scores", {})[key] = max(1, min(5, int(v)))
            else:
                data.setdefault("scores", {})[key] = None

        data.setdefault("overall_tone", None)
        data.setdefault("key_phrases",  [])
        data["error"] = None
        return data

    except Exception as exc:
        result = {k: v for k, v in _EMPTY.items()}
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
