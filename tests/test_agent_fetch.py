"""CB-028 pinning tests — search-triggered agent fetch (ratified 2026-07-09).

Covers acceptance tests T1–T6 + T8's module half from
docs/design_sessions/2026-07-09-search-triggered-agent-fetch__cc.md.
T7 (one-fetch-at-a-time) is enforced STRUCTURALLY by the blocking st.status
flow in app.py — a second click cannot fire while a turn is in flight — and
the Clear/replace semantics are session-state pops, not module logic.
T8's end-to-end half (SEDAR routing on a real fetched filing) is the R8
LIVE evidence gate, exercised at review, not unit-testable here.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import agent_fetch
from modules.agent_fetch import (
    FetchedUpload,
    build_agent_prompt,
    build_provenance,
    cache_fetched_pdf,
    fetch_pdf_bytes,
    gateway_config,
    parse_agent_reply,
    request_filing_url,
    safe_fetch_filename,
)


PDF_BYTES = b"%PDF-1.7 fake body for tests" * 10


# --- T1: the UploadedFile shim -------------------------------------------

def test_shim_exposes_upload_interface_and_is_byte_identical():
    shim = FetchedUpload(PDF_BYTES, "TOU_FY2025.pdf")
    assert shim.name == "TOU_FY2025.pdf"
    assert shim.size == len(PDF_BYTES)
    assert shim.getvalue() == PDF_BYTES
    # File-like too — extract_text_from_pdf hands the object to pdfplumber.
    assert shim.read(5) == b"%PDF-"
    shim.seek(0)
    assert shim.read() == PDF_BYTES


# --- T2: config / graceful degradation -----------------------------------

def test_gateway_config_none_when_any_var_missing():
    full = {
        "OPENCLAW_GATEWAY_URL": "https://gw.example",
        "OPENCLAW_GATEWAY_TOKEN": "tok",
        "OPENCLAW_GATEWAY_SESSION_KEY": "agent:main:telegram:direct:1",
    }
    assert gateway_config(env=full) == {
        "url": "https://gw.example",
        "token": "tok",
        "session_key": "agent:main:telegram:direct:1",
    }
    for missing in full:
        partial = {k: v for k, v in full.items() if k != missing}
        assert gateway_config(env=partial) is None
    assert gateway_config(env={}) is None


# --- T3: the strict agent-reply contract ----------------------------------

def test_parse_agent_reply_contract_states():
    found = parse_agent_reply(
        'Sure! {"status": "found", "url": "https://ir.example/a.pdf", "notes": "IR page"}'
    )
    assert found == {"status": "found", "url": "https://ir.example/a.pdf",
                     "notes": "IR page"}

    assert parse_agent_reply('{"status": "not_found", "url": null, "notes": "no match"}')["status"] == "not_found"
    assert parse_agent_reply('{"status": "blocked", "url": null, "notes": "cloudflare"}')["status"] == "blocked"

    # Malformed replies are terminal and honest — never a guessed URL.
    assert parse_agent_reply("no json here")["status"] == "agent_reply_unparseable"
    assert parse_agent_reply('{"status": "maybe"}')["status"] == "agent_reply_unparseable"
    assert parse_agent_reply('{"status": "found", "url": null}')["status"] == "agent_reply_unparseable"
    assert parse_agent_reply('{"status": "found", "url": "ftp://x"}')["status"] == "agent_reply_unparseable"


def test_agent_prompt_bans_sedar_and_demands_contract():
    canadian = build_agent_prompt("Tourmaline Oil", "FY2025 annual statements", True)
    assert "SEDAR+ is OFF LIMITS" in canadian
    assert '"status": "found" | "not_found" | "blocked"' in canadian
    assert "Do NOT download" in canadian
    us = build_agent_prompt("Prologis", "FY2025 10-K", False)
    assert "SEC EDGAR" in us and "OFF LIMITS" not in us


def test_request_filing_url_sends_auth_and_session_key(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, headers=headers, body=json, timeout=timeout)
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"choices": [{"message": {"content":
                '{"status": "found", "url": "https://ir.example/f.pdf", "notes": "ok"}'}}]},
        )

    monkeypatch.setattr(agent_fetch.httpx, "post", fake_post)
    config = {"url": "https://gw.example/", "token": "tok",
              "session_key": "agent:main:telegram:direct:1"}
    reply = request_filing_url("Co", "FY2025", True, config)
    assert reply["status"] == "found"
    assert captured["url"] == "https://gw.example/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer tok"
    assert captured["headers"]["x-openclaw-session-key"] == "agent:main:telegram:direct:1"
    assert captured["body"]["model"] == "openclaw/default"
    assert captured["timeout"] == agent_fetch.AGENT_TIMEOUT_SECONDS


def test_request_filing_url_gateway_error_is_honest(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(agent_fetch.httpx, "post", boom)
    reply = request_filing_url("Co", "FY2025", True,
                               {"url": "https://gw", "token": "t", "session_key": "s"})
    assert reply["status"] == "gateway_error"
    assert "connection refused" in reply["notes"]


# --- T4/T5: the app re-fetches and verifies the bytes itself ---------------

def _fake_get(content: bytes, content_type: str = "application/pdf"):
    def fake_get(url, follow_redirects=True, timeout=None):
        return SimpleNamespace(
            raise_for_status=lambda: None,
            content=content,
            headers={"content-type": content_type},
        )
    return fake_get


def test_fetch_pdf_bytes_records_sha256(monkeypatch):
    monkeypatch.setattr(agent_fetch.httpx, "get", _fake_get(PDF_BYTES))
    result = fetch_pdf_bytes("https://ir.example/f.pdf")
    assert result["ok"] is True
    assert result["byte_size"] == len(PDF_BYTES)
    import hashlib
    assert result["sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()


def test_fetch_pdf_bytes_rejects_non_pdf(monkeypatch):
    monkeypatch.setattr(
        agent_fetch.httpx, "get",
        _fake_get(b"<html>please enable javascript</html>", "text/html"),
    )
    result = fetch_pdf_bytes("https://ir.example/landing")
    assert result == {
        "ok": False, "reason": "BAD_BYTES",
        "detail": "response is not a PDF (content-type: text/html)",
    }


def test_fetch_pdf_bytes_enforces_size_cap(monkeypatch):
    big = b"%PDF-" + b"0" * (agent_fetch.MAX_FETCH_BYTES + 1)
    monkeypatch.setattr(agent_fetch.httpx, "get", _fake_get(big))
    result = fetch_pdf_bytes("https://ir.example/huge.pdf")
    assert result["ok"] is False and result["reason"] == "BAD_BYTES"
    assert "exceeds" in result["detail"]


def test_fetch_pdf_bytes_fetch_failure_is_honest(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("dns failure")

    monkeypatch.setattr(agent_fetch.httpx, "get", boom)
    result = fetch_pdf_bytes("https://gone.example/f.pdf")
    assert result["ok"] is False and result["reason"] == "FETCH_FAILED"


# --- T6: the provenance receipt --------------------------------------------

def test_provenance_receipt_shape():
    receipt = build_provenance("https://ir.example/f.pdf", "abc123", 42)
    assert receipt["url"] == "https://ir.example/f.pdf"
    assert receipt["sha256"] == "abc123"
    assert receipt["byte_size"] == 42
    assert receipt["retrieval_method"] == "app_agent_fetch"
    assert receipt["agent_channel"] == "openclaw_gateway"
    assert receipt["retrieval_timestamp_utc"]  # ISO stamp present


def test_fetched_pdf_caching_and_filename_sanitization(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_fetch, "FETCHED_PDF_DIR", tmp_path / "_fetched")
    name = safe_fetch_filename("Tourmaline Oil / Corp", "FY2025: annual (final)")
    assert name.endswith(".pdf")
    assert "/" not in name and ":" not in name and "(" not in name
    path = cache_fetched_pdf(PDF_BYTES, name)
    assert path is not None
    assert Path(path).read_bytes() == PDF_BYTES
