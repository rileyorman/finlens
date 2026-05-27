import json
import os

_WATCHLIST_PATH = os.path.join("library", "watchlist.json")


def load_watchlist() -> list:
    """Return list of saved ticker strings, or [] if file doesn't exist."""
    try:
        with open(_WATCHLIST_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_watchlist(tickers: list) -> None:
    """Persist the ticker list to disk."""
    os.makedirs("library", exist_ok=True)
    with open(_WATCHLIST_PATH, "w") as f:
        json.dump(tickers, f)


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
