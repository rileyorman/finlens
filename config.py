import os
import sys
import tempfile
from pathlib import Path

EXTRACTION_MODEL    = "claude-haiku-4-5-20251001"   # Fast, cheap, accurate for numbers
ANALYSIS_MODEL      = "claude-sonnet-4-6"              # Good reasoning, low cost
BEAR_BULL_MODEL     = "claude-sonnet-4-6"              # Same
MAX_EXTRACTION_FRONT = 50_000   # Front slice: cover page + business overview
MAX_EXTRACTION_BACK  = 150_000  # Back slice: financial statements (always at end of filing)
MAX_FILING_CHARS     = 80_000   # Sonnet cap for analysis/summary calls (Calls 2-4)

PROJECT_ROOT = Path(__file__).parent
FILING_LIBRARY_PATH = PROJECT_ROOT / "filing_library.json"

# Mutable local storage. Windows Streamlit can fail to write to AppData on this
# machine, so cache-like artifacts live in the system temp directory.
if sys.platform == "win32":
    _TEMP_BASE = Path(tempfile.gettempdir()) / "FinLens"
    LIBRARY_DIR = _TEMP_BASE
    CACHE_DIR = _TEMP_BASE / "cache"
else:
    LIBRARY_DIR = PROJECT_ROOT / "library"
    CACHE_DIR = Path("/tmp/finlens_cache")

LIBRARY_PDFS_DIR = LIBRARY_DIR / "pdfs"
ANALYSIS_CACHE_DIR = LIBRARY_DIR / "analysis"
EDGAR_TEXT_DIR = LIBRARY_DIR / "edgar_text"


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


for _dir in (LIBRARY_DIR, LIBRARY_PDFS_DIR, ANALYSIS_CACHE_DIR, EDGAR_TEXT_DIR, CACHE_DIR):
    _dir.mkdir(parents=True, exist_ok=True)
FILING_LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
_migrate_appdata_storage()
