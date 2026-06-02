# FinLens

## What This App Does

FinLens is an AI-powered investment analysis platform built with Python and Streamlit.

It helps analyze company filings, financial statements, market data, watchlists, and portfolios. The app can upload PDFs, fetch SEC EDGAR filings, extract structured financial data with Claude, generate investment signals, compare filings, run valuation tools, detect red flags, analyze MD&A sentiment, manage watchlists and portfolios, and export reports.

FinLens should be treated as an investment analysis workspace, not just a PDF-to-Excel tool.

## Strategic Context (June 2026)

- **Roadmap addendum:** `docs/FinLens_Roadmap_Addendum.md` — 5 priority feature specs and 30+ tier-mapped commercial features. This supersedes older roadmap framings for any feature decisions.
- **Mastery curriculum:** `docs/FinLens_Mastery_Curriculum.html` — 20-hour study guide. Several roadmap features serve specific chapters (Curriculum Mode, Memo Builder, Filing Diff Viewer, Catalyst Calendar).
- **Weekly audit:** `docs/audits/STEP_7_OPUS_REVIEW_PROMPT.md` — run Sundays after CC's audit report.
- **Build order priority:** Lot-level position tracking → Catalyst Calendar → Memo Builder → Filing Diff Viewer → Curriculum Mode. See addendum for full sequence.

## Engineering Principle: Empirical Evidence > Documentation

When code is empirically demonstrated to work (real API call, real metrics
captured), that evidence outweighs any documentation-based "correction."
APIs change faster than docs. Working code should NEVER be replaced with
"theoretically more correct" code based on docs alone.

Correct sequence:
1. Keep what empirically works
2. If improvement is proposed, verify the change empirically BEFORE shipping
3. Never assume the proposed change is safe just because it matches docs

Reference incident: Jun 2 2026 — Anthropic API TTL format change from "1h"
(working) to 3600 (docs-suggested) broke prompt caching. The API accepts
string TTL values; documentation lagged behavior. Rolling back to "1h"
restored function.

When reviewing changes that touch external APIs: ask "is there an empirical
test showing the current code works?" before suggesting changes.

## Core Architecture

Primary workflow:

1. User uploads a filing PDF or fetches a filing from SEC EDGAR.
2. FinLens extracts filing text or structured filing data.
3. Claude analyzes the filing using the configured model architecture.
4. The app displays statements, summary metrics, investment signals, red flags, sentiment, valuation, peer comparison, DCF, and scenario outputs.
5. Results can be saved locally and optionally synced to Supabase.
6. Users can export Excel reports and Word investment memos.
7. Saved analyses can feed the filing library, portfolio manager, watchlist, and comparison tools.

Main entry point:

- `app.py` - Streamlit UI and application orchestration.

Important project files:

- `config.py` - Claude model names, input limits, and cache directory.
- `.env` - local secrets such as API keys. Do not commit.
- `.env.example` - example environment variables.
- `requirements.txt` - Python dependencies.
- `filing_library.json` - local filing library metadata.
- `portfolio_registry.json` - local portfolio registry.
- `library/` - local library data, PDFs, and watchlist files.
- `cache/` - cached responses. Ignored by git.
- `run.bat` - local app launcher.
- `run_service.bat` - service-mode launcher for NSSM.
- `setup_service.ps1` - Windows service setup script.

## Current Module Structure

Current files in `modules/`:

- `__init__.py`
- `cache.py` - response caching helpers.
- `claude_analyzer.py` - Claude prompts and Anthropic API calls.
- `dcf_calculator.py` - discounted cash flow calculations.
- `edgar_fetcher.py` - SEC EDGAR filing lookup/fetch helpers.
- `education_content.py` - educational UI content.
- `excel_exporter.py` - Excel workbook generation and summary metric helpers.
- `filing_comparison.py` - year-over-year filing comparison.
- `filing_library.py` - local filing library persistence.
- `market_data.py` - market data and ticker lookup helpers.
- `market_ticker.py` - ticker/market display helpers.
- `mda_sentiment.py` - MD&A sentiment analysis.
- `memo_exporter.py` - Word investment memo generation.
- `pdf_extractor.py` - PDF text extraction with `pdfplumber`.
- `peer_comparison.py` - peer group and competitor comparison data.
- `portfolio_manager.py` - portfolio-level analysis display data.
- `portfolio_registry.py` - local portfolio/ticker registry.
- `red_flag_detector.py` - red/yellow flag detection logic.
- `scenario_simulator.py` - scenario and sensitivity analysis.
- `stock_tracker.py` - stock data helper used by watchlist and portfolio views.
- `supabase_storage.py` - optional Supabase persistence for filings and PDFs.
- `watchlist.py` - local watchlist persistence.

Note: if `git status` shows `modules/learning.py` as deleted, treat that as existing working-tree state. Do not restore or remove it unless explicitly asked.

## Current Tech Stack

Core:

- Python
- Streamlit
- Anthropic Claude API
- pdfplumber
- openpyxl
- python-dotenv

Data, market data, and charts:

- pandas
- yfinance
- plotly

HTTP/API support:

- httpx
- certifi

Exports and persistence:

- python-docx
- Supabase
- streamlit-cookies-manager

Local development environment:

- Windows 11
- VS Code
- PowerShell
- Python virtual environment in `venv/`

## Claude Model Architecture

Claude model configuration lives in `config.py`.

Current model setup:

```python
EXTRACTION_MODEL = "claude-haiku-4-5-20251001"
ANALYSIS_MODEL = "claude-sonnet-4-6"
BEAR_BULL_MODEL = "claude-sonnet-4-6"
```

Current input limits:

```python
MAX_EXTRACTION_FRONT = 50_000
MAX_EXTRACTION_BACK = 150_000
MAX_FILING_CHARS = 80_000
```

Architecture:

- Haiku is used for fast, lower-cost extraction.
- Sonnet is used for reasoning-heavy analysis.
- Bear/bull case generation currently uses Sonnet.
- Input truncation and response caching are used to control API cost.

When changing model behavior, prefer updating `config.py` instead of hardcoding model names inside modules.

## Important Windows SSL Note

`modules/claude_analyzer.py` contains an important Windows SSL workaround for Avast HTTPS inspection.

Known-good pattern:

```python
ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ssl_ctx.load_default_certs()
ssl_ctx.check_hostname = True
client = anthropic.Anthropic(
    api_key=api_key,
    http_client=httpx.Client(verify=ssl_ctx, trust_env=False),
)
```

Do not casually replace this with `certifi.where()` or `ssl.create_default_context()` unless Windows + Avast behavior has been retested.

## Running Locally

Regular PowerShell:

```powershell
cd "C:\Users\riley\OneDrive\Documents\Python Project\finlens"; .\venv\Scripts\Activate.ps1; streamlit run app.py
```

Alternative:

```powershell
.\run.bat
```

The local app usually runs at:

```text
http://localhost:8501
```

Use semicolons (`;`) instead of `&&` when chaining commands in PowerShell.

## Git Workflow

Development happens on the `dev` branch.

Stable, tested, demo-ready changes are merged from `dev` into `main` for deployment.

Before every commit, run:

```powershell
python -m py_compile app.py
```

Keep detailed git command sequences outside this file. This file should capture project rules and expectations, not serve as a full git operations manual.

Do not commit secrets, `.env`, `.streamlit/secrets.toml`, cache files, generated PDFs, generated Excel files, or generated Word documents.

## Windows Service Deployment

FinLens can run as a Windows service using NSSM.

Relevant files:

- `setup_service.ps1` - installs/configures the service.
- `run_service.bat` - launches the Streamlit app in service mode.
- `logs/service_stdout.log` - service stdout log.
- `logs/service_stderr.log` - service stderr log.

Service name:

```text
FinLens
```

Keep detailed NSSM operational commands outside this file. Service install, restart, stop, start, and removal steps belong in deployment notes or a dedicated operations document.

## Supabase Storage

FinLens can optionally use Supabase for filing and PDF persistence.

Current tables:

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

`modules/supabase_storage.py` should fail gracefully when credentials are missing or API calls fail.

## Cache Directory

`config.py` currently places the cache outside OneDrive on Windows:

```python
CACHE_DIR = Path(r"C:\Users\riley\AppData\Local\FinLens\cache")
```

On non-Windows systems, it uses:

```python
CACHE_DIR = Path("/tmp/finlens_cache")
```

This avoids OneDrive warnings from mass cache deletion.

## Coding Standards

Keep code beginner-friendly.

Prefer simple, readable implementations over clever abstractions.

Use clear variable names and straightforward control flow.

Add comments when they explain non-obvious business logic, financial calculations, API behavior, Streamlit state, or Windows-specific behavior.

Use f-strings for string interpolation.

Good:

```python
message = f"Analysis complete for {company_name}"
```

Avoid:

```python
message = "Analysis complete for " + company_name
```

Wrap external API calls in `try/except` so the app can show a useful error instead of crashing.

External API or fragile I/O areas include:

- Anthropic Claude API
- yfinance
- SEC EDGAR
- Supabase
- HTTP requests
- PDF extraction
- Excel export
- Word export
- Local file persistence

Simple pattern:

```python
try:
    result = external_client.call(...)
except Exception as e:
    st.error(f"API call failed: {e}")
    return None
```

Before commits, run:

```powershell
python -m py_compile app.py
```

## Documentation Standards

When documenting commands, specify whether they require:

- Regular PowerShell
- Admin PowerShell

Use PowerShell syntax for Windows commands.

Use semicolons (`;`) instead of `&&` for chained PowerShell commands.

Keep documentation aligned with the actual repository.

## Current Roadmap

Relevant roadmap items:

- Improve one-page Investment Memo export.
- Wire red flags into the Word memo.
- Prepare for demos with company selection and rehearsal.
- Test bank filing support with USB 10-K.
- Test insurance filing support with Aflac 10-K.
- Add sector-aware logic for corporate, bank, and insurance filings.
- Gracefully suppress metrics that do not apply to a filing type.
- Improve small-cap market data reliability where yfinance is weak.
- Continue improving ticker lookup by company name.
- Streamlit Community Cloud deployment and secrets setup.
- Build Signal Tracker.
- Improve peer benchmarking.
- Add or improve MD&A sentiment delta and language-change analysis.
- Add earnings quality scoring.
- Add earnings call transcript analysis.
- Improve filing comparison engine.
- Improve scenario simulator.
- Add financial distress scoring.
- Continue Portfolio Manager features:
  - position tracking
  - live P&L
  - portfolio weights
  - watchlist integration
  - benchmark comparison
  - filing alerts
  - thesis tracking
  - portfolio risk narrative

## Deployment Checklist

Before deployment or demo:

1. Confirm work is on `dev`.
2. Run `python -m py_compile app.py`.
3. Start Streamlit locally and confirm the app loads.
4. Test the affected user flow.
5. Confirm `.env` and `.streamlit/secrets.toml` are not committed.
6. Confirm generated reports and PDFs are not committed.
7. Merge `dev` into `main` only when stable.
8. If using Windows service deployment, restart the FinLens service through the approved NSSM operations process.
9. Check service logs if the app does not start.

## Communication Preferences

Codex uses `CODEX_MEMORY.md` for project context.

Explain changes briefly and clearly.

Use beginner-friendly language.

Be specific about what changed and why.

Prefer practical next steps over long theoretical explanations.
