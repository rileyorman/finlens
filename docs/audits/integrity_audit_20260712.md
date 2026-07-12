# FinLens Data Integrity Engine — Audit 2026-07-12

**VERDICT: PASS** — no poisoned fixture passed silently; no baseline regressed;
full suite green; lint clean; hooks active. Last week's required follow-up
(schema bump) confirmed resolved; last week's #1 observability recommendation
(persist usage telemetry) confirmed IMPLEMENTED — Step 4 has real data for the
first time.

- Run by: CC (Sunday audit Step 1), Fable 5
- Machine: local dev (venv Python 3.14; CI is authoritative at 3.11)
- Full suite: **628 passed in 53.44s** (live run, no secrets needed)
- Lint: **All checks passed!** (`ruff check .`, live run)
- Hooks: `core.hooksPath = .githooks` ✓ active; ruff 0.15.20 installed ✓

---

## Operational sub-checks

### Hook portability
- `git config core.hooksPath` → `.githooks` ✓; ruff 0.15.20 ✓. No action.

### Schema & cache health — CLEAN
- `CURRENT_SCHEMA_VERSION = 7` (bumped 2026-07-07 per last week's follow-up,
  Riley signed off — comment cites the CB-021→024 whitelist additions).
- This week's data-shape changes reviewed against the bump rule: the new
  top-level keys `mda_metrics` (MDA_FETCHER_SPEC stages 0–3) and the
  Stage-2 heal-carry are ADDITIVE OPTIONAL keys with absent-key-safe readers,
  deliberately OUTSIDE the `normalize_financial_data` scaling whitelist
  (their values carry their own printed `unit_scale`, parsed at the consumer —
  the Stage-3 tie rule). Same precedent as `hedging_book` (CB-034, no bump).
  **No bump required; reasoning recorded here.**

### Test suite (live)
- `pytest tests/ -v`: **628 passed, 0 failed** (628 collected).
- Detection suite `test_integrity_detection.py`: **18/18 passed** (separate
  live run) — poisoned-fixture battery, identity rules (pass + flag +
  honest-skip), layer-period agreement (CB-016), document-class (CB-015).

### Lint (live)
- `ruff check .` → **All checks passed!**

---

## PART 1 — Detection test (poisoned fixtures)
**PASS — no silent passes.** The scripted battery
(`tests/test_integrity_detection.py::test_poisoned_fixtures_are_caught`) ran
live: all 18 detection assertions fired as expected. Two NEW rules entered the
engine this week (MDA_FETCHER_SPEC Stage 3, commit 753e421) with their own
pins: `mda_netback_internal_tie` (components-sum-to-printed-total; the
wrong-column-misalignment negative is pinned) and `mda_ffo_anchor_tie`
(MD&A CFO anchor vs canonical operating_cash_flow; quarterly-anchor and
unparseable-scale honest-skip negatives pinned) —
`tests/test_mda_integrity_rules.py`, 10 pins.

## PART 2 — Log-learning review
**Real volume for the first time: 234 moat-log records** (52 validations — 28
since 2026-07-05 — plus 57 prior-column-continuity, 49 cross-extractor, 33
FMP cross-validation, 28 figure-presence, 15 dispositions).

Rule behavior (run / warned across all 52 validations):
- `revenue_growth_sanity`: 35 run, **4 warned** — the only sanity rule with
  real warn volume. Observed range −73.5% → **+290.2%**: legitimate
  resource-cycle growth is INSIDE the warn band and the max observation sits
  just under the +300% threshold. This is working-as-intended (warn, not
  block) but the threshold is now evidence-calibrated: commodity filers WILL
  warn in price-recovery years. No change recommended — the warn is
  informative, not noisy (4/35 = 11%).
- `sedar_balance_sheet_identity`: 13 run, **2 warned** — both are the Peyto
  CB-033 wrong-scope capture (the rule catching a real extraction defect by
  exactly the missing 365,910). The moat's marquee save this cycle.
- Never-warned with meaningful volume (healthy, not untested — each has a
  pinned flag-path test): `gross_margin_range` (13 run; observed 40.0%–71.6%,
  comfortably inside bounds), `net_margin_ceiling` (30 run; −28.4%–55.6%),
  `sedar_total_assets_identity` (22 run), `sedar_layer_period_agreement`
  (13 run), `sedar_extraction_confidence` (27 run).
- New rules: `mda_netback_internal_tie` + `mda_ffo_anchor_tie` (2 runs each,
  0 warned — TOU + ARX, both byte-exact anchors); `hedging_fair_value_bs_tie`
  (1 run 0 warned + 2 honest skips — Peyto tie 0.04%).
- No rule shows the "never fired AND untested" smell; every warn path has a
  pinned test.

**Tuning recommendation (evidence-tied):** none required this cycle. Watch
`revenue_growth_sanity` — if 2nd-year commodity-recovery filings push more
legitimate observations past 3.0, consider a resource-sector-aware band
(decision for a casebook entry, not a quiet threshold move).

## PART 3 — Cross-validation review
- **Gemini cross-extractor** (49 records): latest per-ticker states — 6
  VERIFIED (ARX, CNQ, CSU, NFG, REI.UN, TECK.B), 3 FLAGGED-soft (ATD, CNR,
  TOU — all previously dispositioned: label-scope/checker-error classes, on
  record), 7 UNCHECKED. **The standing verdicts predate this week's new
  line-item-backed fields** (CB-031/032 revenue+bottom-line+capex+D&A,
  CB-034 realized_derivative_gains, CB-035 interest_expense) — the queued
  next cross-extractor run is the action (open-queue item 3).
- **FMP cross-validation** (33 records): advisory-only posture holds
  (CLAUDE.md: FMP is an unreliable witness generally; never adjudicates
  alone). No new systematic divergence to surface.
- NEW this week, same family: the `mda_ffo_anchor_tie` receipt chain is an
  intra-filing cross-check that agreed byte-exact on both armed filers (TOU
  3,387,019,000; ARX 3,093,500,000) — an independent MD&A-side witness for
  operating_cash_flow at zero marginal cost.

## PART 4 — Coverage gaps
Sector corpus (17 SEDAR fixtures, by mapper profile):
- **resource_sector: 3** (CNQ, TOU, ARX) — last week's thin-coverage gap
  CLOSED (was 1); plus PEY.TO analyzed live via the cold-load drill (not yet
  a fixture — promotion candidate when ratified).
- **reit_sector: 3** (REI.UN, CAR.UN, DIR.UN); **insurance_sector: 2**
  (IFC, SLF); **mining_sector: 2** (AEM, TECK.B);
  **mining_exploration_sector: 2** (NFG, SIG); **default: 4** (CSU, CNR,
  SHOP, ATD).
- **financial_sector: 1 (RY) — still the thinnest profile.** A 2nd bank
  remains the top deliberate fetch target (carried from 2026-07-09; the
  banking coverage-gap research report now maps exactly what a 2nd bank
  would exercise).
- NEW STRUCTURAL GAP (from the O&G value-chain research): midstream +
  downstream O&G have ZERO coverage and need their own sector profiles — a
  pipeline filer today mis-routes to the upstream peer set (queued).

## PART 5 — Regression confirmation
**No regression.** The full 628-test suite (live) includes every pinned
identity/mapping ruling backing the corpus (CB-013 identity set, CB-016
layer-period, CB-017/020 loss handling, CB-025/026 suppression + semantics,
CB-029→032 alias packs, CB-034 hedging, CB-035 finance-expenses, MDA Stage-3
ties) — all green. Baseline EDGAR filers (MSFT, NVDA) validated in the moat
log this cycle with clean statuses; no per-rule drift against the 2026-07-09
report.

---

## Step 7 — Sector Profile Review (data-layer health)
Qualifying profiles (n≥2): resource (3), reit (3), default (4), insurance
(2), mining (2), mining_exploration (2). financial (1) has no teeth.

(a) **High-frequency unmapped labels — one candidate now PASSES the utility
gate:** `cash and cash equivalents` is unmapped in **9 filers across 4
profiles** (4/4 default, 3/3 REIT, 2/3 resource, plus explorer variants) and
this week acquired CONCRETE analytical consumers: the Leverage (net debt)
and Liquidity dashes Riley hit live on Peyto and TOU. Together with
`total current assets` / `total current liabilities` (3/4 default, 2/3 REIT,
3/3 resource, 2/2 explorer) these are exactly the utility-gated
balance-sheet candidates already queued (current ratio, net debt) — the scan
now supplies the corpus-wide frequency evidence. Recommendation: run the
governed promotion (casebook definition → aliases → registry regen → full
suite) alongside the queued STRUCTURAL-SUBTOTAL CLASSIFIER design session
(unlabeled-subtotal filers like Peyto need the arithmetic inference to reach
these labels at all). Top deferred candidates unchanged otherwise: REIT
`investment properties` (3/3), insurance `debt securities` (2/2).

(b) Common-not-universal: `equity_accounted_income` +
`fair_value_adjustments_financial_instruments` (REIT, 2/3) unchanged —
still awaiting a 4th REIT.

(c) New label variants: **CB-035 "finance expenses"** (TOU) promoted this
week into the accepted interest_expense finance-rollup family — found via
the dashboard-review loop rather than this scan (the scan sees only
fixtures' unmapped[]; the dashboard loop sees the CONSEQUENCE — five N/A
dashes — which is why both loops matter).

(d) Cross-sector leakage: none found. `total revenue` unmapped on ARX+TOU is
the CB-025 suppression working BY DESIGN (net-of-royalties rollups);
`exploration and evaluation assets` 3/3 resource is the CB-009 STOCK
deliberately unmapped (flow maps, stock doesn't).

---

## Prioritized tuning actions
1. **[coverage, carried + sharpened]** Fetch a 2nd bank (financial_sector
   n=1 is the last single-filer profile). The banking research report
   (docs/research/2026-07-11) names the cheap-win note surfaces it would
   exercise.
2. **[promotion, NEW evidence]** Cash + current-asset/liability subtotals now
   pass the utility gate (9-filer frequency + live Leverage/Liquidity
   consumers) — promote via the governed process, coordinated with the
   structural-subtotal classifier design session.
3. **[verification, carried]** Run the cross-extractor over the corpus — the
   standing Gemini verdicts predate ~8 new line-item-backed fields
   (CB-031/032/034/035).
4. **[observability, small]** The targeted extractors (hedging, MD&A) do not
   write usage-log records — extend `log_cache_usage` persistence to
   sedar_extractor's `_call_claude` so Step 4 sees their spend.

---

# Weekly Summary — Sunday Audit 2026-07-12

**Step 1 — Integrity engine: PASS.** Detection battery 18/18 (live), full
suite **628/628 passed** (live), lint **clean** (live), hooks **active**.
Schema version **7** — consistent with the week's changes (mda_metrics /
hedging_book are additive optional keys outside the scaling whitelist; no
bump required, reasoning recorded above).

**Step 2 — Memory cross-check:** Synced 7 CODEX_MEMORY.md items + 1
STERLING_BRIEF.md re-sync + 1 session-memory fix.
- CODEX_MEMORY.md (+91/−6): (1) Trust-Is-Page-Level principle added (was
  absent); (2) CB-036 non-GAAP receipt-and-caption principle added (new this
  week); (3) CB-025 `suppressed_default_aliases` machine-enforcement added;
  (4) canonical-field header extended CB-024→CB-026 incl. the debt PAIR RULE
  + CB-026 `includes_impairment` D&A; (5) cross-extractor v4 (CB-014
  DERIVED status) added to the v3 paragraph; (6) SOPS secrets migration
  added to Shell And Commands (CODEX's old guidance would have launched the
  app with no keys); (7) Change Propagation Rule digest added (pre-existing
  gap found by the full diff).
- STERLING_BRIEF.md: stale-stamp FLAG fixed — two manifest-listed headings
  changed after the 2026-07-09 stamp; brief item 9 re-synced (rollup-alias
  suppression, debt pair, combined-DD&A semantics); stamp → 2026-07-12 @
  dev aeab820. Observation for Riley: the two new CLAUDE.md principles
  (Trust-Is-Page-Level, CB-036) are in neither the brief's iron rules nor
  its manifest — consider adding items (Sterling builds display surfaces
  where both apply).
- Session memory: `mini-no-ssh-key.md` STATUS line was stale (predated the
  gateway HTTP channel) — updated same session; the no-SSH-key rule itself
  unchanged. All other entries consistent.

**Step 3 — Release radar:** **Nothing requires action before next deploy.**
- Anthropic: two minor in-window entries (Jul 8 Console API-key expiration
  support — existing keys unaffected, optional hygiene; Jul 10 docs-only
  CMEK expansion). No model/API/caching/pricing changes; string `"1h"` TTL
  remains the documented form; sonnet-5 intro pricing through 2026-08-31
  unchanged. anthropic SDK: latest remains 0.116.0 (pre-window).
- Streamlit: nothing newer than 1.59.1. Date correction for the audit log:
  1.59.0 published 2026-07-06 and 1.59.1 2026-07-08 (INSIDE this window;
  already vetted clean — its removals touch nothing in FinLens). The
  docs.streamlit.io changelog page is stale; GitHub releases authoritative.
- FMP: no changes (latest changelog entry Jun 05). EDGAR: no changes (rate
  policy unchanged). SEDAR+: scheduled full-day maintenance outage Sat
  Jul 11 ET — window passed; any Jul 11 fetch failures in logs are the
  outage, re-run don't debug.
- Dependencies: plotly 6.9.0 + google-genai 2.11.0 released Jul 9 — FinLens
  unaffected (venv pre-versions fine; cross_extractor.py uses only
  client + types, grep-verified against genai's breaking module). Security:
  no advisories on direct deps; the transitive soupsieve HIGH pair
  (CVE-2026-49477/49476, Jul 9) is patched in 2.8.4 — venv already on
  2.8.4, not vulnerable.

**Step 4 — Cost audit:** **Real data for the first time** (last week's
recommendation implemented: `~/.finlens/usage_log.jsonl`, pinned by
tests/test_usage_log.py). Week of 2026-07-05 → 12: **26 calls**.
- Haiku 4.5 (extraction): 7 calls, 202K in / 19K out, 149K cache-write,
  0% cache-read — expected: each filing's extraction input is unique;
  cache-write is claiming the shared system prompt.
- Sonnet 5 (analysis/SEDAR): 19 calls, 335K in / 21K out, **43% cache hit**
  (433K cache-read vs 243K cache-write) — caching is working on the
  analysis paths.
- Largest outputs: four `analyze_financials` extraction calls (~4.6K out
  each) — the expected heavy call; no unexpectedly large calls; no
  tier mismatches (extraction on Haiku, analysis on Sonnet-5, per
  architecture).
- Gap: the targeted extractors (hedging note, MD&A metrics — sonnet-5 via
  sedar_extractor) do not persist usage records; ~4 known paid calls this
  week are invisible to this audit. Recommendation #4 above.

**Step 5 — Live app:** **UP** (infra-level). `/healthz` → `{"status":"ok"}`
(matches last week); root URL 303s through the share.streamlit.io auth mint
back to the app's login — the viewer-auth gate functioning end-to-end, no
crash/sleeping page on any hop. Version alignment vs main remains not
fetch-verifiable through the auth gate (requires an authenticated browser
session — tooling limit, not a fault).

**Step 6 — Build-order alignment:** **Aligned.** This week = the MD&A
fetcher (design→build→live-verify, MDA_FETCHER_SPEC), the CB-031→036
correctness/casebook run, Call 4 bug-class fixes, and trust receipts —
squarely the data-layer/correctness track the roadmap addendum names as
"the highest-priority pre-feature work item." Three deploys to main
(4b68625, e3b1762, 300f7e4). 185 commits this week. No unexplained drift.

**Step 7 — Sector profile review:** Healthy; ONE promotion candidate now
passes the utility gate (cash + current subtotals — 9-filer frequency +
live Leverage/Liquidity consumers); resource_sector coverage gap closed
(1→3); financial_sector (n=1) is the last thin profile; no cross-sector
leakage; the by-design unmapped classes (CB-025 suppression, CB-009 stock)
confirmed behaving.

## Overall week status: **PASS WITH NOTES**
No blockers; no silent detection failures; no regressions; app up; suite
628 green; release radar clean; schema consistent; memory synced. The notes
(all carried as queue items, none urgent): 2nd bank for financial_sector
coverage; the cash/current-subtotals promotion candidate (now
utility-gate-passing); the cross-extractor re-run over ~8 new fields;
usage-log persistence for the targeted extractors; consider adding the two
new CLAUDE.md principles to STERLING_BRIEF's manifest.
