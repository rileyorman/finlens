import os
import shutil
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

# Mutable local storage. Windows uses AppData to avoid OneDrive permission/sync issues.
# Streamlit Cloud and non-Windows environments fall back to the project library directory.
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA")
if _LOCALAPPDATA:
    LIBRARY_DIR = Path(_LOCALAPPDATA) / "FinLens"
else:
    LIBRARY_DIR = PROJECT_ROOT / "library"

LIBRARY_PDFS_DIR = LIBRARY_DIR / "pdfs"
FILING_LIBRARY_PATH = LIBRARY_DIR / "filing_library.json"
ANALYSIS_CACHE_DIR = LIBRARY_DIR / "analysis"

# Cache directory — Windows: outside OneDrive to prevent sync conflicts on cache clears.
# Linux (Streamlit Cloud): /tmp is writable and appropriately ephemeral for a cache.
if sys.platform == "win32":
    CACHE_DIR = LIBRARY_DIR / "cache"
else:
    CACHE_DIR = Path("/tmp/finlens_cache")


def safe_write_text(path, content, encoding="utf-8") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(content, encoding=encoding)
    except PermissionError:
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding=encoding,
                dir=path.parent,
                delete=False,
                suffix=".tmp",
            ) as f:
                f.write(content)
                tmp_path = Path(f.name)
            shutil.move(str(tmp_path), str(path))
        except Exception:
            tmp_path2 = Path(tempfile.gettempdir()) / path.name
            tmp_path2.write_text(content, encoding=encoding)
            shutil.move(str(tmp_path2), str(path))


def safe_write_bytes(path, content: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_bytes(content)
    except PermissionError:
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                delete=False,
                suffix=".tmp",
            ) as f:
                f.write(content)
                tmp_path = Path(f.name)
            shutil.move(str(tmp_path), str(path))
        except Exception:
            tmp_path2 = Path(tempfile.gettempdir()) / path.name
            tmp_path2.write_bytes(content)
            shutil.move(str(tmp_path2), str(path))
