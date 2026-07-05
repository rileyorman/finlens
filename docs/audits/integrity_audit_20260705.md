# FinLens Data Integrity Engine — Audit Report

**Date:** 2026-07-05 (Sunday audit)
**Run per:** docs/audits/INTEGRITY_AUDIT_PROMPT.md (first run of this audit format — Part 5 establishes the baseline; no prior dated audit exists to diff against)
**Runner note:** executed by Claude Code (CC) in-session; the prompt names Opus 4.8 as the runner — recorded as a deviation, model actually used: Fable 5.
**Log state at run:** 89 physical lines, 89 parsed, 0 unparseable (utf-8-sig reader diagnostics clean); 24 integrity records, 16 cross-validation, 43 cross-extractor agreement, 5 disposition, 1 extraction_figure_presence.

## VERDICT: PASS

- Part 1: zero silent passes — all 5 poisoned fixtures flagged (live run, plus 9/9 in `tests/test_integrity_detection.py`).
- Part 5: no baseline regression detectable — all available baselines return `clean`; this run freezes the baseline for future audits.
- PASS is on the audit's own criteria (poison detection + baseline stability). Findings below still require action — see the prioritized list at the end.

---

## PART 1 — DETECTION TEST (poisoned NVDA FY2026 fixtures)

Live run of `tests/test_integrity_detection.py` harness (scripted, reproducible; `validate_filing` only — no log writes):

| Corruption | Result | Rule(s) fired |
|---|---|---|
| Swap Revenue and Cost of Revenue | PASS (flagged) | gross_margin_range, net_margin_ceiling, revenue_growth_sanity, revenue_reconciliation |
| Set fiscal year to 2010 | PASS (flagged) | fiscal_year_recency |
| Inflate gross margin above 100% | PASS (flagged) | gross_margin_range, net_margin_ceiling, revenue_reconciliation |
| Set net income > revenue | PASS (flagged) | net_margin_ceiling |
| Set revenue growth to +300% | PASS (flagged) | revenue_growth_sanity |

**ANY SILENT PASS: NO.** Full pytest detection suite: 9 passed in 0.38s (includes SEDAR confidence/pattern-match/total-assets-identity and unresolved-ticker tests).

## PART 2 — LOG-LEARNING REVIEW

Source: `analyze_log()` over 24 integrity records (2026-06-05 → 2026-07-04). n=24 is above the analyzer's low-sample threshold (10) but still thin — treat calibration signals as directional.

**Rules that never failed on real data (8):** gross_margin_range, net_margin_ceiling, revenue_reconciliation, fiscal_year_recency, sedar_extraction_confidence, sedar_mapping_pattern_match, sedar_total_assets_identity, accounting_standard_recorded.
- The first four are proven fireable by the Part 1 poison harness — "never fired in production" here means clean corpus, not dead rule.
- The three sedar_* rules and accounting_standard_recorded have never failed outside unit tests. sedar_total_assets_identity (6 real runs, all pass) is self-validating by construction; the confidence/pattern rules are threshold-pinned by tests. No loosening/tightening evidence yet.

**Rules that fired:** revenue_growth_sanity — 3 failures / 15 runs (20%, below the 30% too-strict flag). All three attributed against the log:
1. **NVDA FY2026, obs +114.2%, 2026-07-04T01:15Z** — the FABRICATED re-analyse extraction (130,497 vs NVDA's real FY2024 60,922 = +114.2%; confirms the fabricated prior column was real FY2024 data). NOTE: this record is in tension with the SESSION_HANDOFF claim that the fabricated analysis produced "zero integrity flags" — the log holds a warnings-status record 21 minutes before the figure-presence FABRICATED verdict (01:36Z). Either the UI run differed from this logged validation or the narration overstated; adjudicate (priority list #2).
2. **CNQ Three Months Ended Dec 31 2024, obs −73.5%, 2026-07-02** — the documented MIXED-PERIOD EXTRACTION DRIFT incident (quarterly revenue in an annual frame). Known, queued.
3. **PLD FY2025, obs +290.2%, 2026-06-11** — UNTRIAGED. Prologis did not triple revenue; the prior-year value in that extraction is almost certainly wrong. PLD_FY2025 is also in the em-dash-damaged cache batch awaiting re-analyse. Needs triage (priority list #1).

**Thresholds legitimate data is approaching:**
- net_margin_ceiling: max real observation 55.6% (NVDA FY2026 true copy: 120.07B / 215.94B) vs 60% ceiling — only 4.4% headroom. NVDA-class AI-cycle margins may legitimately cross 60%. Watch; do NOT raise on one observation.
- gross_margin_range: comfortable (obs 46.9%–71.5% inside 0–100%).
- revenue_growth_sanity: the min/max breaches shown in the distribution section (+290.2%, −73.5%) ARE the flagged failures above — the analyzer's "[!] should have flagged" wording misreads its own data (it did flag). Minor analyzer polish item (priority list #6).

## PART 3 — CROSS-VALIDATION REVIEW (FinLens vs FMP)

16 CV records (14 v1, 2 v2-era entries in the summary view).

**Tight agreement (0.0% on all four headline fields):** AAPL FY2025, MSFT FY2025, SHOP FY2025, NVDA FY2026 (good June-4 copy). US large-cap XBRL filers agree byte-tight when FMP has the period.

**Divergences (all advisory per v2 design):**
- **NVDA FY2026 revenue, 39.6% (v2 record: FinLens 130.50B vs FMP 215.94B)** — this is the fabricated extraction being caught by cross-validation. The CV signal was directionally CORRECT here (FMP matched the true filed value; the FinLens-side number was the fabricated one). Recorded as evidence that the advisory CV triage signal has real value even under the "FMP is an unreliable witness" principle — advisory-only remains the right design; no change.
- **JPM FY2025 revenue, 34.8%** — definitional (FMP total revenue vs bank net revenue presentation). Known class, no FinLens error.
- **JPM FY2025 operating_cash_flow, 246.5%** — CLOSED 2026-07-03: adjudicated against the as-filed 10-K; FinLens −147.78B is byte-identical to the filed line; FMP +100.87B is a phantom value. No FinLens fix.

**Systematic pattern:** all 7 SEDAR/TSX filers (AEM, CNQ, SU, NGEX, REI.UN + CB/MKL transient) are UNMATCHED — FMP premium-blocks TSX tickers at the current tier. Structural, known, and governed by the CROSS_VALIDATE CURRENCY GATE prerequisite before any FMP tier upgrade. The Gemini cross-extractor (Part 3's real successor for SEDAR filers) covers what FMP cannot: latest-view 9 VERIFIED / 2 PARTIAL / 3 FLAGGED (1 hard = CNR interest_expense, dispositioned checker_error) / 8 UNCHECKED (transient gemini 503s, re-runnable). Open triage targets: 4 (ATD net_income, ATD gross_profit, REI.UN property_operating_costs, REI.UN net_operating_income) — all known v3 targets from the tenth session.

## PART 4 — COVERAGE GAPS

**Sectors actually in the integrity log (24 filings):** US tech/semis (AAPL, MSFT, NVDA, SHOP, PLTR-era), US bank (JPM), US P&C insurance (CB, MKL — MKL all-skipped shell), US REITs (PLD, O), specialty retail (COST), Canadian REIT (REI.UN), convenience retail (ATD), gold mining (AEM ×2), integrated O&G (SU), upstream O&G (CNQ, quarterly), mineral exploration (NGEx ×2 under two sector spellings), plus 3 unknown-sector legacy/garbled records.

**Missing from the log entirely:** Canadian bank (RY is ground-truthed at the fixture/mapper layer but has never run through validate_filing into the log), life insurer (SLF — same), TECK.B, CSU, CNR, CAR.UN, DIR.UN, NFG (campaign filers validated at the mapper layer, not engine-logged), thin-margin grocer, French-language filing, scanned/no-text-layer PDF, SPAC.

**Honest framing:** engine confidence is only as broad as what reached the log. The SEDAR campaign corpus is mostly validated via fixtures/registry/cross-extractor, not via engine log records — that is a coverage statement about the LOG, not an error.

**Next deliberate fetch targets (aligned with the existing queue, not new scope):** (1) the boring TSXV junior explorer (mining_exploration n=2 — queue item), (2) the remaining cold-load dry-run slots (explorer / REIT / financial-or-insurer), (3) run a corpus filer with a known engine path (e.g. RY) through the full engine→log path so the bank shape exists in the log.

## PART 5 — REGRESSION CONFIRMATION

No prior dated integrity audit exists — **this run establishes the baseline.** Future audits diff against this table.

| Baseline | Status | Rules run | Detail |
|---|---|---|---|
| NVDA FY2026 (tests/fixtures) | clean | 5 | all 5 rules passed, none skipped |
| NVDA FY2026 (analysis cache, June-4 good copy) | clean | 4 | fiscal_year_recency skipped (field_unavailable) |
| AAPL FY2025 (analysis cache) | clean | 3 | fiscal_year_recency + revenue_growth_sanity skipped (field_unavailable) |
| MSFT FY2025 | UNAVAILABLE | — | no cached analysis on disk (only MSFT_FY2010); honest skip |
| JPM FY2025 | UNAVAILABLE | — | no cached analysis on disk; honest skip |

No drift detectable (nothing to drift from). Action: decide the durable Part 5 baseline set (priority list #4).

## SUNDAY ADDITION (per SESSION_HANDOFF pick-up list item 2 — labeled addition, not part of the base prompt)

**Quarantined fabrication evidence:** `~/.finlens/analysis/NVDA_FY2026_claude-sonnet-4-6.json.FABRICATED_EVIDENCE_20260703` — present and intact. Contents confirm the handoff record: fiscal_year=FY2026, prior=FY2025, first revenue line 130,497,000,000 (NVDA's real FY2025 revenue mislabeled FY2026).

**extraction_figure_presence records:** exactly 1 — `2026-07-04T01:36:13Z, company=NVIDIA Corporation, checked=74, found=3, ratio=0.041, verdict=FABRICATED`. Matches the handoff's gate evidence exactly. Only one record exists because no extraction has run since the guard shipped (the guard logs PASS records too; the next successful extraction should produce the first PASS record — verify at next audit).

**Evidence chain cross-check (new finding):** the fabricated run left THREE independent traces — (i) the integrity warnings record (+114.2% growth, 01:15Z), (ii) the v2 CV DISAGREE record (130.50B vs FMP 215.94B), (iii) the figure-presence FABRICATED record (01:36Z). The system's layered signals were better than the incident narration credited; the genuinely silent layer was the UI quality score (already fixed to name its basis) and the pre-guard save path (fixed by a046092).

---

## PRIORITIZED TUNING / ACTION LIST (each tied to its evidence)

1. **Triage PLD FY2025 revenue_growth_sanity failure (+290.2%, log 2026-06-11).** Untriaged wrong-looking prior-year revenue in a cached analysis; PLD is also in the em-dash re-analyse batch — fold the triage into that re-analyse (after fabrication fix (b) lands, per the pick-up list). Evidence: integrity log record 2026-06-11T04:45Z.
2. **Adjudicate the "zero integrity flags" tension on the fabricated NVDA run.** The log holds a warnings-status NVDA FY2026 record (revenue_growth_sanity, +114.2%) at 01:15Z, before the 01:36Z FABRICATED verdict. Either the live UI run differed from this logged validation or the handoff narration overstated the silence. Correct the handoff record whichever way the evidence lands (integrity-first: the written record should match the log). Evidence: both log records quoted above.
3. **Close the 4 open cross-extractor triage targets** (ATD net_income, ATD gross_profit, REI.UN property_operating_costs, REI.UN net_operating_income) via the /integrity-log disposition tooling. The two REI.UN GEMINI_MISSING targets belong to the queued derived-fields design decision — write dispositions there, not ad-hoc. Evidence: analyze_log §6 triage table (4 OPEN).
4. **Decide the durable Part 5 baseline set.** MSFT FY2025 / JPM FY2025 named by the audit prompt do not exist as cached analyses. Options: regenerate via EDGAR fetch, or amend the prompt's baseline list to assets that are version-controlled (fixtures). Evidence: Part 5 table.
5. **Watch net_margin_ceiling headroom (4.4%).** NVDA true FY2026 net margin 55.6% vs 60% ceiling. One more AI-cycle filer could legitimately breach. Do not raise on n=1; log the next approach. Evidence: analyze_log §4 distribution.
6. **Analyzer polish (low):** §4 prints "[!] ... should have flagged" for observations that DID flag (the failures are in the same dataset). Reword to distinguish "breach that flagged" from "breach that slipped." Evidence: §4 output vs §3 failure counts this run.
7. **Log hygiene (low, known):** NGEx logged under two sector spellings, AEM duplicated, 3 garbled/unknown legacy records — all covered by the existing MOAT-LOG LEGACY RECORD NOISE queue item; no new action.
8. **Re-run the 8 UNCHECKED cross-extractor filers** (transient gemini-3.5-flash 503s) for log completeness when convenient — not gate-progress (all EXACT-spine). Evidence: analyze_log §6 unchecked reasons.

---

# WEEKLY SUMMARY — Sunday audit 2026-07-05

**Overall week status: PASS WITH NOTES**

**Step 1 — Integrity engine report card: PASS.**
- Detection: 5/5 poisoned fixtures flagged, zero silent passes; detection suite 9/9 live.
- Schema: CURRENT_SCHEMA_VERSION = 6, CONSISTENT with the week — the week's normalization change (08daaaa, boundary unit-scaling of promoted SEDAR fields) is exactly what the v6 comment records; the mapper rename (1b8d584) carried a documented deliberate NO-bump decision (absence-is-honest reasoning, handoff).
- Tests: 231/231 passed (live run, 10.93s).
- Lint: ruff clean repo-wide ("All checks passed!", ruff 0.15.20 installed).
- Hook portability: core.hooksPath = .githooks — active.

**Step 2 — Memory cross-check: 3 items synced to CODEX_MEMORY.md, 2 session-memory corrections.**
- ADDED to CODEX_MEMORY.md: "Valid Anthropic Model IDs (current — do not 'correct')" block (was absent — Codex could have 'corrected' live model strings from stale training data).
- ADDED to CODEX_MEMORY.md: "SEDAR Canonical Revenue Semantics (per-sector)" summary (gross-of-royalties rule, bare-revenue negative rule, royalties-stored-negative, augment-don't-mint; pointer to CLAUDE.md full block).
- MOVED within CODEX_MEMORY.md: the Jun 2 2026 cache-TTL reference incident sat under Number Formatters; relocated to its home under Empirical Evidence > Documentation.
- Session memory: security_posture.md corrected (Avast is gone from the machine as of 2026-07-03 — pattern reframed as generic-interceptor hygiene); workflow_rules.md annotated with the Codex retirement (access ends 2026-07-13) and OpenClaw succession note.

**Step 3 — Release radar:**
- Anthropic: Opus 4.7 fast-mode removal Jul 24 2026 and Opus 4.1 retirement Aug 5 2026 — FinLens unaffected (config.py uses claude-haiku-4-5-20251001 / claude-sonnet-4-6). Cache diagnostics public beta (cache_miss_reason) — optional nice-to-have for the caching architecture. ADVISORY: search results indicate introductory pricing ($2/$10 per MTok) ending Aug 31 2026 with standard $3/$15 after — if that applies to Sonnet 4.6, analysis-call costs rise ~50% Sept 1; VERIFY on the Anthropic console before acting (empirical-first).
- Streamlit: installed 1.57.0; latest 1.58.0 (May 28). Breaking removals (element.add_rows, LangChain handler) — grep confirms neither is used in FinLens. No action required before deploy.
- FMP: no June–July 2026 endpoint deprecations found (changelog last updated May 21). No action; tier upgrade remains gated behind the currency-gate prerequisite regardless.
- EDGAR: 10 req/s policy unchanged. SEDAR+: no policy changes found.
- Dependency advisories: pip-audit NOT installed in this venv — last clean machine audit was the 2026-07-02 security sweep. RECOMMEND: add pip-audit to dev tooling so this check is machine-run each Sunday.

**Step 4 — Cost audit: NO PERSISTENT COST DATA ACCESSIBLE (stated explicitly).**
- log_cache_usage() in modules/claude_analyzer.py captures cache_read/cache_write/input_tokens per call but only print()s them; neither service log contains any usage lines. logs/ holds no cost artifacts.
- RECOMMENDED MECHANISM: append each log_cache_usage() dict as JSONL to ~/.finlens/usage_log.jsonl (timestamp + model + call name — same pattern as the integrity log); the Sunday audit can then report weekly tokens by model tier and cache hit rate from data. Until then, tier-mismatch review is not possible from evidence.
- Architecture check (static): extraction=Haiku, analysis/bear-bull=Sonnet per config.py — matches CLAUDE.md; no hardcoded model strings found outside config.

**Step 5 — Live app health: UNVERIFIED (auth-gated), not down.**
- https://finlens-ai.streamlit.app responds but 303-redirects into the Streamlit viewer-auth flow — the deployment is private, so content health cannot be verified without a login. Platform is serving; app process state unknown from outside.
- Version alignment: deployed = main, which remains ~208+ commits behind dev (known, deliberately gated behind correctness gate #1; the 24-commit eleventh-session batch adds to this). The known WEEKLY_AUDIT_2026-06-15 magnitude-misreport issue on main is unchanged until a merge happens.
- Not flagged as a blocker: no external users; deploy is gated. Riley should eyeball the app when logged in, or we drive it with browser tooling in-session.

**Step 6 — Build-order alignment: DRIFTED from the addendum queue, ALIGNED with the governing sequencing — documented, no flag.**
- Roadmap addendum top of queue: lot-level position tracking. Zero commits on it this week.
- The week's ~70 commits went to: correctness-gate work (checker precision (b)/(c), fabrication guard a046092, ground-truth passes) — aligned with the #1 correctness gate that explicitly supersedes feature work — plus a Riley-directed aesthetics/UX/economics/commodities sweep (rationale explicit in the eleventh-session handoff). Drift from the addendum is deliberate and recorded, not silent.

**Step 7 — Sector profile review (3 qualifying sectors: reit ×3, mining ×2, insurance ×2):**
- (a) STRONGEST SIGNAL: **"Total liabilities" is unmapped in ALL 7 multi-sector-qualifying filers** (3/3 REIT, 2/2 mining, 2/2 insurance) — machine confirmation of the handoff's "total_liabilities — clean next field" build note. "Total liabilities and equity" nearly as widespread (feeds the assets identity check today via raw-label match). "Total equity" 2/2 mining + 2/2 insurance — but per the handoff this is a SCOPED PER-SECTOR build (NCI/unitholder ambiguity), not a blanket alias.
- (a) "Cash and cash equivalents" unmapped in reit/mining/insurance/resource but IS an alias in mining_exploration_sector (`cash`) — top candidate to promote to a default canonical field when balance-sheet expansion starts.
- (b) Known pending REIT 2/3 candidates (equity_accounted_income, fair_value_adjustments_financial_instruments) remain at 2/3 — still awaiting a 4th REIT. Balance-sheet "Equity accounted investments" also at 2/3 (DIR.UN, REI.UN).
- (c) New label variants: note-suffixed forms ("Cash and cash equivalents (Note 12)") appear on the unmapped side only; no mapped-field variant drift found.
- (d) Cross-profile hits, triaged: REI.UN "Operating income" matches a DEFAULT alias yet stays unmapped — VERIFIED DELIBERATE (the documented blended-NOI decision; CLAUDE.md says RioCan's printed subtotal is preserved in unmapped[] by design). RY "Insurance service result" matches an insurance_sector alias — correct routing (RY is financial_sector); by design. **NFG "Interest expense" matches a DEFAULT canonical alias yet is unmapped — small genuine anomaly** (defaults are supposed to always run); investigate when next touching the mapper — same family as the RY interest_expense sub-label item.

**Step 8 — Opus strategic review:** prepared, Riley's action (new claude.ai chat per docs/audits/STEP_7_OPUS_REVIEW_PROMPT.md, attach this report as the CC report card).

---

# ADDENDUM (same day, post-audit) — NVDA FY2026 June-4 copy: HUMAN VERIFICATION + CAPEX ADJUDICATION

Riley hand-transcribed from the as-filed FY2026 10-K (transcription-first protocol; clean-room caveat: headline values had been named in-session beforehand, so this stamp is corroborative rather than blind).

**VERIFIED — tie exactly to the filing (both years, $M):**

| Line | Filed FY2026 / FY2025 | Stored (June-4 cache) | Verdict |
|---|---|---|---|
| Revenue | 215,938 / 130,497 | 215,938M / 130,497M | TIE |
| Operating expenses | 23,076 / 16,405 | 23,076M / 16,405M | TIE |
| Operating income | 130,387 / 81,453 | 130,387M / 81,453M | TIE |
| Net income | 120,067 / 72,880 | 120,067M / 72,880M | TIE |
| Total assets | 206,803 / 111,601 | 206,803M / 111,601M | TIE |
| Operating cash flow | 102,718 / 64,089 | 102,718M / 64,089M | TIE |

Gross margin (71.1%) ties the computed stored ratio; assets ≡ liabilities + equity holds in-cache to the dollar. The filed prior column (130,497 = FY2025) also SOURCE-CONFIRMS the fabrication evidence chain: the quarantined re-analyse extraction had presented exactly that value as FY2026.

**ADJUDICATED WRONG — capex (closes the handoff's "capex 138.7M looks implausible" open item):**

- Filed (MD&A liquidity disclosure): capital expenditures **$6.1B FY2026 / $3.4B FY2025**.
- Stored: "Capital Expenditures" **138,735,000 (138.7M) / 97,890,000 (97.9M)**.
- Off by ~44x / ~35x with INCONSISTENT factors — this is NOT a unit-scaling error (would be a uniform 1000x). Line-specific error under a verified spine.
- Note: filed values are MD&A-rounded; the exact statement line was not transcribed. Irrelevant at 44x divergence.
- **ROOT CAUSE CORRECTED (same day, live EDGAR re-run):** the June-4 copy is `source=edgar` (schema 2, 2026-06-05) — its numbers came from XBRL companyfacts, NOT model extraction. The wrong capex is an XBRL TAG-MAPPING error: edgar_fetcher maps "Capital Expenditures" from `PaymentsToAcquirePropertyPlantAndEquipment` (+ a discontinued-ops tag), but NVDA files capex as a combined property-equipment-AND-intangibles line under a different concept. The June-era code surfaced a wrong-but-real tagged value; the earlier hypothesis ("extractor pulled a wrong line or fabricated") is retracted for this case. A fresh EDGAR run (2026-07-05 14:17 local) through current code returns capex=None for the same accession — honest absence replaces the confident wrong number (gate-wise: FAIL-class → PASS-class), while the spine remains byte-exact on all six human-verified lines, both years. Remaining coverage item: add NVDA's actual capex tag to the alias list after empirically checking companyfacts for which concept carries ~6.1B.
- **NEW FINDING from the re-run — FCF FALLBACK SILENTLY MISLABELS OCF (gate-relevant):** `excel_exporter.py:569` computes `fcf_c = (ocf_c - capex_c) if (ocf_c is not None and capex_c is not None) else ocf_c` — when capex is None, the "FREE CASH FLOW" metric silently displays plain OCF. Live-confirmed: fresh NVDA analysis shows FCF 102.72B (= OCF exactly); true FCF ≈ 96.6B (102.7 − 6.1). ~6% overstatement rendered confidently, and fcf_yield / fcf_conv / P-FCF inherit it. This is a confident-wrong-DERIVED-number path — honest degradation requires suppressing or relabeling ("OCF — capex unavailable") when capex is missing.
- **GUARD SCOPE CLARIFIED:** the figure-presence guard runs on every `analyze_financials` (text-extraction) call — the XBRL path performs no model extraction, so no figure-presence record is written there (correct: XBRL values are as-filed by construction; the risk class on that path is tag-mapping, not fabrication — exactly what this incident was). Docs describing the guard as covering "every extraction" should carry this scoping.

**Consequences:**
1. The June-4 copy is now HUMAN-VERIFIED on the income-statement spine, total assets, and OCF — and KNOWN-WRONG on capex. Any consumer deriving FCF (OCF − capex), DCF inputs, or capex-based red flags from this cache overstates FCF by ~$6B. The cache is NOT hand-edited (no silent data surgery); the fix path is the queued NVDA re-analyse after fabrication fix (b) lands (NVDA is already in the em-dash re-analyse batch). Until then this is a documented confident-wrong-number in a dev-local cache — no external exposure.
2. GUARD-CLASS GAP made concrete: the aggregate figure-presence guard (>=20% presence threshold) would NOT catch a single wrong line among ~74 correct ones. Two queued designs would: the PRIOR-COLUMN CONTINUITY RULE (see handoff queue) and a per-figure extension of the presence check (annotate each row found/not-found in source rather than only the aggregate ratio). Fold the per-figure idea into the continuity-rule design session.
3. Priority-list update: action item #2's adjudication direction is reinforced (the log's layered signals outperformed the narration), and the PLD +290.2% triage (#1) now has a confirmed sibling error-class: single-line extraction errors in EDGAR-era caches.
