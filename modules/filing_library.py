import json
from datetime import datetime
from pathlib import Path

_LIBRARY_PATH = Path(__file__).parent.parent / "filing_library.json"


def _load() -> dict:
    if not _LIBRARY_PATH.exists():
        return {"entries": []}
    try:
        with open(_LIBRARY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"entries": []}


def _save(library: dict) -> None:
    with open(_LIBRARY_PATH, "w", encoding="utf-8") as f:
        json.dump(library, f, indent=2)


def get_entries() -> list:
    """Return all library entries, newest first."""
    return _load()["entries"]


def library_count() -> int:
    return len(get_entries())


def add_entry(
    file_hash: str,
    file_name: str,
    file_size: int,
    financial_data: dict,
    summary_data: dict | None,
    bear_bull_data: dict | None,
    dashboard_data: dict | None = None,
) -> None:
    """Add or update a filing entry. Keyed on file_hash so the same PDF never duplicates."""
    lib = _load()

    ticker = (summary_data or {}).get("ticker") or "—"

    entry = {
        "id":              file_hash,
        "company_name":    financial_data.get("company_name", "Unknown"),
        "ticker":          ticker,
        "period":          financial_data.get("period", ""),
        "fiscal_year":     financial_data.get("fiscal_year", ""),
        "analysed_at":     datetime.utcnow().isoformat(),
        "file_name":       file_name,
        "file_size_bytes": file_size,
        "financial_data":  financial_data,
        "summary_data":    summary_data,
        "bear_bull_data":  bear_bull_data,
        "dashboard_data":  dashboard_data,
    }

    entries = lib["entries"]
    for i, existing in enumerate(entries):
        if existing["id"] == file_hash:
            entries[i] = entry   # refresh in place (re-analysis updates the record)
            _save(lib)
            return

    entries.insert(0, entry)     # prepend so newest is first
    _save(lib)


def delete_entry(entry_id: str) -> None:
    """Remove a single entry by its file hash."""
    lib = _load()
    lib["entries"] = [e for e in lib["entries"] if e["id"] != entry_id]
    _save(lib)
