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
- Status: OPEN
- Date: opened 2026-07-03 (ninth session)
- Decided by: pending (Riley)
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

### CB-009: capitalized E&E is NOT exploration_expense — alias rejected, mint decision pending
- Status: OPEN (the rejection is settled; the mint decision is the open half)
- Date: opened 2026-07-05/06 (SIG FY2024 pilot review)
- Decided by: rejection CC (pilot disposition); mint decision pending (Riley)
- Scope: `exploration_expense` + possible new field / mining_exploration_sector / SIG vs NFG
- Decision: SIG's cash-flow investing line "Exploration and evaluation
  assets" (−6,927,597) must NOT alias to `exploration_expense`. OPEN
  question: mint a new canonical field for capitalized E&E additions
  (e.g. exploration capex), or leave capitalized-explorer spend honestly
  unmapped?
- Reasoning: NFG EXPENSES exploration (income statement) — that is what
  `exploration_expense` means; SIG CAPITALIZES it (investing outflow onto
  the balance sheet). Mapping both to one field collapses the exact
  accounting-policy split an analyst comparing explorers needs to see.
  Augment-don't-mint requires a genuinely different concept for a new name
  — this IS one, which is why it needs a mint decision rather than an
  alias.
- Evidence: SIG FY2024 bundle (two-read agreement on the value); NFG
  precedent 41c08dc ("Capitalized E&E preserved in unmapped[], expensed
  E&E maps"); alias rejection recorded in ba405b0 commit message.
- Enforced by: absence of the alias (deliberate); this entry.

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
  collision).
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

---

*Backfill status: seeded 2026-07-05 with the eleven adjudications
recoverable from CLAUDE.md, SESSION_HANDOFF.md, and the 2026-07-05/06 pilot
session. Older judgment calls found later in the archive should be added
with their original dates.*
