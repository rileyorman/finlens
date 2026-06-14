# Resource Economics Snapshot — Feature Spec

**Status:** Designed, not built. Roadmap feature for post–mining-campaign build.
**Scope:** Fuse filing fundamentals (accounting) with market data (commodity + equity prices) to produce the economic picture neither source gives alone. Applies across mining_sector and resource_sector (O&G) — both commodity-driven.

## 1. Thesis
A filing gives the accounting picture (revenue, production costs, DD&A, net income). Market data gives the price picture (commodity spot, share price, market cap). Neither alone answers what a value investor asks: is the economic margin durable, and is this company cheap or is the whole sector cheap? The Snapshot fuses both. Flagship output for mining is AISC vs spot price; for O&G it is netback vs crude/gas price. This is the payoff layer on top of the sector profiles the SEDAR campaign builds. Orients to value-investing: margin of safety as cost-vs-price spread, downside protection via reserve life, owner-earnings view through the cycle.

## 2. Architecture (settled)
Own panel in v1, standalone module underneath. Calculation logic lives in modules/economics/resource_economics.py (the brains). v1 renders as its own dedicated tab — isolated, demoable, does not destabilize existing flow. Later the same module is callable from Single Analysis, Portfolio, and Comparison as an enrichment layer. Panel for UI, module for brains, enrichment-everywhere later.

## 3. Three tiers
### Tier 1 — Filing x Market overlay (cheap, no new API)
Sources: filing (already extracted) + yfinance (in stack, free).
Inputs: filing revenue/costs/DD&A/net income/sector_inferred; yfinance share price, market cap, shares outstanding, commodity spot (gold, copper, WTI, natural gas via futures/ETF proxies).
Outputs: earnings yield, revenue vs market cap multiple, net margin contextualized, commodity price trend overlay vs fiscal period, "cheap company or cheap sector?" framing.
Cost: free (yfinance). Optional one $-flagged Claude call for narrative summary. Cache spot prices in session state.
Caveat: yfinance commodity proxies imperfect — document which proxy per commodity.

### Tier 2 — MD&A operational extraction (the flagship metric)
Sources: Tier 1 + MD&A prose extraction.
BLOCKER: requires MD&A/HTML-text extraction capability currently blocked (structured-only path doesn't reach MD&A; only PDF Upload gives full prose). Gated on that fetcher work.
Inputs (from MD&A): production volume (oz/tonnes/lbs/boe), AISC ($/oz) miners / netback ($/bbl or boe) O&G, realized price vs spot (hedging quality), by-product credits (polymetallic).
Outputs: AISC vs spot (mining) / netback vs commodity (O&G) — flagship margin-of-safety snapshot; realized vs spot; unit economics per unit produced; implied margin per ounce/barrel.
Why payoff: AISC/netback are MD&A-only — confirmed empirically on Agnico (none of AISC building blocks in the consolidated income statement). This tier makes FinLens speak the language analysts price on.

### Tier 3 — Reserves & cycle positioning (full vision)
Sources: Tier 1+2 + reserve reports (NI 43-101 mining / NI 51-101 O&G) + forward curves + peer data.
Inputs: reserve life, forward commodity curves, peer percentile positioning (ties to Industry Context panel).
Outputs: reserve life/runway at current production; earnings yield vs cycle position; peer percentile on cost curve (low-cost producer = durable advantage = moat); downside scenario at trough prices (pairs with Dalio stress + Munger inversion).
Heaviest data needs. Reserve data often PDF-table/technical-report sourced — distinct extraction problem.

## 4. Sector coverage (v1 = all resource)
Gold mining: AISC vs gold spot (Gold futures/GLD). Base metals copper/zinc: C1 cash cost vs metal spot (Copper futures/COPX). O&G upstream: netback vs WTI/Brent/gas (WTI/Brent/Henry Hub). Streaming/royalty: cash margin near-100%, structurally different (underlying metal basket). Streaming/royalty (FNV/WPM) may need separate handling, same way mining splits producer vs explorer.

## 5. Build order
1. Tier 1 module + panel — standalone resource_economics.py, own tab, yfinance overlay. Demoable, free, no blockers.
2. Tier 2 — gated on MD&A fetcher. Adds AISC/netback flagship.
3. Tier 3 — reserves + cycle positioning. Ties to Industry Context panel.
Dependencies: mining_sector + resource_sector must parse cleanly first (SEDAR campaign). Tier 2 depends on MD&A/HTML fetcher (currently blocked).

## 6. Value-investing alignment
Margin of safety = cost-vs-price spread shown explicitly. Durable advantage = low-cost-producer cost-curve percentile (T3). Downside protection = economics at trough prices (T3 + Dalio/Munger inversion). Owner earnings = through-cycle view, not single-year accounting net income distorted by commodity swings.

## 7. Open questions for build time
Which yfinance commodity proxies are reliable vs needing a real commodity API (FMP Economic Indicators/Sector Performance may help T1). Whether streaming/royalty needs its own economics sub-path. Reserve-data sourcing (T3) — distinct extraction problem.
