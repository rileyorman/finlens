EXTRACTION_MODEL    = "claude-haiku-4-5-20251001"   # Fast, cheap, accurate for numbers
ANALYSIS_MODEL      = "claude-sonnet-4-6"              # Good reasoning, low cost
BEAR_BULL_MODEL     = "claude-sonnet-4-6"              # Same
MAX_EXTRACTION_FRONT = 50_000   # Front slice: cover page + business overview
MAX_EXTRACTION_BACK  = 100_000  # Back slice: financial statements (always at end of filing)
MAX_FILING_CHARS     = 80_000   # Sonnet cap for analysis/summary calls (Calls 2-4)
