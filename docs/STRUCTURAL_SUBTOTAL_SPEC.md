# Structural-Subtotal Classifier + Cash/Current-Subtotal Promotion — Spec

Status: **DESIGN RATIFIED 2026-07-12** (three decisions ratified by Riley,
recorded in §Ratified decisions; casebook entry ships with the enforcement
commit per the same-commit rule).
Owner (planned): modules/integrity (classifier + rule + mapper gate) +
sedar_extractor.py (annotation wiring) + modules/excel_exporter.py
(canonical-first consumers) + sedar_aliases.json (promotion).

## Why

Three queued items are one design:

1. **CB-033 (Peyto):** the extractor INVENTS labels for unlabeled printed
   subtotals — it labeled Peyto's non-current-liabilities block subtotal
   "Total liabilities" (2,241,748; the true total 2,607,658 never appears
   in the filing) and the mapper mapped it. Caught downstream by
   `sedar_balance_sheet_identity` failing by exactly 365,910. The queued
   extraction-prompt fix (`label_inferred`) was design-gated as Option A
   drift risk.
2. **STRUCTURAL-SUBTOTAL CLASSIFIER (queued 2026-07-12):** a row whose
   value equals the sum of the contiguous rows above it (since the last
   inferred subtotal) is structurally a subtotal, whatever its label.
   Hand-verified on Peyto: every real subtotal ties; the CB-033 wrong
   label shows up as a LABEL-vs-STRUCTURE CONTRADICTION (ties as a block
   sum, not as current + non-current).
3. **UTILITY-GATED PROMOTION (Step 7 audit, 2026-07-12):** `cash and cash
   equivalents` + current-asset/liability subtotals are unmapped in 9
   filers across 4 profiles and now have CONCRETE consumers — the
   Liquidity and Leverage dashboard dashes Riley hit live on Peyto and
   TOU. Current ratio + net debt are the value-investing ratios that pass
   Riley's 2026-07-07 utility gate.

THE KEY INSIGHT: the classifier is a deterministic POST-EXTRACTION pass
(pure Python, zero API). It never touches the shared extraction prompt —
the Option A drift risk that gated CB-033 evaporates.

## Ratified decisions (Riley, 2026-07-12)

1. **v1 = FULL PACKAGE**: row annotation + the contradiction integrity
   rule + the MAPPER GATE (a structure-contradicted row refuses to map
   total-scope canonical fields — Peyto's wrong "Total liabilities" flips
   to honest-unmapped, the SHOP-class CB-013 negative-rule outcome). The
   17-fixture value-snapshot suite is the machine proof that no existing
   mapping regresses.
2. **CB-033's extraction-prompt fix is SUPERSEDED**: arithmetic detects
   invented-label wrongness without flagging inference and without prompt
   drift. The prompt-side `label_inferred` change is retired; the casebook
   entry records the supersession.
3. **FULL PROMOTION**: `cash` → default field (aliases incl. the exact
   bare "cash" label Peyto prints), `total_current_assets` +
   `total_current_liabilities` → new default fields ("total …" exact
   labels immediately; bare "current assets"/"current liabilities" allowed
   ONLY on structure-confirmed subtotal rows — the new STRUCTURE-GATED
   ALIAS mechanism). Liquidity + Leverage go canonical-first.

## Classifier algorithm (deterministic, zero API)

Per statement, per period column, walking rows in order:
- Maintain the running block (rows since the last inferred subtotal).
- A row is a **block SUBTOTAL** when its value ≈ sum(current block), block
  size ≥ 2.
- A row is a **GRAND TOTAL** when its value ≈ sum(prior inferred
  subtotals) — both hypotheses tested separately (the Peyto liabilities
  case needs this: 2,241,748 ties as a BLOCK sum; a true total would tie
  as subtotal + subtotal).
- Tolerance: max(absolute 1.0 filing-unit, relative 0.5%) per comparison
  (covers rounding); a candidate must tie in EVERY period column that has
  a numeric value (multi-period agreement — Peyto ties both years).
- Caveats handled by design: parenthetical negatives (values are already
  signed at this layer); memo/"of which" lines (a non-tying row simply
  stays in the running block — recall bias toward NOT classifying);
  multi-level nesting (the two hypotheses above; deeper nesting degrades
  to honest non-classification, never a wrong classification).

**CONTRADICTION**: a row whose label claims total scope (contains "total
liabilities" / "total assets" / "total equity" / statement-total phrases)
but whose arithmetic proves BLOCK-subtotal scope (or vice versa) is marked
`structure_conflict: true` with both scopes recorded. Peyto's invented
"Total liabilities" is the motivating instance.

## Enforcement (the full package)

- **Annotation**: rows gain `structure` (subtotal / total / data — data
  meaning "not proven", never "proven data") and `structure_conflict`.
  Runs in attach_mapping's input path so the mapper and downstream
  consumers all see it (normalize-at-the-boundary).
- **Integrity rule** `structure_label_contradiction` (warn): fires when
  any mapped-or-unmapped row carries structure_conflict — catches the
  CB-033 class at the boundary, before (and in addition to) the identity
  rule backstop.
- **Mapper gate**: total-scope canonical fields (total_assets,
  total_liabilities, total_equity + the new current-subtotal fields)
  REFUSE a structure-contradicted row; the row stays visible in
  unmapped[] with the conflict recorded. Honest absence > wrong scope.
- **Structure-gated aliases**: new per-alias key `requires_structure`
  ("subtotal" | "total") — the alias matches only rows the classifier
  proved. Used for the bare "current assets"/"current liabilities"
  labels; inert on filers where the classifier proves nothing (honest
  unmapped, exactly today's behavior).

## Promotion (the consumers)

- `cash` (DEFAULT, balance_sheet-scoped): aliases "cash and cash
  equivalents" (9 filers), "cash and equivalents", "cash, cash
  equivalents and short-term investments", bare "cash" (Peyto's exact
  label; exact-match semantics keep "cash held in trust" etc. out). The
  existing explorer-profile `cash` field keeps its profile placement
  (same canonical name — the CLAUDE.md augment rule, mining_sector
  pattern).
- `total_current_assets` / `total_current_liabilities` (DEFAULT,
  balance_sheet-scoped): exact "total current assets"/"total current
  liabilities" immediately; bare forms via requires_structure="subtotal".
- **Consumers wired canonical-first** (scrape fallback retained for
  EDGAR/manual paths): `_calc_summary_metrics` ca_c / cl_c / cash_c →
  Liquidity (current ratio) and Leverage (net debt = debt − cash) arm on
  canonical data. TOU stays honest-N/A on Leverage (no cash line exists —
  the capital-management-measures pack is that fix, separately queued).
- Governed process per field: casebook entry → aliases → fixture re-maps →
  registry regen → FULL suite (registry-sync + value-snapshot) → pins.

## Build stages

- **Stage 0** — classifier as a pure module (modules/integrity/
  structure.py): algorithm + contradiction detection + pins on the real
  Peyto/TOU/ARX shapes (incl. the CB-033 contradiction positive and the
  every-real-subtotal-ties positives; memo-line and nesting negatives).
- **Stage 1** — wiring: annotation at the attach_mapping boundary +
  the `structure_label_contradiction` integrity rule + moat-log evidence.
- **Stage 2** — mapper gate + requires_structure alias mechanism +
  the three-field promotion + fixture/registry regen + pins.
- **Stage 3** — consumer wiring (_calc_summary_metrics canonical-first) +
  live verification (Peyto reload: Liquidity/Leverage arm; TOU: Liquidity
  arms, Leverage stays honest-N/A).

Each stage through the normal gate. Casebook entry (CB-037) ships with the
first enforcement commit and records the CB-033 supersession.
