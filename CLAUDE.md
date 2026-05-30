# FinLens

## What This App Does
Streamlit app that extracts financial data from PDFs using the Claude API and exports structured reports to Excel.

## Key Files
- `app.py` — main Streamlit UI
- `modules/claude_analyzer.py` — Anthropic API integration (PDF → structured JSON)
- `modules/pdf_extractor.py` — pdfplumber text extraction
- `modules/excel_exporter.py` — Excel report generation

## Run
```
streamlit run app.py
```
Or double-click `run.bat`.

## Tech Stack
- Python, Streamlit, Claude API (claude-sonnet-4-6), pdfplumber, openpyxl

## Supabase Schema
```sql
CREATE TABLE filings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at timestamptz DEFAULT now(),
  ticker text,
  company text,
  period text,
  data jsonb,
  CONSTRAINT filings_ticker_period_unique UNIQUE (ticker, period)
);

CREATE TABLE pdfs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at timestamptz DEFAULT now(),
  ticker text,
  period text,
  file_data text,
  CONSTRAINT pdfs_ticker_period_unique UNIQUE (ticker, period)
);
```

## Known Issues
- **Avast antivirus — SSL CERTIFICATE_VERIFY_FAILED on Windows**
  Avast performs HTTPS inspection (man-in-the-middle): it presents its own certificate, signed by the Avast CA, which lives in the Windows system cert store. The certifi bundle does not include the Avast CA, so `load_verify_locations(certifi.where())` fails with `unable to get local issuer certificate`.

  **Fix (applied in `claude_analyzer.py`, both `analyze_financials` and `analyze_summary`):**
  ```python
  ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
  ssl_ctx.load_default_certs()  # Windows system cert store — includes Avast CA
  ssl_ctx.check_hostname = True
  client = anthropic.Anthropic(
      api_key=api_key,
      http_client=httpx.Client(verify=ssl_ctx, trust_env=False),
  )
  ```
  Do NOT use `ssl.create_default_context()` — it calls `set_default_verify_paths()` which Avast intercepts.
  Do NOT use `certifi.where()` alone — certifi's bundle does not include Avast's CA.

## Coding Preferences
- Keep code simple and beginner-friendly
- Python only
- No over-engineering — straightforward solutions preferred
- Brief explanations of changes and why

## Cache Directory & OneDrive
- `cache/` is excluded from git (`.gitignore`) but lives inside the OneDrive-synced project folder by default, which causes OneDrive to flag mass deletions when cache is cleared.
- To fix: change `CACHE_DIR` in `config.py` to a path outside OneDrive, e.g. `Path(r"C:\Users\riley\AppData\Local\FinLens\cache")`. The cache module reads `CACHE_DIR` from config so no other changes are needed.

## Notes
- This is the standalone original app. It has also been merged into FinTelligence (`C:\Users\riley\OneDrive\Documents\orman_intelligence\`).
- Project location: `C:\Users\riley\OneDrive\Documents\Python Project\finlens\`

## Next Session
1. **MHH market data** — yfinance unreliable for small-caps. Investigate alternatives: try `yf.download()` for price, or Alpha Vantage free tier as a fallback source.
2. **Summary tab metrics showing — / N/A** — keyword mismatch between Haiku extraction labels and `_calc_summary_metrics()` lookup. Need to debug with a real MHH output: log what Haiku returns vs. what the function expects.
3. **Test on bank and insurance filings** — USB 10-K (bank mode) and Aflac 10-K (insurance mode) before June meeting. Expect broken metrics; sector detection logic needed to suppress them gracefully.
