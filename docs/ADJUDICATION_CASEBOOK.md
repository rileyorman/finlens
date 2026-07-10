# FinLens Adjudication Casebook

**Status:** v1 — format ratified by Riley 2026-07-05

## Purpose

The casebook is the single canonical home for **judgment-class adjudications**:
decisions where an analyst had to choose what a number *means*, with the
reasoning and evidence attached. Per the moat analysis (SESSION_HANDOFF.md,
"Moat thinking", 2026-07-05): data is re-scrapable; judgment history cannot
be backfilled. This file makes that history citable instead of archaeology
scattered across commit messages, handoff prose, and session memory.

Entries are **append-only in spirit**: a ratified decision is never edited
into a different decision — it is SUPERSEDED by a new entry that cites it.
Typo/link fixes are fine.

## What qualifies (inclusion criteria)

IN:
- **Field-definition rulings** — what a canonical field means when filers
  present the concept differently (issued-gross insurance, rental-only NOI).
- **Checker-dispute adjudications** — FinLens vs an independent witness
  (Gemini, FMP, prior-column checker): who was right, why, and the
  classification (extraction error / checker error / both honest).
- **Mapping rejections with reasoning** — a plausible alias or mapping
  deliberately NOT made, and why (these prevent future wrong mappings and
  are invisible everywhere else).
- **Open definition questions** — logged as OPEN entries so the question
  itself is citable before it is decided.

OUT:
- Routine alias additions (label evidence, no judgment — the aliases file's
  `source` field is their record).
- Bug fixes and incidents without a definitional ruling (handoff/archive owns
  those).
- Process/ops decisions (handoff owns those).

## Anti-drift rule (where definitions live)

CLAUDE.md ("Canonical Field Definitions", "SEDAR Canonical Revenue
Semantics") remains the **enforcement copy** — the text the mapper and
reviewers must follow. Casebook entries cite those sections and the pinning
tests; they do NOT restate full definitions. If an entry and CLAUDE.md ever
disagree, that is a defect: flag it, do not silently fix either side.

## Entry template

```
### CB-NNN: <short title>
- Status: RATIFIED | OPEN | SUPERSEDED (by CB-NNN)
- Date: <decision date, or date opened>
- Decided by: <Riley | Riley+CC | pending>
- Scope: <canonical field(s) / sector profile(s) / filers>
- Decision: <the ruling in 1-3 sentences; for OPEN: the question with the
  options stated fairly>
- Reasoning: <the tradeoff weighed and why this side won>
- Evidence: <filers + key values, commits, integrity-log records>
- Enforced by: <CLAUDE.md section / aliases entry / test / code path>
```

## Workflow

1. A new adjudication gets its entry **in the same commit** as (or before)
   its enforcement change; the commit message cites the CB ID.
2. Open questions get an OPEN entry when first hit; they should also appear
   in the SESSION_HANDOFF.md open queue until decided.
3. When Riley decides an OPEN entry, flip Status to RATIFIED in place and
   fill Decision/Reasoning (the question text may be compressed, not lost).
4. To change a ratified decision: new entry, SUPERSEDED marker on the old.
5. IDs are sequential and never reused.

---

# Entries

### CB-001: insurance_finance_result = issued-gross, never the net rollup
- Status: RATIFIED
- Date: 2026-06-17
- Decided by: Riley+CC
- Scope: `insurance_finance_result` / insurance_sector / IFC, SLF
- Decision: take the "insurance finance income (expense) from contracts
  issued" line, gross; never net in reinsurance finance; never take a
  printed "Net insurance financial result" subtotal even when the filer
  prints one.
- Reasoning: cross-insurer comparability — SLF prints no net rollup, so
  issued-gross is the only line common to both insurers. This deliberately
  reports a number that disagrees with IFC's own printed subtotal.
- Evidence: IFC −1,041 taken (printed net −879 deliberately not taken);
  SLF −6,787 (hand-confirmed 2026-06-17, no rollup exists). Gemini
  cross-check CONFLICT on both insurers triaged as this deliberate
  decision, not an error.
- Enforced by: CLAUDE.md "Canonical Field Definitions →
  insurance_finance_result"; insurance_sector profile in
  modules/integrity/sedar_aliases.json.

### CB-002: REIT net_operating_income = rental-only NOI, conditional lift/derive
- Status: RATIFIED
- Date: 2026-06-17
- Decided by: Riley+CC
- Scope: `net_operating_income` / reit_sector / REI.UN, CAR.UN, DIR.UN
- Decision: pure REITs LIFT the printed rental-only NOI line exactly;
  blended REITs (development/service-fee income mixed into the operating
  subtotal) DERIVE rental-only NOI and do NOT lift the blended subtotal.
- Reasoning: a blended "Operating income" is not comparable to a pure
  REIT's rental NOI; rental-only is the concept the persona needs.
- Evidence: CAR.UN 730,654 and DIR.UN 355,432 exact lifts; REI.UN derived
  720,404 = 1,176,428 − 414,386 − 41,638 (printed blended 798,716 preserved
  in unmapped[]; difference 78,312 = 62,358 residential margin + 15,954
  service fees, closes exactly).
- Enforced by: CLAUDE.md "Canonical Field Definitions →
  net_operating_income"; derivation logic in sedar_mapper (fires only where
  a development/inventory line exists).

### CB-003: property_operating_costs definition — TWO AXES
- Status: DECIDED — see CB-012 for the full decision record (rental-only,
  ratified by Riley 2026-07-06). BOTH axes resolved there: (i) INCLUSION =
  rental-only; (ii) SIGN = lifted values keep the filer's as-presented sign,
  the derived blended-REIT value is a positive cost magnitude (CLAUDE.md
  SIGN NOTE). BOOKKEEPING NOTE (2026-07-06): CB-012 was minted during the
  clean-sweep session without noticing this earlier entry covered the same
  question — CB-012 holds the ruling; this entry stays as the original
  question record. Found during the same-day handoff cleanup.
- Date: opened 2026-07-03 (ninth session); decided 2026-07-06 (as CB-012)
- Decided by: Riley (via CB-012)
- Scope: `property_operating_costs` / reit_sector / REI.UN, CAR.UN, DIR.UN
- Decision (question): decide BOTH axes together — (i) INCLUSION: blended
  total including residential inventory cost of sales (REI.UN 637,855,
  matches the filing's printed subtotal) vs rental-only (456,024 =
  414,386 + 41,638, consistent with CB-002's rental-only NOI); (ii) SIGN:
  REI.UN presents +637,855 while CAR.UN (−281,431) and DIR.UN (−110,786)
  store negative as-presented.
- Reasoning (tension): comparability-to-filing vs internal consistency with
  CB-002. Same filer, same line family, currently opposite treatment across
  two fields. Deciding inclusion without sign just relocates the
  inconsistency.
- Evidence: current values above; Gemini spike CONFLICT on REI.UN triaged —
  the 637,855 reconciles exactly to RioCan's own NOI presentation, so the
  current value is not a wrong number, it is an undecided definition.
- Enforced by: (once decided) CLAUDE.md "Canonical Field Definitions →
  property_operating_costs" — currently documents the OPEN state.

### CB-004: resource-sector canonical revenue = GROSS of royalties; bare "Revenue" is never a safe alias
- Status: RATIFIED
- Date: 2026-06-17 (ground truth); negative rule pinned 2026-07-03
- Decided by: Riley+CC
- Scope: `revenue`, `royalties` / resource_sector / CNQ, SU (Suncor)
- Decision: for royalty-reporting resource filers, canonical revenue is the
  GROSS product-sales line; net-of-royalties "Revenue" lines stay UNMAPPED
  BY DESIGN; no bare "revenue" alias may ever be added in this sector;
  `royalties` is stored NEGATIVE as-presented.
- Reasoning: a bare alias would capture the net line and collapse the
  gross/royalty split the sector analysis depends on (royalty burden % of
  gross). Honest-unmapped beats silently-net.
- Evidence: CNQ "Product sales" 41,509 taken, net "Revenue" 35,656 not;
  Suncor "Gross revenues" 52,377 (alias shipped 35cda16, Task B); royalties
  −5,853; CNQ royalty burden 14.1% ties to canonical 5,853/41,509.
- Enforced by: CLAUDE.md "SEDAR Canonical Revenue Semantics"; negative rule
  pinned by test (35cda16 — test fails if a bare alias is ever added).

### CB-005: FMP is an unreliable correctness witness GENERALLY
- Status: RATIFIED
- Date: 2026-07-03 (widened from the SEDAR-scoped original, e8e7062)
- Decided by: Riley+CC
- Scope: all cross-validation; every filer class including US/USD/XBRL
- Decision: an FMP value must NEVER adjudicate a discrepancy alone; FMP
  mismatches are advisory-only triage signals; internal accounting
  identities and the Gemini second-extractor are the preferred witnesses.
- Reasoning: FMP returned a phantom value on the filer class it should
  handle best (see evidence) — plus known currency mismatches and TSX
  coverage gaps on the SEDAR side.
- Evidence: JPM FY2025 operating_cash_flow — FMP +100.9B vs as-filed 10-K
  (accession 0001628280-26-008131, R9) (147,782) USD millions,
  byte-identical to FinLens's XBRL tag; FMP's value matches NO filed year.
- Enforced by: CLAUDE.md "Cross-Check Source" principle; cross_validate.py
  v2 currency/definitional guard (0c6b2ab); cross_extractor as the scalable
  correctness path.

### CB-006: CNR interest_expense sign — FinLens correct, checker lost the sign
- Status: RATIFIED
- Date: 2026-07-03 (disposition written via scripts/write_cross_disposition.py)
- Decided by: Riley+CC (re-verified against source before writing)
- Scope: `interest_expense` / CNR FY2025 / checker-dispute class
- Decision: FinLens −913 is correct and faithful; Gemini's +913 lost the
  as-presented sign. Disposition: checker_error.
- Reasoning: CNR FY2025 PDF p6 prints "Interest expense (913)" —
  parenthesized/negative as-presented — and −913 reconciles the income
  cascade (6,587 − 913 + 502 + 88 = 6,264).
- Evidence: integrity log — CNR_FY2025_sedar.json field=interest_expense
  checker_version=3, disposition=checker_error. Note: interest_expense is a
  KNOWN-SLIPPERY field (checker disagreed twice across runs for different
  reasons — watch, not a bug).
- Enforced by: the written disposition record (moat log, append-only).

### CB-007: ATD interest_expense — component-vs-total false positive
- Status: RATIFIED
- Date: 2026-07-03
- Decided by: Riley+CC
- Scope: `interest_expense` / ATD / checker-dispute class
- Decision: FinLens 690.8 ("Financial expenses (Note 9)", the statement
  total) is correct; Gemini's 159.3 pulled ONE note component (lease
  interest), violating its consolidated-statements-only instruction.
  Disposition: checker line-scope violation.
- Reasoning: Note 9 (PDF p.98) decomposes 690.8 = 483.3 debt interest +
  159.3 lease interest + 36.3 accretion + 11.9 other — Gemini's number is a
  real number from the wrong altitude.
- Evidence: v3 run adjudication record; SESSION_HANDOFF.md item #7 (run
  validation).
- Enforced by: the written disposition; the v3 label-gate (db948cb) now
  soft-flags label-scope mismatches generally.

### CB-008: NVDA capex — confirmed line-specific extraction error under a verified spine (XBRL wrong-tag)
- Status: RATIFIED
- Date: 2026-07-05 (human-verified against the as-filed 10-K)
- Decided by: Riley (hand transcription) + CC
- Scope: `capex` / NVDA FY2026 June-4 cache / extraction-error class
- Decision: stored capex 138.7M/97.9M is WRONG (filed ~$6.1B/$3.4B); the
  surrounding spine (revenue, opex, operating income, net income, total
  assets, OCF) ties exactly both years. Root cause: edgar_fetcher maps
  capex from PaymentsToAcquirePropertyPlantAndEquipment only; NVDA files
  combined P&E+intangibles capex under a different XBRL concept.
- Reasoning: the inconsistent error factors (~44x/~35x) rule out unit
  scaling — it is a wrong line, not a wrong scale. Guard-class lesson: an
  aggregate figure-presence guard cannot catch a single wrong line among
  ~74 correct ones; per-figure checks (prior-column continuity) are the
  right guard class.
- Evidence: docs/audits/integrity_audit_20260705.md ADDENDUM; cache NOT
  hand-edited (fix = queued re-analyse after fabrication fix (b)); known
  consequence until then: FCF/DCF consumers of this cache overstate FCF
  ~$6B.
- Enforced by: open-queue items "NVDA CAPEX XBRL TAG COVERAGE" + the
  re-analyse batch; prior-column continuity checker (shipped 7f0a65e line)
  as the future guard.

### CB-009: capitalized E&E is NOT exploration_expense — alias rejected, field minted
- Status: DECIDED
- Date: opened 2026-07-05/06 (SIG FY2024 pilot review); mint ratified
  2026-07-06 (Riley+CC design session, same day as CB-010/CB-011)
- Decided by: rejection CC (pilot disposition); mint Riley (all four
  session questions ratified as recommended)
- Scope: `exploration_expense` + minted `capitalized_exploration_additions`
  / mining_exploration_sector / SIG vs NFG
- Decision (four rulings):
  1. MINT `capitalized_exploration_additions`: capitalized E&E additions —
     the investing cash outflow adding to exploration & evaluation assets.
     Value stored AS-PRESENTED (negative outflow; royalties precedent).
     DELIBERATELY a different concept from `exploration_expense` (P&L):
     IFRS 6 lets explorers choose either policy, so the two fields are a
     designed PAIR — comparing explorers requires both, and the policy
     split staying visible is the point.
  2. NAME: capitalized_exploration_additions — says capitalized (policy),
     exploration (concept), additions (a flow, not the asset stock).
  3. ALIASES (both, n=2): "exploration and evaluation assets" [SIG_FY2024]
     + "purchases of exploration and evaluation assets" [NFG_FY2024], both
     statement-scoped to cash_flow. NFG evidences the pair design live: it
     expenses exploration work AND capitalizes acquisition-type E&E, so
     both fields map on one filer (fixture mapped_count 6 -> 7).
  4. MECHANISM (two pieces, both required): (a) statement-scoped aliases —
     an alias may declare "statements": ["cash_flow"]; scoped aliases FAIL
     CLOSED on items without statement attribution. Valid here where it was
     rejected for CB-010: stock vs flow genuinely live in DIFFERENT
     statements (NFG's balance sheet carries the IDENTICAL label
     "Exploration and evaluation assets" for the asset STOCK 34,505,484 —
     an unscoped alias would map the wrong concept). (b) Duplicate-ambiguity
     grouping by (normalized_label, statement) instead of label alone —
     without it, SIG's own stock/flow twin labels self-destruct as
     "ambiguous" before aliases are consulted. Same label in the SAME
     statement keeps the old ambiguity semantics; items without statement
     info group under None (old behavior preserved). Conservation
     side-effect handled: cross-statement same-label same-value pairs are
     no longer silently benign-skipped — they stay visible in unmapped[]
     (corpus effect confined to mining-family fixtures, the only ones whose
     line_items include cash_flow: AEM/NFG/TECK.B benign counts fell,
     unmapped rose, mapped counts unchanged except NFG's +1).
- Reasoning: NFG EXPENSES exploration (income statement) — that is what
  `exploration_expense` means; SIG CAPITALIZES it (investing outflow onto
  the balance sheet). Mapping both to one field collapses the exact
  accounting-policy split an analyst comparing explorers needs to see.
  Augment-don't-mint requires a genuinely different concept for a new name
  — this IS one.
- Evidence: SIG FY2024 bundle (two-read agreement on the value); NFG
  precedent 41c08dc ("Capitalized E&E preserved in unmapped[], expensed
  E&E maps"); alias rejection recorded in ba405b0 commit message; NFG
  fixture post-mint maps BOTH fields (exploration_expense 52,563,340 and
  capitalized_exploration_additions −3,853,119) with the balance-sheet
  stock still honestly unmapped. [ADDITION 2026-07-06, same day: SIG
  promoted to fixture #15 — the originating filer now carries the minted
  field live: capitalized_exploration_additions −6,927,597 mapped from
  the cash-flow statement via the statement-scoped alias, the
  identically-labeled balance-sheet stock honestly unmapped; pinned by
  the SIG fixture test.]
- Enforced by: sedar_aliases.json (scoped aliases) + sedar_mapper.py
  (statement_scope index, per-statement duplicate grouping,
  conservation-safe multi-match tail) + _CANONICAL_SCALE_FIELDS
  classification (the scaling-whitelist gate caught the missing entry —
  machine enforcement working); tests
  test_cb009_capitalized_ee_additions_map_from_cash_flow_only,
  test_cb009_scoped_alias_fails_closed_without_statement_attribution,
  test_cb009_same_statement_same_label_different_values_still_ambiguous,
  test_cb009_nfg_purchases_line_maps_to_capitalized_additions.

### CB-010: cash collision — note sub-component must not beat the statement total
- Status: DECIDED
- Date: opened 2026-07-05/06 (SIG FY2024 pilot review); ratified 2026-07-06
  (Riley+CC design session, same day as CB-011)
- Decided by: Riley (both questions ratified as recommended)
- Scope: `cash` / mining_exploration_sector (rule is per-field opt-in) / SIG
- Decision (two rulings):
  1. MECHANISM — prefer_specific_alias: when distinct labels collide on one
     canonical field with different values, the match that arrived via the
     LONGEST normalized alias wins ("cash and cash equivalents" — the
     concept's full name — beats bare "cash", the note component).
     Restrictions that keep it honest: applies only when every colliding
     match is an exact alias match (pattern-prefix length is not a
     specificity signal), and only when the longest label is unique — a
     length tie stays ambiguous and blocks as before. Statement-scoping was
     REJECTED on evidence: note-breakdown rows land inside the extracted
     balance_sheet row list, so statement attribution cannot discriminate
     total from component. Explicit priority ordering was rejected as a
     hidden convention (Minimize-Human-Error).
  2. SCOPE — per-field opt-in via a declarative
     "collision_resolution": "prefer_specific_alias" flag on the canonical
     field config in sedar_aliases.json; only `cash` carries it now (the
     n=1 evidenced shape). A general rule was rejected: on income-statement
     fields a different-values collision is often genuinely ambiguous
     (blended vs segment revenue), and integrity-first prefers
     honest-unmapped over a silently-wrong pick. Future fields opt in
     through a casebook decision.
  VISIBILITY: every resolution is recorded in mapping
  meta.resolved_collisions (canonical_field, rule, chosen_label,
  rejected_labels) — never silent; the rejected row stays in unmapped[].
- Reasoning: the correct value is unambiguous (15,208,214 — the components
  1,883,531 + 13,324,683 GICs sum to it exactly, both years); the rule
  needed to capture WHY it's unambiguous (the total's label is the
  concept's full name) without licensing silent winners on genuinely
  ambiguous fields.
- Evidence: SIG FY2024 mapping.json meta.collisions (identical in both
  independent reads); post-decision corpus re-map machine-confirmed zero
  mapped-count changes and zero resolved collisions across all 14 fixtures
  (no fixture carries the SIG shape — the rule fires only on the evidenced
  collision). [ADDITION 2026-07-06, same day: SIG promoted to fixture #15
  — the rule FIRED LIVE in production for the first time: cash mapped
  15,208,214 from "Cash and cash equivalents (Note 4)", the bare "Cash"
  note row rejected, resolution recorded in meta.resolved_collisions;
  pinned by the SIG fixture test.]
- Enforced by: sedar_mapper.py collision guard (CB-010 branch) +
  sedar_aliases.json cash flag; tests
  test_cb010_cash_collision_resolves_to_most_specific_alias (SIG values)
  and test_cb010_fields_without_the_flag_still_block_on_collision
  (opt-in boundary).

### CB-011: mining-producer profile extension — n=2 evidence in hand, design session unblocked
- Status: DECIDED
- Date: opened 2026-07-03 (TECK.B deferral); evidence completed 2026-07-05
  (K FY2024); ratified 2026-07-06 (Riley+CC design session)
- Decided by: Riley (all four questions ratified as recommended)
- Scope: `revenue`, `cost_of_revenue`, `net_income`, production costs, DD&A
  / mining_sector + defaults / AEM, TECK.B, K
- Decision (four rulings):
  1. mining_sector `revenue` gains bare "revenue" [TECKB_FY2025] AND
     "metal sales" [K_FY2024]. Sector-scoped — the resource_sector royalty
     NEGATIVE RULE is untouched; mining producers seen so far print a single
     revenue line with royalties inside costs, so the gross/net split that
     rule protects does not arise in mining_sector.
  2. DEFAULT `net_income` gains "profit for the year" [TECKB_FY2025] —
     generic IFRS wording, nothing mining-specific ("net earnings" [ATD]
     precedent for a default alias with single-filer evidence). Maps the
     CONSOLIDATED total incl. NCI (TECK.B 1,072, not the 1,401
     attributable-to-shareholders line) per existing net_income semantics.
  3. mining_sector `production_costs` gains "production cost of sales"
     [K_FY2024]; `mine_development_amortization` gains "depreciation,
     depletion and amortization" [K_FY2024] — augment-don't-mint: same
     concepts as AEM's aliases in Kinross's wording. The AEM-flavored
     canonical name stays (renames are breaking).
  4. LABELED ADDITION beyond the original scope: DEFAULT `cost_of_revenue`
     gains bare "cost of sales" [TECKB_FY2025] — the standard IFRS caption.
     Values stay as-presented: TECK.B's includes D&A, ATD's variant
     explicitly excludes it (semantics tag on the ATD alias records this).
- CORRECTION recorded during the session: this entry previously said K's
  "Metal sales" alias "already shipped (a2b2b4d)" — that commit touched
  field_aliases.py, the PILOT COMPARATOR's table, not the production
  mapper. The production-side alias ships with this decision; a pinning
  test now covers the production route explicitly.
- Reasoning: profile-extension review discipline required a second mining
  filer before claiming the sub-shape; K FY2024 was that mandatory
  validation event and PASSED (93/93 rows two-read agreement).
- Evidence: AEM FY2025 (ground-truthed 2026-07-01); K FY2024 pilot bundle;
  TECK.B fixture. Post-decision re-map: TECK.B mapped_count 2 -> 5
  (revenue 10,756 / cost_of_revenue -8,099 / net_income 1,072 join
  gross_profit + total_assets); identity check 10,756 - 8,099 = 2,657 =
  mapped gross_profit, closes exactly. All other fixtures unchanged
  (machine-confirmed, zero collisions corpus-wide); CNQ still 6 with bare
  net "Revenue" honest-unmapped.
- Enforced by: sedar_aliases.json additions; registry regen (TECK.B
  stored=resolved=5); tests test_teckb_cb011_extension_maps_revenue_cost_of_sales_and_profit,
  test_k_producer_labels_map_in_mining_sector, updated
  test_teckb_fixture_resolves_existing_mining_sector_profile_without_new_aliases,
  and the resource_sector negative guard's updated docstring stating the
  mining_sector exception boundary.

### CB-012: property_operating_costs is RENTAL-ONLY — the two-axis definition gap closed
- Status: DECIDED (this entry ANSWERS CB-003, which recorded the same open
  question since 2026-07-03 — cross-referenced there; both axes resolved:
  inclusion here, sign in the CLAUDE.md SIGN NOTE this entry enforces)
- Date: opened 2026-06-17 (ground-truth pass, recorded in CLAUDE.md as an
  OPEN definition question; formalized as CB-003 on 2026-07-03); ratified
  2026-07-06 (Riley+CC design session — the fourth and final decision of
  the clean-sweep session)
- Decided by: Riley
- Scope: `property_operating_costs` / reit_sector / REI.UN vs CAR.UN, DIR.UN
- Decision: RENTAL-ONLY — rental property operations only, excluding
  residential/development inventory cost of sales. Conditional rule
  mirroring `net_operating_income` exactly: pure REITs LIFT their printed
  rental-only line (CAR.UN -281,431; DIR.UN -110,786 — unchanged); blended
  REITs DERIVE from the same rental-only components the NOI derivation uses
  (REI.UN: 456,024 = 414,386 recoverable + 41,638 non-recoverable), with
  the printed blended subtotal ("Total operating costs" 637,855, includes
  181,831 residential inventory cost of sales) preserved in unmapped[].
- Reasoning: (a) internal consistency — the blended value contradicted the
  SAME filer's derived NOI on the SAME line family; with rental-only, the
  identity closes exactly: 1,176,428 − 456,024 = 720,404. (b) Definition
  uniformity — rental-only is already the field's de facto meaning on both
  pure-REIT filers; blended-as-printed would have degraded the definition
  to "whatever subtotal prints". (c) Comparability-to-filing is preserved,
  not lost: the printed subtotal stays visible in unmapped[], the same
  pattern the NOI rule set with RioCan's blended "Operating income" 798,716.
- Evidence: REI.UN FY2025 fixture (post-decision re-map: mapped_count 7→6,
  field now derived 456,024; only fixture that changed corpus-wide); CAR.UN
  and DIR.UN pure lifts machine-confirmed unchanged.
- Enforced by: `_derive_reit_rental_noi` extension in sedar_mapper.py
  (derives both NOI and rental-only property_operating_costs from shared
  components under the same blended-shape condition); CLAUDE.md
  "Canonical Field Definitions" section updated from OPEN to DECIDED;
  updated REI.UN fixture test pins the derived value, the identity closing
  exactly, and the printed line's presence in unmapped[].

### CB-013: total_equity is the grand total (incl. NCI) via prefer_primary_alias; total_liabilities as printed; identity rule as backstop
- Status: DECIDED
- Date: ratified 2026-07-06 (Riley+CC design session, all five rulings as
  recommended)
- Decided by: Riley
- Scope: `total_equity` + `total_liabilities` (new default canonical
  balance-sheet fields) / all sectors / all 15 corpus filers; new mapper
  collision strategy `prefer_primary_alias`; new integrity rule
  `sedar_balance_sheet_identity`
- Decision: (1) `total_equity` = the filer's printed GRAND-TOTAL equity
  line, consolidated INCLUDING NCI where presented within equity —
  operationally, the equity line that closes assets ≡ liabilities + equity.
  The attributable/NCI-excluding subtotal is deliberately NOT taken when a
  grand total exists (stays in unmapped[]). (2) `total_liabilities` = the
  printed "Total liabilities" subtotal as-presented; SHOP (no printed
  subtotal) stays honestly unmapped, deliberately NOT derived as
  assets − equity (a derived value would make the identity check pass by
  construction). (3) Five equity aliases in declared priority order:
  "total equity" > "total shareholders' equity" > "total unitholders'
  equity" > "unitholders' equity" > "shareholders' equity total".
  (4) Collisions resolve via new per-field opt-in `prefer_primary_alias`:
  earliest-declared alias wins, recorded in meta.resolved_collisions.
  (5) New deterministic integrity rule `sedar_balance_sheet_identity`
  (warn): total_assets ≈ total_liabilities + total_equity, tolerance 0.5,
  honest field_unavailable skip when a component is missing.
- Reasoning: cross-filer label ambiguity is real and value-bearing — SLF
  prints "Total shareholders' equity" 24,532 as the NCI-EXCLUDING subtotal
  beside "Total equity" 25,492, while the SAME label IS the grand total on
  CNQ/CNR/SHOP/SIG; "Unitholders' equity" is attributable-only on DIR.UN
  (3,399,261 vs grand 4,731,073) but the grand total on REI.UN. Grand-total
  (incl. NCI) is consistent with CB-011's consolidated net_income ruling
  and is the only definition that closes the balance-sheet identity.
  CB-010's `prefer_specific_alias` (longest label) could NOT be reused — it
  picks the WRONG line on SLF (the subtotal's label is longer), proving the
  fields need distinct strategies. CB-010 rejected explicit priority
  ordering for `cash` as hidden convention; here the order IS the ruling
  (a printed grand-total line supersedes scoped lines) and is documented,
  so the objection does not carry. Known residual risk — a future insurer
  printing ONLY an NCI-excluding subtotal would map the wrong concept —
  is converted from silent error to flagged conflict by ruling (5): the
  identity then fails by exactly the excluded amount.
- Evidence: all 15 fixtures — identity ties EXACTLY on all 14 filers with
  a printed Total liabilities line (e.g. RY 2,325,006 = 2,185,855 +
  139,151; SLF 398,455 = 372,963 + 25,492; SIG 50,130,571 = 6,250,396 +
  43,880,175); prefer_primary_alias fires on exactly SLF and DIR.UN
  corpus-wide, both resolving to the printed "Total equity"; SHOP's
  current + long-term subtotals (1,392 + 324 = 1,716) equal
  assets − equity (15,189 − 13,473), confirming honest absence not
  extraction failure; live moat-log record 182 (AEM FY2025 replay,
  sedar_balance_sheet_identity passed, diff 0.0 at raw-dollar scale).
  mapped_count +2 on 14 fixtures, +1 on SHOP (registry regenerated, all
  15 rows campaign_validated, stored == resolved).
- Enforced by: CLAUDE.md "Canonical Field Definitions" (total_equity /
  total_liabilities entries — the enforcement copy); sedar_aliases.json
  total_equity `collision_resolution: prefer_primary_alias` + ordered
  aliases; sedar_mapper.py alias_order index + prefer_primary_alias
  collision branch; rules.py `sedar_balance_sheet_identity` +
  engine.py `_check_balance_sheet_identity` (ctx components resolve
  top-level-then-mapped like total_assets); _CANONICAL_SCALE_FIELDS
  classification; tests: test_cb013_* (mapper: SLF/DIR.UN resolution,
  secondary grand-total forms, SHOP honest absence + no derivation,
  14-fixture identity closure with pinned count) and
  test_sedar_balance_sheet_identity_* (detection: pass / wrong-concept
  flag at RY's real NCI 59 / honest skip).

### CB-014: derived fields get structural DERIVED status in the cross-check — never sent to Gemini, never dispositioned, never capping the filer state
- Status: DECIDED
- Date: opened 2026-07-03 (open-queue design item "derived fields in the
  cross-check denominator"; scope grew 2026-07-06 when CB-012 made REI.UN
  property_operating_costs a second derived field); ratified 2026-07-06
  (Riley+CC design session, all five rulings as recommended)
- Decided by: Riley
- Scope: cross_extractor.py comparison contract / all derived mapped
  fields (corpus census: ATD gross_profit, REI.UN net_operating_income +
  property_operating_costs) / CROSS_EXTRACTOR_VERSION 3 → 4
- Decision: (1) Derived fields are never sent to Gemini and appear in
  every cross-check record with explicit structural per-field status
  DERIVED / reason derived_by_construction — explicit annotation, not
  silent exclusion. (2) DERIVED rows are excluded from the aggregate-state
  computation: VERIFIED stays reachable for filers carrying derived
  fields; the PARTIAL-cap alternative was presented and rejected (PARTIAL's
  ratified meaning is "the WITNESS honestly abstained"; a derived field is
  "WE decided by construction"). (3) DERIVED needs no triage disposition
  and is not re-opened by checker_version bumps; version 3 → 4, v3 records
  preserved append-only (REI.UN's v3-linked "other" disposition stays as
  history). (4) _derived_label becomes substring (was prefix) and
  derived_label_mismatch fires when EITHER label is derived-marked (was
  both — unreachable once FinLens-side derived fields left the
  comparison); the surviving real case is Gemini deriving gross_profit
  (the prompt invites it) against a printed FinLens line. (5) CB-013-aware
  FIELD_DESCRIPTIONS for total_equity (grand total INCLUDING NCI, not the
  attributable subtotal) and total_liabilities ship in the same commit so
  the checker's concept definitions stay in lockstep with the mapper's
  rulings. Edge guard: a mapping with ONLY derived fields returns honest
  UNCHECKED (no_line_item_backed_fields), never a vacuous VERIFIED.
- Reasoning: a synthetic value has no statement line for an independent
  extractor to find — GEMINI_MISSING (or a reason-less soft CONFLICT
  against the filer's printed blended line) was structurally guaranteed
  every run, which is triage cost with zero information content, made
  perpetual by version-linked disposition keys (analyze.py
  _cx_disposition_key includes checker_version). A derived field's
  verification path is different by nature: ATD gross_profit's inputs
  (revenue, cost_of_revenue) are both themselves in the denominator
  (transitively covered); REI.UN's NOI identity is pinned by test, though
  its cost components are not canonical fields — coverage stated honestly,
  not overclaimed. Silent exclusion was rejected on integrity-first
  grounds: the log must show the field exists and why it was not
  independently checked.
- Evidence: LIVE FIRST RUN (2026-07-06, gemini-3.5-flash, moat-log record
  183): REI.UN FY2025 = VERIFIED — the first VERIFIED this filer has ever
  been eligible for — 8/8 line-item-backed fields AGREE byte-exact
  (including first-run agreement on the new CB-013 fields: total_equity
  7,157,263 via "Unitholders' equity", total_liabilities 7,737,129), both
  derived fields recorded DERIVED/derived_by_construction with
  gemini_value null. Pre-fix live costs on record: the 2026-07-03 v3 run
  had REI.UN FLAGGED on property_operating_costs; ATD gross_profit's
  reason mis-bucketed scope_masked_agree vs derived_label_mismatch purely
  on Gemini's phrasing (prefix-only detection).
- Enforced by: cross_extractor.py (checkable/derived split in
  cross_check_filing, FIELD_STATUS_DERIVED +
  FIELD_REASON_DERIVED_BY_CONSTRUCTION, _aggregate_state exclusion with
  anti-vacuous-VERIFIED guard, _derived_label substring, either-sided
  _masked_agree_reason, UNCHECKED_NO_LINE_ITEM_BACKED_FIELDS,
  CROSS_EXTRACTOR_VERSION "4", CB-013-aware FIELD_DESCRIPTIONS);
  analyze.py needs no change (DERIVED is outside CX_TRIAGE_STATUSES by
  construction); tests test_cb014_* (7 pins: prompt exclusion + DERIVED
  annotation, VERIFIED-reachable, conflicts-not-masked, all-derived →
  UNCHECKED, substring detection, deterministic suffix reason,
  description lockstep).

### CB-015: document-class validation at ingest — deterministic structural classifier, one honest stop, warn on unaudited, info-recorded in the moat log
- Status: DECIDED
- Date: opened 2026-07-02 (gate-adjacent open-queue item, from the cold
  Suncor near-miss resolved by a manual structural check); ratified
  2026-07-06 (Riley+CC design session, all five rulings as recommended —
  the third design decision of the fifteenth session)
- Decided by: Riley
- Scope: all PDF/docx analysis ingest flows (fresh upload incl. the SEDAR
  toggle, Single Analysis re-analyse, Portfolio Manager re-analyse,
  Filing Comparison warn-only); new module
  modules/integrity/document_class.py; new engine rule
  document_class_recorded
- Decision: (1) DETECTOR = deterministic structural heuristics on
  already-extracted text, zero API cost (statement-family headings ×4,
  notes-to-FS, auditor's report, corroboration markers). A Claude
  classification call was REJECTED for v1 (per-upload cost,
  non-determinism, and the lexical signals proved decisive); escalate
  only on an observed real misclassification. (2) CLASSES:
  statements_audited (≥3/4 families + notes + auditor),
  statements_unaudited (≥3/4 + notes, no auditor — the CNQ signature),
  no_statements_detected, extraction_empty. (3) ENFORCEMENT: flag-not-
  block with ONE honest stop — no_statements_detected refuses on analysis
  flows BEFORE any Claude spend, with a message naming what was looked
  for; statements_unaudited warns and proceeds (hard-blocking would have
  blocked the sanctioned CNQ FY2024 fixture); audited passes silently.
  (4) SCOPING: NOT applied to the 8-K fetcher (press releases are
  deliberate — wrong class is contextual), the EDGAR 10-K synthetic path
  (no PDF), registry loads (pre-validated), or cached loads; the
  ingestion worker reuses the module later. (5) MOAT-LOG: class recorded
  via info-severity engine rule document_class_recorded (deliberately
  NOT warn in v1 — a warn-tier rule would flip CNQ's cached validation
  status as a side effect; severity escalation is a future decision made
  with recorded evidence). NOT sedar_only (plain uploads are classified
  too); legacy caches skip honestly. No schema bump (additive field,
  absence honest).
- Reasoning: the app performed ZERO validation that an uploaded PDF is
  the document class the analysis assumes — a silent-error class UPSTREAM
  of every extraction guard, invisible during the curated era and
  immediate the moment real users upload. An honest "this doesn't look
  like financial statements" is a PASS under the cold-load gate; a
  confident analysis of an MD&A is exactly the FAIL class. The one hard
  stop is justified because analysis of a statements-less document is
  wrong by construction AND wastes API spend; everything else stays
  flag-not-block per integrity-first.
- Evidence: calibration 2026-07-06 over 18 real corpus PDFs — 17/18
  statements_audited, CNQ FY2024 uniquely statements_unaudited (the one
  genuinely unaudited pack; the auditor's report is a clean discriminator
  while bare unaudited/interim/condensed markers are noisy: audited ATD
  says "unaudited" ×6 in prose, RY "condensed" ×5); synthetic negatives
  (press release, MD&A-only) land no_statements_detected — MD&A refused
  DESPITE citing "financial statements" because the structural signature
  (headings + notes) is required, not the phrase. Live evidence gate:
  moat-log record 184 (SIG FY2024 replay — the classifier's own verdict
  on the real PDF recorded as document_class_recorded:
  statements_audited). KNOWN LIMITATION recorded: English-only markers —
  a French filing lands no_statements_detected with an honest refusal
  until French markers are added (the gate's French edge-slot, queued
  separately).
- Enforced by: modules/integrity/document_class.py (classifier +
  refusal/warning message builders); app.py _gate_document_class at the
  four ingest sites (gate BEFORE Claude spend; class attached to
  financial_data["document_class"] + signals); engine.py
  _check_document_class_info + rules.py document_class_recorded (info);
  tests tests/test_document_class.py (12 pins incl. the CNQ signature,
  MD&A-refused-despite-the-phrase, ATD unaudited-marker noise immunity,
  3/4 tolerance, notes requirement, curly-apostrophe fold) +
  test_document_class_recorded_as_info_only /
  test_document_class_skips_honestly_when_absent (detection).

### CB-016: mixed-period drift — annual-preference period picker (root cause) + layer-agreement guard rule (the class)
- Status: DECIDED
- Date: opened 2026-07-03 (MIXED-PERIOD EXTRACTION DRIFT, surfaced by the
  CNQ re-analyse); ratified 2026-07-06 (Riley+CC design session, all five
  rulings as recommended — the fourth decision of the fifteenth session)
- Decided by: Riley
- Scope: app.py SEDAR financial_data construction / new module
  modules/sedar_periods.py / new integrity rule
  sedar_layer_period_agreement / all SEDAR ingest paths
- Decision: (1) ROOT-CAUSE FIX — the app-layer period picker
  (sedar_period_keys) carries the same annual preference as the canonical
  mapper ("year(s) ended"/"year "-labeled columns win; newest year =
  current, second-newest = prior; prior comes ONLY from annual columns —
  a single annual column yields prior=None rather than a quarterly
  prior). Columns with no annual labels (balance-sheet instant dates,
  bare labels) keep the original behavior. (2) TESTABILITY EXTRACTION —
  the picker + row builder move from app.py to modules/sedar_periods.py
  (app.py imports them); the fix could not be test-pinned where it lived
  (importing app.py executes the Streamlit script; no test imported it).
  (3) GUARD RULE for the class — sedar_layer_period_agreement (warn,
  sedar_only): every line-item-backed mapped field must agree (abs tol
  0.5) with a statement row carrying its verbatim source_label; agreement
  with ANY same-label row passes (CB-009 cross-statement twins must not
  false-fire); derived fields, unmatched labels, and fields without a
  unit-consistent reference skip honestly with counts. (4) Severity warn,
  zero API cost. (5) Scope boundaries: the historical mixed-period CV
  record stays (append-only); CNQ's cached analysis heals on next
  re-analyse; the quarterly-keyed cache entry will miss after the fix —
  accepted, that key was itself the bug; CB-015's unaudited warning on
  the same pack is complementary.
- Reasoning: two consumers of the same extracted statements picked period
  columns independently — the app layer sorted by (year, -index) so
  quarterly columns sorted first on Q4 packs, while the mapper preferred
  year-ended columns. Reproduction from the fixture showed the incident
  was WORSE than recorded: prior resolved to "Year Ended Dec 31 2024" —
  the SAME fiscal year as current (the degenerate-prior shape of the PLD
  XBRL bug, now on the SEDAR path). Fix-the-instance AND guard-the-class:
  the rule outlives the picker (any future path reintroducing layer
  divergence — new picker, new ingest route, the ingestion worker — is
  caught). IMPLEMENTATION SUBTLETY (found during build, recorded so it is
  not "simplified" away): normalize_financial_data scales statement rows
  and promoted top-level canonical fields to raw dollars but leaves
  mapping.mapped values in filing units — the rule therefore compares
  rows against the PROMOTED top-level copies (equal to mapped by
  construction, unit-consistent with rows); comparing rows to
  mapping.mapped directly would false-fire by the unit scale on every
  scaled filer.
- Evidence: deterministic reproduction from the CNQ fixture (pre-fix pick:
  current="Three Months Ended Dec 31 2024", prior="Year Ended Dec 31
  2024"; row Product sales 11,064 vs mapped 41,509). LIVE post-fix replay
  (moat-log record 185): pick = annual/annual, row layer 41,509/40,835,
  sedar_layer_period_agreement PASSED on all 8 line-item-backed fields
  (0 skipped), revenue_growth_sanity computes −0.9% YoY (the incident
  flagged −73.4%), fiscal_year label annual (heals the cache-key drift),
  CNQ overall_status clean.
- Enforced by: modules/sedar_periods.py (annual-preference picker, pinned
  by tests/test_sedar_periods.py — 7 pins incl. the CNQ pick, annual-only
  and instant-date non-regression, single-annual → prior=None); engine.py
  _check_layer_period_agreement + promoted_canonical_values /
  all_statement_rows ctx + rules.py sedar_layer_period_agreement;
  detection tests (drift caught / agree passes / CB-009 twin labels no
  false-fire / honest skip without unit-consistent reference).

### CB-017: "net loss and comprehensive loss" is DEFAULT net_income (explorers keep net_loss via prefer_profile); summary-card scrape guards
- Status: DECIDED
- Date: ratified 2026-07-06 (Riley+CC, from the Allied AP.UN FY2025 REIT
  cold-load dry-run FAIL — the fifth ruling of the fifteenth session)
- Decided by: Riley
- Scope: default `net_income` aliases / mining_exploration_sector
  `net_loss` / excel_exporter summary-card + dashboard-chart matchers
- Decision: (1) DEFAULT net_income gains alias "net loss and comprehensive
  loss" — the IFRS combined-SCI bottom line on loss-year filers,
  as-presented negative, consolidated (CB-011-consistent); same generality
  class as "profit for the year" (also added off n=1). (2) The exploration
  profile's SAME-label net_loss alias gets prefer_profile: true — explorers
  keep their net_loss spine; the prefer_profile whitelist deliberately
  widens to two uses (was REIT NOI only; pinned by test). (3) Summary
  cards: net_income reads the promoted canonical value FIRST (SEDAR),
  scrape as guarded fallback with component-row exclusion ("joint
  venture"); capex lookup excludes interest rows AND "investment
  properties" — REIT capex stays deliberately UNCLAIMED (definitional:
  property additions vs leasing costs vs improvement allowances needs its
  own design session; mirrors the PLD XBRL non-claim), so REIT FCF renders
  an honest "—". Exclusions live at module level and apply to
  two_year_statement_pairs (dashboard charts) too — same matchers, same
  defect family. BUILD-TIME DEVIATION CAUGHT AND RESOLVED FAITHFULLY: with
  interest rows excluded, the pre-existing stem fallback then claimed
  "Additions to investment properties" as capex (FCF would show 68.2M);
  the ratified honest-"—" required the additional "investment properties"
  exclusion — the test caught the gap between ruling text and legacy
  matcher behavior before it shipped.
- Reasoning: the Allied dry-run displayed two confident wrong numbers from
  the legacy label scrapes (Net Income 0 via the "Net income from joint
  venture" substring hit vs filed (1,327,532); FCF 119.8M via the
  {capit,expen} stem hit on "Interest expense (net of the impact of
  capitalization)"), and net_income failed the amended spine bar as
  honestly-unmapped. Canonical-first is the Normalize-at-the-Boundary
  principle applied to the summary layer; the scrape guards protect the
  non-mapped paths the canonical fields don't reach yet.
- Evidence: Allied AP.UN FY2025 dry-run slot record (SESSION_HANDOFF.md,
  2026-07-06) — both defects reproduced in code from the cached analysis;
  corpus re-map zero drift (SIG/NFG net_loss intact via prefer_profile,
  value-snapshot + registry-sync machine-confirmed).
- Enforced by: sedar_aliases.json (default alias + prefer_profile flag);
  excel_exporter.py (_NI_EXCLUDE / _CAPEX_EXCLUDE at module level,
  canonical-first ni_c); tests test_cb017_* (mapper: bottom line → default
  net_income, explorer keeps net_loss) +
  test_prefer_profile_escape_hatch_is_limited_to_ratified_uses (widened
  whitelist pin) + four test_summary_metrics pins (component-row,
  canonical-first, interest-exclusion honest-None, genuine-capex-suffix
  still matches).

### CB-018: canonical-first extended to revenue (same-row prior rule); bare-EPS scale exemption; financial_sector PCL parenthetical alias

- Date/status: 2026-07-06, DECIDED (ratified by Riley in-session with the
  TD FY2025 financial-or-insurer cold-slot fix queue; commit 56cb4fd).
- Questions: (1) does the summary layer's revenue read get the CB-017
  canonical-first treatment, and where does its PRIOR-year value come from?
  (2) are bare "Basic"/"Diluted" statement rows per-share figures exempt
  from unit scaling? (3) does financial_sector `provision_for_credit_losses`
  cover TD's parenthetical label form?
- Rulings: (1) YES — `_canonical_pair` reads the promoted canonical field
  first in BOTH _calc_summary_metrics and two_year_statement_pairs
  (Revenue + Net Income), with the label scrape kept as the fallback for
  non-mapped paths. PRIOR RULE: the prior comes from the SAME statement row
  as the canonical value, located by the mapping's verbatim source_label
  (the CB-016 layer-agreement invariant makes that row exist); when the row
  is absent the prior is an honest None — never a differently-matched
  scrape row (a canonical current against a scraped prior is a
  mixed-basis YoY, a confident-wrong-number generator). (2) YES —
  exact-match exemption for bare {basic, diluted, basic and diluted}
  labels; longer labels ("basic weighted average number of shares")
  deliberately NOT exempted. (3) YES — augment-don't-mint: "provision for
  (recovery of) credit losses" added as a second alias (evidence n=2:
  RY plain form + TD parenthetical form).
- Reasoning: the TD dry-run displayed FIVE wrong figures from ONE root —
  the revenue scrape matched "Repurchase agreements and short sales
  (Interest expense)" via the bare "sales" alias (11,602/13,322) while the
  mapper held "Total revenue" (67,777/57,223): wrong Revenue card, false
  −12.9% YoY, false "Revenue declining sharply" red flag, Quality 0/100,
  and a 177.0% net-margin display (20,538/11,602). The engine layer was
  simultaneously CORRECT (growth +18.4%, margin 30.3%) because it reads
  canonical fields — proof the defect class lives only in the legacy
  scrape layer (doctrine rule 1; the Phase-2 legacy-scrape retirement
  stays queued). The EPS defect: banks print an "Earnings per share"
  header with bare sub-row labels, so the per-share regex missed them and
  $11.57 rendered "$11.6M".
- Evidence: TD FY2025 slot record (SESSION_HANDOFF.md, 2026-07-06) —
  FAIL adjudication with all three mechanisms code-confirmed, then re-run
  PASS with Riley's delta transcription (Revenue 67.78B +18.4%, NI margin
  30.3%, EPS $11.57/$4.73, red flags Clean, mapping 7 fields). Corpus:
  zero fixture drift machine-confirmed (value snapshot + registry sync,
  no regen). The same slot also surfaced the extraction OUTPUT-BUDGET
  truncation (engineering fix, commit 5700002: 32k budget + honest
  stop_reason=max_tokens error, no same-cap retry) — recorded here for
  the slot's completeness, not as a judgment ruling.
- Enforced by: excel_exporter.py (_canonical_pair; canonical-first rev in
  _calc_summary_metrics; _pair_canonical_first in
  two_year_statement_pairs), claude_analyzer.py (_BARE_EPS_LABELS
  exact-match in is_per_share_line_item), sedar_aliases.json (PCL second
  alias, source TD_FY2025_dryrun); tests: 4 canonical-first pins
  (test_summary_metrics), 2 bare-EPS pins (test_normalize_financial_data),
  1 alias pin (test_sedar_mapper).

---

### CB-019: sector-aware red-flag suppression — explorer-only v1, visible suppressed[] records, suppressed flags never drive the signal

- Date/status: 2026-07-07, DECIDED (ratified by Riley). PROVENANCE NOTE:
  first ruling produced by the three-agent pipeline pilot — designed by
  Fable via API (full session record with spec and acceptance tests:
  docs/design_sessions/2026-07-07-sector-aware-red-flags__fable.md, from
  brief docs/design_briefs/2026-07-07-sector-aware-red-flags.md);
  implementation assigned to Sterling (sandbox); CC reviews/wires/commits.
- Questions: (1) should detect_flags be sector-aware? (2) which flags
  suppress for which sector profiles? (3) do suppressed flags still count
  toward the DECLINE/INVESTIGATE override? (4) suppress by profile alone or
  gate on revenue absence? (5) REIT current-ratio and bank/insurer
  balance-sheet-metric doctrine?
- Rulings: (1) YES, but evidence-gated — v1 covers exactly ONE profile:
  `mining_exploration_sector` suppresses operating_income, net_income, and
  free_cash_flow negatives ("the expected shape of a pre-revenue explorer",
  NGEx cold-load finding #3); liquidity and leverage checks KEEP FIRING
  (cash runway is the primary explorer distress axis). All other profiles:
  insufficient evidence — default behavior, no invented doctrine.
  (2) Suppression is POST-evaluation and every suppression produces a
  visible `suppressed[]` record (value, breached threshold, would-be
  severity, sector rationale) — the unmapped[] pattern; SKIP ≠ SUPPRESS
  (None metric = skip, as today, never a suppression record).
  (3) NO — suppressed flags never count toward the override; NGEx-shaped
  input flips from false INVESTIGATE to honest None BY DESIGN.
  (4) Profile-only (Riley, Q4): the mapper routes revenue-booking miners to
  mining_sector; revisit on a counterexample. (5) DELIBERATELY DEFAULT
  (Riley, Q1+Q2): REIT current-ratio red (Allied 0.53x) stays until n≥2–3
  REITs; bank/insurer current-ratio/ND-EBITDA/interest-coverage stay until
  one actually FIRES on a bank (today they None-skip; accepted residual:
  the first bank where they compute may ship a nonsense red before the
  revisit — watch item, not doctrine). EDGAR filers stay sector-unknown →
  default flags (Q6). Return shape: additive keys only (`suppressed`,
  `sector_profile`); all three consumers verified non-strict
  (app.py:689, app.py:6859, portfolio_manager.py:108).
- Reasoning: the false-signal evidence (NGEx #3) and the working-flag
  counter-evidence (Allied's HONEST net-loss yellow; TD's correct CLEAN)
  both bind — so suppress only where the false read is evidenced, keep
  everything else firing, and make every suppression as visible as the
  flags themselves. The design session (Fable-API) notably REFUSED to
  encode REIT/bank doctrine off n=1 evidence and escalated to Riley —
  who chose to wait for evidence on both.
- Enforced by: modules/red_flag_detector.py (SECTOR_FLAG_RULES,
  _resolve_sector_profile, 4-step detect_flags — implemented by Sterling on
  feature/cb-019-sector-aware-red-flags, reviewed and merged by CC same
  day); tests/test_red_flag_sector_rules.py (20 tests: T1–T11 + profile
  resolution edges + rules-table structural pin); app.py Red Flag panel
  (CB-019 sector-adjusted strip + "N sector-adjusted" on the panel label so
  Clean never hides an adjustment). Suite 425 green at merge. Sterling's
  one flagged ambiguity (parallel rationale strings for net_income /
  free_cash_flow) accepted as written at review. REAL-DATA NOTE: the NGEx
  7/2 cache resolves the profile correctly but fires ZERO flags — its
  loss-sign convention means ni_c reads +123.3M from the "Net loss" row
  (stale pre-CB-017 cache, no canonical net field); the suppression
  mechanics are therefore evidenced by the pinned T1 fixture, and the sign
  finding is queued separately (CB-020 candidate).

### CB-020: loss-form net-income sign convention — loss-declaring label ⇒ −abs(value); scrape is load-bearing; net-income-only scope

- Date/status: 2026-07-07, DECIDED (ratified by Riley). PROVENANCE NOTE:
  first ruling produced by CC directly (Opus 4.8) rather than Fable via
  ask_fable.py — the CC-first workflow test Riley opened 2026-07-07 (CC takes
  well-evidenced/deterministic/prior-ruling-constrained calls in-house; Fable
  reserved for high-powered/ambiguous ones; Riley stays ratifier). Full
  session record with spec + acceptance tests:
  docs/design_sessions/2026-07-07-explorer-loss-sign-convention__cc.md, from
  brief docs/design_briefs/2026-07-07-explorer-loss-sign-convention.md.
- Questions: (1) what is the canonical net-income sign convention? (2) the
  deterministic rule to sign a loss-form bottom line without double-negating
  a parenthetical loss or flipping a genuine profit? (3) does the summary
  scrape negate a loss-form match or render "—"? (4) old-cache handling —
  heal-in-place vs schema bump? (5) scope — net-income-only or a
  statement-wide inversion detector? (6) CB-019 interaction? (7) card
  display?
- Rulings: (1) net_income is SIGNED — profit positive, loss negative,
  consolidated incl. NCI (CB-011-consistent); the explorer `net_loss` field
  holds the same concept under a loss-year name and is stored NEGATIVE (same
  as royalties). (2) LOSS-DECLARING label = normalized label contains "loss"
  AND none of {"income","profit","earnings"} → store −abs(value); otherwise
  as-presented. The profit-word exclusion protects the "Net income (loss)"
  template (value's own sign authoritative); −abs (not plain negate) prevents
  double-negating a parenthetical loss. Verified against all 8 corpus/dry-run
  labels. (3) The rule lives at TWO sites: the summary-scrape fallback in
  _calc_summary_metrics (LOAD-BEARING — NGEx's bare "Net loss" matches no
  mapper alias, so its bottom line is unmapped and the scrape feeds the card)
  and the mapper boundary for net_income/net_loss assignment (defense-in-depth,
  no current firing filer — all corpus losses present parenthetically so −abs
  is a no-op). Plus the summary layer reads financial_data["net_loss"] as a
  canonical fallback before the scrape (CB-018 canonical-first extended to the
  explorer field). (4) Scrape NEGATES the loss-form match; does NOT render "—"
  (the loss is knowable — printed on the statement; honest absence is for
  genuinely-unknowable values). (5) NO schema bump — ni_c is computed at
  render time from unchanged stored rows; the fix corrects the derivation
  (wrong→right), same class as prior _fmt_num/PLD heals; the schema principle
  governs stored SHAPE, which is stable. (6) NET-INCOME-ONLY scope: NGEx's
  negative "Interest income" (−5,898,385) hints at a statement-wide
  loss-buildup presentation but is insufficient evidence (n=1) for a
  statement-wide inversion detector — DEFERRED (revisit on a second inverted
  filer or a full NGEx re-transcription); the n=1 refusal mirrors CB-019's
  discipline. (7) CB-019 unchanged — once ni_c reads −123.3M for
  mining_exploration_sector, CB-019 suppresses net_income + FCF negatives with
  visible suppressed[] records and the false INVESTIGATE → honest None,
  exactly as its T1 fixture models. (8) Card: signed is sufficient — _fmt_num
  already renders "-123.3M"; accounting-parentheses "(123.3M)" an optional
  polish at CC wiring.
- Reasoning: the codebase investigation (not brief-only) CORRECTED the brief's
  "likely live in the mapper" hedge — bare "Net loss" matches no alias, so
  the bug lives entirely in the scrape — and found that SIG/NFG display
  correctly only by coincidence (parenthetical presentation → negative row →
  scrape happens to get the right sign). NGEx's positive-magnitude "Net loss"
  is the mirror case the same scrape signs wrong. A sign-normalization rule
  keyed on label semantics neutralizes the presentation-format difference.
  This depth is the CC-first value: a brief-only architect (Fable) could not
  have read the aliases/tests to find the net_loss-separate-field mechanism.
- Evidence: NGEx FY2025 cached analysis (~/.finlens/analysis, schema 6,
  2026-07-02): net_income empty, mapping.mapped = {cash, total_assets,
  interest_expense}, income row "Net loss" = 123,335,862 POSITIVE,
  "Interest income" = −5,898,385. Code: excel_exporter.py:632-634 (ni_c
  scrape fallback), :483-484 (_NI_LABELS has "net loss"), :210-255 (_lookup
  no sign transform); red_flag_detector.py:154-159 (if ni_c < 0);
  sedar_aliases.json:71-108 (default net_income aliases — no bare "net loss"),
  :454-468 (explorer net_loss long-form aliases); test_sedar_mapper.py:905-906
  /:1110/:1699 (net_loss stored negative for NFG/SIG — parenthetical filers).
- Enforced by: CC-implemented directly (Riley chose CC-direct over Sterling
  to minimize metered cost on a small deterministic change; Sterling reserved
  for work where an independent implementer adds value). modules/integrity/
  sedar_mapper.py (`_is_loss_declaring_label` shared predicate + CB-020
  post-pass signing net_income/net_loss); modules/excel_exporter.py
  (`_signed_bottom_line` + `_find_row`/`_find_row2` row-returning lookups;
  sign-corrected scrape with net_income → net_loss → signed-scrape ordering in
  BOTH `_calc_summary_metrics` AND `two_year_statement_pairs` — the charts
  sibling path was caught by the Change Propagation Rule and fixed in the same
  pass so card and chart never disagree); CLAUDE.md net_income/net_loss
  sign-convention note (same commit). Tests: tests/test_cb020_loss_sign.py
  (17 tests: predicate T1, scrape T2–T8, canonical-first T6/T7, mapper
  defense-in-depth T9/T9b, no-drift T10, CB-019 interaction T11/T11b, plus 3
  charts sibling-path guards). GATES: full suite 425→442 green; /detection-test
  18 green (gate still catches poison); registry-sync tests confirm ZERO
  fixture drift (the mapper post-pass fires only on positive-magnitude loss
  labels, which no corpus filer has — value-snapshot + resolved-count machine
  checks pass, no registry regen needed). INTEGRITY-LOG EVIDENCE GATE NOT
  TRIGGERED — the load-bearing fix is a render-layer summary/chart derivation
  (not engine input), and the mapper post-pass is a proven no-op on all
  current data (engine behavior unchanged); same reasoning as CB-019. Live
  evidence: the real NGEx 7/2 cache now renders ni_c = −123,335,862 (was
  +123.3M) through both the card and the charts, healing in-place with NO
  schema bump (R6 — the stored "Net loss" row is unchanged; only the buggy
  render-time derivation is corrected). Deferred follow-ups: bare "net loss"
  as a canonical explorer alias + NGEx fixture (OQ2); statement-wide inversion
  detection (OQ1/R7).

---

## CB-021: Free Cash Flow — `operating_cash_flow` + `capex` canonical fields; sector-aware CapEx (PP&E, or PP&E + E&E for O&G/mining); acquisitions excluded; composition disclosed

DECIDED 2026-07-07 (Riley). Motivation: CNQ's Key Metrics showed only 2 of 5
(Revenue, Net Income); Free Cash Flow rendered an honest "—" because the capex
label scrape did not recognize CNQ's "Net expenditures on property, plant and
equipment" line (OCF scraped fine at 13,386; capex None → FCF None). FCF is a
core value-investing metric, so map it the governed way rather than patch the
scrape.

RULINGS:
1. MINT two DEFAULT canonical fields, both cash_flow-statement-scoped:
   `operating_cash_flow` = the "cash flows from operating activities" subtotal
   (indirect method; CNQ = 13,386); `capex` = additions to property, plant &
   equipment, stored NEGATIVE as-presented (CNQ = −5,291 from "Net
   expenditures on property, plant and equipment").
2. CAPEX EXCLUDES ACQUISITIONS / M&A by design — a buyout must never enter
   FCF. CNQ's "Acquisition of Chevron's assets" (−9,163) is deliberately
   UNMAPPED (no alias matches it); pinned by the CNQ value snapshot.
3. SECTOR-AWARE CAPEX (Riley's finance-expert ruling): general filers → CapEx
   = PP&E only; OIL & GAS / MINING filers → CapEx = PP&E + E&E (the full
   capital-investment lifecycle). E&E is carried by
   `capitalized_exploration_additions` (CB-009), extended to resource_sector
   with CNQ's "Net expenditures on exploration and evaluation assets" (−92).
   Its PRESENCE is the sector signal (that field only maps in
   resource/mining/explorer sectors), so no separate sector check is needed.
   CNQ CapEx = 5,291 + 92 = 5,383; FCF = 13,386 − 5,383 = 8,003.
4. FULL DISCLOSURE (Riley): the metric states what CapEx includes — "(PP&E)"
   vs "(PP&E + E&E)". Generalized to a calculation caption under EVERY Key
   Metric card (the receipts principle applied to ratios): FCF "OCF 13.39B −
   CapEx 5.38B (PP&E + E&E)", Net Income "net income 6.11B ÷ revenue 41.51B";
   metrics that are genuinely N/A (O&G has no gross-profit line) carry no
   caption (honest silence).
5. FEED SCOPE: the cash-flow statement is fed to the mapper for mining-family
   AND resource (O&G) filers via a SINGLE SOURCE OF TRUTH
   `sedar_mapper.mapper_statement_keys` — the prior mining-only rule was
   DUPLICATED in three places (attach_mapping, build_filing_registry,
   test_filing_registry) and drifted the moment this shipped; all three now
   delegate (Minimize Human Error, rule-of-three met).
6. EXPLORER COLLISION: the new default `operating_cash_flow` alias "cash flows
   from operating activities" collided with the explorer field
   `net_cash_used_in_operating_activities` (SIG's exact label). Pre-revenue
   explorers keep their own OCF spine via `prefer_profile: true` (same
   mechanism as CB-017's net_loss and the REIT NOI); pinned by the
   ratified-uses whitelist test.

CORRECTNESS NOTE: unlike the balance sheet (assets ≡ liabilities + equity), the
cash-flow statement has no single-filing identity, so these fields lean on
ground-truth + the Gemini cross-check, not a self-check.

CANONICAL-FIRST: `_calc_summary_metrics` and `two_year_statement_pairs` prefer
the mapped operating_cash_flow / capex over the label scrape; the scrape (with
its CB-017 interest-exclusion guards) stays the fallback for non-mapped
(EDGAR/manual) paths. The CapEx chart mirrors the card's PP&E+E&E composition
so OCF − CapEx on the chart reconciles to the card's FCF.

- Enforced by: CC-implemented directly. sedar_aliases.json (operating_cash_flow
  + capex default fields; capitalized_exploration_additions on resource_sector;
  explorer OCF prefer_profile); sedar_mapper.py (`mapper_statement_keys` single
  source of truth); sedar_extractor.py + scripts/build_filing_registry.py +
  tests/test_filing_registry.py (all delegate); claude_analyzer.py
  (`_CANONICAL_SCALE_FIELDS` += operating_cash_flow, capex); excel_exporter.py
  (`_fmt_compact`, canonical-first + sector-aware capex + capex_basis + calcs,
  in `_calc_summary_metrics` AND `two_year_statement_pairs`); app.py (calc
  captions under each Key Metric card); CLAUDE.md Canonical Field Definitions
  (same commit). Tests: 5 in test_summary_metrics.py; prefer_profile whitelist
  updated; CNQ value snapshot re-stored (8→11) + registry regenerated (only CNQ
  changed). GATES: full suite 452→457 green; ruff clean; empirically verified
  on the real CNQ fixture (OCF 13,386 / CapEx 5,383 / FCF 8,003, acquisition
  excluded, mapped_count 8→11, zero collisions). INTEGRITY-LOG EVIDENCE GATE
  NOT TRIGGERED — new mapped fields flow through the existing
  `_run_integrity_checks` on load (engine wiring unchanged); the change is
  canonical coverage + render-layer disclosure. Deferred: operating_cash_flow /
  capex aliases for non-CNQ filers as each is ground-truthed (labels differ);
  EBITDA-margin for O&G (needs an operating_income definition); full-corpus FCF
  widening.

---

## CB-022: Debt/Equity leverage — `long_term_debt` + `short_term_debt` canonical fields; interest-bearing borrowings only (leases & M&A excluded); suppressed for banks/insurers; composition disclosed

DECIDED 2026-07-07 (Riley). Complements CB-021: cash generation (FCF) and
balance-sheet risk (leverage) are the two halves of a value investor's core
read. CNQ's "Leverage" tile was N/A (net-debt/EBITDA needs EBITDA); Debt/Equity
is broadly computable and reuses the already-mapped total_equity (CB-013).

RULINGS:
1. MINT two DEFAULT balance-sheet-scoped canonical fields: `long_term_debt`
   ("long-term debt") + `short_term_debt` ("current portion of long-term
   debt") — interest-bearing borrowings, presented positive.
2. TOTAL DEBT = long_term_debt + short_term_debt. EXCLUDES leases (filers break
   lease obligations out separately — AEM/CNR/CNQ all do — and the aliases
   don't match lease labels) and operating liabilities. Debt/Equity = total
   debt / total_equity.
3. SUPPRESSED FOR BANKS/INSURERS: financial_sector / insurance_sector filers
   get honest N/A — deposits and policy liabilities make D/E a different
   concept (integrity-first, same spirit as the economics-panel gating).
4. DISCLOSURE: the ratio states its composition ("LT debt + current portion")
   in a caption under the Financial Health panel, and it joins that panel as a
   6th RAG check (thresholds ≤1.0 GREEN, ≤2.0 AMBER, >2.0 RED) feeding the
   Quality score (rescaled to available checks).

CANONICAL-FIRST: total debt prefers the mapped fields (feeding BOTH net_debt
and D/E so they never disagree); the balance-sheet debt scrape is the fallback
for non-mapped EDGAR/manual paths.

GROUND-TRUTH (all three drifted fixtures verified against their balance sheets,
leases correctly excluded): CNQ D/E 0.48 (LT 16,419 + current 2,400 / equity
39,468); AEM 0.008 (a genuinely low-debt miner — LT 196,271, current 0, equity
24.7B; lease obligations broken out separately); CNR 0.98 (capital-intensive
railway — LT 20,300 + current 906 / equity 21,568).

- Enforced by: CC-implemented directly. sedar_aliases.json (long_term_debt +
  short_term_debt default fields, balance-sheet-scoped); claude_analyzer.py
  (_CANONICAL_SCALE_FIELDS += both); excel_exporter.py (canonical-first total
  debt feeding net_debt + de_ratio; sector gating; debt_equity calc caption);
  app.py (_quality_score + _dash_rag debt_equity thresholds; 6th RAG tile;
  disclosure caption; "5 checks" → "6 checks"); CLAUDE.md Canonical Field
  Definitions (same commit). Tests: 3 in test_summary_metrics.py; AEM/CNR/CNQ
  fixture assertions updated; 3 fixtures re-stored + registry regenerated.
  GATES: full suite 457→460 green; ruff clean; empirically verified (D/E 0.48 /
  0.008 / 0.98 against source balance sheets). Integrity-log gate not triggered
  (canonical coverage + render-layer disclosure; engine wiring unchanged).
  Deferred: lease-inclusive leverage variant; debt aliases for other filers as
  ground-truthed; a bank/insurer-appropriate leverage metric.

## CB-023: EBIT / EBITDA / Interest-Cover — `pretax_income` + `interest_expense`; EBIT = pre-tax income + interest (add-back); gated off banks/insurers

DECIDED 2026-07-07 (Riley). CNQ's EBITDA Margin + Interest Cover were N/A
because CNQ prints no operating-income line (straight from expenses to
"Earnings before taxes"), so EBITDA (= OI + D&A) and interest cover (=
EBIT / interest) had no numerator. Both unlock from the same derivation.

RULINGS:
1. MINT default income-statement-scoped `pretax_income` ("earnings before
   taxes", "income before income taxes", "income before taxes"); map
   `interest_expense` for resource ("interest and other financing expense").
2. EBIT = pre-tax income + interest expense (the standard add-back), used when
   no printed operating-income line exists; a printed operating income is
   preferred where present. Includes non-operating items in EBT (FX, risk-mgmt)
   — the accepted standard-EBIT tradeoff for comparability.
3. EBITDA = EBIT + D&A. Unlocks EBITDA Margin (Key Metrics), Interest Cover =
   EBIT / interest, and Leverage = net-debt / EBITDA (Financial Health).
4. GATED OFF BANKS/INSURERS: EBIT/EBITDA/interest-cover are not meaningful for
   financial_sector / insurance_sector (interest is core to their business) —
   honest N/A. `pretax_income` still MAPS on those filers (a real line); only
   the derived metrics are withheld.
5. DISCLOSURE: the EBITDA-margin caption notes "(EBIT + D&A)"; Interest Cover
   shows "EBIT / interest"; and when EBIT is an add-back, a caption discloses
   "EBIT = pretax + interest".

GROUND-TRUTH (CNQ): interest 592, pretax 8,059 -> EBIT 8,651; DD&A 6,681 ->
EBITDA 15,332. EBITDA Margin 36.9% (/ gross revenue 41,509), Interest Cover
14.6x, Leverage 1.22x. CNQ now has all 6 Financial Health checks and 4 of 5 Key
Metrics (Gross Margin stays N/A — O&G has no COGS).

- Enforced by: CC-implemented directly. sedar_aliases.json (pretax_income
  default; interest_expense resource alias); claude_analyzer.py
  (_CANONICAL_SCALE_FIELDS += pretax_income); excel_exporter.py (canonical-first
  interest; EBIT derivation gated off financials; int_cover + ebit captions);
  app.py (Financial Health discloses int_cover + the EBIT add-back). Tests: 3
  in test_summary_metrics.py; 6 fixture assertions updated; 7 fixtures re-stored
  (all gained pretax_income; CNQ + interest_expense) + registry regenerated.
  GATES: full suite 460->463 green; ruff clean. Empirically verified (EBITDA
  margin 36.9%, interest cover 14.6x, leverage 1.22x on CNQ; suppressed on
  RY/IFC). CB-023 casebook + CLAUDE.md same commit. Deferred: strict operating
  income as an alternative EBIT; per-filer interest_expense aliases; a
  bank/insurer-appropriate coverage metric.

## CB-024: Netback Margin — the O&G gross-margin analog; `transportation_costs`; sector-aware Key Metrics card

DECIDED 2026-07-07 (Riley). Gross Margin is genuinely N/A for O&G (no
cost-of-goods line), so rather than fake it, the Key Metrics card shows the
operating NETBACK MARGIN for resource filers — the standard O&G profitability
measure, computed from the income statement.

RULINGS:
1. MINT resource-scoped income-statement `transportation_costs`
   ("transportation, blending and feedstock").
2. Operating netback = net revenue (gross revenue − royalties) − production
   (operating_expense) − transportation. Netback margin = netback / NET revenue
   (after royalties — Riley's denominator choice, the stricter post-royalty
   convention). CNQ: 35,656 − 8,093 − 9,984 = 17,579; margin 17,579 / 35,656 =
   49.3%.
3. SECTOR-AWARE CARD: for resource filers the "Gross Margin" Key Metrics card
   becomes "Netback Margin" (the O&G-correct analog); non-resource filers keep
   Gross Margin. Netback excludes D&A, G&A, financing, taxes (field-level
   operating margin). Composition disclosed ("netback X / net revenue Y").
4. PER-BARREL NETBACK ($/boe) is DEFERRED — it needs production VOLUMES, which
   live in the MD&A, not the financial statements; that is the Tier-2 /
   MD&A-fetcher build (scoped in the handoff), not this income-statement metric.

Resource-only: gated on transportation_costs, which maps only for O&G filers
(presence is the signal). Ground-truthed on CNQ: netback 17,579, margin 49.3%.

- Enforced by: CC-implemented directly. sedar_aliases.json (transportation_costs
  resource alias); claude_analyzer.py (_CANONICAL_SCALE_FIELDS +=
  transportation_costs); excel_exporter.py (netback + netback_margin + caption);
  app.py (sector-aware Key Metrics card: Netback Margin for O&G, Gross Margin
  otherwise). Tests: 2 in test_summary_metrics.py; CNQ fixture assertion updated;
  CNQ re-stored (mapped_count 16) + registry regenerated. GATES: full suite
  463->465 green; ruff clean. Integrity-log gate not triggered. CB-024 casebook
  + CLAUDE.md same commit. Deferred: per-barrel netback (MD&A volumes);
  transportation aliases for other O&G filers as ground-truthed.

---

## CB-025: Resource gross revenue on rollup-printing filers — `suppressed_default_aliases` mechanism; TOU/ARX triage aliases

DECIDED 2026-07-09 (Riley; the TOU FY2025 + ARX FY2025 agent-ingestion triage
session — the first n=2 adjudication produced entirely by the worker
pipeline). HEADLINE FINDING (CC, beyond the worker's 7 questions): both
bundles carried a WRONG-CONCEPT canonical revenue. Each filer prints a
"Total revenue" rollup that is NET of royalties — component sums tie exactly
(TOU 6,019,970 = 4,940,024 commodity sales + 1,230,294 risk-mgmt premiums +
132,679 marketing − 513,879 royalties + 31,399 other + 420,981 realized
gains − 221,528 unrealized; ARX 6,075.7 = 5,421.7 − 536.8 + 1,190.8) — and
the DEFAULT profile's "total revenue" alias captured it. The gross-of-royalties
NEGATIVE RULE (CNQ ruling, 2026-06-17) only forbade ADDING a resource alias
for net lines; it had no machine enforcement against default aliases, and CNQ
never tripped it because CNQ prints no "Total revenue" line. Unfixed, CB-024's
netback margin would also double-subtract royalties.

RULINGS:
1. Canonical `revenue` for TOU/ARX = "Commodity sales from production"
   (gross production top line, CNQ "Product sales" precedent; new resource
   alias, n=2). Marketing revenue / hedging premiums / rollup lines stay
   unmapped as components.
2. NEW MECHANISM `suppressed_default_aliases`: a sector profile may suppress
   named default aliases for a named canonical field. resource_sector
   suppresses ALL FOUR default revenue rollup aliases ("total revenue",
   "total revenues", "revenue total", "revenues") — the negative rule is now
   MACHINE-ENFORCED, not documentation. Suppressed lines stay visible in
   unmapped[] (same honest behavior as CNQ's bare net "Revenue").
3. Bare `royalties` alias (resource, income-statement-scoped) — n=2, negative
   as-presented on both filers, consistent with the stored-NEGATIVE rule.
   Ships WITH ruling 1 (royalties against a net revenue would double-count).
4. Triage alias family (concept-unambiguous, no new judgment): pretax_income
   += "net income before income taxes" (ARX); operating_cash_flow +=
   "total cash flow from operating activities" (TOU) + "cash flow from
   operating activities" (ARX); capex (resource) += "property, plant and
   equipment" CASH_FLOW-SCOPED (TOU; the identical label is the balance-sheet
   asset stock — CB-009 stock/flow pattern) + "property, plant and equipment
   development expenditures" (ARX); short_term_debt += "current debt" (TOU).
5. Typographic-apostrophe normalization: `_normalize_label` folds U+2019/U+2018
   to ASCII "'" — ARX prints "Total shareholders’ equity" (grand total,
   identity ties 7,046.3 + 8,264.0 = 15,310.3) and the curly quote defeated
   every CB-013 alias. Pure-logic change; _MAPPER_LOGIC_REV bumped 1→2.
6. LABELED ADDITION (beyond the ratified list, surfaced by the corpus drift
   check): long_term_debt += "non-current debt" (DIR.UN). The ratified
   "current debt" alias fires on DIR.UN's balance sheet, and alone it would
   compute an understated D/E (870,407 current-only vs true total debt
   2,968,950). The IFRS current/non-current pair maps as a PAIR.
7. DEFERRED (Riley, explicit): bare "Operating" / "Transportation" expense
   labels (n=2 but dangerously generic) — netback margin stays honestly
   unavailable on TOU/ARX until a scoped ruling.
8. Q-noise closed with no action: TOU's combined "Net income and comprehensive
   income" row (bottom line already maps from the clean "Net income" row,
   same value); per-share rows (no canonical consumer — fails the
   mapping-utility gate).

- Enforced by: CC-implemented directly (commit cites CB-025).
  sedar_mapper.py (suppressed_default_aliases in _build_match_indexes;
  apostrophe fold in _normalize_label; _MAPPER_LOGIC_REV 2);
  sedar_aliases.json (all aliases above + resource suppression block).
  Tests: tests/test_cb025_tou_arx_triage.py (16 pins incl. suppression
  scoped-to-resource, stock/flow fail-closed, DIR.UN debt pair);
  DIR.UN fixture re-stored 9→11 (only the debt pair added, zero value
  changes, machine-verified) + registry regenerated; full suite 485 green.

## CB-026: Combined "DD&A and impairment" line — maps WITH `includes_impairment` semantics; EBITDA composition disclosed

DECIDED 2026-07-09 (Riley — RE-RATIFIED same day: the morning triage ruled
"leave unmapped"; Riley then surfaced the standard-practice evidence that
BOTH DD&A and impairment are non-cash EBITDA add-backs, and re-ratified to
map-with-disclosure). Evidence n=2: TOU "Depletion, depreciation,
amortization and impairment" 3,000,251; ARX "Depletion, depreciation and
amortization and impairment of property, plant and equipment" 1,547.2 —
combining is the sector norm on gas-weighted filers.

RULING: the combined line maps to `depletion_depreciation_amortization` with
semantics {"includes_impairment": true} (ATD `excludes_da` tag precedent),
income-statement-scoped (the cash-flow add-back twin stays unmapped).
EBITDA = EBIT + this line — "EBITDA excluding impairment", the conventional
metric — and the composition is DISCLOSED: the EBITDA-margin caption reads
"(EBIT + D&A incl. impairment)" via the new `da_basis` metrics key.

CONSUMER FIX REQUIRED BY THE RULING: `_calc_summary_metrics` D&A was a bare
cash-flow-row scrape (_DA_LABELS carries bare "depreciation"/"amortization"
keywords) which would have matched the combined line SILENTLY — impairment
inside EBITDA with no caption saying so. D&A is now canonical-first
(promoted `depletion_depreciation_amortization`, scrape fallback for
non-mapped paths), reading the semantics tag for the disclosure.

HONEST CAVEAT (recorded, accepted): cross-filer EBITDA comparability — CNQ's
pure D&A line carries no impairment; in a big-impairment year TOU's EBITDA
add-back is a disclosed different composition. The caption is the mitigation.

- Enforced by: CC-implemented directly (commit cites CB-026).
  sedar_aliases.json (two combined-line aliases with semantics, resource);
  excel_exporter.py (_calc_summary_metrics canonical-first D&A + da_basis +
  caption disclosure). Tests: 5 pins in test_cb025_tou_arx_triage.py (both
  label forms, CNQ pure line carries NO tag, caption with/without tag).

## CB-027: Multi-commodity tracking — record ALL commodity families, benchmark each proxied one, claim NO primary

DECIDED 2026-07-09 (Riley — this ruling SUPERSEDES the morning's
"suppress-when-ambiguous" framing after Riley redirected: many producers
sell oil AND natural gas AND NGLs at once, oil has grades (sweet/heavy,
oil sands), and he wants ALL of them recorded). Motivating evidence: the
queued gas-weighted ambiguity item hit its predicted case at n=2 — TOU
(Canada's largest gas producer) and ARX (Montney gas-weighted) carry the
IDENTICAL sector string "Upstream Oil & Gas" as oil-weighted CNQ, so the
Economics panel benchmarked all three confidently against WTI. The string
cannot reveal revenue weighting; picking one commodity was the defect.

RULINGS:
1. `classify_commodities()` records EVERY commodity family evidenced for a
   filer ({name, source, proxy_available}); vocabulary adds NGLs and oil
   sands. "Upstream Oil & Gas" → crude oil + natural gas, both recorded.
2. The panel renders a FULL benchmark block (spot, linkage/correlation,
   trend, indexed chart) per PROXY-AVAILABLE family — WTI and Henry Hub side
   by side — and the header states "no revenue weighting claimed". Ratified
   option: "All benchmarks, none primary." This dissolves the CNQ dilemma:
   CNQ keeps its WTI benchmark and honestly gains the gas one.
3. RECORD-ONLY families (oil sands, NGLs — no liquid free-tier proxy) appear
   in metadata.commodities with an honest no-proxy marker; a lookalike proxy
   is NEVER borrowed for them. Oil-sands strings still proxy crude oil
   (blend pricing) with the standing WCS-differential caveat.
4. Bare "gas" without oil evidence stays unclassified (midstream "Gas
   Gathering and Processing" — pinned; matches the legacy conservative pin).
5. BACK-COMPAT: legacy single-commodity snapshot keys stay wired to
   benchmark #1, whose identity matches the historical infer_commodity()
   pick on every previously-supported shape — single-commodity filers (AEM)
   are bit-identical.
6. DEFERRED (recorded): revenue-weighting extraction from the IFRS 15
   disaggregation note (the real long-term source — the oil/gas/NGL revenue
   split is printed in the filings); WCS/NGL benchmark data sources; grade
   granularity (sweet/heavy) beyond the oil-sands family name.

- Enforced by: CC-implemented directly (commit cites CB-027).
  resource_economics.py (classify_commodities + RECORD_ONLY_COMMODITIES;
  build_resource_economics_snapshot commodity_benchmarks list +
  metadata.commodities/multi_commodity; infer_commodity now delegates —
  single source of truth); app.py (multi-commodity header, per-benchmark
  spot/linkage cards + trend + indexed charts via extracted render
  helpers). Tests: 6 pins in test_resource_economics.py (family recording,
  record-only marking, bare-gas pin, per-proxy benchmark blocks, legacy-key
  back-compat, single-commodity shape unchanged).

## CB-028: Search-triggered agent fetch — the flywheel front door; fetched bytes converge on the upload path by construction

DECIDED 2026-07-09 (Riley — ratified all 8 rulings + 4 open questions as
recommended; full ruling doc:
docs/design_sessions/2026-07-09-search-triggered-agent-fetch__cc.md; brief:
docs/design_briefs/2026-07-09-search-triggered-agent-fetch.md). Riley's UX,
verbatim: "search a company and a filing and have OpenClaw fetch it and load
it into the Upload Financial Statements section so I can then click analyze."

RULINGS (summary — the ruling doc is authoritative):
R1 fetch lane INSIDE the Upload expander, own Canadian checkbox (default
True); R2 honest staged blocking states via st.status (240s agent turn /
120s byte fetch), every failure shows the manual-upload fallback; R3 strict
one-JSON-object agent contract (found/not_found/blocked), fetch-only,
issuer/EDGAR only, NO SEDAR+ CAPTCHA automation, never guess a URL; R4 the
app re-fetches bytes ITSELF, sha256 provenance receipt rides inside
financial_data (additively — cache, library, Supabase all carry it), bytes
cached to ~/.finlens/pdfs/_fetched/ for Re-Analyse; R5 the UploadedFile shim
(io.BytesIO + .name/.size/.getvalue) is assigned to the SAME uploaded_file
variable, so the 20MB guard, docx branch, cache key, CB-015 document-class
gate, extraction, mapper, engine, moat log, and library fire UNCHANGED BY
CONSTRUCTION — no second path to drift; R6 no auto-analyze, no auto-spend
(the analyze click and its cost stay with the user; one Sterling turn per
click); R7 config = OPENCLAW_GATEWAY_URL/_TOKEN/_SESSION_KEY via the SOPS
store + .env.example same commit (the lost-GEMINI-key lesson), missing →
lane disabled with honest caption; R8 evidence gate = live end-to-end on an
uncached filer + moat-log JSONL + failure states exercised.
OQ1 session key: REUSE the Telegram-routed key (every fetch visible in
Riley's thread — visibility rule for free; revisit at user #2). OQ2 EDGAR
URLs accepted; copy says best-for-Canadian. OQ3 240s agent timeout.
OQ4 the fetch lane's Canadian checkbox stays independent of the manual one.

- Enforced by: CC-implemented directly (commit cites CB-028).
  modules/agent_fetch.py (pure/UI-agnostic: contract prompt + parser,
  gateway turn, byte re-fetch with %PDF- magic + 20MB cap, sha256 receipt,
  FetchedUpload shim, _fetched cache); app.py (fetch lane in the Upload
  expander; same-variable convergence with manual-upload-wins clearing and
  BytesIO rewind; provenance stamp before save_cache); .env.example.
  Tests: 12 pins in tests/test_agent_fetch.py (T1–T6 + T8 module half; T7
  structural via the blocking st.status flow).

---

*Backfill status: seeded 2026-07-05 with the eleven adjudications
recoverable from CLAUDE.md, SESSION_HANDOFF.md, and the 2026-07-05/06 pilot
session. Older judgment calls found later in the archive should be added
with their original dates.*
