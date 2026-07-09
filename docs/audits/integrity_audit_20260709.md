# FinLens Data Integrity Engine — Audit 2026-07-09

**VERDICT: PASS** — no poisoned fixture passed silently; no baseline regressed;
full suite green. One required follow-up (schema-version bump) flagged below —
process, not a detection failure.

- Run by: CC (Sunday audit Step 1), Opus 4.8
- Machine: local dev (Python 3.14.6 venv; CI is authoritative at 3.11)
- Full suite: **465 passed in 5.96s** (secrets injected via SOPS)
- Lint: **All checks passed!** (`ruff check .`)
- Hooks: `core.hooksPath = .githooks` ✓ active; ruff 0.15.20 installed ✓

---

## Operational sub-checks

### Hook portability
- `git config core.hooksPath` → `.githooks` ✓ (pre-commit gate active)
- ruff installed (0.15.20) ✓ — lint gate active
- No action.

### Schema & cache health — ⚠ REQUIRED FOLLOW-UP
- `CURRENT_SCHEMA_VERSION = 6` (modules/analysis_cache.py), set 2026-07-01 in
  commit `08daaaa` ("scale all promoted SEDAR canonical fields at the boundary").
- **Finding:** CB-021 → CB-024 (2026-07-07) added **7 new fields** to the
  `normalize_financial_data` scaling whitelist in `modules/claude_analyzer.py`
  — `capex`, `operating_cash_flow`, `long_term_debt`, `short_term_debt`,
  `pretax_income`, `interest_expense`, `transportation_costs` — **without
  bumping `CURRENT_SCHEMA_VERSION`** (still 6).
- Per CLAUDE.md "Schema Versioning for Cached Data": *"When changing
  normalize_financial_data() or any data shape: bump CURRENT_SCHEMA_VERSION."*
  Adding fields to the scaling whitelist is a normalize change → the rule
  applies.
- **Risk assessment:** LOW-but-nonzero. A cache written before CB-021 generally
  would not contain these fields at all (the mapper aliases didn't exist), so
  the new Key-Metric cards (FCF, D/E, EBIT/EBITDA, Netback) would show N/A
  rather than a wrong number. The residual risk is a pre-CB cache that already
  held one of these fields stored *unscaled*, now read by a scaling-aware
  consumer → potential 1000× display error with no visible symptom (exactly the
  class the schema gate exists to prevent).
- **Action (NOT auto-applied — needs Riley's sign-off):** bump
  `CURRENT_SCHEMA_VERSION` to 7 with a comment noting the CB-021→024 whitelist
  additions, OR record a deliberate no-bump decision with rationale. Do not
  ship the next analysis-path change without resolving this.

### Test suite
- `pytest tests -q` (secrets injected): **465 passed in 5.96s**, 0 failed.
- Detection suite `test_integrity_detection.py`: **18 passed** — including
  `test_poisoned_fixtures_are_caught` (the reproducible Part-1 poisoned-fixture
  battery), the SEDAR balance-sheet & total-assets identity rules (pass + flag +
  honest-skip), layer/period-agreement (CB-016), and document-class (CB-015).

### Lint
- `ruff check .` → **All checks passed!** Clean tree; nothing slipped past the
  per-commit gate.

---

## PART 1 — Detection test (poisoned fixtures)
**PASS — no silent passes.** The battery is scripted in
`tests/test_integrity_detection.py::test_poisoned_fixtures_are_caught` and
re-runs identically each audit (the manual poisoning from
INTEGRITY_AUDIT_PROMPT.md is now encoded). All 18 detection assertions fired as
expected: identity mismatches flag, wrong-concept equity picks flag, missing
components skip honestly (not silently), and info-only rules stay
informational. No corruption passed silently.

## PART 2 — Log-learning review
**Thin on this clone — insufficient volume to tune.** The local moat log
(`~/.finlens/integrity_log.jsonl`) holds **2 records**, both 2026-07-09,
`extraction_figure_presence` for *Mastech Digital, Inc.* (Haiku 4.5), figure
presence 98.68% and 98.75%, both **PASS**. No warnings fired, but n=2 is far too
small to call any rule "too loose." The substantive detection evidence this
week is the test suite (465 green), not accumulated production logs. No
threshold-tuning recommendation is warranted without more log volume.
*Recommendation:* accumulate real analysis runs before the next tuning pass.

## PART 3 — Cross-validation review
**No new divergence data this clone.** No FMP-vs-FinLens divergence records
present locally to review. The standing posture holds (CLAUDE.md): FMP is an
unreliable witness generally; Gemini second-extraction is the correctness path;
FMP never adjudicates alone. Nothing to surface.

## PART 4 — Coverage gaps
Sector corpus (15 SEDAR fixtures, by mapper profile):
- **reit_sector:** 3 (CAR.UN, DIR.UN, REI.UN) — well covered
- **insurance_sector:** 2 (IFC, SLF) — covered (n=2)
- **mining_sector:** 2 (AEM, TECK.B); **mining_exploration_sector:** 2 (NFG, SIG)
- **financial_sector:** 1 (RY) — **thin**
- **resource_sector (O&G):** 1 (CNQ) — **thin**
- **default/corporate:** 4 (ATD, CNR, CSU, SHOP)

Biggest gaps for next deliberate fetch: a **2nd bank** (financial_sector n=1) and
a **2nd O&G filer** (resource_sector n=1) — both single-filer profiles carry
un-cross-checked judgment-class rulings. See Part 7 for the sector-label scan.

## PART 5 — Regression confirmation
**No regression.** The identity/mapping rulings that back the corpus
(CB-013 balance-sheet identity, CB-016 layer-period agreement, CB-017 net-loss
bottom line, CB-020 loss sign) are pinned by tests that all pass. The full
465-test suite matches a clean baseline; no per-rule drift.

---

## Prioritized tuning actions
1. **[REQUIRED, needs sign-off]** Resolve the schema-version gap — bump
   `CURRENT_SCHEMA_VERSION` 6→7 for the CB-021→024 whitelist additions, or
   record a deliberate no-bump decision. Evidence: `git log -L` on the version
   line (last change 2026-07-01) vs whitelist additions 2026-07-07.
2. **[coverage]** Fetch a 2nd bank and a 2nd O&G filer to cross-check the
   single-filer `financial_sector` / `resource_sector` judgment rulings.
3. **[observability]** Wire `log_cache_usage()` output to a persistent JSONL so
   Part 2 / Step 4 have real data (see Step 4 in the weekly summary).

---

# Weekly Summary — Sunday Audit 2026-07-09

**Step 1 — Integrity engine:** **PASS.** Detection battery 18/18, full suite
**465/465 passed**, lint **clean**, hooks **active** (`.githooks`, ruff 0.15.20).
Schema version **6** — ⚠ **required follow-up**: CB-021→024 (2026-07-07) added 7
fields to the `normalize_financial_data` scaling whitelist without a
`CURRENT_SCHEMA_VERSION` bump. Needs a 6→7 bump or a recorded no-bump decision
(Riley's sign-off).

**Step 2 — Memory cross-check:** Synced 4 items.
- CODEX_MEMORY.md: (1) model IDs — added `claude-sonnet-5` as the Sonnet tier +
  the "thinking disabled" gotcha (was still listing sonnet-4-6 only);
  (2) `property_operating_costs` — updated from "OPEN definition question" to
  RESOLVED (CB-012, rental-only derive-for-blended); (3) added the CB-013→CB-024
  new canonical fields (total_equity, total_liabilities, net_income sign,
  FCF/capex, debt, EBIT inputs, transportation_costs).
- STERLING_BRIEF.md: Iron Rule #2 updated with sonnet-5 + gotcha; "Last synced"
  stamp bumped 2026-07-05 @ 3b6e912 → 2026-07-09 @ 36282a5.
- Session memory dir: empty (no MEMORY.md, no entries) — nothing to reconcile.
- **Minor flag (no edit):** CLAUDE.md "CI Python Version" section says local dev
  runs Python 3.13, but the venv is **3.14.6**. Substance unaffected (CI 3.11 is
  authoritative). Flagged for Riley rather than silently editing the source of
  truth.

**Step 3 — Release radar:** No blocking changes.
- Claude Sonnet 5 released 2026-06-30 (matches config); promo pricing $2/$10 per
  Mtok ends **Aug 31, 2026** (cost note, not code). Rate limits raised. No model
  FinLens uses is deprecated. Prompt-cache `"1h"` string unaffected.
- Streamlit 1.59.0/1.59.1 (Jul 6/8) removed `element.add_rows` + LangChain
  handler — **grep confirmed 0 `.add_rows(` usages in FinLens**, safe.
- FMP: possible plan-based endpoint enforcement (changelog dates unconfirmed);
  watch `modules/fmp.py` for new limit errors. EDGAR/SEDAR: no changes.
- anthropic SDK 0.115–0.116 released; no Messages-API breakage. Other deps clean.

**Step 4 — Cost audit:** **No cost data accessible.** No token/cost tracking
artifact exists; `logs/` holds only service stdout/stderr. `log_cache_usage()`
in claude_analyzer.py builds a usage dict (cache_read / cache_write /
input_tokens) but **only returns it — nothing persists it to disk.**
*Recommendation:* append its output to `~/.finlens/usage_log.jsonl` per call so
future audits can compute per-tier spend and cache hit-rate. Model-tier config
matches the CLAUDE.md architecture (Haiku extraction / Sonnet-5 analysis) — no
mismatch found by inspection.

**Step 5 — Live app:** **UP.** `finlens-ai.streamlit.app` — `/healthz` returns
`{"status":"ok"}`, auth service minting fresh login tokens (not the sleep page,
no HTTP error). App is viewer-auth-gated, so in-app UI state / deployed commit
hash are not fetch-verifiable — infra is healthy. Version alignment vs `main`
not confirmable without an authenticated session (tooling limit, not a fault).

**Step 6 — Build-order alignment:** **Aligned.** This week = CB-021→024
canonical-field additions (data layer), sonnet-5 upgrade, Docker + SOPS infra.
The roadmap addendum frames the SEDAR/data-layer + rule-tuning work as *"the
highest-priority pre-feature work item"* preceding all 10 build-order features
("No sequence change — only framing"), so the data-layer sprint is on-priority.
Docker/SOPS was interleaved deployment hardening (reasonable, off the feature
queue). No unexplained drift to lower-priority features.

**Step 7 — Sector profile review:** **Healthy, no promotions warranted.**
Qualifying profiles (n≥2): reit_sector (3), insurance_sector (2, newly
qualifying), mining_sector (2), mining_exploration_sector (2). High-frequency
unmapped labels are all either generic structural subtotals / identity-RHS lines
("Total liabilities and equity", "Cash and cash equivalents", EPS "Basic"/
"Diluted") or **balance-sheet asset/liability line items deferred by design**
(balance-sheet line-item mapping is utility-gated, commit eb5a872).
- (a) Top deferred candidate: REIT **"Investment properties"** (3/3) — the core
  REIT asset, unmapped only because b/s line items are gated; log for the
  utility-gate decision. Secondary: insurance **"Debt securities"** (2/2).
- (b) `equity_accounted_income` + `fair_value_adjustments_financial_instruments`
  (REIT) remain "common not universal" pending a 4th REIT (unchanged).
- (c) New variants: verified **"Loss for the year"** (NFG+SIG) is NOT a
  bottom-line miss — both explorers correctly map their comprehensive-loss line
  to `net_loss`; the unmapped label is a pre-OCI intermediate subtotal. No flag.
- (d) Cross-sector leakage: none found.

## Overall week status: **PASS WITH NOTES**
One required follow-up (schema-version bump/decision) and three low-priority
recommendations (2nd bank + 2nd O&G filer for coverage; persist usage telemetry;
CLAUDE.md local-Python version note). No blockers; app up; suite green.
