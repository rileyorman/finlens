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
- [ADDITION] Campaign status: CSU ✅ (IFRS/USD/Dec) · CNR ✅ (US GAAP/CAD/Dec) · RY ✅ (IFRS/CAD/Oct, 246pp) · REI.UN ✅ (IFRS/CAD/Dec, filer #4, FY2025, 56pp) · SHOP ✅ (US GAAP/USD/Dec, filer #5, FY2025, 135pp) · ATD ✅ (IFRS/USD/Apr, filer #6, FY2025, 130pp). All 6 PDF-verified, CI-locked. ATD validated Jun 13 2026: April FY-end confirmed (first non-Dec/Oct in corpus), IFRS+USD (second IFRS/USD data point after CSU), page locator OK (18 unique swept), all IS/BS/CF values confirmed by independent pdfplumber pass, overall_status=clean. gross_margin_range and revenue_reconciliation still SKIP (no explicit Gross profit subtotal in ATD IS — finding, see item 12). Next filer TBD.
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

[ADDITION — Jun 12 2026, REI.UN] When adding the REIT sector profile, decide whether rule skips that currently land as `field_unavailable` should instead be promoted to `sector_excluded` for intent-clarity. REI.UN FY2025: `gross_margin_range` and `revenue_reconciliation` skipped as `field_unavailable` (gross_profit not present), not as `sector_excluded`. A REIT profile could register these rules as explicitly inapplicable — making the skip reason self-documenting rather than incidental. The operational difference: `sector_excluded` signals "rule doesn't apply to this sector by design"; `field_unavailable` signals "rule would apply but data was missing." For REITs these are the same outcome, but for future rule audits the distinction matters. See open queue item 9.

**5. Mapping confidence separate from extraction confidence.**
Each mapped item records match_type: exact | pattern, alongside the extractor's per-line confidence. Integrity Engine flag-and-warn distinguishes "uncertain read" from "uncertain mapping".

**6. Validation: existing fixtures become mapping tests.**
Run mapper over CSU/CNR/RY fixtures; assert known mappings (CNR "Revenues (Note 4)" → revenue 17304; CSU "Finance costs" → interest_expense; RY "Provision for credit losses" → bank field and NOT any generic field) + the conservation invariant. Failing assertion = finding; never weaken to pass.

**v1 scope cut:** income statement fields only. Balance sheet + cash flow follow the same machinery in a later step.

**Build order:** 1) sedar_aliases.json schema + initial aliases from the three fixtures' actual labels. 2) Mapper module (Codex, from this spec). 3) Mapping tests over existing fixtures. 4) Wire mapper into extract_sedar_filing() output path. 5) Integrity Engine: extraction-confidence rule + accounting_standard informational handling (per Settled Decision 4 update) — engine commits: /detection-test then /integrity-log.

[ADDITION — VALIDATED Jun 2026, REI.UN] Sector-specific revenue labels (e.g. "Rental revenue" for REITs) must NOT be added as generic revenue aliases — they belong in a per-sector profile layered on top of the standard-aware alias table. RioCan has no "Total Revenue" label; revenue is implicit from components ("Rental revenue" + "Residential inventory sales" + "Property management and other service fees"). Adding "Rental revenue" → generic `revenue` would silently mis-map non-REIT filers that have a rental sub-line. The REIT sector profile must define `reit_revenue` (or equivalent sector-canonical field), populated from sector-specific aliases. No generic revenue field mapped for REI.UN — 0 fields mapped under current alias table; locked in test_sedar_mapper.py::test_reiun_fixture_zero_mapped_under_current_alias_table.

[ADDITION — VALIDATED Jun 2026, REI.UN] IFRS REIT net income includes unrealized fair-value gains/losses on investment properties. REI.UN FY2025: Net income = $69,295K, of which Fair value loss on investment properties, net = −$137,359K and Income (loss) from equity-accounted investments = −$236,934K. Without these items, operating income was $798,716K — a 10× difference. GAAP-distorting but IFRS-correct under IAS 40 investment property fair-value model. Candidate Integrity Engine rule (post-campaign): flag net_income-based valuation metrics (P/E, EV/EBIT) for IFRS real-estate filers as containing fair-value adjustments — flag-and-warn severity, not block.

[ADDITION — VALIDATED Jun 2026, REI.UN] REIT trust structure uses terminology distinct from corporate GAAP: cash flow statement uses "Distributions paid to Unitholders" (not "dividends paid"), balance sheet uses "Unitholders' equity" (not "shareholders' equity"). Both are verbatim labels locked into REI.UN fixture assertions (test_reiun_fy2025_reit_watch_items). Any future alias that maps these labels to corporate-equivalent canonical fields must be REIT-sector-profile-scoped, not generic. "Distributions" ≠ "dividends" in yield calculations.

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

1. **Alias additions** ✅ — Implemented Jun 13 2026 (commit for items 1/12/13). Nine alias changes/additions to `sedar_aliases.json` drawn from 6-filer corpus evidence:
   - `"operating income"` → `operating_income`, standards promoted to `["IFRS", "US GAAP"]` (REI.UN + ATD evidence)
   - `"net income"` → `net_income`, standards promoted to `["IFRS", "US GAAP"]` (REI.UN evidence)
   - `"interest costs, net"` → `interest_expense`, standards `["IFRS"]`, source `REI.UN_FY2025`
   - `"revenues"` → `revenue`, standards promoted to `["IFRS", "US GAAP"]` (ATD evidence)
   - `"financial expenses"` → `interest_expense`, standards `["IFRS"]`, source `ATD_FY2025`
   - `"net earnings"` → `net_income`, standards `["IFRS"]`, source `ATD_FY2025` — enabled by item 13 benign-duplicate fix (collision guard now resolves identical-value "Net earnings" pairs)
   - `"income (loss) from operations"` → `operating_income`, standards `["US GAAP"]`, source `SHOP_FY2025`
   - `"gross profit"` → `gross_profit`, standards `["IFRS", "US GAAP"]`, source `SHOP_FY2025`
   - `"cost of sales, excluding depreciation, amortization and impairment"` → `cost_of_revenue`, standards `["IFRS"]`, source `ATD_FY2025`, `semantics: {excludes_da: true}` (enables item 12 derived gross profit with D&A caveat)
   - REIT sector profile: deferred until a second REIT filer is validated.
   - Tests updated: `test_shop_fixture_maps_four_fields_us_gaap` (mapped_count 2→4), `test_atd_fixture_maps_five_fields_with_derived_gross_profit` (0→5 + derived), `test_reiun_fixture_maps_three_fields_after_alias_additions` (0→3). All 55 tests pass.
2. **Cosmetics:** `$`-escaping in analyst text; `REI.UN` → `REI-UN.TO` yfinance format mapping; `.PDF.PDF` double-extension display bug (reproduced on `RioCan_FY2025_annual_financials.pdf.pdf` — confirmed live).
3. **Dev-mode model selector:** Haiku / Sonnet / Opus 3-way selector for development testing.
4. **Investigate:** Null FinLens values in cross-validation record for REI.UN despite successful extraction — values extracted but not propagating to the CV record. Reproduced on REI.UN Jun 12.
5. **Investigate:** Degenerate log entries (ticker `""` / `"—"`, all rules skipped) from generic PDF upload path — ticker-resolution gating appears to be missing before the integrity check fires.
6. **Next campaign filer (foreign/structural):** Alimentation Couche-Tard (ATD, TSX, IFRS, USD reporting, April fiscal year-end) — adds first non-Dec/Oct year-end to corpus. [Corrected Jun 12 2026: ASML/Toyota removed — not SEDAR+ reporting issuers; SHOP was originally selected from that candidate set for this reason.] ✅ Validated Jun 13 2026 — see campaign status. Next filer TBD.
7. **Gemini second-extractor cross-check:** Independent extraction of SEDAR PDFs via Gemini API, diffed against Claude extraction as an integrity signal; mitigates FMP premium-wall cross-val gaps. Design session needed before build.
8. **SEDAR staleness gap:** `fiscal_year_recency` skips on all SEDAR filings because `filing_year_int` is unresolved at extraction time, so no lag check runs. EDGAR filings get lag checked (JPM FY2025: lag=1 year, filed 2026); a stale SEDAR PDF would currently pass silently. Fix: resolve `filing_year_int` from SEDAR filing metadata or PDF cover date at extraction time. [Found Jun 12 2026, REI.UN integrity-log review]
9. **REIT sector-skip distinction:** REI.UN skipped `gross_margin_range` via `field_unavailable`, NOT `sector_excluded` — the sector machinery did not fire a profile exclusion; the data simply wasn't present. When a REIT sector profile is added, decide whether these skips should become explicit `sector_excluded` (intent-documented) rather than incidental `field_unavailable`. See also point 4 of Phase 2 Design (sector profiles). [Jun 12 2026]
10. **SHOP SEDAR PDF rerun** ✅ — Full validation completed Jun 13 2026 on `SHOP_FY2025_annual_financials.pdf` (135pp, FY2025, fiscal_year_end=December 31, 2025 confirmed). Page locator: BS=13pp ([70,71,73,74,93,94,101,102,103,113,114,115,116]), IS=19pp, CF=2pp ([76,77]), 25 unique swept pages. Currency=USD confirmed (no CAD default). Accounting standard = "U.S. GAAP" (verbatim). Independent pdfplumber: 17/17 FY2025 fixture values found in PDF text (revenue 11,556 · COGS 6,001 · gross profit 5,555 · ops income 1,468 · unrealized loss (186) · net income 1,231 · total assets 15,189 · equity 13,473 · eq. investments 4,582 · operating CF 2,033 · investing CF (1,190) · financing CF (811) · beginning cash 1,498 · end cash 1,545 · maturities (1,043)). Integrity engine: overall_status=clean, 6 rules passed, 2 skipped (revenue_reconciliation: cost_of_revenue unmapped; fiscal_year_recency: filing_year_int unresolved — item 8). SHOP PDF has single extension `.pdf` (double-extension bug at item 2 does NOT affect SHOP). Prior two blockers resolved: (a) FY2025 SEDAR PDF obtained; (b) mapper normalization bug fixed (item 11, commit 1da92f5).
12. **IFRS retail — no explicit Gross profit subtotal** ✅ — Implemented Jun 13 2026 (commit for items 1/12/13). Chose option (b): added `"cost of sales, excluding depreciation, amortization and impairment"` as a specific IFRS alias for `cost_of_revenue` with `semantics: {excludes_da: true}`. Mapper (sedar_mapper.py) derives `gross_profit = revenue − cost_of_revenue` post-mapping when `gross_profit` is not directly mapped but both `revenue` and `cost_of_revenue` are; derived entry carries `derived: True, excludes_da: True` and is NOT counted in `mapped_count`. Engine (engine.py) reads mapper-derived gross_profit as fallback when raw label lookup fails, then propagates `cost_of_revenue_excludes_da` flag into `gross_margin_range` and `revenue_reconciliation` rule messages as a D&A caveat. Both rules now RUN for ATD (no longer skip) with message suffix: "[NOTE: cost_of_revenue excludes D&A — derived margin not comparable to COGS-inclusive benchmarks]". Conservation invariant updated: `mapped_count + unmapped_count + benign_skipped_count == total` (derived gross_profit not counted). ATD FY2025 derived gross_profit = 72856.8 − 59835.5 = 13021.3 MUSD.
13. **ATD "Net earnings" duplicate collision** ✅ — Implemented Jun 13 2026 (commit for items 1/12/13). Chose option (b) variant with value-equality guard: mapper now classifies duplicate normalized labels as **benign** (identical non-null value → use first occurrence, silently skip rest, record in `benign_skipped_count`) or **ambiguous** (different values or null → all go to unmapped, existing behavior). ATD "Net earnings" (2592.4 × 2) and REI.UN "Net income" (69295 × 2) and CSU "Net income (loss)" (586 × 2) all resolve as benign. Different-value duplicates still block (existing `test_collision_guard_keeps_both_distinct_labels_unmapped` still passes, new `test_ambiguous_duplicate_different_values_still_blocks` locks this in). Design rule: same-value duplicates = OCI preamble echo (safe to de-duplicate by position); different-value duplicates = genuinely ambiguous data (must stay unmapped until extraction scope is narrowed). `benign_skipped_count` added to mapper meta; conservation invariant updated accordingly.
14. **Next campaign filer TBD:** ATD completes the original 5-filer slate plus the SHOP addition. Candidates for filer #7: (a) a second Canadian REIT (to validate REIT sector profile per Phase 2 Design); (b) a resource sector filer (Suncor, Barrick, or similar — tests commodity revenue labels); (c) a large Quebec-domiciled insurer (Intact Financial, for insurance sector skip). Design session needed to select.

11. **Mapper accounting_standard normalization bug** ✅ — Claude extracts accounting standard verbatim from filing text: "U.S. GAAP" (with periods). Alias table tags use "US GAAP" (no periods). `_standard_allowed()` in `sedar_mapper.py` did a literal `accounting_standard in standards` check → "U.S. GAAP" not in ["US GAAP"] → all US GAAP aliases blocked on SHOP SEDAR path → 0 fields mapped. Fixed Jun 13 2026: added `_normalize_standard()` helper (strip periods + spaces, casefold); `_standard_allowed()` now normalizes both sides before comparison. Unit tests added to test_sedar_mapper.py covering: "U.S. GAAP" → US GAAP alias fires; IFRS exact pass; genuinely different standard ("Japanese GAAP") still rejects. [Found Jun 13 2026, SHOP SEDAR PDF rerun; resolved Jun 13 2026]
