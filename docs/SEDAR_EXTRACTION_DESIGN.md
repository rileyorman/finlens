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
- [ADDITION] Industry-native analysis display views (bank/REIT/insurer-shaped Analysis pages) — roadmap item, post-campaign; data-layer sector profiles land first.

## Phase 2 Design: Standard-Aware Alias Table (designed Jun 2026, Fable 5 session — settled, do not relitigate without Riley)

**Pipeline position:** extraction output → alias mapper → normalize_and_validate() → Integrity Engine.

**1. Three-stage mapping: normalize → match → classify.**
Normalize: strip note references ("(Note 4)", "(note 18)"), case, trailing punctuation; collapse whitespace. Match: exact (normalized) first, then pattern rules (e.g. label starting "amortization of intangible" → amortization). NO fuzzy matching in v1 — silent misclassification is worse than honest unmapped.

**2. Table is data, not code: sedar_aliases.json.**
Each canonical field lists aliases; each alias tagged standards: ["IFRS"], ["US GAAP"], or both. Mapper branches on the filing's accounting_standard and consults only valid aliases. Flywheel property: new filer → unmapped labels → JSON edit + fixture, never engine changes. The git history of this file IS the error-correction asset.

**3. Unmapped labels preserved, never dropped.**
Contract carries mapped (canonical fields) + unmapped (verbatim label + value). Campaign review step per filer: inspect unmapped list, decide what earns an alias. Conservation invariant: len(mapped) + len(unmapped) == total extracted line items.

**4. Sector profiles — general mechanism, evidence-populated.**
sedar_aliases.json carries a sector_profiles section: each profile defines sector-specific canonical fields + aliases, selected via existing sector_inferred / sector-skip machinery. v1 ships ONE profile: financial_sector (net_interest_income, provision_for_credit_losses, total_revenue_bank — per RY validation). Generic fields stay null for profiled sectors — never force-map (e.g. RY "Net interest income" must NOT map to generic revenue). Future profiles (REIT, insurance, rail) added only when a campaign filer provides the label evidence. Industry-native analysis DISPLAY views are a separate roadmap item — v1 display: N/A markers, consistent with existing Dalio stress N/A behavior.

**5. Mapping confidence separate from extraction confidence.**
Each mapped item records match_type: exact | pattern, alongside the extractor's per-line confidence. Integrity Engine flag-and-warn distinguishes "uncertain read" from "uncertain mapping".

**6. Validation: existing fixtures become mapping tests.**
Run mapper over CSU/CNR/RY fixtures; assert known mappings (CNR "Revenues (Note 4)" → revenue 17304; CSU "Finance costs" → interest_expense; RY "Provision for credit losses" → bank field and NOT any generic field) + the conservation invariant. Failing assertion = finding; never weaken to pass.

**v1 scope cut:** income statement fields only. Balance sheet + cash flow follow the same machinery in a later step.

**Build order:** 1) sedar_aliases.json schema + initial aliases from the three fixtures' actual labels. 2) Mapper module (Codex, from this spec). 3) Mapping tests over existing fixtures. 4) Wire mapper into extract_sedar_filing() output path. 5) Integrity Engine: extraction-confidence rule + accounting_standard informational handling (per Settled Decision 4 update) — engine commits: /detection-test then /integrity-log.

## Session Log — June 12, 2026 (continued)

### Shipped

Phase 2 build order steps 1–5 complete.

| Commit | Description |
|---|---|
| `5be8a6f` | IFRS/US GAAP alias table initial population |
| `b67ac6c` + `205a144` | Mapper module + mapping tests |
| `f513fd5` | Wire mapper into extract_sedar_filing() output path (step 4) |
| `39213de` | Integrity Engine: extraction-confidence rule, pattern-match info, accounting-standard recording (step 5) |
| `ddf2424` | SEDAR+ upload toggle and Re-Analyse path for Canadian filings |
| `504afad` | Integrity-warning surfacing in UI; log-evidence review gate added to CLAUDE.md and CODEX_MEMORY.md |
| `e335216` | Defect 2: derive period keys per-statement — balance sheet values now resolve |
| `18d89ad` | Log path fix: pin all .finlens paths via FINLENS_DATA_DIR; eliminate Path.home() divergence |

### Live Verification — RioCan (REI.UN) FY2025

End-to-end run confirmed: extraction → mapping (1 mapped / 33 unmapped / 34 total, conservation invariant holds) → balance sheet populated → Integrity Engine entry status `clean` with all three SEDAR rules passing (`sedar_extraction_confidence`, `sedar_mapping_pattern_match`, `accounting_standard_recorded`) → IFRS recorded.

**Defect 1 root cause resolved:** `Path.home()` returned different paths under NSSM LocalSystem vs. interactive session, splitting log writes across two `.finlens` directories. Fixed by pinning all paths via `FINLENS_DATA_DIR` env var (commit `18d89ad`). Canonical location: `C:\Users\riley\.finlens`.

### Open Queue (in priority order)

1. **Alias retag:** Add `"operating income"` alias to `["IFRS", "US GAAP"]` per RioCan evidence. REIT sector profile deferred until a second REIT filer is validated.
2. **Cosmetics:** `$`-escaping in analyst text; `REI.UN` → `REI-UN.TO` yfinance format mapping; `.PDF.PDF` double-extension display bug.
3. **Dev-mode model selector:** Haiku / Sonnet / Opus 3-way selector for development testing.
4. **Investigate:** Null FinLens values in cross-validation record for REI.UN despite successful extraction — values extracted but not propagating to the CV record.
5. **Investigate:** Degenerate log entries (ticker `""` / `"—"`, all rules skipped) from generic PDF upload path — ticker-resolution gating appears to be missing before the integrity check fires.
6. **Next campaign filer:** CAP REIT or Fairfax Financial.
