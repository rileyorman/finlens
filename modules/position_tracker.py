import json
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_POSITIONS_FILE = _DATA_DIR / "positions.json"


def _ensure_data_dir() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_all() -> dict:
    try:
        _ensure_data_dir()
        if not _POSITIONS_FILE.exists():
            return {}
        with _POSITIONS_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_all(data: dict) -> bool:
    try:
        _ensure_data_dir()
        with _POSITIONS_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False


def load_positions(portfolio_name: str) -> list[dict]:
    """
    Load all positions for a given portfolio.
    Returns a list of position dicts, or [] if none found.
    """
    try:
        data = _load_all()
        portfolio = data.get(portfolio_name, {})
        if not isinstance(portfolio, dict):
            return []
        return list(portfolio.values())
    except Exception:
        return []


def save_position(
    portfolio_name: str,
    ticker: str,
    shares: float,
    avg_cost: float,
    purchase_date: str,
    notes: str | None = None,
) -> bool:
    """
    Add or update a position for a ticker in a portfolio.
    If the ticker already exists, overwrites it.
    Returns True on success, False on failure.
    """
    try:
        data = _load_all()
        if portfolio_name not in data:
            data[portfolio_name] = {}
        ticker = ticker.strip().upper()
        data[portfolio_name][ticker] = {
            "ticker": ticker,
            "shares": float(shares),
            "avg_cost": float(avg_cost),
            "purchase_date": str(purchase_date),
            "notes": notes if notes else None,
        }
        return _save_all(data)
    except Exception:
        return False


def delete_position(portfolio_name: str, ticker: str) -> bool:
    """
    Remove a position for a ticker in a portfolio.
    Returns True on success, False on failure.
    """
    try:
        data = _load_all()
        portfolio = data.get(portfolio_name, {})
        ticker = ticker.strip().upper()
        if ticker not in portfolio:
            return False
        del portfolio[ticker]
        data[portfolio_name] = portfolio
        return _save_all(data)
    except Exception:
        return False


def calculate_pl(position: dict, current_price: float) -> dict:
    """
    Calculate P&L metrics for a single position.
    Returns a dict with cost basis, current value, unrealized gain/loss, and percentage.
    """
    try:
        shares = float(position.get("shares", 0))
        avg_cost = float(position.get("avg_cost", 0))
        current_price = float(current_price)
        cost_basis = shares * avg_cost
        current_value = shares * current_price
        unrealized_gain = current_value - cost_basis
        unrealized_gain_pct = (unrealized_gain / cost_basis * 100) if cost_basis else 0.0
        return {
            "ticker": position.get("ticker", ""),
            "shares": shares,
            "avg_cost": avg_cost,
            "current_price": current_price,
            "cost_basis": cost_basis,
            "current_value": current_value,
            "unrealized_gain": unrealized_gain,
            "unrealized_gain_pct": unrealized_gain_pct,
            "purchase_date": position.get("purchase_date", ""),
            "notes": position.get("notes"),
        }
    except Exception:
        return {
            "ticker": position.get("ticker", ""),
            "shares": 0.0,
            "avg_cost": 0.0,
            "current_price": 0.0,
            "cost_basis": 0.0,
            "current_value": 0.0,
            "unrealized_gain": 0.0,
            "unrealized_gain_pct": 0.0,
            "purchase_date": position.get("purchase_date", ""),
            "notes": position.get("notes"),
        }


def calculate_portfolio_pl(
    positions: list[dict],
    prices: dict[str, float],
) -> dict:
    """
    Calculate portfolio-level P&L across all positions.
    Skips any position whose ticker is not present in the prices dict.
    """
    pl_rows = []
    for pos in positions:
        ticker = pos.get("ticker", "")
        price = prices.get(ticker)
        if price is None:
            continue
        pl_rows.append(calculate_pl(pos, price))

    total_cost_basis = sum(r["cost_basis"] for r in pl_rows)
    total_current_value = sum(r["current_value"] for r in pl_rows)
    total_unrealized_gain = total_current_value - total_cost_basis
    total_unrealized_gain_pct = (
        (total_unrealized_gain / total_cost_basis * 100)
        if total_cost_basis
        else 0.0
    )

    position_weights = {}
    position_contributions = {}
    for r in pl_rows:
        weight = (r["current_value"] / total_current_value * 100) if total_current_value else 0.0
        contribution = (r["unrealized_gain"] / total_cost_basis * 100) if total_cost_basis else 0.0
        position_weights[r["ticker"]] = weight
        position_contributions[r["ticker"]] = contribution

    return {
        "positions": pl_rows,
        "total_cost_basis": total_cost_basis,
        "total_current_value": total_current_value,
        "total_unrealized_gain": total_unrealized_gain,
        "total_unrealized_gain_pct": total_unrealized_gain_pct,
        "position_weights": position_weights,
        "position_contributions": position_contributions,
    }
