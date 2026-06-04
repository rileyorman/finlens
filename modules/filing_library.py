import json
from datetime import datetime, timezone
from pathlib import Path

from config import FILING_LIBRARY_PATH, LIBRARY_PDFS_DIR, safe_write_bytes, safe_write_text

_PROJECT_ROOT = Path(__file__).parent.parent
_OLD_LIBRARY_PATH = _PROJECT_ROOT / "filing_library.json"
_OLD_PDFS_DIR = _PROJECT_ROOT / "library" / "pdfs"
_LIBRARY_PATH = FILING_LIBRARY_PATH


def _migrate_old_storage() -> None:
    try:
        _LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
        LIBRARY_PDFS_DIR.mkdir(parents=True, exist_ok=True)
        if _OLD_LIBRARY_PATH.exists() and not _LIBRARY_PATH.exists():
            safe_write_bytes(_LIBRARY_PATH, _OLD_LIBRARY_PATH.read_bytes())
        if _OLD_PDFS_DIR.exists():
            for old_file in _OLD_PDFS_DIR.iterdir():
                if old_file.is_file():
                    new_file = LIBRARY_PDFS_DIR / old_file.name
                    if not new_file.exists():
                        safe_write_bytes(new_file, old_file.read_bytes())
    except Exception:
        pass


def _normalize_file_path(path_value: str | None) -> str | None:
    if not path_value:
        return path_value
    try:
        path = Path(path_value)
        if path.parts[-2:] and len(path.parts) >= 2 and path.parts[-2] == "pdfs":
            return str(LIBRARY_PDFS_DIR / path.name)
    except Exception:
        pass
    return path_value


_migrate_old_storage()


def _load() -> dict:
    if not _LIBRARY_PATH.exists():
        return {"entries": []}
    try:
        with open(_LIBRARY_PATH, "r", encoding="utf-8") as f:
            library = json.load(f)
        changed = False
        for entry in library.get("entries", []):
            old_path = entry.get("file_path")
            new_path = _normalize_file_path(old_path)
            if new_path != old_path:
                entry["file_path"] = new_path
                changed = True
        if changed:
            _save(library)
        return library
    except Exception:
        return {"entries": []}


def _save(library: dict) -> None:
    _LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    safe_write_text(_LIBRARY_PATH, json.dumps(library, indent=2))


def get_entries() -> list:
    """Return all library entries, newest first."""
    return _load()["entries"]


def library_count() -> int:
    return len(get_entries())


def import_entries(entries: list[dict]) -> None:
    """Replace the local library with prebuilt entries."""
    _save({"entries": entries})


def add_entry(
    file_hash: str,
    file_name: str,
    file_size: int,
    financial_data: dict,
    summary_data: dict | None,
    bear_bull_data: dict | None,
    dashboard_data: dict | None = None,
    raw_text: str | None = None,
    mda_sentiment: dict | None = None,
    source: str = "pdf",
    file_path: str | None = None,
) -> None:
    """Add or update a filing entry. Keyed on file_hash so the same filing never duplicates."""
    lib = _load()

    ticker = (summary_data or {}).get("ticker") or "—"

    entry = {
        "id":              file_hash,
        "company_name":    financial_data.get("company_name", "Unknown"),
        "ticker":          ticker,
        "period":          financial_data.get("period", ""),
        "fiscal_year":     financial_data.get("fiscal_year", ""),
        "analysed_at":     datetime.now(timezone.utc).isoformat(),
        "file_name":       file_name,
        "file_size_bytes": file_size,
        "financial_data":  financial_data,
        "summary_data":    summary_data,
        "bear_bull_data":  bear_bull_data,
        "dashboard_data":  dashboard_data,
        "mda_sentiment":   mda_sentiment,
        "raw_text":        raw_text,
        "source":          source,
        "file_path":       file_path,
    }

    entries = lib["entries"]
    for i, existing in enumerate(entries):
        if existing["id"] == file_hash:
            # Preserve stored raw_text when a cache-hit update passes None —
            # we don't want to wipe text that was saved on the original analysis.
            if raw_text is None and existing.get("raw_text"):
                entry["raw_text"] = existing["raw_text"]
            if not file_path and existing.get("file_path"):
                entry["file_path"] = existing["file_path"]
            if source == "pdf" and existing.get("source"):
                entry["source"] = existing["source"]
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
