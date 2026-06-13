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
- [ADDITION] Campaign status: CSU ✅ (IFRS/USD/Dec) · CNR ✅ (US GAAP/CAD/Dec) · RY ✅ (IFRS/CAD/Oct, 246pp) · REI.UN ✅ (IFRS/CAD/Dec, filer #4, FY2025, 56pp). All PDF-verified, CI-locked (f93868b, 49f14d0, d8dd41c). · SHOP ◐ (US GAAP/USD/Dec, filer #5) — field mapping EDGAR-verified, CI-locked at b6e79c5. SEDAR PDF path NOT yet exercised: page locator, USD-on-SEDAR currency detection, and SEDAR-path integrity log entry all pending PDF retrieval. Do not count as SEDAR-validated until rerun. Next: ASML/Toyota or SHOP SEDAR PDF rerun (see open queue item 10).
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

1. **Alias additions (VALIDATED, REI.UN evidence):** Three additions confirmed by campaign filer #4 — add to sedar_aliases.json before next campaign run:
   - `"operating income"` → `operating_income`, standards `["IFRS", "US GAAP"]` (previously US GAAP only — REI.UN proves this label appears in IFRS filings)
   - `"net income"` → `net_income`, standards `["IFRS"]`, source `REI.UN_FY2025` (currently US GAAP only; REI.UN income statement uses this label verbatim)
   - `"interest costs, net"` → `interest_expense`, standards `["IFRS"]`, source `REI.UN_FY2025` (IFRS REITs use this; generic "Finance costs" alias does not match)
   - When these are added, update test_sedar_mapper.py::test_reiun_fixture_zero_mapped_under_current_alias_table to assert mapped_count == 3 (or whatever resolves). Do NOT weaken — update assertions to reflect new expected behavior.
   - REIT sector profile: deferred until a second REIT filer is validated.
   - Additional proposals from SHOP (filer #5, US GAAP/USD, EDGAR-verified): `"income (loss) from operations"` → `operating_income`, standards `["US GAAP"]`, source `SHOP_FY2025` (Shopify uses non-standard ops label; alias "operating income" does not match because normalization strips note refs but not `(loss)` qualifiers embedded in label names); `"gross profit"` → `gross_profit`, standards `["IFRS", "US GAAP"]`, source `SHOP_FY2025` (verbatim in SHOP; generic enough for both standards). When these two are added, update test_sedar_mapper.py::test_shop_fixture_maps_revenue_and_net_income_us_gaap to assert mapped_count == 4 and add assertions for the newly mapped fields. Do NOT weaken — update assertions to reflect new expected behavior.
2. **Cosmetics:** `$`-escaping in analyst text; `REI.UN` → `REI-UN.TO` yfinance format mapping; `.PDF.PDF` double-extension display bug (reproduced on `RioCan_FY2025_annual_financials.pdf.pdf` — confirmed live).
3. **Dev-mode model selector:** Haiku / Sonnet / Opus 3-way selector for development testing.
4. **Investigate:** Null FinLens values in cross-validation record for REI.UN despite successful extraction — values extracted but not propagating to the CV record. Reproduced on REI.UN Jun 12.
5. **Investigate:** Degenerate log entries (ticker `""` / `"—"`, all rules skipped) from generic PDF upload path — ticker-resolution gating appears to be missing before the integrity check fires.
6. **Next campaign filer (foreign/structural):** Alimentation Couche-Tard (ATD, TSX, IFRS, USD reporting, April fiscal year-end) — adds first non-Dec/Oct year-end to corpus. [Corrected Jun 12 2026: ASML/Toyota removed — not SEDAR+ reporting issuers; SHOP was originally selected from that candidate set for this reason.]
7. **Gemini second-extractor cross-check:** Independent extraction of SEDAR PDFs via Gemini API, diffed against Claude extraction as an integrity signal; mitigates FMP premium-wall cross-val gaps. Design session needed before build.
8. **SEDAR staleness gap:** `fiscal_year_recency` skips on all SEDAR filings because `filing_year_int` is unresolved at extraction time, so no lag check runs. EDGAR filings get lag checked (JPM FY2025: lag=1 year, filed 2026); a stale SEDAR PDF would currently pass silently. Fix: resolve `filing_year_int` from SEDAR filing metadata or PDF cover date at extraction time. [Found Jun 12 2026, REI.UN integrity-log review]
9. **REIT sector-skip distinction:** REI.UN skipped `gross_margin_range` via `field_unavailable`, NOT `sector_excluded` — the sector machinery did not fire a profile exclusion; the data simply wasn't present. When a REIT sector profile is added, decide whether these skips should become explicit `sector_excluded` (intent-documented) rather than incidental `field_unavailable`. See also point 4 of Phase 2 Design (sector profiles). [Jun 12 2026]
10. **SHOP SEDAR PDF rerun** — once PDF retrieved: full-sweep page locator, verify reporting currency recorded as USD (confirm no CAD default on SEDAR path), independent text-search re-verification against fixture values, /integrity-log to confirm SEDAR-source entry written. [Deferred Jun 12 2026]
