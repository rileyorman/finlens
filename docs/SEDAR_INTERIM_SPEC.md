# SEDAR Quarterly / Interim Analysis + TTM — Spec

Status: **DESIGN RATIFIED 2026-07-12** (six decisions ratified by Riley,
twenty-seventh session; §Ratified decisions). BUILD SEQUENCED after the
CB-039 batch deploys — the derivation work deserves fresh attention, per
the same discipline as CB-038 Phase 2. Casebook entry (CB-040) ships with
the first enforcement commit.

Owner (planned): modules/sedar_periods.py (window-class parser + the new
selection mode) + the SEDAR analysis flow in app.py (labeling, captions,
TTM assembly) — CB-016's existing annual-preference picker is UNTOUCHED
(its pins hold).

## Why

Quarterly analysis for SEDAR filers has never been designed: the corpus is
FY-only by selection, not by capability. The pipeline has already ingested
an interim document (CNQ's corpus fixture is the unaudited Q4 pack —
CB-016 deliberately picked the annual column out of it), document_class
already classifies interims (statements_unaudited, warn-and-proceed), and
the point-in-time integrity checks work unchanged on an interim balance
sheet. What is missing is period-selection correctness on quarter-only
packs and the quarter/TTM derivations.

## Empirical grounding (from disk, 2026-07-12 — no fetch needed)

- The extraction layer already emits WINDOW-TYPED column keys. CNQ Q4
  pack, income statement + cash flow: ["Three Months Ended Dec 31 2024",
  "Three Months Ended Dec 31 2023", "Year Ended Dec 31 2024", "Year Ended
  Dec 31 2023"]; balance sheet: instant dates. The window semantics are in
  the key text — the column-header equivalent of XBRL start/end dates.
- **THE CB-016 QUARTER-ONLY TRAP (located exactly):** on a Q2/Q3 pack
  there are NO annual-labeled columns, so `sedar_period_keys` falls to its
  year-sort fallback and pairs current = "Three Months Ended Jun 30 2026"
  with prior = "Six Months Ended Jun 30 2026" — the SAME YEAR'S YTD column
  as the prior period. Every YoY delta silently wrong: the gate-forbidden
  class. This is the defect the new selection mode exists to make
  impossible.
- **Discrete cash-flow columns EXIST in Canadian interim PDFs** (CNQ
  prints "Three Months Ended" cash-flow columns) — unlike XBRL 10-Qs,
  where OCF is YTD-only. This grounds the lift-over-derive decision.
- CB-039's ratified machinery (duration taxonomy, strict chain gate,
  composite receipts, degenerate-TTM honesty) transfers with the label
  parse replacing date arithmetic: "Three Months" = Q · "Six Months" = H1
  · "Nine Months" = 9M · "Year(s) Ended" = FY.

## Ratified decisions (Riley, 2026-07-12)

1. **WINDOW-CLASS-AWARE COLUMN PAIRING**: columns of different window
   classes are NEVER paired as current/prior. Prior = same window class,
   prior year (the IAS 34 comparative). This is a NEW selection mode for
   quarter-only packs; CB-016's annual preference on annual/mixed packs is
   untouched and stays pinned.
2. **DOCUMENT-DRIVEN TRIGGER FIRST**: an interim uploaded cold must be
   handled honestly by document shape (no annual columns → interim mode,
   honest labeling), with an explicit period selector as a later
   enhancement. Cold-load robustness outranks UI.
3. **LIFT OVER DERIVE** for discrete quarters (the CB-012 conditional
   pattern): where the filer PRINTS a discrete three-month column, LIFT it
   as-filed; DERIVE by YTD differencing (YTDn − YTDn−1, composite receipt
   naming both columns) only where no discrete column exists. As-filed
   beats derived whenever the filer gives us the number.
4. **TTM AS ITS OWN STAGE**: TTM = FY (from the library's stored annual
   filing) + YTD_current − YTD_prior (both from the interim's own columns
   — IAS 34 mandates the comparative). CROSS-DOCUMENT, so it requires
   scale AND currency agreement gates between the two filings
   (annual-in-millions vs interim-in-thousands is a live trap); any gate
   failure → honest N/A. Composite receipts cite both documents.
5. **LABELING + PERMANENT CAPTION**: interim analyses carry an honest
   period label (e.g. "Q2 2026 — three months ended Jun 30 2026") and a
   PERMANENT "unaudited interim" caption; the recency and prior-column
   continuity rules get interim-aware scoping (an interim must not
   satisfy — or falsely trip — an annual-continuity expectation).
6. **GROUND TRUTH PER PROTOCOL**: the first interim filer is hand-verified
   against the source PDF under the transcription protocol before the
   shape is trusted. Candidate: TOU or Peyto Q1-2026 interim via the
   CB-028 agent-fetch front door (Sterling fetch on Riley's go-ahead at
   build time).

## Strict gates (operational form)

- A column key that parses to no window class is unusable for pairing or
  derivation (honest exclusion) — the label-parse equivalent of CB-039's
  duration-taxonomy exclusion.
- Differencing requires same window family, same fiscal year, adjacent
  ordinals (Q from H1−Q1, etc.), parsed from key text — never from column
  position.
- TTM requires: the stored annual's fiscal year immediately precedes the
  interim's year; scale equality; currency equality. Each failure →
  honest N/A, no receipt.
- Nothing ever pairs across window classes, and no interim figure renders
  without the unaudited caption.

## Stages (planned)

- **Stage 0** — pure window-class column parser (label → {class, end
  year/date}) + pins on the real CNQ fixture keys and synthetic Q2/Q3
  shapes, including the located CB-016 trap as a regression case.
  **DONE 2026-07-12 (parse_period_window in modules/sedar_periods.py;
  ambiguous combined headers — "Three and six months ended ..." — are
  honest exclusions).**
- **Stage 1** — quarter-only selection mode in sedar_periods (the trap
  becomes impossible) + document-driven interim labeling + the permanent
  unaudited caption + rule scoping (decision 5).
  **DONE 2026-07-12 (same commit as Stage 0; CB-040 casebook entry ships
  with it): window-class pairing branch in sedar_period_keys (CB-016
  annual preference untouched, pins hold; class preference FY > Q > H1 >
  9M); labeling is the honest column-key text by construction ("Three
  Months Ended Jun 30 2026"); amber "unaudited interim" header caption,
  document-driven off the fiscal_year window parse; prior-column
  continuity checker skips interim payloads (UNCHECKED /
  interim_period_not_annual); fiscal_year_recency verified needing no
  scoping. 8 new pins.**
- **Stage 2** — discrete-quarter lift-over-derive with composite receipts
  for the derived branch. **STAGE 2a DONE 2026-07-12: one shared
  period-column picker (select_period_pair / select_current_period_value
  in modules/sedar_periods.py); the mapper feed
  (sedar_extractor._first_statement_value), the row layer, and the
  registry script's _mapper_source_value — previously byte-level
  TRIPLICATES whose first-column fallback could map a YTD value while the
  rows showed the discrete quarter — now delegate to it and agree by
  construction. Zero corpus drift machine-proven (value-snapshot suite,
  all 17 filers + registry sync). This IS the LIFT half: both layers
  select the printed discrete column wherever it exists.**
  **SCOPE FINDING (evidence-forced, recorded 2026-07-12): the DERIVE
  fallback is CROSS-DOCUMENT — a Q2/Q3 pack's YTD-only statement does not
  print the prior ordinal's YTD (that figure lives in the PREVIOUS
  quarter's filing; only prior-YEAR comparatives are printed), so YTD
  differencing needs the library's stored prior interim and folds into
  Stage 3's cross-document machinery. OPEN DESIGN QUESTION for Stage 3
  (needs Riley): MIXED-WINDOW METRICS — when income pairs Q columns while
  a YTD-only cash flow pairs H1 columns, cross-statement derived metrics
  (e.g. FCF conversion vs quarterly net income) would silently mix
  windows; decide suppression vs annotation before any derived interim
  metric ships.**
- **Stage 3** — cross-document TTM with the scale/currency gates, PLUS
  (per the Stage-2 scope finding) the cross-document YTD-differencing
  fallback and the mixed-window metric decision.
  **STAGE 3 CORE DONE 2026-07-12 (Riley waived the deploy-first
  sequencing; fetch + extraction spend approved):**
  `modules/sedar_ttm.py` — `build_ttm_from_interim(interim, annual)`
  assembles the four headline flows (revenue, net_income,
  operating_cash_flow, capex) under the three ratified gates; per-field
  chain failures are field-level honest N/A; the YTD component is the
  LARGEST window printed (9M > H1 > Q — at Q2/Q3 the row layer shows the
  discrete quarter but TTM consumes the year-to-date column, pinned);
  same-label ambiguity across flow statements is honest absence. 9 pins
  (tests/test_sedar_ttm.py). **LIVE-VERIFIED on the real shape same
  session:** Sterling located the issuer-hosted TOU Q1-2026 combined
  MD&A+statements PDF (tourmalineoil.com; sha256 8D3F7319…463D, saved
  to ~/.finlens/pdfs/TOU_Q1_2026.pdf); cold extraction mapped 16 fields
  (confidence 0.95, quarter-only "Three Months Ended March 31 2026/2025"
  columns — the CB-040 pairing exercised live); TTM vs the stored FY2025
  fixture: all gates PASS, revenue 4,929,506 · net_income 707,554 ·
  OCF 3,241,335 · capex −2,834,859, composite receipts citing both
  documents.
  **STAGE 3b RATIFIED + BUILT 2026-07-12 (three decisions by Riley):**
  (1) TTM PANEL — a "Trailing Twelve Months (derived)" expander above
  the analysis tabs, rendered ONLY when the loaded analysis is an
  interim AND a same-issuer stored annual passes all three gates
  (find_stored_annual_for_interim: ticker match, else exact company
  name; year == interim − 1; interims never serve as the annual side;
  honest absence otherwise — never a half-panel). Values render in the
  documents' own presentation basis with the permanent
  derived-not-as-filed caption + per-field composite receipts.
  LIVE-VERIFIED against the real 34-entry library: the TOU Q1-2026
  interim finds the stored annual, all gates pass, values identical to
  the Stage-3 verification. (2) MIXED-WINDOW METRICS: **SUPPRESS** —
  per-statement window classes ride in financial_data.period_windows
  (set at the boundary, rebuilt by the heal path); _calc_summary_metrics
  suppresses fcf_conv + fcf_yield to honest "—" when income and
  cash-flow windows BOTH parse and differ, with the reason captioned on
  the Financial Health panel. Partial window info never suppresses;
  paths without period_windows (annual SEDAR / EDGAR / FMP) untouched
  — pinned. (3) Q2/Q3 CROSS-DOCUMENT DIFFERENCING: **DEFERRED to the
  first real Q2-2026 pack (~early Aug 2026)** — no live document exists
  to verify the arithmetic against, and the suppress rule keeps any
  early-loaded Q2 pack honest meanwhile. 9 new pins.
  OPEN NOTE (flagged at build, NOT in tonight's scope): Leverage
  (net-debt / EBITDA) on an interim uses a QUARTERLY EBITDA against
  annual-calibrated RAG thresholds — an instant-vs-flow calibration
  question, distinct from window mixing; needs its own ruling before
  interim Leverage is trusted.
  **GROUND-TRUTH STAMP: PASS (Riley, 2026-07-12 — decision 6 CLOSED):**
  the four TTM input rows transcribed from the source PDF first (both
  columns, transcription protocol), then compared: 8/8 byte-identical
  (Commodity sales from production 1,447,049 / 1,457,567 · Net income
  657,560 / 212,678 · Total cash flow from operating activities
  942,627 / 1,088,311 · Property, plant and equipment (660,162) /
  (813,898)). The in-app flow-verify happened the same night (CC drove
  the full UI run; the TTM panel, interim caption, and receipts were
  observed live — two display-layer findings fixed and pinned, 605cddf
  + 72f58f0). The interim shape is the first hand-anchored quarterly
  filer. Remaining on this spec: the deferred Q2/Q3 differencing
  (~early Aug 2026) and the interim-Leverage calibration ruling.
- Ground truth (decision 6) runs with the first live interim; CB-040
  ships with the Stage 1 (first enforcement) commit.
