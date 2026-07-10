"""Search-triggered agent fetch (CB-028, ratified 2026-07-09).

The client-demand-flywheel front door: the user names a company + filing,
the OpenClaw agent finds the issuer-hosted (or EDGAR) direct-PDF URL over
the gateway channel, and THIS module re-fetches the bytes itself, verifies
them, and hands back an UploadedFile-compatible shim that converges on the
app's existing fresh-upload path — so every gate (CB-015 document class,
extraction, mapper, engine, moat log) fires unchanged by construction.

Design rules enforced here (docs/design_sessions/
2026-07-09-search-triggered-agent-fetch__cc.md):
- R3: strict one-JSON-object agent contract; fetch-only; no SEDAR+ CAPTCHA.
- R4: the app never trusts relayed content — bytes are re-fetched from the
  returned URL with a sha256 receipt; non-PDF or oversized -> BAD_BYTES.
- R6: this module never analyzes and never spends Claude tokens.
- R7: config comes ONLY from env (SOPS-injected); anything missing means
  the feature is disabled, never a crash.

UI-agnostic by design: pure functions in, structured dicts out (the
resource_economics pattern). app.py owns all Streamlit rendering.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx

# Mirrors the manual uploader's large-file guard (app.py: 20 MB warning
# threshold); here it is a hard cap because nobody eyeballed the download.
MAX_FETCH_BYTES = 20 * 1024 * 1024

AGENT_TIMEOUT_SECONDS = 240   # OQ3: agent turns observed at 60s-3min (ARX)
FETCH_TIMEOUT_SECONDS = 120

# R7: all three must be present for the lane to enable.
ENV_URL = "OPENCLAW_GATEWAY_URL"
ENV_TOKEN = "OPENCLAW_GATEWAY_TOKEN"
ENV_SESSION_KEY = "OPENCLAW_GATEWAY_SESSION_KEY"

FETCHED_PDF_DIR = Path.home() / ".finlens" / "pdfs" / "_fetched"

_VALID_STATUSES = {"found", "not_found", "blocked"}


class FetchedUpload(io.BytesIO):
    """UploadedFile-compatible shim (R5).

    Exposes exactly what the fresh-upload flow consumes — .name, .size,
    .getvalue() — plus the file-like read/seek it inherits from BytesIO
    (extract_text_from_pdf feeds the object to pdfplumber directly).
    """

    def __init__(self, data: bytes, name: str):
        super().__init__(data)
        self.name = name
        self.size = len(data)


def gateway_config(env: dict | None = None) -> dict | None:
    """Return {url, token, session_key} or None when any piece is missing.

    None means the fetch lane renders disabled with an honest caption —
    graceful degradation (supabase_storage posture), never a crash.
    """
    import os
    source = env if env is not None else os.environ
    url = (source.get(ENV_URL) or "").strip()
    token = (source.get(ENV_TOKEN) or "").strip()
    session_key = (source.get(ENV_SESSION_KEY) or "").strip()
    if not (url and token and session_key):
        return None
    return {"url": url, "token": token, "session_key": session_key}


def build_agent_prompt(company: str, filing: str, canadian: bool) -> str:
    """The R3 contract prompt. Fetch-only, issuer/EDGAR only, one JSON object."""
    venue = (
        "the company's own investor-relations website (issuer-hosted). "
        "SEDAR+ is OFF LIMITS (it is CAPTCHA-protected; do not attempt it)."
        if canadian
        else "the company's own investor-relations website, or SEC EDGAR."
    )
    return (
        "You are locating a financial filing PDF. Company: "
        f"{company.strip()!r}. Filing wanted: {filing.strip()!r}.\n"
        f"Search {venue}\n"
        "Find the DIRECT URL to the PDF document itself (a link whose "
        "response is the PDF, not a landing page). Do NOT download or relay "
        "the file contents.\n"
        "Reply with EXACTLY one JSON object and no other prose:\n"
        '{"status": "found" | "not_found" | "blocked", '
        '"url": "<direct PDF url or null>", '
        '"notes": "<one line: what you searched / why blocked>"}\n'
        'Use "blocked" when the IR site refuses automated access '
        '(e.g. Cloudflare). Use "not_found" when you cannot locate the '
        "filing with confidence — never guess a URL."
    )


def parse_agent_reply(text: str) -> dict:
    """Extract and validate the R3 JSON object from the agent's reply.

    Returns {"status": ..., "url": ..., "notes": ...}; a malformed reply
    returns status "agent_reply_unparseable" (terminal, honest — no retry
    loop in v1).
    """
    match = re.search(r"\{.*\}", str(text or ""), flags=re.DOTALL)
    if not match:
        return {"status": "agent_reply_unparseable", "url": None,
                "notes": "no JSON object found in agent reply"}
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return {"status": "agent_reply_unparseable", "url": None,
                "notes": f"JSON parse error: {exc}"}
    status = str(payload.get("status") or "").strip().lower()
    if status not in _VALID_STATUSES:
        return {"status": "agent_reply_unparseable", "url": None,
                "notes": f"unrecognized status {status!r}"}
    url = payload.get("url")
    url = str(url).strip() if url else None
    if status == "found" and not (url and url.lower().startswith("http")):
        return {"status": "agent_reply_unparseable", "url": None,
                "notes": "status=found but no usable http(s) url"}
    return {"status": status, "url": url,
            "notes": str(payload.get("notes") or "").strip()}


def request_filing_url(
    company: str,
    filing: str,
    canadian: bool,
    config: dict,
    timeout: float = AGENT_TIMEOUT_SECONDS,
) -> dict:
    """One gateway agent turn (R3). Returns the parsed contract dict, or
    {"status": "gateway_error", ...} on transport failure.

    The session key routes the exchange into Riley's Telegram thread, so
    the visibility rule is satisfied automatically (OQ1: reuse ratified).
    """
    try:
        response = httpx.post(
            config["url"].rstrip("/") + "/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {config['token']}",
                "x-openclaw-session-key": config["session_key"],
                "Content-Type": "application/json",
            },
            json={
                "model": "openclaw/default",
                "messages": [{
                    "role": "user",
                    "content": build_agent_prompt(company, filing, canadian),
                }],
            },
            timeout=timeout,
        )
        response.raise_for_status()
        body = response.json()
        text = (
            (body.get("choices") or [{}])[0].get("message", {}).get("content")
            or ""
        )
    except Exception as exc:
        return {"status": "gateway_error", "url": None,
                "notes": f"{type(exc).__name__}: {exc}"}
    return parse_agent_reply(text)


def fetch_pdf_bytes(
    url: str,
    timeout: float = FETCH_TIMEOUT_SECONDS,
    max_bytes: int = MAX_FETCH_BYTES,
) -> dict:
    """R4: the app fetches the bytes ITSELF and verifies they are a PDF.

    Returns {"ok": True, "data", "sha256", "byte_size"} or
    {"ok": False, "reason": "FETCH_FAILED" | "BAD_BYTES", "detail"}.
    """
    try:
        response = httpx.get(url, follow_redirects=True, timeout=timeout)
        response.raise_for_status()
        data = response.content
    except Exception as exc:
        return {"ok": False, "reason": "FETCH_FAILED",
                "detail": f"{type(exc).__name__}: {exc}"}

    if len(data) > max_bytes:
        return {"ok": False, "reason": "BAD_BYTES",
                "detail": f"{len(data):,} bytes exceeds the "
                          f"{max_bytes // (1024 * 1024)} MB cap"}
    # %PDF- magic beats the content-type header (issuer CDNs frequently
    # mislabel); a landing page or HTML error would fail this check.
    if not data.startswith(b"%PDF-"):
        content_type = ""
        try:
            content_type = response.headers.get("content-type", "")
        except Exception:
            pass
        return {"ok": False, "reason": "BAD_BYTES",
                "detail": f"response is not a PDF "
                          f"(content-type: {content_type or 'unknown'})"}
    return {
        "ok": True,
        "data": data,
        "sha256": hashlib.sha256(data).hexdigest(),
        "byte_size": len(data),
    }


def build_provenance(url: str, sha256: str, byte_size: int) -> dict:
    """R4 receipt — the worker provenance shape, app-flavored."""
    return {
        "url": url,
        "sha256": sha256,
        "byte_size": byte_size,
        "retrieval_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "retrieval_method": "app_agent_fetch",
        "agent_channel": "openclaw_gateway",
    }


def safe_fetch_filename(company: str, filing: str) -> str:
    """Filesystem- and display-safe name for the shim and the _fetched cache."""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{company}_{filing}").strip("_")
    return (stem[:120] or "agent_fetched_filing") + ".pdf"


def cache_fetched_pdf(data: bytes, filename: str) -> str | None:
    """Persist the bytes so Re-Analyse works later (the registry-entry
    dead-end lesson). Returns the path, or None on failure (non-fatal)."""
    try:
        FETCHED_PDF_DIR.mkdir(parents=True, exist_ok=True)
        path = FETCHED_PDF_DIR / filename
        path.write_bytes(data)
        return str(path)
    except Exception:
        return None
