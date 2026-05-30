import base64
import os

import streamlit as st


def _get_secret(name: str) -> str | None:
    try:
        value = st.secrets.get(name)
    except Exception:
        value = None
    return value or os.environ.get(name)


def get_client():
    try:
        url = _get_secret("SUPABASE_URL")
        key = _get_secret("SUPABASE_KEY")
        if not url or not key:
            return None

        from supabase import create_client

        return create_client(url, key)
    except Exception:
        return None


def save_filing(ticker, company, period, data: dict) -> bool:
    try:
        client = get_client()
        if client is None or not ticker or not period:
            return False

        payload = {
            "ticker": str(ticker).upper(),
            "company": company or "",
            "period": str(period),
            "data": data or {},
        }
        client.table("filings").upsert(payload, on_conflict="ticker,period").execute()
        return True
    except Exception:
        return False


def load_all_filings() -> list[dict]:
    try:
        client = get_client()
        if client is None:
            return []

        response = (
            client.table("filings")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )
        return response.data or []
    except Exception:
        return []


def save_pdf(ticker, period, pdf_bytes: bytes) -> bool:
    try:
        client = get_client()
        if client is None or not ticker or not period or not pdf_bytes:
            return False

        payload = {
            "ticker": str(ticker).upper(),
            "period": str(period),
            "file_data": base64.b64encode(pdf_bytes).decode("ascii"),
        }
        client.table("pdfs").upsert(payload, on_conflict="ticker,period").execute()
        return True
    except Exception:
        return False


def load_pdf(ticker, period) -> bytes | None:
    try:
        client = get_client()
        if client is None or not ticker or not period:
            return None

        response = (
            client.table("pdfs")
            .select("file_data")
            .eq("ticker", str(ticker).upper())
            .eq("period", str(period))
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if not rows or not rows[0].get("file_data"):
            return None
        return base64.b64decode(rows[0]["file_data"])
    except Exception:
        return None
