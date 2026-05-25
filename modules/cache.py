import hashlib
import json
from datetime import datetime
from pathlib import Path

from config import CACHE_DIR as _CACHE_DIR


def get_cache_key(pdf_bytes: bytes) -> str:
    """SHA-256 hash of the raw PDF bytes — same file always maps to the same key."""
    return hashlib.sha256(pdf_bytes).hexdigest()


def load_cache(cache_key: str) -> dict | None:
    """Return cached payload for this key, or None if not found / unreadable."""
    path = _CACHE_DIR / f"{cache_key}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_cache(cache_key: str, filename: str,
               financial_data: dict, summary_data: dict | None,
               bear_bull_data: dict | None = None,
               dashboard_data: dict | None = None) -> None:
    """Persist all Claude API responses to a single JSON file."""
    _CACHE_DIR.mkdir(exist_ok=True)
    path = _CACHE_DIR / f"{cache_key}.json"
    payload = {
        "filename":       filename,
        "cached_at":      datetime.utcnow().isoformat(),
        "financial_data": financial_data,
        "summary_data":   summary_data,
        "bear_bull_data": bear_bull_data,
        "dashboard_data": dashboard_data,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def clear_cache() -> int:
    """Delete all cache files. Returns the number of files removed."""
    if not _CACHE_DIR.exists():
        return 0
    count = 0
    for f in _CACHE_DIR.glob("*.json"):
        f.unlink()
        count += 1
    return count


def cache_count() -> int:
    """Return the number of cached entries currently on disk."""
    if not _CACHE_DIR.exists():
        return 0
    return sum(1 for _ in _CACHE_DIR.glob("*.json"))
