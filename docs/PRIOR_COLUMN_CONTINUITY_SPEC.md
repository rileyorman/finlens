# Prior-Column Continuity Checker — Build Spec (v1)

**Status:** RATIFIED by Riley 2026-07-05 (all five design decisions).
**Builder:** Sterling (sandbox branch). **Reviewer/committer:** CC.
**Queue ref:** SESSION_HANDOFF.md "PRIOR-COLUMN CONTINUITY RULE" +
"per-figure presence annotation" fold-in (both from the 2026-07-05 NVDA
capex investigation).

## What this catches

Filing N's comparative (prior-year) column must tie to filing N−1's as-filed
current-year figures. A number that contradicts the previous filing is a
restatement (analytical signal) or an error (extraction defect) — either way
a human should look. Concrete motivating case: the 2026-07-03 fabricated
NVDA extraction presented real-FY2024 values as its comparative column; a
stored FY2025 filing would have exposed the mismatch instantly and
deterministically, with zero API cost.

HONEST SCOPE NOTE: the current corpus holds few consecutive-year pairs, so
this rule fires rarely TODAY. It is a forward-looking guard — every new
fiscal year of an already-analyzed filer arms it. Same-year duplicate-copy
divergence (e.g. the two NVDA FY2026 caches disagreeing on capex) is a
DIFFERENT check — noted as a future extension, OUT of v1 scope.

## Ratified decisions (do not relitigate in the build)

1. Standalone checker module + its own integrity-log record type
   (`prior_column_continuity`), NOT a rules.py rule inside validate_filing.
   Four-state model: VERIFIED / PARTIAL / FLAGGED / UNCHECKED. Never blocks.
2. v1 fields: `revenue`, `net_income`, `total_assets`,
   `operating_cash_flow`, `capex`. Full-statement comparison is a later
   version.
3. Mismatch = FLAG for human triage, never a block. Tolerance 0.5%
   relative. Dispositions via append-only records, mirroring the
   cross-extractor triage pattern (`restatement` / `extraction_error` /
   `checker_error` / `other`).
4. No prior filing on disk = honest UNCHECKED with reason, never a silent
   pass.
5. Per-figure presence annotation ships in the same session (Part B below),
   because both exist to catch the single-wrong-line case the aggregate
   figure-presence ratio cannot see.

## Part A — modules/integrity/prior_column.py

### Inputs and prior-filing lookup

- Entry point: `check_prior_column(payload: dict, analysis_dir: Path | None,
  log_path: Path | None) -> dict` — `payload` is a loaded analysis-cache
  JSON (the shape written to `~/.finlens/analysis/`). Both paths default to
  production locations but MUST be parameterizable (tests use tmp_path;
  Sterling never touches a real log — see Testing).
- Locate filing N−1 by CONTENTS, not filename: scan `analysis_dir/*.json`
  for payloads where ticker matches AND
  `financial_data.fiscal_year == current payload's
  financial_data.fiscal_year_prior`. Filenames are not a reliable key
  (period-label drift is a known defect class — see MIXED-PERIOD item in
  the handoff).
- Multiple candidates for N−1 → prefer the most recent `timestamp`; record
  the chosen file's basename in the output record.
- No candidate → state UNCHECKED, reason `no_prior_filing`.
- Currency gate (mirrors cross_validate v2): both payloads'
  `financial_data.currency` must be present and equal, else UNCHECKED with
  reason `currency_mismatch` / `currency_unknown`. NO FX conversion, ever.

### Field resolution (reuse, don't re-mint)

For each v1 field, resolve a value from a payload's financial_data by:
1. `mapping.mapped[<canonical>].value` when present (SEDAR analyses), else
2. a small explicit alias list over statement `line_item` labels. Reuse or
   mirror the alias sets already used by the four-headline cross-check
   (cross_validate.py) and excel_exporter's summary metrics — do NOT invent
   new label semantics. capex aliases: "Capital Expenditures" plus the
   as-filed variants already present in caches; document the final alias
   list in the module.

Comparison per field: filing N's `value_prior` (comparative column) vs
filing N−1's `value` (its current year).

### Per-field status and filing-level state

- MATCH: both values present, relative diff = |a−b| / max(|a|,|b|) ≤ 0.005.
- CONFLICT: both present, diff beyond tolerance. Record both values +
  pct_diff.
- FIELD_MISSING: either side lacks the field (None or unresolvable).
  Structural, not an error.
- Filing-level state: FLAGGED if ≥1 CONFLICT; VERIFIED if ≥1 comparison
  ran and all MATCH; PARTIAL if no CONFLICT but some fields FIELD_MISSING
  (and ≥1 MATCH); UNCHECKED per the lookup/currency gates above (also for
  unreadable/corrupt candidate files — fail closed, reason `reader_error`).

### Integrity-log record (append-only)

record_type `prior_column_continuity`, checker_version 1, plus: timestamp
(UTC ISO), ticker, fiscal_year (N), prior_fiscal_year, prior_source_file
(basename only), both payloads' schema_version and currency, state, reason
(UNCHECKED only), and per-field entries {canonical_field, value_prior_n,
value_prior_filing, pct_diff, status}. Append via a new helper in
modules/integrity/log.py following the existing append helpers exactly
(utf-8, one JSON line, no BOM). Dispositions: new record_type
`prior_column_disposition` keyed by (ticker, fiscal_year, canonical_field,
checker_version) — same append-only pattern as cross_extractor_disposition;
extend scripts/write_cross_disposition.py OR add a sibling script, builder's
choice, but the /integrity-log renderer must show open vs dispositioned.

### Reader/renderer (definition of done includes the reader)

Add a section to modules/integrity/analyze.py (after the Gemini section):
counts by state, per-CONFLICT detail lines (both values, pct_diff, triage
status via dispositions). Follow the existing section style, pure ASCII.
Lesson on record (eighth session): a ratified record type without reader
coverage is an incomplete build.

### Runner

scripts/run_prior_column.py — scans the analysis dir, runs the check for
every payload, prints a summary table, appends records. `--dry-run` prints
WITHOUT writing (default OFF; the first live write-run happens on Riley's
machine via CC with /integrity-log evidence — not in the sandbox).

## Part B — per-figure presence annotation (separate branch)

modules/claude_analyzer.py:
- `_figure_presence` additionally returns per-row detail: for each checked
  row {section, line_item, found}. Aggregate checked/found/ratio and the
  FABRICATED verdict logic are UNCHANGED.
- The integrity-log record gains `missing_rows`: list of "section:line_item"
  for rows not found, capped at 20 entries (log-size discipline; record the
  total missing count separately as `missing_count`).
- financial_data["figure_presence"] carries the same per-row detail so a
  future UI chip can name the suspect lines (UI wiring is CC-side app.py
  work, OUT of this build).
- Extend tests/test_extraction_guard.py: per-row correctness, missing_rows
  cap, aggregate behavior unchanged.

## Testing (both parts)

- All I/O parameterized; tests run fully offline against tmp_path dirs and
  logs. NEVER the real ~/.finlens.
- Part A minimum cases: consecutive-year MATCH (VERIFIED); capex-style
  CONFLICT (FLAGGED, pct_diff correct); missing field (PARTIAL); no prior
  filing (UNCHECKED/no_prior_filing); currency mismatch (UNCHECKED, no FX);
  corrupt prior JSON (UNCHECKED/reader_error, fail-closed); multiple
  candidates → newest timestamp wins; disposition round-trip (write, then
  reader shows DISPOSITIONED).
- Fabrication regression case: synthetic pair modeled on the real incident —
  N payload with value_prior = real-FY2024-style numbers vs an N−1 payload
  holding the true prior year → FLAGGED.
- Full suite green + ruff clean, per standing rules.

## Delivery

Two branches in the sandbox: `feat/prior-column-continuity` (Part A) and
`feat/figure-presence-rows` (Part B). Per-branch report: files changed,
test summary, ruff, 3–5 sentence summary. CC reviews, runs /detection-test
+ the integrity-log evidence gate on the live first run, commits to
canonical, and regenerates nothing (no fixture/mapped_count changes are
expected from this build — if any test forces one, STOP and flag).
