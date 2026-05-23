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

## Notes
- This is the standalone original app. It has also been merged into Orman Intelligence (`C:\Users\riley\OneDrive\Documents\orman_intelligence\`).
