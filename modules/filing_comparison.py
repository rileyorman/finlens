import platform
import ssl
import json
import re

import anthropic
import httpx

from config import EXTRACTION_MODEL
from modules.mda_sentiment import analyze_mda_sentiment

_SYNTHESIS_CHARS = 40_000
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
OPUS_48_MODEL = "claude-opus-4-8"


def _text_content(response) -> str:
    return next((b.text for b in response.content if b.type == "text"), "")


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


def _make_client(api_key: str):
    if platform.system() == "Windows":
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.load_default_certs()
        ssl_ctx.check_hostname = True
        return anthropic.Anthropic(
            api_key=api_key,
            http_client=httpx.Client(verify=ssl_ctx, trust_env=False),
        )
    return anthropic.Anthropic(api_key=api_key)


_SYNTHESIS_SYSTEM = """You are a financial analyst comparing two annual reports from the same company.

Your task: analyse the shift in management tone and communication style between the two periods.

Return ONLY a valid JSON object — no markdown fences, no preamble, no explanation:

{
  "tone_shift": "One or two sentences describing how overall management tone changed.",
  "themes": [
    {"topic": "string", "direction": "increased" | "decreased", "detail": "string"}
  ],
  "language_shifts": [
    {"type": "appeared" | "disappeared" | "changed", "phrase": "string"}
  ],
  "error": null
}

Rules:
- tone_shift: 1-2 sentences. Be specific about direction and character of change.
- themes: exactly 3-5 entries. Focus on topics with meaningful prominence shifts.
- language_shifts: exactly 3-5 entries. Use verbatim phrases where possible (one sentence max each).
- direction must be exactly "increased" or "decreased".
- type must be exactly "appeared", "disappeared", or "changed".
- Return ONLY the JSON object."""


_SYNTHESIS_USER = """Compare these two filings from the same company.

Filing 1 ({label_1}) — MD&A Sentiment scores:
{sentiment_1}

Filing 2 ({label_2}) — MD&A Sentiment scores:
{sentiment_2}

---
Filing 1 ({label_1}) text:
{text_1}

---
Filing 2 ({label_2}) text:
{text_2}"""


def compare_filings(
    raw_text_1: str,
    raw_text_2: str,
    label_1: str,
    label_2: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
) -> dict:
    """Compare two filings: MD&A sentiment + synthesis. Always returns dict, never raises."""
    result = {
        "sentiment_1": None,
        "sentiment_2": None,
        "comparison":  None,
        "label_1":     label_1,
        "label_2":     label_2,
        "error":       None,
    }

    try:
        result["sentiment_1"] = analyze_mda_sentiment(raw_text_1, api_key, model=model)
        result["sentiment_2"] = analyze_mda_sentiment(raw_text_2, api_key, model=model)

        client = _make_client(api_key)
        user_msg = _SYNTHESIS_USER
        user_msg = user_msg.replace("{label_1}", label_1)
        user_msg = user_msg.replace("{label_2}", label_2)
        user_msg = user_msg.replace("{sentiment_1}", json.dumps(result["sentiment_1"], indent=2))
        user_msg = user_msg.replace("{sentiment_2}", json.dumps(result["sentiment_2"], indent=2))
        user_msg = user_msg.replace("{text_1}", (raw_text_1 or "")[:_SYNTHESIS_CHARS])
        user_msg = user_msg.replace("{text_2}", (raw_text_2 or "")[:_SYNTHESIS_CHARS])

        if model == OPUS_48_MODEL:
            response = client.messages.create(
                model      = model,
                max_tokens = 8000,
                system     = [{"type": "text", "text": _SYNTHESIS_SYSTEM, "cache_control": {"type": "ephemeral"}}],
                messages   = [{"role": "user", "content": user_msg}],
                thinking   = {"type": "adaptive"},
                output_config = {"effort": "high"},
            )
        else:
            response = client.messages.create(
                model      = model,
                max_tokens = 2048,
                system     = [{"type": "text", "text": _SYNTHESIS_SYSTEM, "cache_control": {"type": "ephemeral"}}],
                messages   = [{"role": "user", "content": user_msg}],
            )

        raw = _text_content(response)

        comparison = _safe_json(raw)
        if comparison.get("error"):
            result["error"] = comparison["error"]
            return result
        comparison.setdefault("tone_shift", None)
        comparison.setdefault("themes", [])
        comparison.setdefault("language_shifts", [])
        comparison["error"] = None
        result["comparison"] = comparison

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result
