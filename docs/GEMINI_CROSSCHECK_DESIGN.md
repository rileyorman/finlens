# Gemini Cross-Check — Design (Item 7)

**Status:** Settled design, not yet built. Designed 2026-06-13 (Opus 4.8 session). Build when moat work becomes priority — payoff is deferred (post-campaign / pre-commercial), not urgent.

## Purpose
Turn the FMP premium wall into a proprietary validation signal. FMP cross-validation goes dark on mid-to-large caps that return `fmp_premium_blocked` — often the most important filings. An independent second extractor (Gemini) re-extracts the same SEDAR PDF; agreement between two independent models becomes a validation signal FinLens owns and FMP-dependent competitors cannot reproduce on Canadian IFRS filings.

## What it replaces — and what it does NOT
- REPLACES: FMP's role as a *validator*, and does it better on blocked filings (dual-model agreement > single third-party agreement).
- DOES NOT REPLACE: FMP's role as a *data source* (DCF cross-validation, key metrics/ratios, sector performance, dividends, economic indicators). Those roadmap integrations still need FMP. Frame this as "closes FMP's validation gap," never "replaces FMP wholesale."

## Settled Decisions

### Decision 1 — Selective trigger
Cross-check fires ONLY where FMP cannot validate: `fmp_premium_blocked`, or genuine IFRS filers FMP doesn't cover. Never the whole corpus. Rationale: value is concentrated exactly where current validation has a hole; running it where FMP already validates buys redundant confirmation at double cost. Accepted tradeoff: two-tier validation provenance (FMP-validated vs cross-extractor-validated) — this is honest complexity; the audit trail SHOULD distinguish them as different strengths of evidence.

### Decision 2 — Agreement = per-field tolerance
No global tolerance. Per-field tolerance map mirroring the integrity engine's existing structure:
- TIGHT on explicitly-stated headline figures (revenue, net income) — a real disagreement here is a real problem.
- LOOSER on derived/subtotal figures (gross profit when computed, operating income when buried) — legitimate variance in which line each model grabs.
Tolerance is RELATIVE with an ABSOLUTE floor ("within X% OR within $Y") to avoid breaking at extremes — percentage-only flags noise on near-zero values and hides real errors on large ones. Mirrors the existing number-formatter magnitude-range discipline.
HONESTY CONSTRAINT: agreement is logged as "two independent extractions concur" — NEVER claimed as proof of correctness. Two LLMs reading the same ambiguously-labeled subtotal can share a failure mode and agree on a wrong number. The audit trail states exactly what agreement is (concurrence) and no more.

### Decision 3 — Disagreement: flag, don't resolve
On divergence, the field is marked "unverified — extractors disagree," logged, and surfaced in the audit trail. NO automatic winner is picked. Rationale: picking a winner fabricates confidence; violates the standing principle (honest "unresolved" > fabricated value). A flagged-uncertain field is the truthful state and better serves a fund manager than a silently-wrong picked number. The flag is a feature.

### Decision 4 — Witness: independent capable extractor
Design names the requirement as "an independent second extractor" (different model lineage so errors are uncorrelated), defaults to Gemini. The model is a CONFIG VALUE, not an architecture decision — switching Flash↔Pro is a one-line setting. Gemini access is Tier 1 (no upgrade needed); selective triggering keeps daily request volume far below Tier 1 caps. Model choice (Flash vs Pro) is a cost-vs-witness-strength tradeoff resolved empirically: measure real disagreement rates and real per-filing token cost from live API responses before committing. NOTE: this is a paid API call (not a subscription) — gets the `$` UI indicator per the standing convention. Verify current Gemini model name + live pricing at build time (Google reshuffled tiers/pricing repeatedly through 2026).

### Decision 5 — Persistence: compute once per filing, read free thereafter
Cross-check results are cached as a logged integrity signal (`cross_extractor_agreement`) in the existing JSONL learning log. The Gemini call happens once per filing per checker behavior version; every subsequent load of the same version reads the stored result at zero API cost. This makes the cost one-time-per-filing-version, not per-analysis or per-view; amortized cost per use trends to nothing. Folds directly into the existing integrity-log moat flywheel (write once, read forever, accretes into the validated-Canadian-fundamentals record). Re-run on: restatement (new `filing_accession`), checker behavior change (`checker_version` bump), extractor schema change, or manual re-validate trigger. Reuses the existing `filing_accession`-as-dedup-key pattern with `checker_version` for staleness detection.

## Open items for build time
- Live Gemini pricing + current model name check (search before build).
- Empirical Flash-vs-Pro decision from real disagreement rates + measured per-filing token cost.
- Per-field tolerance values (calibrate during use, same as engine thresholds — provisional until evidence).
- Cache-staleness rule confirmation (restatement / schema-change / manual re-validate).
