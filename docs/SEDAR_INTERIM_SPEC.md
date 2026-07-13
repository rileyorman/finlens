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
  for the derived branch.
- **Stage 3** — cross-document TTM with the scale/currency gates.
- Ground truth (decision 6) runs with the first live interim; CB-040
  ships with the Stage 1 (first enforcement) commit.
