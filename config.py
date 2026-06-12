import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

# Load .env before resolving paths so FINLENS_DATA_DIR is available.
# override=False means already-set env vars (e.g. from NSSM service env) win.
load_dotenv(Path(__file__).parent / ".env", override=False)

EXTRACTION_MODEL    = "claude-haiku-4-5-20251001"   # Fast, cheap, accurate for numbers
ANALYSIS_MODEL      = "claude-sonnet-4-6"              # Good reasoning, low cost
BEAR_BULL_MODEL     = "claude-sonnet-4-6"              # Same
MAX_EXTRACTION_FRONT = 50_000   # Front slice: cover page + business overview
MAX_EXTRACTION_BACK  = 150_000  # Back slice: financial statements (always at end of filing)
MAX_FILING_CHARS     = 80_000   # Sonnet cap for analysis/summary calls (Calls 2-4)

PROJECT_ROOT = Path(__file__).parent
_PROJECT_LIBRARY_PATH = PROJECT_ROOT / "filing_library.json"

# Canonical app-data root. FINLENS_DATA_DIR env var must be set when the
# app runs as a Windows service: LocalSystem's Path.home() resolves to
# C:\Windows\System32\config\systemprofile, diverging from the user's
# C:\Users\{user}\.finlens. Set FINLENS_DATA_DIR=C:\Users\{user}\.finlens
# in .env (or the NSSM service environment) to pin the canonical path.
# Interactive sessions can omit the var; Path.home() is used as fallback.
_finlens_data_dir = os.environ.get("FINLENS_DATA_DIR", "").strip()
_APP_BASE = Path(_finlens_data_dir) if _finlens_data_dir else Path.home() / ".finlens"

LIBRARY_DIR = _APP_BASE
CACHE_DIR = _APP_BASE / "cache" if sys.platform == "win32" else Path("/tmp/finlens_cache")

LIBRARY_PDFS_DIR = LIBRARY_DIR / "pdfs"
FILING_LIBRARY_PATH = LIBRARY_DIR / "filing_library.json"
ANALYSIS_CACHE_DIR = LIBRARY_DIR / "analysis"
EDGAR_TEXT_DIR = LIBRARY_DIR / "edgar_text"
YFINANCE_CACHE_DIR = LIBRARY_DIR / "yfinance_cache"


def safe_write_text(path, content, encoding="utf-8") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding=encoding)


def safe_write_bytes(path, content: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _copy_file_if_missing(source: Path, target: Path) -> None:
    if source.exists() and source.is_file() and not target.exists():
        safe_write_bytes(target, source.read_bytes())


def _copy_dir_files_if_missing(source_dir: Path, target_dir: Path, pattern: str = "*") -> None:
    if not source_dir.exists() or not source_dir.is_dir():
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    for source in source_dir.glob(pattern):
        if source.is_file():
            _copy_file_if_missing(source, target_dir / source.name)


def _migrate_appdata_storage() -> None:
    try:
        _copy_file_if_missing(_PROJECT_LIBRARY_PATH, FILING_LIBRARY_PATH)
    except Exception:
        pass

    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        return
    old_dir = Path(local_appdata) / "FinLens"
    if not old_dir.exists() or old_dir == LIBRARY_DIR:
        return

    try:
        _copy_file_if_missing(old_dir / "filing_library.json", FILING_LIBRARY_PATH)
        _copy_file_if_missing(old_dir / "watchlist.json", LIBRARY_DIR / "watchlist.json")
        _copy_dir_files_if_missing(old_dir / "pdfs", LIBRARY_PDFS_DIR)
        _copy_dir_files_if_missing(old_dir / "analysis", ANALYSIS_CACHE_DIR, "*.json")
        _copy_dir_files_if_missing(old_dir / "cache", CACHE_DIR, "*.json")
        _copy_dir_files_if_missing(old_dir / "edgar_text", EDGAR_TEXT_DIR)
    except Exception:
        pass


for _dir in (LIBRARY_DIR, LIBRARY_PDFS_DIR, ANALYSIS_CACHE_DIR, EDGAR_TEXT_DIR, CACHE_DIR, YFINANCE_CACHE_DIR):
    _dir.mkdir(parents=True, exist_ok=True)
FILING_LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
_migrate_appdata_storage()

# Second migration: copy data from temp directory if it exists
# (previous codebase stored data in %TEMP%\FinLens; new location is
# ~/.finlens for persistence).
try:
    if sys.platform == "win32":
        old_temp = Path(tempfile.gettempdir()) / "FinLens"
        if old_temp.exists() and old_temp != LIBRARY_DIR:
            _copy_file_if_missing(old_temp / "filing_library.json", FILING_LIBRARY_PATH)
            _copy_file_if_missing(old_temp / "watchlist.json", LIBRARY_DIR / "watchlist.json")
            _copy_dir_files_if_missing(old_temp / "pdfs", LIBRARY_PDFS_DIR)
            _copy_dir_files_if_missing(old_temp / "analysis", ANALYSIS_CACHE_DIR, "*.json")
            _copy_dir_files_if_missing(old_temp / "edgar_text", EDGAR_TEXT_DIR)
except Exception:
    pass
