# Per-Filer Facts Store — Spec (DESIGN RATIFIED 2026-07-13)

**Status:** design ratified by Riley 2026-07-13 (twenty-eighth session,
evening — four decisions, recorded verbatim below). **Build deliberately
deferred to a fresh session** (the CB-042 precedent: bank the design at
ratification, never build the deep layer at marathon-end).

**What this is:** the FinLens library treated explicitly as "Canada's
companyfacts under construction" — a per-filer archive of every analyzed
filing's mapped values, keyed by (canonical field, window, source
document, filed date). It is the corpus flywheel's data model stated
precisely and the moat-thinking longitudinal layer made concrete
(SESSION_HANDOFF.md "Moat thinking"). Once it exists, Q2/Q3 YTD
differencing, restatement detection, TTM-anything, and every longitudinal
feature become MECHANICAL queries instead of per-feature plumbing.

**Strategic corollary (recorded at the queue item, 2026-07-12):** the SEC
company-facts work proved structured data still needs the judgment layer
(the NVDA phantom came FROM perfect mandated XBRL; CB-038/039 are casebook
rulings ABOUT structured data) — a CSA-mandates-XBRL "regulatory clock" is
a tailwind for this store, not a threat.

## Ratified decisions (Riley, 2026-07-13)

1. **Data model: append-only JSONL.** One record per (ticker, field,
   window, source document). Reads resolve LATEST-FILED-WINS per (ticker,
   field, window); the superseded record is never deleted — restatement
   history is preserved BY CONSTRUCTION, so restatement detection becomes
   a query, not a feature (the divergence-database moat candidate falls
   out of the data model). Same idiom as the integrity log:
   human-inspectable, append-only, JSONL.
2. **Writer boundary + classification.** Facts append at ANALYSIS-SAVE
   time (the same boundary where library entries are written — one
   writer); a backfill script regenerates the store from the 19 CI-locked
   corpus fixtures. The store is REBUILDABLE cache-class data — the
   integrity log remains the precious moat record. Sterling never writes
   it (the standing moat boundary); tests stay isolated via
   FINLENS_DATA_DIR (already machine-enforced by conftest).
3. **v1 scope: archive + read API only.** `get_facts()` (resolved,
   latest-filed-wins) and `fact_history()` (raw appends, restatements
   visible). sedar_ttm stays UNTOUCHED in v1 (shipped + pinned at CB-044
   — the empirical-evidence rule); consumers CONVERGE onto the store in
   the August arc. v1 adds no second computation path, so there is zero
   dual-source-of-truth risk.
4. **Sequencing: spec now, build fresh.** This document is the banked
   design; stages below are queued for a fresh session.

## Record schema (v1)

```json
{
  "record_type": "fact",
  "schema_version": 1,
  "ticker": "TOU",
  "company_name": "TOURMALINE OIL CORP.",
  "field": "revenue",
  "value": 4940024,
  "currency": "CAD",
  "scale": "thousands",
  "window": {"class": "FY", "year": 2025, "label": "2025"},
  "statement": "income_statement",
  "source_label": "Commodity sales from production",
  "derived": false,
  "semantics": null,
  "source_doc": {
    "kind": "sedar_pdf",
    "sha256": "<when available>",
    "file_name": "TOU_FY2025.pdf",
    "filing_date": "2026-03-04"
  },
  "mapper_version": 8,
  "recorded_at": "<ISO-8601>"
}
```

Notes:
- `window` comes from `parse_period_window` on the column key (CB-039/040
  discipline: labels' own text, never fp) — FY / Q / H1 / 9M + year.
  BOTH the current and prior columns of an analyzed statement yield facts
  (a filing attests two periods).
- `derived` + `semantics` ride from mapping.mapped verbatim (CB-014:
  derived facts are marked, never laundered; CB-026: includes_impairment
  travels with the value).
- `scale`/`currency` stored as-presented (the CB-040 gates live in
  consumers; the store never rescales or converts).
- Resolution key: (ticker, field, window.class, window.year). Collision →
  latest `source_doc.filing_date` wins (ties: latest `recorded_at`).
  `fact_history()` returns every record for the key, oldest first.
- Idempotency: appending an identical (ticker, field, window, value,
  source_doc.sha256|file_name, mapper_version) record is a no-op —
  re-analysing the same PDF never duplicates.

## Location

`~/.finlens/facts_store.jsonl` (via FINLENS_DATA_DIR — the persistent-
storage principle: outside temp, outside cloud sync). Module:
`modules/facts_store.py`.

## Stages (queued for a fresh session)

- **Stage 0 — module + pins:** `modules/facts_store.py` with
  `append_facts(extraction, source_doc_meta)` (mapping.mapped +
  statement columns → fact records), `get_facts(ticker, field=None,
  window_class=None)`, `fact_history(ticker, field, window)`, the
  idempotency rule, and pins (latest-filed-wins, history preservation,
  no-op duplicates, derived/semantics ride-through).
- **Stage 1 — the writer:** wire `append_facts` at the analysis-save
  boundary (library-entry write site in app.py) + the backfill script
  (`scripts/backfill_facts_store.py`) over the corpus fixtures via the
  registry. Evidence gate: show the JSONL lines + a fact_history query
  demonstrating latest-filed-wins on the TOU FY2025 + Q1-2026 pair.
- **Stage 2 (August arc) — convergence:** Q2/Q3 cross-document
  differencing BUILT ON the store against real Q2 packs; sedar_ttm reads
  the store; TTM-FCF valuation base (removes the CB-041 DCF warning);
  the restatement-detection rule (prior-column continuity's mechanical
  successor) as an integrity-engine consumer.

## Anti-goals (v1)

- No FX conversion, no rescaling, no derived-metric computation in the
  store — consumers own semantics; the store owns provenance.
- No Supabase/sync in v1 (local-first; the commercial multi-tenant story
  is post-gate).
- Never a second computation path beside sedar_ttm in v1 (decision 3).
