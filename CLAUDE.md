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
- **Avast antivirus** blocks httpx's Windows cert store access. Fix: build the SSL context manually in `claude_analyzer.py` using `ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)` + `load_verify_locations(certifi.where())`, then pass `httpx.Client(verify=ssl_ctx, trust_env=False)`. Do NOT use `ssl.create_default_context()` — it calls `set_default_verify_paths()` which Avast intercepts.

## Coding Preferences
- Keep code simple and beginner-friendly
- Python only
- No over-engineering — straightforward solutions preferred
- Brief explanations of changes and why

## Notes
- This is the standalone original app. It has also been merged into Orman Intelligence (`C:\Users\riley\OneDrive\Documents\orman_intelligence\`).
