import sys
from pathlib import Path

EXTRACTION_MODEL    = "claude-haiku-4-5-20251001"   # Fast, cheap, accurate for numbers
ANALYSIS_MODEL      = "claude-sonnet-4-6"              # Good reasoning, low cost
BEAR_BULL_MODEL     = "claude-sonnet-4-6"              # Same
MAX_EXTRACTION_FRONT = 50_000   # Front slice: cover page + business overview
MAX_EXTRACTION_BACK  = 150_000  # Back slice: financial statements (always at end of filing)
MAX_FILING_CHARS     = 80_000   # Sonnet cap for analysis/summary calls (Calls 2-4)

# Cache directory — Windows: outside OneDrive to prevent sync conflicts on cache clears.
# Linux (Streamlit Cloud): /tmp is writable and appropriately ephemeral for a cache.
if sys.platform == "win32":
    CACHE_DIR = Path(r"C:\Users\riley\AppData\Local\FinLens\cache")
else:
    CACHE_DIR = Path("/tmp/finlens_cache")
