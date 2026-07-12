# MD&A Fetcher — Operational-Metrics Extraction Spec

Status: **DESIGN RATIFIED 2026-07-12** (four decisions ratified by Riley, recorded
in §Ratified decisions; NOT YET BUILT — build stages in §Build stages).
Owner (planned): sedar_extractor.py (locator + extraction) + modules/integrity/
document_class.py (new class) + app.py Economics tab (display) +
modules/integrity (validation) + modules/agent_fetch.py (fallback fetch lane).

## Why

All five sector coverage-gap reports (docs/research/, 2026-07-10 → 2026-07-11)
independently converge on the MD&A fetcher as the single biggest coverage
unlock and the recorded Tier-2 gate (docs/RESOURCE_ECONOMICS_SNAPSHOT_SPEC.md
§3). The decisive numbers analysts quote are MD&A-resident because NI 52-112
(Canada) and Reg G (US) PROHIBIT non-GAAP measures from the audited statements
and FORCE a quantitative reconciliation into the MD&A:

- O&G upstream: production volumes + commodity mix (adversarial scans found
  ZERO volume disclosures in the audited statements), $/boe operating netback
  (TOU $16.02/boe, ARX $29.14/boe — arithmetic ties in print), FFO /
  free-funds-flow (ARX Q1-2026 FFF $459M vs FinLens statements-derived FCF
  ≈$543M — the working-capital exclusion), net-debt/FFO + targets,
  differentials, breakevens, shareholder-return waterfalls.
- Mining: AISC/oz (AEM $1,373/oz), cash cost by-product vs co-product
  ($979 vs $1,035 — a 5.7% swing from presentation alone), per-mine oz/tpd/grade.
- Banking: ROTE, adjusted EPS, segment NIM, average-balance table.
- REIT: FFO/AFFO (NAREIT ≠ REALPAC — different calculations), AFFO payout,
  same-property NOI, leasing spreads.

One fetch+parse build serves all sectors; v1 ships one sector's metric pack.

## Ratified decisions (Riley, 2026-07-12)

1. **v1 sector pack: O&G UPSTREAM.** Production volumes + commodity mix,
   $/boe operating netback (closes CB-024's deferred flagship), FFO/FFF
   family, realized price vs benchmark, hedge coverage % (closes CB-034's
   recorded v1 exclusion). Rationale: WCSB client base; the Tier-2
   "COMING SOON" panel (app.py ~9436) is the waiting UI slot; six corpus
   O&G filers (CNQ, SU, TOU, ARX, WCP, PEY.TO) form the ground-truth set.
2. **Trust policy: RECEIPT + PERMANENT CAPTION** (two-part state). An
   MD&A figure earns a "reconciled to statements" receipt when its printed
   NI 52-112 reconciliation ties to mapped canonical anchors (FFO → the
   verified operating_cash_flow; netback components → revenue/royalties/
   operating_expense/transportation_costs), AND it permanently carries an
   "issuer-defined non-GAAP" caption with the issuer's verbatim definition
   string. MD&A figures NEVER enter canonical statement fields — they live
   in their own namespace (financial_data["mda_metrics"]). This is the
   enforcement decision for the cross-sector "company-defined non-GAAP
   earnings needs a receipt" pattern (confirmed 5×: O&G FFF, midstream DCF,
   mining AISC, banking adjusted-EPS, REIT FFO/AFFO). Casebook entry lands
   with the enforcement commit per the same-commit rule.
3. **Sourcing: IN-PDF FIRST, FETCH FALLBACK.** Locate MD&A pages inside the
   already-ingested PDF first (TOU's canonical PDF is a combined
   "Q4 MD&A + annual statements" pack — the prose is already on disk); if
   absent, the CB-028 agent-fetch lane requests the standalone MD&A from the
   issuer IR page (same R3 fetch-only contract, R4 app-refetch, sha256
   provenance, document-class gate).
4. **Trigger: ON-DEMAND BUTTON** ("📄 Extract MD&A Metrics $", Economics
   tab, ~$0.05–0.15 per filing) — the exact CB-034 ratified-trigger pattern;
   analysis spend stays the user's click; result persists to the analysis
   cache and survives heals.

## Pipeline (planned)

- **document_class extension**: new class `mda` so a standalone MD&A document
  is ACCEPTED at ingest rather than refused as no_statements_detected (the
  `_MDA_RE` marker in document_class.py is the existing recorded-but-unused
  seam; CB-015 anticipated class expansion). Combined packs keep their
  statements class; the locator handles finding the MD&A section within.
- **`locate_mda_pages(pdf_path)`** — content-density predicate per the CB-034
  locator pattern (NOT heading-scan): netback/production/FFO vocab + table
  signals + numeric density; recall-biased, page-capped with dropped pages
  disclosed. Tuned against the six corpus O&G filers before shipping.
- **`extract_mda_metrics(pdf_path, sector_pack)`** — own prompt pair (the
  statement SYSTEM_PROMPT forbids notes/prose and MUST NOT be touched);
  reuses streaming `_call_claude` via keyword params; zero-spend
  `no_mda_detected` honest exit. The prompt REQUIRES, per metric: the value,
  the verbatim source label, source_page, the issuer's DEFINITION STRING,
  and the printed RECONCILIATION rows (NI 52-112 guarantees they exist).
  Never just the number.
- **Normalized `mda_metrics` schema** (v1, O&G pack):
  `production_volumes[]` (per-product: gas MMcf/d, liquids bbl/d, total
  boe/d, period), `commodity_mix`, `netback_table[]` (per-boe components:
  revenue, royalties, opex, transportation, hedging-if-included, netback;
  `variant_definition` string — TOU includes realized hedging, the
  4-component form doesn't), `ffo_reconciliation` (CFO anchor → FFO → FFF,
  per-share values, working-capital adjustment), `realized_prices[]` (vs
  benchmark), `guidance{}` (capex program, breakeven if printed),
  `source_pages`, `dropped_pages`, `extraction_confidence`,
  `figure_presence`, `status`. Every record: verbatim label + source_page
  (Trust-Is-Page-Level).
- **Figure-presence guard** — every extracted number must appear
  (comma-normalized) in the located page text; misses render an UNVERIFIED
  warning; fabrication surfaced, never silent (CB-034 pattern).
- **Naming**: `mda_metrics` is deliberately distinct from the existing
  `mda_sentiment` (Call 5 prose sentiment) — different payloads, different
  triggers; do not merge them.

## Storage + provenance (planned)

- Fetched standalone MD&A PDFs: `~/.finlens/pdfs` with a document-class
  discriminator in the filename; registry entries gain a second slot
  (`mda_pdf_path`) — `resolve_campaign_pdf` today resolves exactly ONE
  `source_pdf_path` per entry, the constraint to extend.
- Provenance: the live app-fetch shape (`agent_fetch_provenance`: url,
  sha256, byte_size, retrieval_timestamp_utc, retrieval_method,
  agent_channel), stored alongside the payload as
  `mda_metrics.provenance`.
- `_heal_sedar_mapping` must carry `mda_metrics` through free re-maps
  (a paid extraction must never be dropped by a heal — hedging_book
  precedent, app.py ~1047).

## Validation (the moat)

- **Netback component tie** (warn): the MD&A's per-boe netback components ×
  disclosed volumes vs the mapped statement lines (revenue, royalties,
  operating_expense, transportation_costs) within tolerance — the arithmetic
  tie the research verified by hand on TOU ($16.02) and ARX ($29.14).
- **FFO reconciliation tie** (warn): the printed CFO anchor in the MD&A's
  FFO reconciliation vs mapped `operating_cash_flow` — exact-family tie;
  the working-capital delta becomes the receipted FCF≠FFF disclosure
  (closes the queued zero-cost caption item).
- Both rules follow the `hedging_fair_value_bs_tie` template (rules.py dict +
  ctx builders + handler + _CHECKS registration); honest skip when either
  side is unmapped; moat-log records via the standard engine re-run.
- Gemini cross-extraction of MD&A figures: FUTURE, not v1 (same "after field
  mileage" trajectory as the hedging note; the issuer-defined nature makes
  the comparison semantics a design question of its own).

## Display (planned)

- The Tier-2 "COMING SOON" panel on the Economics tab goes live: $/boe
  netback (with variant caption + component receipt), production volumes +
  mix, realized price vs benchmark spot, netback-vs-commodity-price.
- FFO/FFF card: per-share values, "issuer-defined non-GAAP" caption with
  definition string, reconciled-receipt state, FCF≠FFF delta disclosed.
- Hedging panel gains hedge coverage % (disclosed hedge volumes ÷ MD&A
  production volumes) — CB-034's named exclusion, unlocked.
- Every card: receipt caption (source page + reconciliation state) or
  honest "—". No third state (Trust Is Page-Level).

## Honest v1 exclusions (named on the panel where relevant)

- Mining / REIT / banking metric packs — Stage 4+ prompt/schema extensions
  on the same infrastructure, each with its own ground-truth pass.
- Reserves/NAV inputs (NI 51-101 Forms in the AIF), EV/2P, RLI, F&D, FDC —
  Tier 3, a different document class. OUT.
- Banking SFI + Pillar 3 Excel packages — standardized form-parsing build,
  not prose extraction. OUT.
- Midstream/downstream SECTOR PROFILES (fee-based DCF, crack-spread
  frameworks + routing guard for pipeline filers mis-bucketed upstream) — a
  separate profile/routing build the fetcher later populates. OUT.
- Earnings releases / supplementals / investor decks as sources (some
  figures — capital efficiency, some differentials — live there, not the
  MD&A body) — recorded, deferred.
- Price-deck sensitivities, cost-curve quartile benchmark datasets,
  forward/consensus figures — permanent-badge class (no filed source).

## Build stages

- **Stage 0** — document_class `mda` + registry second-document slot +
  provenance shape. Pure plumbing, no API spend.
- **Stage 1** — `locate_mda_pages` + `extract_mda_metrics` (O&G pack) +
  schema + figure-presence guard. Tuned/ground-truthed on the six corpus
  O&G filers.
- **Stage 2** — Economics-tab Tier-2 panel + FFO card + hedge coverage % +
  on-demand button + cache/heal persistence.
- **Stage 3** — the two tie rules + moat-log records + red-flag candidates
  (e.g. payout of FFF > 100%).
- **Stage 4 (later)** — agent-fetch fallback lane for MD&A-only filers;
  additional sector packs; release/supplement sources.

Each stage through the normal gate (review → full suite → live verification
on a corpus filer before the next stage).

## Pins (planned)

Locator real-PDF pins (skipif-guarded for CI) on TOU/Peyto/ARX pages; schema
+ figure-presence pure pins; tie-rule pins with honest-skip negatives;
document_class `mda` classification pins; heal-carry pin for mda_metrics.
