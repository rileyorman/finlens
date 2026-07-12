# Quick Financials → EDGAR Company-Facts — Spec

Status: **DESIGN RATIFIED 2026-07-12** (four decisions ratified by Riley,
§Ratified decisions; direction pre-ratified 2026-07-10 from the FMP audit).
Owner (planned): modules/edgar_fetcher.py (builder + shared tag table) +
app.py Quick Analysis tab (wiring + receipts display).

## Why

FMP is an unreliable witness generally (CLAUDE.md Cross-Check Source
principle; the JPM +100.9B phantom operating_cash_flow vs the as-filed
(147,782) is the proof case). The 2026-07-10 FMP audit ratified the
direction: retire FMP from every load-bearing number path; US tickers get
as-filed XBRL from the free SEC company-facts API; FMP keeps ONLY data with
no filed source (earnings estimates/calendar), permanently badged.

EMPIRICAL GROUNDING (live probe, 2026-07-12): companyfacts/CIK0001045810
(NVDA) — 4.0MB, entity + dei/us-gaap taxonomies confirmed; latest annual
revenue fact {end 2026-01-25, val 215,938,000,000, accn
0001045810-26-000021, form 10-K, filed 2026-02-25}; same-period duplicate
facts everywhere (comparative re-reports → latest-`filed` selection is
restatement-aware BY CONSTRUCTION); and THE TRAP REPRODUCED FROM THE
PRIMARY SOURCE: NVDA's `PaymentsToAcquirePropertyPlantAndEquipment` facts
END IN 2012 ($138.7M) while `PaymentsToAcquireProductiveAssets` carries
today's $6.042B — tag presence ≠ tag currency.

## Ratified decisions (Riley, 2026-07-12)

1. **ANNUAL OPTIONS FIRST**: Latest Annual / Last 2 Years / Last 4 Years
   move to as-filed EDGAR (they ride the existing pinned annual machinery).
   Latest Quarter + TTM stay on FMP (badged) until a Phase-2 quarterly
   design — TTM needs Q4 = FY − 3 quarters derivation (no Q4 10-Q exists),
   its own correctness risk zone.
2. **RAW DOLLARS**: the builder emits raw dollars, `scale = 1`,
   `_normalized = True` — the codebase-wide convention (normalize-at-the-
   boundary). FMP's pre-scaled-millions convention is aggregator-era debt
   that stops here; the preview formats scale=1 correctly.
3. **PER-FIGURE RECEIPTS**: every value carries its XBRL tag + accession +
   form + period end (e.g. "us-gaap:Revenues · 10-K 0001045810-26-000021 ·
   FY ended 2026-01-25"), rendered in the preview — corpus-grade
   provenance; the full inversion of the FMP badge.
4. **HONEST N/A**: a missing/unmatched tag leaves the field honestly
   absent (CB-021 discipline — derived fields require ALL components).
   FMP is never consulted for a load-bearing number again.

## THE CRITICAL SELECTION RULE (the reason this was design-gated)

The existing `_annual_facts` semantics — first concept in the list with ANY
annual facts wins — is safe on the EDGAR-filing path ONLY because accession
pinning skips concepts that lack the chosen filing's facts (the 2026-07-06
NVDA fix). The quick path has NO accession. First-concept-with-facts would
select NVDA's stale PP&E tag and serve the 2012 $138.7M as current capex —
the phantom, reborn.

**RULE: concept candidates COMPETE ON RECENCY.** For each canonical field:
per concept, select its latest annual fact (max (end, filed), duration
≥300 days for flows — the PLD filter); then the CONCEPT whose latest fact
has the most recent `end` wins the field (ties → earlier in the declared
list). A concept the filer stopped feeding loses automatically, forever,
for every filer. Pinned with the real NVDA shape.

Restatements: within a concept, facts sharing the same `end` resolve to the
latest `filed` (the probe shows 2–5 duplicates per period from comparative
re-reports) — as-filed-and-as-restated by construction.

## Builder (planned): `build_financial_data_from_edgar_facts(ticker, limit=1)`

- CIK via the existing `get_cik` (three-tier); companyfacts via the
  existing `_SESSION`/`HEADERS` (declared User-Agent); small in-process
  cache keyed by CIK (the payload is ~MBs — one fetch serves all periods).
- ONE SHARED TAG TABLE: extract the inline concept lists from
  `get_financial_data` to a module-level table both paths consume (the
  NVDA-hardened capex chain must never fork). The existing path's
  accession-pinned semantics are UNCHANGED (its pins prove it).
- Output: the EXACT FMP-builder key set (drop-in for the preview/analyze/
  library consumers) with: raw dollars, `scale=1`, `_normalized=True`,
  `source="edgar"` (flips ALL existing badging to the trusted branch
  automatically), `period_history` from the top-`limit` distinct annual
  `end`s, and `receipts` — a structured dict per emitted field/row:
  {tag, accession, form, end, filed}.
- Honest gaps expected and accepted: `ebitda` (not an XBRL concept —
  absent, never derived here), `gross_profit` (GrossProfit tag where
  filed; else derived revenue − cost only when BOTH present, marked
  derived), `total_debt` (long-term + current-portion tag family with the
  composition in the receipt; neither → None).

## App wiring (planned)

- Quick Analysis tab: the three ANNUAL period options route US tickers to
  the new builder; Quarter/TTM keep FMP + the unvalidated caption.
  Canadian tickers stay blocked (SEDAR is their path).
- Preview: caption becomes the as-filed receipt line ("As filed with the
  SEC — us-gaap XBRL company facts; per-figure receipts below") + a
  receipts expander (tag · accession · form · period per figure).
- Library auto-save: `source="edgar"`, entry id prefix `edgar_facts_`;
  the sidebar tag renders "· EDGAR" and the dashboard FMP warning no
  longer fires — by the existing keying, zero new badge code.
- FMP's remaining surface after this ships: Quarter/TTM quick options
  (Phase 2 retires), Stock Tracker snapshot cards (Phase 3 candidate),
  earnings calendar/estimates (permanent, no filed source, badged).

## Stages

- **Stage 1** — shared tag table extraction (zero-behavior-change refactor,
  existing pins green) + the recency-competition selector + the builder +
  pins (NVDA phantom-capex shape from the live probe; restatement
  latest-filed; PLD duration filter reuse; honest-N/A negatives).
  **DONE 2026-07-12 (f404f8a), live-verified.**
- **Stage 2** — app wiring (period routing, receipts display, library
  save) + live verification. **DONE 2026-07-12 (fb3fbee),
  flow-confirmed.**
- **Phase 3 (candidate)** — Stock Tracker snapshot cards.

Casebook entry (CB-038) shipped with the Stage 1 commit.

---

# PHASE 2 — Quarterly + TTM (DESIGN RATIFIED 2026-07-12, same session)

## Empirical grounding (NVDA 10-Q probe, 2026-07-12)

- Revenue is dual-tagged in Q2/Q3 10-Qs: discrete ~90-day facts AND
  year-to-date facts (181d for H1, 272d for 9M).
- **Operating cash flow is YTD-ONLY** — no discrete quarterly OCF facts
  exist (10-Q cash-flow statements are presented year-to-date). This
  EVIDENCE-FORCES the TTM construction: sum-of-4-discrete-quarters is
  impossible for cash-flow items from raw facts.
- **The `fp` field LIES**: the 181-day H1 fact carries fp="Q2". Period
  identity comes from date arithmetic ONLY.
- Prior-quarter facts are re-reported in later filings (Q1-2026's 10-Q
  re-reports Q1-2025) — the latest-`filed` dedupe handles restatements
  here exactly as on the annual path.

## Ratified decisions (Riley, 2026-07-12 night)

1. **YTD DIFFERENCING** for discrete flow quarters: Q1 = YTD₁;
   Qₙ = YTDₙ − YTDₙ₋₁; Q4 = FY − YTD_Q3. Every derived value carries a
   COMPOSITE receipt naming its component facts (accessions + windows).
   Balance items use the latest instant directly.
2. **STRICT DATE-CHAIN GATE** on every derived value; any violation →
   the field is honest-N/A. The fp label is never trusted.
3. **AMENDMENTS INCLUDED**: the quarterly path selects from
   {10-Q, 10-Q/A} (+ {10-K, 10-K/A} for FY components) — an amendment is
   the MOST corrected statement of a period; latest-`filed` prefers it
   naturally. The annual path's v1 filter (10-K only) is untouched until
   its own review.

## TTM construction (the only viable method — see grounding)

TTM_flow = FY + YTD_current − YTD_prior, where:
- FY = the latest annual fact (the existing recency-competition selection).
- YTD_current = the latest post-FY year-to-date fact
  (start == FY.end + 1 day — the chain rule).
- YTD_prior = the same-ordinal YTD window one year earlier
  (start == FY.start; duration within ±7 days of YTD_current's).
- No post-FY 10-Q yet → TTM degenerates to FY exactly (correct, and
  receipted as such).
- Balance/instant items: the latest quarterly instant (no summing).
- Ratios recomputed from TTM components; receipts composite
  ("TTM = FY2026 [accn] + YTD 2026-01-26→2026-04-26 [accn] − YTD
  2025-01-27→2025-04-27 [accn]").

## Duration classification (date-window taxonomy, day counts only)

discrete quarter 60–120d · H1 150–210d · 9M 240–300d · FY ≥300d (the
existing _is_annual_duration threshold). Facts outside every window are
unusable for derivation (honest exclusion).

## Strict chain rules (operational form)

- YTD_current.start must equal FY.end + 1 day.
- YTD_prior.start must equal FY.start, and its day-count must be within
  ±7 days of YTD_current's (same ordinal without trusting fp).
- Quarter differencing: YTDₙ and YTDₙ₋₁ must share a start date and
  differ by 60–120 days; Q4 = FY − YTD_Q3 requires YTD_Q3.start ==
  FY.start and FY.end − YTD_Q3.end between 60–120 days.
- Every rule failure → that field honest-N/A with no receipt (the CB-038
  corollary: receipts cite only what was actually emitted).

## Stages (Phase 2)

- **Stage 1** — quarterly selectors (recency competition over
  {10-Q,10-Q/A} facts; duration taxonomy; chain validators) + the TTM
  and discrete-quarter assemblers + pins (probe-shaped synthetic
  fixtures: the fp-lie case, YTD-only OCF, chain-violation negatives,
  degenerate-TTM-equals-FY, restatement dedupe).
- **Stage 2** — wire the Latest Quarter + TTM Quick options to the
  builders; FMP retires from the Quick tab entirely (its remaining
  surface: Stock Tracker cards + earnings calendar, per CB-038);
  captions + composite receipts; live verification (NVDA mid-year shape).
- Casebook entry (CB-039) ships with the first enforcement commit.
