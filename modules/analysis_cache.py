import json
import re
from pathlib import Path

from config import ANALYSIS_CACHE_DIR, safe_write_bytes, safe_write_text

_CACHE_DIR = ANALYSIS_CACHE_DIR
_OLD_CACHE_DIR = Path(__file__).parent.parent / "library" / "analysis"
CURRENT_SCHEMA_VERSION = 3


def _migrate_old_cache() -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if _OLD_CACHE_DIR.exists() and _OLD_CACHE_DIR != _CACHE_DIR:
            for old_file in _OLD_CACHE_DIR.glob("*.json"):
                new_file = _CACHE_DIR / old_file.name
                if not new_file.exists():
                    safe_write_bytes(new_file, old_file.read_bytes())
    except Exception:
        pass


_migrate_old_cache()


def analysis_cache_path(ticker: str, period: str) -> Path:
    """Return path to the local analysis cache JSON for ticker/period."""
    safe = re.sub(r"[^\w\-]", "_", f"{ticker}_{period}")
    return _CACHE_DIR / f"{safe}.json"


def save_analysis(ticker: str, period: str, results: dict) -> bool:
    """Serialize analysis results to disk. Returns False on any write/JSON failure."""
    try:
        if not ticker or not period:
            return False
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = analysis_cache_path(ticker, period)
        payload = dict(results)
        payload["schema_version"] = CURRENT_SCHEMA_VERSION
        safe_write_text(path, json.dumps(payload, indent=2, default=str))
        return True
    except Exception:
        return False


def load_analysis(ticker: str, period: str) -> dict | None:
    """Load cached analysis results, or None when absent/unreadable."""
    try:
        if not ticker or not period:
            return None
        path = analysis_cache_path(ticker, period)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        if data.get("schema_version") != CURRENT_SCHEMA_VERSION:
            data["_is_stale"] = True
            data["_stale_reason"] = (
                f"Schema {data.get('schema_version', 'unset')} loaded by code "
                f"expecting {CURRENT_SCHEMA_VERSION}"
            )
        return data
    except Exception:
        return None


def analysis_exists(ticker: str, period: str) -> bool:
    """Return True if cached analysis JSON exists for ticker/period."""
    try:
        if not ticker or not period:
            return False
        return analysis_cache_path(ticker, period).exists()
    except Exception:
        return False
