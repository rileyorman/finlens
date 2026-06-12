# SEDAR+ PDF Extraction Layer — Phase 1 Design Spec

**Status:** Approved design, pre-implementation. Designed June 12, 2026 (Claude Fable 5 session).
**Purpose:** Extract financial statements from Canadian IFRS filings (SEDAR+ PDFs, no XBRL). This is the Phase 2 commercial moat — a validated Canadian dataset competitors skip.
**Handoff note:** Any model picking this up should read this spec + CLAUDE.md + INTEGRITY_ENGINE_OPERATING_GUIDE.md before writing code. Architecture decisions below are settled — do not relitigate without Riley's sign-off.

## Pipeline

SEDAR+ PDF → page locator → Claude extraction (Sonnet 4.6) → IFRS mapping layer → normalize_and_validate() → Integrity Engine → analysis (existing path)

New module: `sedar_extractor.py`. Everything downstream of the mapping layer reuses existing code — normalize at the boundary, not in consumers.

## Settled design decisions

1. **Hybrid extraction, not whole-PDF.** Programmatic pass (pdfplumber text search for "Consolidated Statements of Financial Position / Income / Cash Flows") locates the 6–10 statement pages. Only those pages go to Claude with a structured JSON extraction prompt. Prompt caching on the extraction system prompt. Model: Sonnet 4.6 (numbers are accuracy-critical; not a Haiku job).

2. **Extend existing schema, don't fork.** New standard-aware alias table (IFRS + US GAAP) parallel to existing label aliases: "Statement of Financial Position" → balance sheet, "Finance costs" → interest expense, "Trade and other receivables" → receivables, etc. New metadata fields: `accounting_standard`, `currency`, `extraction_confidence` (per line item), `source: "sedar_pdf"`. Schema bump to v4 — stale-cache warning UI already handles this.

   [ADDITION — VALIDATED Jun 2026: CNR files US GAAP on SEDAR+ (NYSE cross-listing) — campaign filer #2. The mapping layer must branch on accounting_standard; Integrity Engine must treat the field as informational, never assume IFRS for SEDAR filers.]

3. **Currency and scale are first-class.** Filings state "in thousands of CAD" (or USD — many TSX filers report USD). Extraction captures both; `normalize_financial_data()` scales at ingestion. Magnitude-range principle applies.

4. **Integrity Engine changes.** One new rule: extraction-confidence — any line item below threshold fires flag-and-warn (st.warning), consistent with existing rules. Existing rules gain an `accounting_standard` check where IFRS legitimately differs (e.g., IFRS permits interest paid in operating OR financing cash flow — cross-validation cannot assume GAAP placement). Sector-skip logic carries over unchanged.

5. **Cache extracted JSON in Supabase.** Keyed by filing, schema-versioned. Claude extraction cost paid once per filing, ever. Re-analysis pulls cached JSON.

6. **Validation campaign (same playbook as US fetch campaign).** Hand-verify 4–5 Canadian filers across sectors against actual PDFs: Constellation Software (software), CN Rail (industrial), Royal Bank (financial — sector-skip test), a REIT, Fairfax (insurer — Markel analog, US side already validated). Pytest fixture per filer, detection tests, /integrity-log after each.

## Phase 1 scope cuts (deliberate)

- **Financial statements only.** MD&A and notes already reach the analyzer via existing PDF Upload path. Do not bundle.
- **Manual PDF ingestion via existing Upload path** with an explicit "Canadian filing (IFRS)" toggle. Auto-detect deferred until extraction is validated. SEDAR+ automated fetching is out of scope (no friendly API; separate project).

## Build order (next steps when work resumes)

1. Codex: `sedar_extractor.py` Phase 1 — page locator + extraction call + JSON contract. (Codex prompt not yet written — write it from this spec.)
2. CC review per standard pipeline (visual run required).
3. IFRS alias table + schema v4 bump.
4. Integrity Engine: extraction-confidence rule + accounting_standard checks. (Commits to engine.py/rules.py → /detection-test then /integrity-log.)
5. Validation campaign filers, one at a time, fixture + /integrity-log each.

## Open items

- Extraction-confidence threshold value: tune during validation campaign.
- Auto-detect IFRS: revisit after validation campaign passes.
- French-language filings: not addressed in Phase 1 — flag if encountered.
- [ADDITION] Locator page-sweep tuning: all three campaign filers show trailing/supplemental page sweep; RY (246pp bank filing) hit 42.5K input tokens with 47 swept pages. CAUTION from RY: the earliest matching cluster can be false positives (body-text references at pp110-111; real consolidated statement at pp146-147) — naive first-cluster or page-cap pruning would have selected wrong pages. Sweep is currently load-bearing for accuracy. Tune only with verification step in place, after more filers.
- [ADDITION] Campaign status: CSU ✅ (IFRS/USD/Dec) · CNR ✅ (US GAAP/CAD/Dec) · RY ✅ (IFRS/CAD/Oct, 246pp). All PDF-verified, CI-locked (f93868b, 49f14d0). Next: Canadian REIT (RioCan or CAP REIT).
