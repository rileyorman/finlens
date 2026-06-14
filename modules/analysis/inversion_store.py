from __future__ import annotations

import json
import re
from pathlib import Path

from config import INVERSION_DIR, safe_write_text


SCHEMA_VERSION = 2
_STORE_DIR = INVERSION_DIR


def _safe_filename(ticker: str, period: str) -> str:
    safe = re.sub(r"[^\w\-]", "_", f"{ticker}_{period}")
    return f"{safe}.json"


def inversion_path(ticker: str, period: str) -> Path:
    return _STORE_DIR / _safe_filename(ticker, period)


def save_inversion(ticker, period, payload) -> bool:
    try:
        if not ticker or not period or not isinstance(payload, dict):
            return False
        _STORE_DIR.mkdir(parents=True, exist_ok=True)
        stamped = dict(payload)
        stamped["schema_version"] = SCHEMA_VERSION
        safe_write_text(inversion_path(ticker, period), json.dumps(stamped, indent=2, default=str))
        return True
    except Exception:
        return False


def load_inversion(ticker, period) -> dict | None:
    try:
        if not ticker or not period:
            return None
        path = inversion_path(ticker, period)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        data.setdefault("dcf_snapshot", None)
        return data
    except Exception:
        return None


def inversion_exists(ticker, period) -> bool:
    try:
        if not ticker or not period:
            return False
        return inversion_path(ticker, period).exists()
    except Exception:
        return False
