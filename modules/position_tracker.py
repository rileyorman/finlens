import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

_DATA_DIR = Path(__file__).parent.parent / "data"
_POSITIONS_FILE = _DATA_DIR / "positions.json"
_LOT_STRATEGIES = {"FIFO", "LIFO", "specific"}


def _ensure_data_dir() -> None:
    _POSITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)


def _new_lot_id() -> str:
    return f"lot_{uuid4().hex[:12]}"


def _coerce_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_lot(lot: dict, fallback_date: str = "") -> dict | None:
    shares = _coerce_float(lot.get("shares"))
    if shares <= 0:
        return None

    normalized = {
        "lot_id": str(lot.get("lot_id") or _new_lot_id()),
        "shares": shares,
        "price": _coerce_float(lot.get("price")),
        "date": str(lot.get("date") or fallback_date or ""),
    }
    notes = lot.get("notes")
    if notes:
        normalized["notes"] = str(notes)
    return normalized


def _normalize_position(position: dict) -> dict | None:
    ticker = str(position.get("ticker", "")).strip().upper()
    if not ticker:
        return None

    lots = position.get("lots")
    if isinstance(lots, list):
        normalized_lots = [
            lot
            for lot in (_normalize_lot(l, position.get("purchase_date", "")) for l in lots if isinstance(l, dict))
            if lot is not None
        ]
    else:
        normalized_lots = []
        shares = _coerce_float(position.get("shares"))
        if shares > 0:
            lot = _normalize_lot(
                {
                    "shares": shares,
                    "price": position.get("avg_cost", 0),
                    "date": position.get("purchase_date", ""),
                    "notes": position.get("notes"),
                }
            )
            if lot:
                normalized_lots.append(lot)

    if not normalized_lots:
        return None
    return {"ticker": ticker, "lots": normalized_lots}


def _normalize_portfolio(portfolio: dict) -> dict:
    normalized = {}
    if not isinstance(portfolio, dict):
        return normalized

    for key, position in portfolio.items():
        if not isinstance(position, dict):
            continue
        pos = _normalize_position({**position, "ticker": position.get("ticker") or key})
        if pos:
            normalized[pos["ticker"]] = pos
    return normalized


def _load_all() -> dict:
    try:
        _ensure_data_dir()
        if not _POSITIONS_FILE.exists():
            return {}
        with _POSITIONS_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_all_normalized() -> dict:
    data = _load_all()
    return {
        str(name): _normalize_portfolio(portfolio)
        for name, portfolio in data.items()
        if isinstance(portfolio, dict)
    }


def _save_all(data: dict) -> bool:
    try:
        _ensure_data_dir()
        with _POSITIONS_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False


def total_shares(position: dict) -> float:
    return sum(_coerce_float(lot.get("shares")) for lot in position.get("lots", []))


def cost_basis(position: dict) -> float:
    return sum(
        _coerce_float(lot.get("shares")) * _coerce_float(lot.get("price"))
        for lot in position.get("lots", [])
    )


def avg_cost(position: dict) -> float:
    shares = total_shares(position)
    return (cost_basis(position) / shares) if shares else 0.0


def oldest_lot_date(position: dict) -> str:
    dated_lots = [str(lot.get("date", "")) for lot in position.get("lots", []) if lot.get("date")]
    return min(dated_lots) if dated_lots else ""


def load_positions(portfolio_name: str) -> list[dict]:
    """
    Load all positions for a given portfolio.
    Old average-cost records are converted to single-lot positions on read.
    """
    try:
        data = _load_all_normalized()
        portfolio = data.get(portfolio_name, {})
        if not isinstance(portfolio, dict):
            return []
        return list(portfolio.values())
    except Exception:
        return []


def add_position(
    portfolio_name: str,
    ticker: str,
    shares: float,
    price: float,
    purchase_date: str,
    notes: str | None = None,
) -> bool:
    """
    Add one purchase lot for a ticker in a portfolio.
    Existing lots are preserved and never merged.
    """
    try:
        data = _load_all_normalized()
        portfolio = data.setdefault(portfolio_name, {})
        ticker = ticker.strip().upper()
        if not ticker:
            return False

        lot = _normalize_lot(
            {
                "lot_id": _new_lot_id(),
                "shares": shares,
                "price": price,
                "date": purchase_date,
                "notes": notes,
            }
        )
        if lot is None:
            return False

        position = portfolio.setdefault(ticker, {"ticker": ticker, "lots": []})
        position.setdefault("lots", []).append(lot)
        return _save_all(data)
    except Exception:
        return False


def save_position(
    portfolio_name: str,
    ticker: str,
    shares: float,
    avg_cost: float,
    purchase_date: str,
    notes: str | None = None,
) -> bool:
    """
    Backward-compatible alias for adding a lot.
    avg_cost is treated as the lot purchase price.
    """
    return add_position(portfolio_name, ticker, shares, avg_cost, purchase_date, notes)


def _sort_lots_for_sale(lots: list[dict], strategy: str, lot_ids: list[str] | None) -> list[dict]:
    if strategy == "FIFO":
        return sorted(lots, key=lambda lot: (str(lot.get("date", "")), str(lot.get("lot_id", ""))))
    if strategy == "LIFO":
        return sorted(lots, key=lambda lot: (str(lot.get("date", "")), str(lot.get("lot_id", ""))), reverse=True)

    requested = list(lot_ids or [])
    order = {lot_id: idx for idx, lot_id in enumerate(requested)}
    return [lot for lot in lots if lot.get("lot_id") in order]


def sell_position(
    portfolio_name: str,
    ticker: str,
    shares: float,
    price: float,
    date: str,
    lot_strategy: str = "FIFO",
    lot_ids: list[str] | None = None,
) -> dict:
    """
    Sell shares from lots using FIFO, LIFO, or a specific lot_id list.
    Returns sale proceeds and realized P&L details, or raises ValueError.
    """
    strategy = lot_strategy or "FIFO"
    if strategy not in _LOT_STRATEGIES:
        raise ValueError("lot_strategy must be one of: FIFO, LIFO, specific")
    if strategy == "specific" and not lot_ids:
        raise ValueError("lot_ids is required for specific lot sales")

    shares_to_sell = _coerce_float(shares)
    sale_price = _coerce_float(price)
    if shares_to_sell <= 0:
        raise ValueError("shares must be greater than zero")

    data = _load_all_normalized()
    portfolio = data.get(portfolio_name, {})
    ticker = ticker.strip().upper()
    position = portfolio.get(ticker)
    if not position:
        raise ValueError(f"No position found for {ticker}")
    if shares_to_sell > total_shares(position) + 1e-9:
        raise ValueError("Cannot sell more shares than currently held")

    lots = position.get("lots", [])
    sale_lots = _sort_lots_for_sale(lots, strategy, lot_ids)
    if strategy == "specific" and shares_to_sell > sum(_coerce_float(lot.get("shares")) for lot in sale_lots) + 1e-9:
        raise ValueError("Selected lots do not contain enough shares")

    remaining_to_sell = shares_to_sell
    realized_cost_basis = 0.0
    sold_lots = []
    for lot in sale_lots:
        if remaining_to_sell <= 1e-9:
            break
        available = _coerce_float(lot.get("shares"))
        sold_shares = min(available, remaining_to_sell)
        lot_price = _coerce_float(lot.get("price"))
        lot["shares"] = available - sold_shares
        remaining_to_sell -= sold_shares
        realized_cost_basis += sold_shares * lot_price
        sold_lots.append(
            {
                "lot_id": lot.get("lot_id"),
                "shares": sold_shares,
                "price": lot_price,
                "date": lot.get("date", ""),
            }
        )

    if remaining_to_sell > 1e-9:
        raise ValueError("Unable to allocate sale across lots")

    position["lots"] = [lot for lot in lots if _coerce_float(lot.get("shares")) > 1e-9]
    if position["lots"]:
        portfolio[ticker] = position
    else:
        portfolio.pop(ticker, None)
    data[portfolio_name] = portfolio
    if not _save_all(data):
        raise ValueError("Failed to save sale")

    proceeds = shares_to_sell * sale_price
    return {
        "ticker": ticker,
        "shares": shares_to_sell,
        "price": sale_price,
        "date": str(date or datetime.today().date()),
        "lot_strategy": strategy,
        "proceeds": proceeds,
        "cost_basis": realized_cost_basis,
        "realized_gain": proceeds - realized_cost_basis,
        "sold_lots": sold_lots,
    }


def delete_position(portfolio_name: str, ticker: str) -> bool:
    """
    Remove a position for a ticker in a portfolio.
    Returns True on success, False on failure.
    """
    try:
        data = _load_all_normalized()
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
    Calculate P&L metrics for a single lot-level position.
    """
    try:
        position = _normalize_position(position) or {"ticker": position.get("ticker", ""), "lots": []}
        current_price = float(current_price)
        shares = total_shares(position)
        total_cost = cost_basis(position)
        current_value = shares * current_price
        unrealized_gain = sum(
            _coerce_float(lot.get("shares")) * (current_price - _coerce_float(lot.get("price")))
            for lot in position.get("lots", [])
        )
        unrealized_gain_pct = (unrealized_gain / total_cost * 100) if total_cost else 0.0
        return {
            "ticker": position.get("ticker", ""),
            "shares": shares,
            "avg_cost": avg_cost(position),
            "current_price": current_price,
            "cost_basis": total_cost,
            "current_value": current_value,
            "unrealized_gain": unrealized_gain,
            "unrealized_gain_pct": unrealized_gain_pct,
            "purchase_date": oldest_lot_date(position),
            "lots": position.get("lots", []),
            "notes": None,
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
            "purchase_date": "",
            "lots": [],
            "notes": None,
        }


compute_pl_for_position = calculate_pl


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
