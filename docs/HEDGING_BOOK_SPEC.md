# Hedging Book — Notes Extraction Spec

Status: **v1 SHIPPED 2026-07-11** (design session ratified same day; casebook CB-034).
Owner: sedar_extractor.py (extraction) + app.py Economics tab (display) +
modules/integrity (validation) + modules/red_flag_detector (flag).

## Why

The bank coverage-gap research (docs/research/2026-07-10-bank-og-coverage-gaps.md)
ranked the hedge book top-5 analytical value and the ONLY top-5 gap reachable
from documents already in the corpus: the disclosures live in the NOTES of the
statement PDFs FinLens already ingests. The Peyto cold-load drill supplied the
motivating number: $248.7M realized derivative gains = 46% of pre-tax earnings,
previously visible only in analysis prose, never as a structured signal.

## The two disclosure geometries (ground-truthed from real filings)

1. **Period-rows** (Peyto FY2025 Note 13, PDF pp. 24–26): one table per index
   (AECO 7A/5A, NYMEX HH, WTI CAD, Propane Conway), rows are quarters with
   Type / Daily Volume / Average Price columns; collars print put–call ranges;
   FX forwards and interest-rate swaps in their own tables; MTM as prose
   sentences ("would have realized a gain of $123.3 million"); subsequent-event
   contracts in a separate section.
2. **Instrument-rows × year-columns** (TOU FY2025, PDF pp. 64–65): rows are
   instrument types, columns are years (2026–2030), weighted-average volumes
   and prices per year, per-instrument fair values summing to a printed total
   ($223,703K).

Both normalize to flat position records — one record per (instrument, period).

## Pipeline

- `locate_derivative_note_pages(pdf_path)` — content-density predicate
  (derivative vocab ≥ 3 + a volume/price table signal + numerics ≥ 10),
  recall-biased, capped at MAX_HEDGING_NOTE_PAGES=8 with dropped pages
  disclosed. Tuned against Peyto (24–26 exact), TOU (64–65 exact), CNQ
  ("16. FINANCIAL INSTRUMENTS" p. 17). Full-annual-report shapes (ARX) also
  pick up MD&A risk tables — same underlying book, prompt filters the rest.
- `extract_hedging_note(pdf_path)` — own prompt pair (the statement
  SYSTEM_PROMPT forbids notes and MUST NOT be touched); reuses the streaming
  `_call_claude` via keyword params; 16k output budget; JSON-repair retry;
  zero-spend `no_note_detected` return when the locator finds nothing.
- Normalized `hedging_book` schema: `commodity_positions[]`, `fx_positions[]`,
  `interest_rate_positions[]`, `mtm_disclosures[]`, `sensitivities[]`,
  `subsequent_event_positions[]`, `fair_value_total`+`fair_value_scale`,
  `as_of`, `source_pages`, `extraction_confidence`, `figure_presence`.
  Verbatim labels/periods + source_page per record (Trust-Is-Page-Level).
- **Figure-presence guard**: every extracted number must appear (comma-
  normalized) in the note page text; misses render an UNVERIFIED warning on
  the panel — fabrication is surfaced, never silent.

## Trigger + persistence

On-demand "🔒 Extract Hedging Book $" button on the Economics tab
(resource-gated), ~$0.05–0.15 per filing (Riley's ratified trigger: analysis
stays your click). PDF resolved by `_hedging_pdf_path_for_current` (per-filing
cache → canonical campaign PDF via the registry). On success: hedging_book →
financial_data, integrity re-runs (fresh moat record arms the tie rule),
analysis cache persists. `_heal_sedar_mapping` carries hedging_book through a
free re-map (a paid extraction must never be dropped by a heal).

## Validation (the moat)

- `hedging_fair_value_bs_tie` integrity rule (warn, 5% relative tolerance):
  note-side net fair value (unit-parsed; unparseable units → honest skip) vs
  balance-sheet rows explicitly labeled derivative/risk-management. Ambiguous
  BS shapes (TOU's identical duplicate labels) deliberately don't match →
  honest skip. Peyto live: 123,700,000 vs 123,651,000 = 0.04% PASS.
- `realized_derivative_gains` canonical field (CB-034) →
  `derivative_gains_concentration` red-flag: yellow ≥ 25%, red ≥ 50% of
  pretax. Peyto: 46% yellow.
- Future (recorded, not v1): Gemini cross-extraction of the note (same
  pattern as the statement cross-check) once the extraction has field mileage.

## Honest v1 exclusions (named on the panel)

- Hedge coverage % — needs production volumes (MD&A-gated, RESOURCE_ECONOMICS
  Tier 2).
- Hedge-price-vs-strip — needs a futures curve (unvalidated source; would
  require badging per Trust-Is-Page-Level).
- Loss-form realized-derivative labels — need CB-020-style label semantics;
  deferred until a real loss-year filer arrives.
- Embedded derivatives / basis prose (TOU) — captured as verbatim notes only.

## Pins

tests/test_hedging_note_extraction.py (locator real-PDF pins skipif-guarded
for CI + schema/figure-presence pure pins), tests/test_cb034_hedging_rules.py
(flag + tie), TOU fixture pins (realized_derivative_gains, count 14).
