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

## Valid Anthropic Model IDs (current — do not 'correct')

These are verified live model IDs. Training-data model lists may be stale — do not change these strings without Riley's confirmation (CLAUDE.md empirical-evidence principle: APIs change faster than docs).

- claude-haiku-4-5-20251001 (Haiku 4.5)
- claude-sonnet-4-6 (Sonnet 4.6)
- claude-opus-4-8 (Opus 4.8, current Opus)
- claude-fable-5 (Fable 5, Claude 5 family, tier above Opus)

## Engineering Principle: Number Formatters Must Handle Full Magnitude Range

FinLens analyzes companies of all sizes — from microcaps ($10M revenue) to
mega-caps ($500B+ revenue). Any helper function that formats a numeric value
for display MUST handle the full range: K (thousands), M (millions), B
(billions), and T (trillions).

Bugs from missing magnitude handling are silent and misleading:
- Palantir's $3.7B revenue displayed as "3.7M" because the formatter capped
  at M (Jun 3 2026 incident, fixed in commit 6a126d9).
- Apple's $371B total assets displayed as "371.0M" for the same reason.

Required pattern for ANY new _fmt_* function:

    def _fmt_num(v):
        if v is None:
            return "—"
        if abs(v) >= 1_000_000_000_000:
            return f"{v / 1_000_000_000_000:,.2f}T"
        if abs(v) >= 1_000_000_000:
            return f"{v / 1_000_000_000:,.2f}B"
        if abs(v) >= 1_000_000:
            return f"{v / 1_000_000:,.1f}M"
        if abs(v) >= 1_000:
            return f"{v / 1_000:,.0f}K"
        return f"{v:,.0f}"

Test cases to verify any number formatter:
- 500 → "500"
- 12_345 → "12K"
- 3_700_000_000 → "3.70B"
- 371_000_000_000 → "371.00B"
- 4_600_000_000_000 → "4.60T"

When reviewing code that creates a new formatter or modifies an existing
one, CC MUST verify the test cases above mentally or in a script before
approving.

## Engineering Principle: Persistent Storage Lives Outside Temp and Cloud Sync

Local data storage location matters more than it appears. Three traps to avoid:

1. **System temp directories (`%TEMP%`, `/tmp`)** — Windows and macOS clear
   these during cleanup, sleep recovery, or low-disk events. Data placed
   here CAN disappear without warning. NEVER store persistent app data
   here (cached filings, library entries, user state).

2. **OneDrive / iCloud / Dropbox folders** — cloud sync churns on every file
   write. Frequently-modified files (logs, caches, db files) cause CPU
   spikes and sync conflicts. NEVER store frequently-written data inside
   a sync folder, even if the project lives there.

3. **AppData (Windows) / Library (macOS)** — generally fine, but some
   anti-virus and permission setups block writes. Test before relying on it.

**Canonical pattern for FinLens app data:**

    if sys.platform == "win32":
        _APP_BASE = Path.home() / ".finlens"
    else:
        _APP_BASE = Path.home() / ".finlens"
    LIBRARY_DIR = _APP_BASE

Path.home() resolves to:
- Windows: C:\Users\{user}
- macOS/Linux: /Users/{user} or /home/{user}

This lives outside OneDrive (which mounts Documents/Desktop) and outside
temp. It survives reboots, doesn't churn cloud sync, and works without
admin permissions.

Reference incident: Jun 3 2026 — FinLens library lived in
`%TEMP%\FinLens\` because of an earlier AppData write issue. Files survived
short-term but were silently truncated when filings were re-cached, and
were vulnerable to Windows disk cleanup. Fixed by moving to
`~/.finlens`.

When designing any new feature that writes files: ask "does this need to
persist across a reboot?" If yes, NOT temp. "Will this be written frequently
during normal use?" If yes, NOT a cloud sync folder.

## SEDAR Canonical Revenue Semantics (per-sector)

The mapper's canonical `revenue` and its sector-specific revenue names carry
deliberate, distinct meanings. Do not "unify" the distinct ones, and do not
re-mint sector names for the same concept (that was the Task A bug, fixed
2026-07-03 — audit: docs/audits/2026-07-02-economics-contract-audit.md).

- `revenue` (default; resource_sector and mining_sector fill THIS slot):
  the filer's top line as canonically chosen. For resource/O&G filers this is
  GROSS product sales BEFORE royalty deductions (CNQ "Product sales" 41,509,
  not the net "Revenue" 35,656; Suncor "Gross revenues" 52,377) — per the
  2026-06-17 ground-truth decision. Display surfaces label it "gross of
  royalties" for resource filers.
  NEGATIVE RULE: on royalty-reporting resource filers, bare "Revenue" /
  net-of-royalties lines stay UNMAPPED BY DESIGN — canonical revenue = gross.
  Bare "revenue" is never a safe alias in this sector (it would capture the
  net line and collapse the gross/royalty split). Pinned by test.
- `rental_revenue` (reit_sector): rental-only revenue per the NOI rule —
  DELIBERATELY a different concept from a REIT's blended total (which, where
  a "Total revenue" line exists, maps to default `revenue` separately).
- `insurance_revenue` (insurance_sector): IFRS 17 insurance revenue —
  DELIBERATELY distinct; not comparable to a corporate top line.
- `royalties` is stored NEGATIVE (as-presented deduction, e.g. "Less:
  royalties" −5,853). Consumers wanting a positive cost must negate it.

When adding a sector profile: if the concept already has a default canonical
name, AUGMENT that name with new aliases (mining_sector pattern). Mint a new
canonical name only for a genuinely different concept, and record why.

## Canonical Field Definitions (judgment-class fields)

These fields carry documented judgment-class definitions. When mapping a new
filer in the same sector, conform to these definitions instead of re-deriving
the concept from the filer's subtotal labels.

### `insurance_finance_result`

DEFINITION: insurance finance income/(expense) from insurance contracts ISSUED
- gross, EXCLUDING reinsurance finance income/(expense).

RULE: take the "insurance finance income (expense) from contracts issued" line.
Do NOT net in reinsurance finance. If the filer prints a combined "Net
insurance financial result" subtotal, do NOT take it; take the issued-gross
component. Rationale: cross-insurer consistency. SLF has no net rollup, so
issued-gross is the only line common to both insurers.

CURRENT FILERS:
- IFC: `insurance_finance_result` = -1,041 from "Insurance finance income
  (expense)" (issued line). IFC also prints "Reinsurance finance income
  (expense)" +162 and "Net insurance financial result" -879; the -879 subtotal
  is deliberately NOT taken.
- SLF: `insurance_finance_result` = -6,787 from "Insurance finance income
  (expenses) from insurance contracts issued". SLF prints no net rollup;
  hand-confirmed 2026-06-17. Its reinsurance-held +69 and segregated-fund
  -1,901 lines are separate and are not netted into this field.

KNOWN TENSION: this reports a number that disagrees with IFC's own printed "Net
insurance financial result" subtotal. That is deliberate for comparability, not
an error. Any future insurer whose statement presents ONLY a net result and no
issued-gross line breaks this rule and needs a design decision, not a silent
map.

### `net_operating_income` (REIT sector, conditional lift/derive field)

DEFINITION: rental-only NOI - rental property operations only, EXCLUDING
residential/development revenue and cost.

RULE: conditional on filer shape:
- PURE REIT: if the filer reports a clean rental-only NOI/net-rental-income
  line with no development blended in, LIFT the printed line exactly.
  Precedents: CAR.UN "Net operating income" 730,654; DIR.UN "Net rental
  income" 355,432. Both are exact lifts, not derived.
- BLENDED REIT: if the operating subtotal mixes development margin and/or
  service-fee income into property results, DERIVE rental-only NOI as
  rental_revenue - rental operating costs (recoverable + non-recoverable),
  excluding residential inventory sales/cost AND property-management/service-fee
  income. Do NOT lift the filer's blended "Operating income" subtotal.

This matches the shipped implementation: derivation fires only where a
development/inventory line exists; pure REITs lift the clean printed line.

CURRENT FILER:
- REI.UN: `net_operating_income` = 720,404, derived as 1,176,428 "Rental
  revenue" - 414,386 "Recoverable under tenant leases" - 41,638
  "Non-recoverable costs". RioCan's printed blended "Operating income" 798,716
  is deliberately NOT used; it is preserved in `mapping.unmapped[]`.

REI.UN RECONCILIATION:
- RioCan printed blended "Operating income" = 798,716.
- Derived rental-only NOI = 720,404.
- Difference = 78,312, composed of 62,358 residential development margin
  (244,189 "Residential inventory sales" - 181,831 "Residential inventory cost
  of sales") plus 15,954 "Property management and other service fees".
- 62,358 + 15,954 = 78,312; closes exactly.

Rental-only NOI excludes BOTH the residential margin AND the service-fee income.
That is why it will not match RioCan's printed operating-income line by design.

### `property_operating_costs` (REIT sector, OPEN definition question)

CURRENT STATE / INCONSISTENCY: `property_operating_costs` currently maps
REI.UN's "Total operating costs" 637,855, which INCLUDES "Residential inventory
cost of sales" 181,831. In the same fixture, `net_operating_income` EXCLUDES
that same residential cost. Same filer, same line family, opposite treatment
across two fields.

OPEN HUMAN DECISION: should `property_operating_costs` be:
- (i) blended total including residential inventory cost of sales: 637,855
  (current REI.UN value; strongest comparability to the filing's printed
  subtotal), or
- (ii) rental-only operating costs: 456,024 = 414,386 "Recoverable under tenant
  leases" + 41,638 "Non-recoverable costs" (strongest internal consistency with
  the rental-only NOI derivation)?

Tradeoff: comparability-to-filing vs internal-consistency-with-NOI. This is a
definition gap, not a wrong number. Leave the current value untouched until
Riley decides the canonical definition.

CURRENT FILERS:
- REI.UN: `property_operating_costs` = 637,855 from "Total operating costs";
  OPEN as described above because the line includes residential inventory cost
  of sales.
- CAR.UN: `property_operating_costs` = -281,431 from "Property operating
  costs".
- DIR.UN: `property_operating_costs` = -110,786 from "Investment properties
  operating expenses".

## Engineering Principle: Cross-Check Source (FMP Is an Unreliable Witness Generally)

CROSS-CHECK SOURCE PRINCIPLE (widened 2026-07-03; original SEDAR-scoped
version e8e7062): FMP is an UNRELIABLE correctness witness GENERALLY —
including US, USD, fully-XBRL-covered filers — not only SEDAR/CAD filers.

PROOF CASE (JPM FY2025 operating_cash_flow): FMP returned +100.9B; the
as-filed 10-K (accession 0001628280-26-008131, R9 Consolidated Statements of
Cash Flows) shows (147,782) USD millions, byte-identical to FinLens's XBRL
tag. FMP's value matches NO filed year — a phantom value on the filer class
FMP should handle best.

ADDITIONAL SEDAR/CAD failure modes (retained — these compound the general
unreliability, they are not the whole principle): FMP has currency mismatches
(reports USD or a different currency than the CAD filing) and coverage gaps
for Canadian issuers (the free tier premium-blocks TSX tickers).

STANDING CONSEQUENCES: internal-consistency checks (accounting identities)
are the preferred validation; the #7 second-extractor cross-check uses Gemini
(an independent extraction of the same source PDF), NOT FMP — Gemini is the
scalable correctness path; an FMP result must NEVER adjudicate a discrepancy
alone. KNOWN GAP (flagged 2026-07-03): cross_validate.py currently runs
FMP comparison on every filing with a ticker + fiscal year, including CAD/SEDAR
filers, with no filing-vs-FMP currency check — this may produce false flags on
Canadian filers. See queue item — the CROSS_VALIDATE CURRENCY GATE is a
prerequisite before any FMP tier/coverage upgrade.

## Engineering Principle: Normalize at the Boundary, Not in Consumers

External data sources (Claude analyses, FMP, yfinance, EDGAR) return data
in inconsistent shapes:
- Currency units vary by filing (thousands vs millions vs billions)
- Field names vary across APIs (`netIncome` vs `net_income` vs `ni`)
- Null values vs missing keys vs zero
- Date formats vary (ISO vs unix timestamp vs human-readable)

When inconsistent data leaks past the ingestion boundary, every consumer
must handle the variance — leading to scattered patches, missed cases, and
recurring bugs in new render paths.

**Pattern to follow:** Normalize ONCE at the boundary (where data enters the
codebase), then pass canonical-form data to every downstream consumer.
Consumers should NEVER need to know about source-specific quirks.

Examples in FinLens:
- `normalize_financial_data()` in `modules/claude_analyzer.py` scales all
  values to raw USD at the point Claude returns financial_data. Statements,
  Dashboard, DCF, and Key Metrics all see raw dollars without scaling logic.
- `_fmt_num()` in `app.py` formats raw values consistently with K/M/B/T
  thresholds. All renders use the same formatter.

**Anti-pattern to avoid:** Letting raw external data flow into session_state
or render functions, then applying per-consumer transformations. This
guarantees that the next new consumer (added six months from now) will have
the same bug.

**Reference incidents (June 2026):**
- `_fmt_num()` capped at M -> Palantir $3.7B displayed as 3.7M (commit 0f08323)
- Filing data in "USD, in thousands" -> Snowflake $4.7B displayed as $4.7M
  across Statements, Dashboard, DCF, Key Metrics independently. Fixed once
  in `normalize_financial_data` (commit c7de60b).

**When adding a new external data source or consumer:**
- Ask "where does this data enter the system?" — normalize there
- Ask "what canonical form do all consumers expect?" — enforce it at the
  boundary
- If you find yourself writing the same transformation in two consumers,
  move it upstream

## Engineering Principle: Don't Silently Truncate Analyst-Generated Text

FinLens's value comes from Claude's analysis — investment signal reasoning,
bull/bear cases, MD&A summaries, capital allocation narratives, framework
perspectives. When this text is truncated on display, users lose the
analytical depth that makes FinLens worth paying for.

Hard-truncation patterns to AVOID for analyst-generated text:

    text[:300]                  # BAD if text is Claude output
    thesis[:500]                # BAD
    reasoning[:1000]            # BAD

Acceptable truncation cases:
- File paths (OS limit ~260 chars on Windows)
- API token chunking in analyzer input (NOT in display layer)
- HTML attributes with strict length constraints

**When in doubt, render the full text.** Layout overflow is recoverable;
lost analytical content is not.

**Reference incident (June 2026):**
- Markel investment thesis cut off mid-word at 300 chars: "...preferred
  stock rede" instead of full reasoning. Fixed by removing the [:300]
  truncation entirely.

When adding a new render path for Claude output: render in full. If layout
breaks, fix the CSS, not the text.

## Engineering Principle: Audit-Driven Fixes for Repeated Patterns

When a bug is discovered in one location, ask: "Could this same bug exist
elsewhere in the codebase with a similar pattern?" If yes, run an audit
before declaring the fix complete.

**Pattern to follow:**
1. Fix the discovered bug in its specific location
2. Identify the underlying pattern (formatter, truncation, deprecation,
   normalization gap, etc.)
3. Grep / search the entire codebase for that pattern
4. Classify each occurrence: legitimate use vs same bug
5. Fix all legitimate-bug occurrences in one commit
6. Document the audit results so future devs see what was checked

**When to use this pattern:**
- Number/text formatting bugs (any _fmt_* helper)
- String truncation bugs (any [:N] pattern)
- Library/API deprecations (any deprecated call)
- Data normalization gaps (any external-data entry point)
- Display bugs from missing magnitude handling

**When NOT to use this pattern:**
- One-off logic bugs specific to a single feature
- UI styling tweaks that genuinely affect only one element
- Configuration changes scoped to a single file

## Engineering Principle: Schema Versioning for Cached Data

Cached data (analysis JSON, library entries, anything persisted to disk)
must include a schema_version field. When the code evolves and the data
shape or normalization changes, bump CURRENT_SCHEMA_VERSION in
modules/analysis_cache.py.

On load, mismatched schema versions should trigger a user-facing warning
prompting Re-Analyse -- never silently display data from an old schema
through a new render path. Silent mismatch produces the worst bugs
(numbers off by 1000x without visible symptoms in the UI).

Reference incident: Jun 4 2026 -- NVIDIA cached analysis showed revenue
$215T because normalize_financial_data() saw currency="USD" and skipped
scaling, but the saved values were stored in millions from an earlier
code path. Fixed by clearing cache; schema versioning prevents recurrence.

When changing normalize_financial_data() or any data shape: bump
CURRENT_SCHEMA_VERSION.

**Reference incidents (June 2026):**
- Number formatters (commit 0f08323): audit found 10 functions needing
  B/T handling, 4 already correct, 10 N/A. Stopped the "Palantir shows
  3.7M instead of 3.7B" recurring bug class.
- String truncations (commit 6dbdb61): audit found 34 [:N] patterns, 2
  additional Category B fixes beyond the initial discovery.
- Streamlit deprecations (commits ea2f5c6, 64ecb52): 68 use_container_width
  + 5 datetime.utcnow() fixed in coordinated commits.
- Financial data normalization (commit 564ee50): audit found 8 entry
  points, 2 missing normalize_financial_data() calls.

**CC review rule:** When CC reviews a fix that resembles one of the bug
categories above, CC MUST proactively run a grep audit and report findings
— even if Riley didn't ask. The cost of an extra audit is small; the cost
of recurring bugs is large.

## Engineering Principle: Fixture mapped_count Changes Require Registry Regen + Full Suite

When any fixture's mapped_count changes (new alias, re-map, new filer), regenerate filing_registry.json via scripts/build_filing_registry.py and run the FULL test suite including test_filing_registry.py — never a narrowed subset. The registry sync tests (test_registry_stored_field_counts_match_fixtures, test_registry_resolved_field_counts_match_live_mapper) are the machine-checkable backstop; a narrowed test run hides registry drift.

## Engineering Principle: Minimize Human Error

No procedure may depend on a human remembering it. In order of preference:
1. Machine-enforced — CI checks, pytest gates, pre-commit hooks, schema versioning
2. Machine-prompted — slash commands in .claude/commands/ that walk the procedure
3. Documented with a sync check — if a rule must live in two places, one is the
   source of truth and an automated/audited step diffs the downstream copy
4. Human memory — not acceptable; if a convention exists only in someone's head
   or chat history, encoding it is the next task

Applies to dev workflow and product alike: the Integrity Engine exists because
manual verification fails silently — the same logic governs how FinLens is built.
When reviewing or writing code, flag any step that relies on remembered convention
and recommend its encoded replacement (rule of three: third manual repetition).

**Faithful Transcription**
When encoding an existing procedure, convention, or spec into a file
(slash command, doc, config), the source content is authoritative:
- Never drop, reword, or replace items from the source. If the source
  seems wrong or incomplete, STOP and flag it — do not fix it silently.
- Additions are allowed only if explicitly labeled as additions in both
  the file and the completion report.
- Every completion report for doc/command changes must include the final
  content verbatim (or a full diff), never a paraphrased summary.
- If the source content is not provided in the task and cannot be found
  verbatim in the repo, ask for it — do not reconstruct from inference.

## Engineering Principle: CI Python Version is Authoritative

CI runs Python 3.11; local dev runs Python 3.13. These versions have real
syntax differences that `py_compile` on 3.13 will silently pass:

- **f-string backslash expressions** — `f"{func(f'\"{x}\"')}"` is valid in
  3.13 (PEP 701) but raises `SyntaxError: f-string expression part cannot
  include a backslash` in 3.11. Fix: assign the inner expression to a
  variable before the f-string.
- **3.12+ syntax** (e.g., type parameter syntax `type X = ...`) — not valid
  in 3.11.

**Rule:** `py_compile` run locally does NOT catch these errors — CI is the
arbiter. When writing f-strings with complex expressions, avoid backslashes
inside `{}` entirely: extract sub-expressions to named variables first.

**Reference incident:** Jun 2026 — `modules/edgar_fetcher.py` used
`f"...{quote(f'\"{query}\"')}..."` at two locations. Passed 3.13 locally,
broke 3.11 CI. Fixed by pre-assigning `quoted_query = quote(f'"{query}"')`.

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
- `sedar_extractor.py` - SEDAR+ PDF extraction; owns Option A cover-page selection (`_ordered_unique_pages`) and `attach_mapping()` (feeds statements to the canonical mapper).
- `scripts/run_cross_extractor.py` - manual Sunday-audit runner for the Gemini second-extractor integrity signal.
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
- `analysis_cache.py` - schema-versioned analysis JSON cache (owns `CURRENT_SCHEMA_VERSION`).
- `cache.py` - response caching helpers.
- `campaign_pdf.py` - deterministic campaign-PDF resolution by recorded canonical filename (spec: `docs/CAMPAIGN_PDF_RESOLVER_SPEC.md`).
- `claude_analyzer.py` - Claude prompts and Anthropic API calls.
- `dcf_calculator.py` - discounted cash flow calculations.
- `document_converter.py` - docx-to-markdown conversion (markitdown) for non-PDF uploads.
- `edgar_fetcher.py` - SEC EDGAR filing lookup/fetch helpers.
- `education_content.py` - educational UI content.
- `excel_exporter.py` - Excel workbook generation and summary metric helpers.
- `filing_comparison.py` - year-over-year filing comparison.
- `filing_library.py` - local filing library persistence.
- `fiscal_ai.py` - Fiscal.ai API helpers (company profile, shares outstanding, logo).
- `fmp.py` - Financial Modeling Prep statement fetch and quick-financials helpers.
- `market_data.py` - market data and ticker lookup helpers.
- `market_ticker.py` - ticker/market display helpers.
- `mda_sentiment.py` - MD&A sentiment analysis.
- `memo_exporter.py` - Word investment memo generation.
- `pdf_extractor.py` - PDF text extraction with `pdfplumber`.
- `peer_comparison.py` - peer group and competitor comparison data.
- `polymarket.py` - Polymarket macro-event probability helpers (experimental).
- `portfolio_manager.py` - portfolio-level analysis display data.
- `portfolio_registry.py` - local portfolio/ticker registry.
- `position_tracker.py` - lot-level position persistence (portfolios, lots, cost basis).
- `red_flag_detector.py` - red/yellow flag detection logic.
- `scenario_simulator.py` - scenario and sensitivity analysis.
- `stock_tracker.py` - stock data helper used by watchlist and portfolio views.
- `supabase_storage.py` - optional Supabase persistence for filings and PDFs.
- `watchlist.py` - local watchlist persistence.

Subpackage `modules/integrity/` — the Data Integrity Engine (the product's moat):

- `engine.py` - detection orchestration; runs rules over an analysis and logs results.
- `rules.py` - detection rules (sanity checks, identity checks, recency).
- `sedar_mapper.py` - SEDAR statement-label-to-canonical-field mapping and sector-profile routing.
- `sedar_aliases.json` - canonical field aliases and sector profiles consumed by the mapper.
- `log.py` - JSONL integrity log persistence (`~/.finlens/integrity_log.jsonl`) and cross-extractor disposition appends.
- `analyze.py` - integrity analysis entry points, including `/integrity-log` cross-extractor review output.
- `cross_validate.py` - four-headline cross-check of extracted figures against FMP.
- `cross_extractor.py` - Gemini second-extractor cross-check for campaign/library filers; writes `cross_extractor_agreement` integrity-log records.

Subpackage `modules/economics/`:

- `resource_economics.py` - Resource Economics Snapshot calculations (filing fundamentals x yfinance market/commodity data).
- `resource_display.py` - display-text helpers for the economics panel (labels, captions, caveats).

Subpackage `modules/analysis/`:

- `munger_inversion.py` - Munger inversion pre-mortem engine.
- `inversion_store.py` - persistent store for inversion results.

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

Doc-only commits should route through the same gate as code (Codex proposes → CC reviews → CC commits) to keep the audit trail consistent. Riley retains override authority for hotfixes.

Pre-commit gate — two tiers:
- **Every commit (machine-enforced):** `py_compile` runs automatically on all
  staged `.py` files via `.githooks/pre-commit`. Configured with
  `git config core.hooksPath .githooks`. If syntax fails, the commit is blocked.
- **Feature commits via `/codex-review` (machine-prompted):** full headless
  Streamlit startup and health-check sequence. This lives as the live-run
  requirement in `/codex-review` Step 5.

**New clone setup (one-time, required):** after cloning, run:

```powershell
git config core.hooksPath .githooks
```

Without this, the pre-commit hook is silently inactive. The Sunday audit
Step 1 checks for this and flags if it is missing.

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

`config.py` places the cache outside OneDrive, under the app data base
(`_APP_BASE`, which is `~/.finlens` by default, overridable via the
`FINLENS_DATA_DIR` env var). On Windows:

```python
CACHE_DIR = _APP_BASE / "cache"   # e.g. ~/.finlens/cache
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

## Change Propagation Rule

Whenever a feature is added or modified, identify ALL code paths that touch the same data or functionality — not just the path addressed in the current task.

**Known path pairs that must be checked together:**

- Fresh upload flow AND Filing Library Load/Re-Analyse — both consume stored filing entries and stored bytes. Changes to upload extraction (e.g. adding docx support) must be mirrored in the Re-Analyse fallback path.
- Single Analysis AND Filing Comparison AND Portfolio Manager — all consume `financial_data` / `summary_data` from session state or the library. Schema changes to those dicts affect all three.
- Anything that writes library entries AND the sidebar rendering that reads them — new fields written by `lib_add` must have safe read-side defaults, and any display logic (labels, buttons) must handle the new field.

**Before finishing any task, explicitly state:**

1. Which sibling paths were checked.
2. Whether each needed the same change or was unaffected. "Checked, not affected" is an acceptable answer — silence is not.
3. When a data schema changes (new field in library entries, `financial_data`, `positions.json`, etc.), how existing stored records without the new field are handled (default value, migration, or schema version bump).

**Reference incident (June 2026):** docx support was added to the fresh upload flow (`_is_docx` branch, `convert_to_markdown`) but the Filing Library Re-Analyse path still called `extract_text_from_pdf` on docx bytes and library entries had no `file_type` field. The fix required touching 6 locations across `app.py` and `filing_library.py`. This rule exists to catch that class of miss before it ships.

## CC Review Checklist

Gates that must be satisfied before any analysis-path change is approved.

**Integrity log evidence gate:** Any new or modified analysis path MUST demonstrate an integrity log entry — show the new JSONL line from `~/.finlens/integrity_log.jsonl` on disk as review evidence. "Reaches the engine" is not "appends to the log."
