# Weekly Audit — 2026-06-15 (Sunday audit, run late)

## Steps completed
1. Codebase vs feature list
2. Memory cross-check
3. Release radar
4. Cost audit
5. Live health check
6. Roadmap priorities

## Steps deferred (run fresh)
7. Fresh-Opus architectural review — per `docs/audits/STEP_7_OPUS_REVIEW_PROMPT.md`
8. Sector-profile review across corpus

## Key findings (priority order)

### 1. [TOP PRIORITY] Production is 194 commits behind
`origin/main` (live app finlens-ai.streamlit.app) = `326c4eb`; `dev` = `d8d0456`; **194 commits ahead.** The live app predates the ENTIRE Integrity Engine/SEDAR pipeline, Munger Inversion, lot-level Position Tracker, EDGAR full-text fetch, and prompt caching.

CRITICALLY: `main` still carries silent-data-corruption bugs already fixed on dev — the 1000x "in thousands" magnitude error and the "$3.7B shown as 3.7M" formatter bug. A live app misreporting financial magnitudes directly undercuts the data-integrity thesis.

**ACTION:** next work session = deliberate dev→main release pass. Pre-deploy checklist:
- (a) make the Avast SSL workaround Windows-only conditional (will break in cloud otherwise),
- (b) verify `~/.finlens` storage on Streamlit Cloud ephemeral filesystem,
- (c) full smoke test,
- (d) deploy.

Do NOT deploy casually — large surface area.

### 2. Audit input is broken
No canonical "43-feature list" exists — it's a 35-item addendum + an unnumbered moat subsystem + a stale older numbering, none status-tracked. Step 1 can't run faithfully without it.

**ACTION:** create one canonical, status-tracked feature list AND number the Integrity Engine/SEDAR moat work into it (currently the biggest shipped subsystem is invisible to the roadmap).

### 3. Strategic: roadmap-vs-reality divergence
The roadmap describes a feature-SaaS product (35 user features, pricing tiers, VC toolkit); actual work is a data-moat product (~90% of recent commits = campaign/integrity). Confirmed independently by Step 1.

**DECISION NEEDED (fresh head):** rewrite the roadmap moat-first to match the June-13 guiding frame, or treat moat work as a detour. Make it a conscious choice, not drift.

### 4. Foundation fixes (from Step 4 cost audit; both "minimize human error" pattern, neither urgent)
- `cache.py:get_cache_key()` is model-agnostic; cross-model isolation works only because every caller remembers to append the model part — fold the model into `get_cache_key()` to make it structural, not remembered.
- Quick Analysis ("Analyse $") doesn't disk-cache its Claude result (re-pays on repeat) — align with the upload path's `load_cache`/`save_cache`.

### 5. Process gap (resolved tonight)
58 local-dev commits were unpushed to `origin/dev` (this whole session was laptop-only). Pushed and backed up during the audit. Note for workflow: nothing in the pipeline routinely pushes to `origin/dev` — work accumulates local-only until forced. Consider adding a push step to the review loop.

## Clean / reassuring
- Cost discipline solid: all Claude calls button-gated + cached, model-specific cache keys confirmed, `$` convention consistent, free-tier limits respected.
- No dependency conflicts: `add_rows`/LangChain unused; plotly/streamlit pins safe.
- Model selection (Opus 4.8 strategy / Sonnet 4.6 daily / Haiku 4.5 routine) still accurate. Note: Fable 5 access suspended by Anthropic June 12 — the dev selector's Fable option is temporarily dead.
