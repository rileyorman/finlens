EXTRACTION_MODEL    = "claude-haiku-4-5-20251001"   # Fast, cheap, accurate for numbers
ANALYSIS_MODEL      = "claude-sonnet-4-6"              # Good reasoning, low cost
BEAR_BULL_MODEL     = "claude-sonnet-4-6"              # Same
MAX_EXTRACTION_CHARS = 150_000  # Haiku cap — keeps large 10-Ks under the 200K token limit
MAX_FILING_CHARS    = 80_000    # Sonnet cap for analysis/summary calls
