import json
from datetime import datetime, timezone
from pathlib import Path

_REGISTRY_PATH = Path(__file__).parent.parent / "portfolio_registry.json"


def load_registry() -> dict:
    if not _REGISTRY_PATH.exists():
        registry = {"portfolios": {}}
        save_registry(registry)
        return registry
    try:
        with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"portfolios": {}}


def save_registry(registry: dict) -> None:
    with open(_REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)


def get_portfolio_names() -> list:
    return sorted(load_registry()["portfolios"].keys())


def create_portfolio(name: str) -> bool:
    """Create a new named portfolio. Returns False if name already exists."""
    reg = load_registry()
    if name in reg["portfolios"]:
        return False
    reg["portfolios"][name] = {
        "created": datetime.now(timezone.utc).date().isoformat(),
        "tickers": [],
    }
    save_registry(reg)
    return True


def delete_portfolio(name: str) -> None:
    reg = load_registry()
    reg["portfolios"].pop(name, None)
    save_registry(reg)


def add_ticker(portfolio_name: str, ticker: str) -> bool:
    """Add a ticker (uppercased). Returns False if already present."""
    ticker = ticker.upper().strip()
    reg = load_registry()
    portfolio = reg["portfolios"].get(portfolio_name)
    if portfolio is None:
        return False
    if ticker in portfolio["tickers"]:
        return False
    portfolio["tickers"].append(ticker)
    save_registry(reg)
    return True


def remove_ticker(portfolio_name: str, ticker: str) -> None:
    ticker = ticker.upper().strip()
    reg = load_registry()
    portfolio = reg["portfolios"].get(portfolio_name)
    if portfolio is None:
        return
    portfolio["tickers"] = [t for t in portfolio["tickers"] if t != ticker]
    save_registry(reg)


def bulk_add_tickers(portfolio_name: str, tickers: list) -> dict:
    """Add multiple tickers. Returns {"added": [...], "skipped": [...]}."""
    added, skipped = [], []
    for t in tickers:
        t = t.upper().strip()
        if not t:
            continue
        if add_ticker(portfolio_name, t):
            added.append(t)
        else:
            skipped.append(t)
    return {"added": added, "skipped": skipped}


def get_tickers(portfolio_name: str) -> list:
    reg = load_registry()
    return list(reg["portfolios"].get(portfolio_name, {}).get("tickers", []))
