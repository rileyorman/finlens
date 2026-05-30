import json
from pathlib import Path

from config import LIBRARY_DIR, safe_write_bytes, safe_write_text

_PROJECT_ROOT = Path(__file__).parent.parent
_OLD_WATCHLIST_PATH = _PROJECT_ROOT / "library" / "watchlist.json"
_WATCHLIST_PATH = LIBRARY_DIR / "watchlist.json"


def _migrate_old_watchlist() -> None:
    try:
        _WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        if _OLD_WATCHLIST_PATH.exists() and not _WATCHLIST_PATH.exists():
            safe_write_bytes(_WATCHLIST_PATH, _OLD_WATCHLIST_PATH.read_bytes())
    except Exception:
        pass


_migrate_old_watchlist()


def load_watchlist() -> list:
    """Return list of saved ticker strings, or [] if file doesn't exist."""
    try:
        with open(_WATCHLIST_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_watchlist(tickers: list) -> None:
    """Persist the ticker list to disk."""
    _WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    safe_write_text(_WATCHLIST_PATH, json.dumps(tickers))


def add_ticker(ticker: str) -> list:
    """Add ticker (case-insensitive dedup). Returns updated list."""
    tickers = load_watchlist()
    upper   = ticker.strip().upper()
    if upper not in [t.upper() for t in tickers]:
        tickers.append(upper)
        save_watchlist(tickers)
    return tickers


def remove_ticker(ticker: str) -> list:
    """Remove ticker (case-insensitive). Returns updated list."""
    tickers = load_watchlist()
    upper   = ticker.strip().upper()
    tickers = [t for t in tickers if t.upper() != upper]
    save_watchlist(tickers)
    return tickers
