# How Analysts Cover the Oil & Gas Value Chain — Upstream (Junior / Mid / Large), Midstream, Downstream — and Where FinLens Stands

**Date:** 2026-07-11
**Companion to** the O&G source-document report (`2026-07-10-bank-og-coverage-gaps.md`) and the mining, banking, and REIT coverage-gap reports (`2026-07-11-*`). Same method, same A/B/C source-document buckets, same purpose — locate the gap by SOURCE DOCUMENT, not by metric cleverness. The axis of segmentation here is the **value chain** (upstream junior → mid → large/integrated → midstream → downstream), because that is the shape of Riley's WCSB client base.

---

## Method

Five-segment sweep across the O&G value chain — upstream junior, upstream mid-cap, upstream large/integrated, midstream, downstream — with the analyst framework for each segment tested against real WCSB filers and their actual filings. Verification was adversarial, attacking the **source-document attribution hardest** (which document class actually carries the load-bearing number): the audited statements + notes, the MD&A, the guidance PR / investor deck, or the NI 51-101 reserves report inside the AIF.

**Primary filers cited:** Kelt (KEL), Hemisphere (HME), Saturn, Tamarack Valley (TVE), Spartan Delta (SDE), Greenfire — juniors; Peyto (PEY), ARC Resources (ARX), Tourmaline (TOU), Whitecap (WCP), Baytex — mid-caps; CNQ, Suncor (SU), Cenovus (CVE), Imperial (IMO) — large/integrated; Pembina (PPL), Keyera (KEY), Enbridge (ENB), TC Energy (TCE), Gibson — midstream.

**Tally: 23 confirmed, 1 refuted (corrected), 0 unverified.** The single refutation *improved* the opportunity — it moved a metric FROM the MD&A INTO the already-ingested statement notes (see Corrections).

---

## The headline

**FinLens's O&G coverage is UPSTREAM-ONLY today — and within upstream, statements-only.** Every canonical field, every derived metric, the CB-034 hedging book, the WCSB peer tiers, and all three Resource Economics tiers assume a **price-taking upstream producer** whose economics are *wellhead price − field costs*. That is the correct model for exactly one of the five segments' cost structures.

Two structural facts fall out of the sweep:

1. **Within upstream, the decisive numbers are almost never in the audited statements.** NAV/share, EV per flowing barrel, recycle ratio, RLI, net-debt-to-funds-flow, per-boe netback, funds flow per share, sustaining-vs-growth capex, the corporate WTI breakeven, the tiered FCF waterfall — the metrics a WCSB client actually asks for — live in the **MD&A, the guidance PR/deck, or the NI 51-101 reserves report inside the AIF.** O&G is the *least* statements-resident sector we have mapped (less than mining, far less than banking or REIT). FinLens reads the one document layer that carries the fewest of the answers.

2. **Midstream and downstream are not "harder upstream" — they are DIFFERENT FRAMEWORKS with ZERO current coverage.** Midstream value is *fee-based EBITDA × a multiple*, leverage is *net-debt/EBITDA against an investment-grade target*, the per-unit metric is *distributable cash flow*, and the master variable is *the % of EBITDA that is take-or-pay/cost-of-service* — a filer engineered to be **commodity-price-insensitive**. Downstream value is *crack spread × throughput* with **inverse** exposure to crude. The resource_sector mapper, the WCSB peer tiers, and the commodity-overlay economics all assume the opposite of both. A pipeline filer today **mis-routes into the upstream WCSB producer peer set** and is scored on Net-Debt/CF against E&P names — a category error.

---

## Segment 1 — Upstream Junior (single-play / small-cap WCSB E&P)

The junior thesis is *reserves-based intrinsic value + takeout comp + survival*. Six confirmed findings; every load-bearing input lives outside the audited statements.

1. **NAV/share from 2P NPV10 is the ANCHOR valuation, not a cross-check** — *NI 51-101 reserves report (F1/F2/F3 in the AIF) + reserves PR.* For a junior, sell-side coverage is built around after-tax NPV10 of 2P reserves + cash − net debt ÷ fully diluted shares, expressed directly per share. *Verified:* Kelt's own reserves PR discloses NAV built exactly this way — $22.75/sh (before-tax 2P NPV10, 12/31/2023) against a $5.72 trading price; evaluator Sproule/McDaniel per NI 51-101. Hemisphere: proved NAV $3.18/sh. Greenfire: 2P NPV10-AT $2.7B → $32.89/sh. (Nuance: issuers headline the *before-tax* NAV; analysts rebuild after-tax — both tables sit in the same F1.) For juniors this is the *primary* peg; for large producers NAV is a secondary cross-check behind EV/DACF.

2. **EV per flowing barrel ($/boe/d) and EV/2P are the dominant RELATIVE comps** — *MD&A (production) + reserves report (2P boe) + statements/notes (net debt) + market data (equity value).* These set the takeout-value case that dominates junior theses. *Verified:* Tamarack 2P = 238.256 MMboe gross (McDaniel/GLJ, NI 51-101) is the EV/2P denominator; production 64,331 boe/d (2024 avg) from the operational update is the $/boe/d denominator; large-cap contrast holds (RBC benchmarks CNQ/SU/IMO/CVE on EV/DACF 4–7.5×, not flowing barrels). **The EV numerator embeds an unvalidated market cap — the exact ARX wrong-issuer hazard; back-solving $/boe/d catches a bad market cap.**

3. **Recycle ratio (operating netback ÷ FD&A cost per boe) is the junior-specific capital-efficiency test** — *reserves report (FD&A/FDC/reserve adds) + MD&A (netback per boe).* *Verified verbatim:* Kelt MD&A defines recycle ratio as "operating netback per BOE to FDA&D cost per BOE"; Tamarack the same; FD&A = field + acquisition capital + change in FDC ÷ reserve additions. Kelt FY2024: 2.4× (2P); Tamarack 2025: 5.15×. (Nuance: filers' netback *includes* realized hedging — the four-component definition omits it.)

4. **Production-per-share GROWTH and $/boe/d of new production define the operating thesis** — *MD&A (per-share) + guidance PR (capital efficiency).* Juniors fund growth off a thin base and issue equity, so absolute growth is value-destructive if share count outruns it — everything normalizes per fully diluted share. *Verified:* Kelt AFFO $0.42/diluted sh; Spartan $0.24/diluted sh; the standard WCSB non-GAAP "capital efficiency = capital ÷ new flowing boe/d ($/boe/d)" surfaced verbatim. **The share-count hinge is the same fully-diluted discipline FinLens already applies to NAV/share — but the denominator lives in the statement notes.**

5. **Balance-sheet/funding risk — net debt/funds flow + borrowing-base REDETERMINATION — is a survival question** — *MD&A (ratio, covenants, headroom) + notes (facility terms, drawn balance) + AIF (redetermination risk factor).* A reserves-based facility resets semi-annually against proved-reserve value; a low price cuts the borrowing base and can force repayment — a solvency spiral. *Verified:* Tamarack 2023 AIF p.65 states verbatim that a sustained price decline "could reduce Tamarack's borrowing base... require that a portion, or all, of... bank debt be repaid"; Kelt notes disclose "semi-annual redeterminations on or before June 30 and November 30." **FinLens's D/E (CB-022) is statement-only and collapses to one ratio — the funding cliff is invisible on otherwise-clean financials.**

6. **Single-asset concentration + high corporate base-decline are the defining risk overlays** — *AIF (property descriptions, concentration risk) + reserves report (RLI) + corporate presentation (type curves, base-decline %).* *Verified:* Tamarack — ~70% of 2026 capital in the Clearwater alone; ~22% corporate base decline; ~$265M sustaining capital just to hold flat; Clearwater 2P "nine years of equivalent production" (RLI). A junior can screen cheap on EV/2P yet be un-investable on a 40% decline or single-pool dependence.

---

## Segment 2 — Upstream Mid-Cap (intermediate WCSB producer)

The mid-cap thesis is *sustainability — does free funds flow at strip cover sustaining capex + dividend?* Six confirmed findings. The whole model is MD&A/deck-resident.

7. **Net debt / funds flow is the WCSB leverage anchor — an MD&A non-GAAP ratio, not a statement line** — *MD&A capital-management/non-GAAP section (numerator components trace to balance sheet + debt note).* Analysts lead with net-debt/FFO (often against a forward-year cash-flow forecast), not US-style net-debt/EBITDA, and every producer publishes an explicit target. *Verified:* Peyto MD&A labels both net debt AND funds from operations non-GAAP, reconciled at the end of the MD&A; ARC target "1.0–1.5× annualized FFO"; Whitecap ~1.0×, forecast 0.5× at YE2026 on strip. **The denominator (funds flow) lives in a different document than the numerator (balance-sheet net debt) — a statements-only mapper cannot reproduce the analyst-facing ratio.**

8. **Operating netback per boe is the core margin metric, defined only in the MD&A** — *MD&A non-GAAP netback table + operational production tables.* No cost-of-goods line exists, so gross margin is genuinely N/A; the WCSB analog is netback = realized price − royalties − opex − transportation, per boe. *Verified:* ARX netback "commodity sales − royalties, operating, transportation... per boe = netback ÷ weighted average daily production," non-GAAP, "may not be comparable to... other entities"; TOU's *operating* netback **includes** realized hedging + risk-management premiums — **same name, materially different components.** This confirms and extends CB-024: FinLens produces the netback *margin %*, but the **$/boe figure the client quotes needs the production-volume denominator, which is an MD&A datum** — the per-barrel netback stays DEFERRED until the MD&A fetcher lands, and the card must disclose *which* netback variant it computed.

9. **Funds flow (FFO) and per-share FFO / free funds flow are the WCSB earnings substitute** — *MD&A non-GAAP reconciliation to the cash-flow statement's operating-activities subtotal.* Intermediates are valued on FFO and free funds flow (FFO − capex), per diluted share, NOT IFRS EPS. *Verified:* Whitecap FY2024 — CFO $1,833.5M − working-capital change $(201.3)M = funds flow $1,632.2M, reported $2.74/$2.73 per share; ARC free funds flow per diluted share, reconciled to CFO. **This is the 4× "company-defined non-GAAP earnings needs a receipt" pattern (see cross-chain note): FFO is CFO *before working-capital changes* — mapping the raw IFRS "cash from operating activities" subtotal alone disagrees with the analyst-quoted FFO/share by the working-capital swing. CB-021 maps OCF+capex → FCF; it does not reproduce FFO.**

10. **Reserve life index, F&D cost, recycle ratio, FDC live in the NI 51-101 reserves disclosure inside the AIF — a separate annual filing** — *Forms 51-101F1/F2/F3 in the AIF; preliminary reserves PR precedes it.* *Verified:* Peyto's reserves PR states verbatim the "51-101F1... F2... F3 will be available in the Annual Information Form to be filed by the end of March," evaluator GLJ; Whitecap names McDaniel and FDC "$12.8B undiscounted" as a 51-101/AIF construct. **RLI is itself analyst-DERIVED = reserves (AIF) ÷ production (MD&A) — a cross-document computation, structurally unreachable from the two documents FinLens ingests today.**

11. **Sustainability = can free funds flow cover maintenance capex + dividend — an MD&A + guidance/presentation construct** — *MD&A operational discussion + guidance PR + investor deck; dividend is a board declaration.* *Verified:* Whitecap — at US$60 WTI, ~$3.3B funds flow → $2.1B capex, $0.9B dividends, $0.3B buyback/debt; "$29.50 breakeven per boe," "dividend fully funded at ≤$50 WTI," "low 20% decline." **Decline rate and capital efficiency are forward, management-asserted figures — unaudited context data that must be BADGED per the page-level-trust rule.** FinLens cannot derive dividend safety — the thing a client actually asks — from the statements alone.

12. **Production mix (gas / oil / NGL / condensate) reframes the whole model** — *MD&A production tables + results PR; absent from audited statements.* Gas-weighted (TOU, PEY) vs oil/liquids-weighted (Baytex, WCP) vs condensate-rich changes the netback, the benchmark (AECO/NYMEX vs WTI/MSW vs condensate premium), and the hedge. *Verified:* ARC 2025 = 374,336 boe/d, 59% gas / 41% liquids; a programmatic scan of ARC's audited statements returned **0 per-product revenue splits and 0 production volumes** — the face carries one aggregate "commodity sales" dollar line. **FinLens's resource_sector canonical `revenue` is exactly that single gross-sales figure (per CLAUDE.md semantics), which ERASES the mix that makes two intermediates comparable or not.** Peer comparison across intermediates is invalid without it. (Post-IFRS-15 a *note* may disaggregate the dollars — never the volumes.)

---

## Segment 3 — Upstream Large / Integrated (senior + oil-sands)

The senior thesis is *return-of-capital resilience — a step-function of the balance sheet.* Six confirmed findings.

13. **The shareholder-return waterfall is governed by explicit net-debt TIERS, not a payout ratio** — *MD&A capital-allocation / non-GAAP section + quarterly PRs.* *Verified:* CNQ (as adjusted Oct 2024) — 60/40 FCF split until $15B net debt, 75/25 between $12–15B, 100% at ≤$12B (superseding the earlier single $10B / 100% rule); Cenovus 50% of EFFF between $9.0–4.0B, 100% at the $4.0B floor. FCF/EFFF is company-defined ("adjusted funds flow less dividends, net capex and abandonment") — reconcile, don't trust at face value. **Modeling a flat payout ratio (the junior/mid habit) mis-forecasts buyback pace; the entire distribution thesis hinges on where net debt sits vs named thresholds — a number that moves quarterly.** (Freshness: date-stamp both waterfalls — CNQ recut around Chevron 2024, Cenovus around MEG Dec 2025.)

14. **Corporate WTI breakeven per barrel — opex + sustaining capital + base dividend as one figure — is an investor-deck metric** — *Investor Day / quarterly deck (supplementary financial measure); inputs trace to MD&A/statements.* *Verified verbatim:* Suncor defines "Corporate WTI breakeven price" as "the U.S. dollar WTI price per barrel that is equal to Suncor's operating costs, dividend payment amount and sustaining capital on a per barrel basis"; trajectory ~$60 (2023) → ~$45 (2025) → ~$37/bbl target (2028 Investor Day); Cenovus ~US$45 WTI covers sustaining capital + base dividend. **Issuer-set definition (what counts as "sustaining"; base vs total dividend) → two breakevens aren't comparable; no auditor receipt → badge-not-replace.**

15. **Long-life / low-decline is a booked, quantified reserves attribute (RLI) in the AIF's NI 51-101 disclosure** — *Statement of Reserves Data (F1) in the AIF; NOT the audited financials.* *Verified exact:* CNQ — total proved 15.231 Bboe (+9%), proved RLI 33 yrs, 2P RLI 44 yrs, ~74% long-life/low-decline, Oil Sands Mining proved RLI ~43 yrs. Mining declines flat-then-cliff; SAGD declines gradually — mixing the two mis-models sustaining capital and terminal value. (Correction: these are FORECAST-price, escalated-cost reserves per COGEH, *not* year-end constant prices.)

16. **Sustaining / maintenance capital — not total capex — gates the FCF waterfall, an MD&A non-GAAP split** — *MD&A non-GAAP section; the cash-flow statement shows only total capex.* *Verified verbatim:* CNQ MD&A — "Maintenance capital is a supplementary financial measure that represents the capital required to maintain annual production at prior period levels"; the breakeven = adjusted funds flow − maintenance capital − dividends. **A producer can flatter its breakeven by classifying maintenance spend as growth — the highest-leverage badge-and-reconcile field in the senior model, with no statement line.** (Precision: CNQ's *own* disclosed FCF subtracts *total* net capex; sustaining-capital-based FCF is analyst convention. Note also CNQ's "net capital expenditures" now INCLUDES acquisitions — the opposite of FinLens's CB-021 M&A exclusion — so the issuer's headline capex must never be lifted blindly.)

17. **The distribution MIX (buyback vs base vs variable/special dividend) is a disclosed policy choice; cumulative-return-of-market-cap is the seniors' scorecard** — *quarterly PRs + MD&A + separate NCIB notices + investor decks.* *Verified:* Cenovus routes 100%-of-EFFF via "share buybacks and/or variable dividends" (variable = the flex valve); Suncor ">70% of average market cap returned 2016–2025 (~$46B)"; CNQ 25-year dividend-increase streak + ~178.7M-share NCIB. **Scattered across three document types; the cumulative-%-of-market-cap figure is an issuer-constructed marketing metric — badge, don't trust blindly.**

---

### Cross-chain finding (integrated producers)

18. **Integrated margin capture is a physical hedge on the WCS–WTI differential — visible ONLY in the MD&A's SEGMENTED (upstream vs downstream) results** — *MD&A segment results + AIF/10-K business description; the consolidated income statement nets it away.* A wide heavy-oil differential HURTS the upstream barrel but HELPS the downstream refinery buying discounted heavy crude. *Verified verbatim:* Cenovus MD&A — "integrated upstream and downstream operations help to mitigate the impact of volatility in light-heavy crude oil differentials"; Suncor's "pit-to-pump" 5-2-2-1 refining-margin index; Imperial Q1-2026 split the effect by segment. **An analyst modeling an integrated as a pure upstream producer gets the differential-sensitivity sign backwards.** This is the bridge into the two segments FinLens has zero coverage of.

---

## Segment 4 — Midstream (pipelines, gathering & processing, storage)

**A DIFFERENT FRAMEWORK. Zero current FinLens coverage.** The only midstream reference in the entire codebase is an *exclusion* — `resource_economics.py` line 178: "Gas Gathering and Processing is midstream, not a producer, and gets no commodity benchmark." Five confirmed findings, none of which the resource_sector mapper can touch.

19. **Fee-based vs commodity-exposed EBITDA mix is the master variable** — *MD&A non-GAAP section + investor deck; segment note for the Infrastructure-vs-Marketing split.* This is the analog to an upstream analyst's commodity-price deck — it sets the multiple, the leverage tolerance, and the fundable payout. *Verified:* Keyera MD&A defines "Fee-based adjusted EBITDA" as a management-defined non-GAAP measure separating fee-for-service (Gathering & Processing + Liquids Infrastructure) from the commodity-exposed Marketing segment; Pembina ~80–90% fee-based; TC Energy 97–98% cost-of-service/take-or-pay. **Blending Marketing commodity margin into a "stable cash flow" thesis is the core midstream mis-analysis — and FinLens has no fee-based field.**

20. **Contract type AND tenor (take-or-pay / ship-or-pay / cost-of-service) determine cash-flow quality** — *MD&A business review + AIF contract profile + investor deck; supported by revenue-recognition/commitments notes.* Take-or-pay removes volume risk; cost-of-service removes volume AND price risk (regulated return); fee-for-service retains volume risk. Weighted-average remaining tenor is the durability measure. *Verified:* Pembina's Peace/Northern volumes "under long-term, firm, take-or-pay contracts," BC lines "cost-of-service... negotiated return on invested capital," uncontracted capacity "interruptible"; weighted-average firm term ~8 yrs (YE2025); TC Energy sanctioned a US$1.5B expansion on a 20-year 100% take-or-pay. **Two midstream filers with identical EBITDA can carry entirely different risk — unreachable from the statements.**

21. **Distributable Cash Flow (DCF) and the DCF payout ratio replace EPS as the primary per-share metric** — *MD&A non-GAAP section, bridged from CFO; guidance PR for forward DCF/share.* IFRS net earnings are crushed by non-cash D&A on massive asset bases, so analysts use DCF (Distributable, not Discounted), DCF/share, and payout = dividends ÷ DCF. *Verified:* Keyera — "distributable cash flow was $159M or $0.69 per share," payout defined as dividends declared ÷ DCF, target 50–70%; Pembina "adjusted cash flow from operating activities per share"; Enbridge 60–70% DCF payout (~65% actual). **This is the SECOND midstream instance of the "company-defined non-GAAP earnings needs a receipt" pattern (now 4× total): upstream FFO/free-funds-flow AND midstream distributable cash flow are the same defect class — a management-defined per-share cash metric, reconciled only in the MD&A, that must be badged with its definition string captured, never taken as a statement line.** The confusion this prevents: "Enbridge's earnings payout looks alarming, but its DCF payout is fine."

22. **Maintenance vs growth capex split is what makes DCF ≠ operating cash flow — and it is buried in the MD&A** — *MD&A capital-expenditures / non-GAAP reconciliation; the cash-flow statement shows total PP&E additions as one line.* DCF deducts MAINTENANCE capex (sustaining); GROWTH capex is not deducted (it builds the secured backlog). *Verified:* Keyera guides maintenance (~$140–160M for 2026) vs growth (~$400–475M) separately, both non-GAAP; Pembina "sustaining capital"; MLP practice confirms it is a subjective management estimate (filers lacking it assume 80/20). **If FinLens takes total PP&E additions as "capex" for a coverage calc, it double-counts growth capex against the dividend and understates coverage — the correct midstream math needs the MD&A maintenance-capex line.**

23. **EV/EBITDA is the primary multiple and net-debt/EBITDA the primary leverage gauge, anchored to an explicit investment-grade target** — *balance sheet + debt note (net debt, incl. hybrids agencies part-weight as equity) + MD&A non-GAAP (adjusted EBITDA); target from MD&A/deck; EV pulls market cap (badge).* *Verified:* Keyera target 2.5–3.0× net debt/adjusted EBITDA "while maintaining investment grade (BBB)"; Pembina proportionately-consolidated 3.5× within investment-grade guardrails; Pembina hybrid subordinated notes carry a 50% DBRS equity weight. Trading multiples ~10.5× (KEY), ~11.2× (PPL), ~16.1× (TCE). **FinLens's Debt/Equity RAG check (CB-022) is the WRONG leverage lens for midstream — the sector lives on net-debt/EBITDA against a stated target, and the multiple is EV/EBITDA not P/E. EV embeds market cap — the ARX-style unvalidated-data poisoning risk.**

---

## Segment 5 — Downstream / Refining & Marketing

**A DIFFERENT FRAMEWORK. Zero current FinLens coverage.** No crack-spread, refining-margin, throughput/utilization, or fuel-marketing field exists in the codebase; "refin-" appears only in unrelated `education_content.py` prose. In WCSB this segment is mostly *inside* the integrateds (Suncor/Petro-Canada, Imperial, Cenovus refining), so its economics surface only through the segment note (Finding 18) — which is precisely why an integrated read backwards without it.

The downstream framework, stated for the build map (self-evident from Finding 18's mechanics; not separately fixture-verified here — see caveats):

- **Crack spread** (e.g., 3-2-1 / Suncor's 5-2-2-1) — the margin between refined-product prices and crude feedstock — is the value driver, with **inverse exposure to crude**: a cheap/discounted heavy barrel *widens* the refiner's margin. This is the opposite sign to every upstream field in FinLens.
- **Refining margin per barrel** — an issuer-defined index (Suncor's 5-2-2-1), an MD&A/deck supplementary measure, not a statement line.
- **Throughput & utilization %** — refinery/upgrader volumes and capacity use — operational MD&A/segment data; the correct "output" denominator (EV/throughput), not boe/d.
- **The commodity-overlay economics module is not merely absent — it would MISLEAD:** `resource_economics.py` fuses commodity *spot* with fundamentals for a *price-taker*. A downstream filer's correlation/beta to crude is *inverse*; a midstream filer's is ~zero by design (that is the product). Running either through the upstream overlay produces a confidently wrong card.

---

## Corrections — refuted claims

**REFUTED (1): "The forward hedge schedule is MD&A/presentation-only; the note carries only the mark."** The two-layer skeleton is half right, but the load-bearing source-document attribution is WRONG — and the correction *moves data into an already-ingested document*, improving the opportunity.

*Verified against ARC FY2014 (SEC 6-K 0001029509-15-000003, statement pp. 60–63) and Whitecap FY2024 consolidated statements:* the granular, contract-by-contract **forward hedge schedule — volumes by commodity, by term, at swap/floor/collar strikes — lives IN the audited financial-statement derivatives note (an IFRS 7 requirement), not the MD&A.** ARC's note tabulates "WTI 3-Way 4,000 bbl/d, Jan–Jun 15, 90.00/65.00/100.00," AECO basis swaps to 2019; Whitecap's lists "WTI Swap Jan–Dec 2026 22,500 bbls/d C$91.55" term by term — MORE granular than the MD&A narrative. **The corrected attribution:** the note carries BOTH the balance-sheet fair value + period realized/unrealized AND the full forward strike schedule. The MD&A/deck adds only the **% of forecast production hedged** (the note gives absolute volumes/strikes, not the %).

**This directly validates CB-034.** The hedging book is a Bucket-A / already-ingested-notes win, exactly as shipped: `extract_hedging_note`, the `derivative_gains_concentration` red flag, and the `hedging_fair_value_bs_tie` integrity rule read the note — the correct source. The only MD&A-gated residual is the % of production covered.

---

## Gap analysis — value chain vs the FinLens inventory (A/B/C by source document)

Buckets: **A** = already-ingested audited statements + notes (cheap wins, no new document class — the CB-034 hedging-note extractor shape). **B** = MD&A-gated (blocked on the shared MD&A fetcher — one fetcher, N sectors; maps to Resource Economics **Tier 2**). **C** = new document class / deep moat (NI 51-101 reserves report in the AIF; maps to **Tier 3**). **NEW-PROFILE** = requires a distinct sector profile + peer set + economics path, like the REIT/insurance routing fork.

| # | Finding | Segment | Status in FinLens | Bucket |
|---|---------|---------|-------------------|--------|
| 2,4 | Fully-diluted share denominator (NAV/sh, prod-per-sh) | jr | **Covered** — same discipline as NAV/share; shares in notes | A |
| Hedge | Forward hedge schedule + fair value + realized/unrealized | jr/mid | **Covered — CB-034** (`extract_hedging_note`, concentration flag, BS-tie rule) | A |
| 1 | NAV/share from 2P NPV10 (anchor for juniors) | jr | Uncovered | C |
| 2 | EV per flowing barrel ($/boe/d) | jr | Uncovered — needs production (B) + 2P (C) + net debt (A) + mkt cap (badge) | B+C |
| 2 | EV/2P ($/boe of reserves) | jr | Uncovered | C |
| 3 | Recycle ratio (netback ÷ FD&A) | jr | Partial — CB-024 gives margin %; FD&A/FDC uncovered | B+C |
| 4 | Production-per-share growth; $/boe/d capital efficiency | jr | Uncovered — volumes MD&A; cap-eff PR/deck | B |
| 5 | Net-debt/funds-flow + borrowing-base redetermination | jr/mid | Partial — CB-022 gives statement D/E; ratio + redetermination risk uncovered | B (+C for AIF risk factor) |
| 6 | Single-asset concentration; base-decline %; RLI | jr | Uncovered | B (decline/type-curve) + C (RLI/reserves) |
| 7 | Net debt / funds flow (WCSB leverage anchor + target) | mid | Uncovered — numerator A, denominator + target B | B |
| 8 | Operating netback **per boe** ($/boe) | mid | Partial — **CB-024 margin % covered**; $/boe deferred on volumes | B |
| 9 | Funds flow (FFO) + FFO/free-funds-flow per share | mid | Partial — CB-021 maps OCF+capex→FCF; FFO (pre-WC) + per-share uncovered | B |
| 10 | RLI, F&D cost, recycle, FDC (reserves) | mid | Uncovered — NI 51-101 in AIF | C |
| 11 | Sustainability / WTI-AECO breakeven / payout | mid | Uncovered — guidance PR/deck; badge as issuer-asserted | B |
| 12 | Production mix (gas/oil/NGL/condensate) | mid | Uncovered — canonical `revenue` erases the split | B |
| 13 | Tiered net-debt→FCF waterfall (non-GAAP FCF/EFFF) | lg | Uncovered — MD&A capital-allocation | B |
| 14 | Corporate WTI breakeven ($/bbl) | lg | Uncovered — investor deck; badge | B |
| 15 | RLI + decline shape (mining vs SAGD), long-life % | lg | Uncovered — NI 51-101 in AIF | C |
| 16 | Sustaining vs growth capex split | lg | Partial — CB-021 total capex covered; maint/growth split uncovered | B |
| 17 | Distribution mix (buyback/base/variable) + NCIB + scorecard | lg | Uncovered — PRs + NCIB notices + deck | B |
| 18 | Integrated margin capture (segment upstream vs downstream) | cross | Uncovered — MD&A segment note; consolidated top line nets it away | B / **NEW-PROFILE** |
| 19 | Fee-based vs commodity EBITDA mix (master variable) | mid-stream | **Uncovered — no field of any kind** | **NEW-PROFILE** + B |
| 20 | Contract type + tenor (take-or-pay/cost-of-service) | mid-stream | **Uncovered** | **NEW-PROFILE** + B/C(AIF) |
| 21 | Distributable Cash Flow + DCF payout ratio | mid-stream | **Uncovered** | **NEW-PROFILE** + B |
| 22 | Midstream maintenance vs growth capex (DCF ≠ OCF) | mid-stream | **Uncovered** | **NEW-PROFILE** + B |
| 23 | EV/EBITDA + net-debt/EBITDA vs IG target | mid-stream | **Wrong lens applied** — CB-022 D/E + upstream Net-Debt/CF peer mis-route | **NEW-PROFILE** |
| DS | Crack spread / refining margin / throughput / utilization | down-stream | **Uncovered — inverse-crude framework; overlay would mislead** | **NEW-PROFILE** + B |
| Route | Peer tiering + commodity overlay | mid/down | **Mis-routes** — pipeline → upstream WCSB peer set; downstream → wrong-sign beta | **NEW-PROFILE** |

**The plain-language findings the table encodes:**

- **Upstream is well-served on the statement spine and mis-served on everything a client asks.** Bucket A for upstream is essentially *done* — gross-of-royalties revenue (CB-025), DD&A incl. impairment (CB-026), OCF, capex PP&E+E&E (CB-021/029), EBIT/EBITDA/interest-cover (CB-022/023), netback margin % (CB-024/030), balance-sheet identity, and the CB-034 hedging book. But NAV, EV/boe, RLI, recycle, net-debt/FFO, per-boe netback, FFO/share, breakeven, and the FCF waterfall are all Bucket B or C. **Upstream's remaining gap is 80% one shared MD&A fetcher (B) + one reserve-report document class (C)** — the same two builds the mining, banking, and REIT reports converge on.

- **Midstream needs a NEW SECTOR PROFILE, not the MD&A fetcher alone.** This is the REIT/insurance-routing precedent, not the CB-034 note-extractor precedent. A midstream template must (a) route to a distinct peer set (Enbridge/TC Energy/Pembina/Keyera — none exist today), (b) swap the leverage lens from Debt/Equity to net-debt/EBITDA-vs-IG-target, (c) lead with DCF and DCF-payout not EPS, (d) surface fee-based-% as a headline field, and (e) **suppress the commodity-overlay economics** (a fee-based filer's crude beta is ~zero by design — the card would mislead). The MD&A fetcher then fills the fee-based-%, contract-tenor, DCF, and maintenance-capex values *into* that profile.

- **Downstream needs the same new-profile treatment with an inverse-sign economics path.** Crack spread and throughput are the value drivers; crude exposure is inverse. In WCSB this mostly lives inside the integrateds, reachable only via the MD&A segment note (Finding 18) — so an integrated-producer read is *wrong today* (modeled as pure upstream, differential sign backwards) until a segment-aware path exists.

- **The routing bug is real and shippable-to-flag now.** `peer_comparison.py` `_SECTOR_KEYWORDS` maps "pipeline" and "oil sands" into the same generic Energy → upstream-WCSB bucket, and `_net_debt_to_cash_flow` is an upstream leverage convention. A pipeline filer is scored on Net-Debt/CF against CNQ/SU/TOU — a category error. The tier buckets are manual picks (the CB-027 lesson: the sector string can't reveal tier); adding a midstream tier + a keyword guard that *refuses* to place a midstream filer in an upstream set is a cheap, high-value guardrail even before the full profile lands.

---

## What FinLens already covers well (upstream statement spine)

The audited-statement layer for a WCSB **upstream producer** is genuinely strong and correctly bounded: gross-of-royalties top line with the negative rule + machine-enforced `suppressed_default_aliases` (CB-025), royalties stored negative, DD&A with the impairment-combined semantics added back in EBITDA (CB-026), operating/transportation opex (CB-024/030), E&E capex whose *presence is the sector signal* (CB-021/029), the CB-034 hedging book (fair value + realized concentration flag + BS-tie rule — the correct notes-layer read, as the refutation confirmed), Debt/Equity with lease + M&A exclusions (CB-022), EBIT/EBITDA/interest-cover/leverage (CB-023), netback margin % (CB-024), multi-commodity benchmark linkage (CB-027), and the assets ≡ liabilities + equity identity. Honest suppressions are in place (D/E and EBIT/EBITDA gated off for financial/insurance filers). Resource Economics **Tier 1** (filing × yfinance overlay, netback-vs-crude framing) is built.

---

## Honest caveats

- **No paywalled sell-side notes were sourced** — the "how analysts cover it" claims are inferred from issuer disclosures (MD&A, reserves PRs, AIFs, decks) + independent methodology references, then verified against those primary filings.
- **EDGAR/issuer 403s and rate-limits** were worked around by using cached/mirror copies (boereport.com, globenewswire, company IR PDFs); a small number of deck figures (e.g., contract roll-off bar charts) are attested by the weighted-average figure they summarize, not the chart image.
- **Downstream is thinner-verified than upstream/midstream** — the crack-spread/throughput framework is stated from Finding 18's confirmed segment mechanics and standard practice, not from a dedicated pure-play WCSB refiner fixture (WCSB downstream is mostly integrated). Treat the downstream rows as design-direction, not fixture-confirmed.
- **Multiples and net-debt bands are time-varying** — every EV/EBITDA, leverage ratio, and breakeven cited is period-stamped and will drift; the *structure* (which document, which metric family) is the durable finding, not the number.
- **The build-order ranking below is judgment**, for Riley's ratification, not a machine-derived priority.
- **Fixture count:** upstream evidence rests on 6 pure-WCSB-producer fixtures already in-corpus (CNQ, SU, TOU, ARX, WCP, PEY); midstream/downstream have **n=0 fixtures** in FinLens today — a first midstream fixture (Pembina or Keyera) is a prerequisite for any midstream profile work.

---

## Open questions for ratification

1. **Midstream: new sector profile — confirm the REIT/insurance-routing precedent applies** (distinct peer set + leverage lens + DCF-led card + commodity-overlay suppression), not a resource_sector alias extension?
2. **DCF naming collision** — "DCF" means Distributable Cash Flow in midstream and Discounted Cash Flow in the existing `dcf_calculator.py`. Confirm the midstream field is labeled `distributable_cash_flow` to avoid the collision.
3. **Fee-based-% as a headline field** — it is management-defined non-GAAP with no statement receipt. Confirm it ships as a badge-with-MD&A-receipt field with the definition string captured (the 4× non-GAAP-receipt pattern)?
4. **Routing guardrail first** — do we ship the "refuse to place a pipeline filer in the upstream peer set" guard *now* (cheap, prevents a live category error) ahead of the full midstream profile?
5. **Downstream scope** — cover it only as an integrated *segment* read (via the MD&A segment note, Finding 18) rather than a standalone refiner profile, given WCSB has almost no pure-play downstream?
6. **NI 51-101 document class** — confirmed shared with the mining NI 43-101 lift (Bucket C / Tier 3); same F1/F2/F3-in-AIF ingestion, evaluator sign-off parsing?

---

## Implications for build order (CC's read — for Riley's ratification)

Sequenced cheapest-first, maximizing shared infrastructure, weighted to Riley's WCSB client base (upstream producers are the majority; midstream is a large and currently-mis-served minority; pure downstream is rare).

1. **Routing guardrail (days, no new infra).** Add a midstream keyword guard to `peer_comparison.py` so a "pipeline"/"gathering"/"midstream" filer is NOT dropped into the upstream WCSB producer set, and suppress the commodity-overlay economics card for it. This stops a live category error (Finding 23 mis-route) before any profile work. Highest value-per-hour item in this report.

2. **The shared MD&A fetcher (Bucket B — Tier 2).** The single highest-leverage build across *all four* coverage reports. For O&G it unlocks, in priority order: production volumes + commodity mix (Finding 12 — the denominator for the entire per-boe family and the fix for the erased-revenue-split problem), per-boe netback (Finding 8 — completes CB-024's deferred $/boe), net-debt/FFO + FFO/share (Findings 7, 9 — the mid-cap leverage + earnings substitute), then breakeven/waterfall/sustaining-capex (Findings 11, 13, 14, 16). One fetcher, five segments' worth of Tier-2 metrics.

3. **Midstream sector profile (NEW-PROFILE, on top of the fetcher).** Once the fetcher exists, stand up the midstream template: peer set (ENB/TCE/PPL/KEY), net-debt/EBITDA-vs-IG-target leverage, DCF + DCF-payout card, fee-based-% headline (badged, definition captured), contract-tenor field. Requires a first midstream fixture (Pembina or Keyera) — currently n=0. This is where FinLens converts a *mis-served* WCSB client segment into a served one.

4. **NI 51-101 reserves document class (Bucket C — Tier 3).** Shared with the mining NI 43-101 lift. Unlocks NAV/share (junior anchor, Finding 1), EV/2P, RLI, recycle/FD&A, FDC (Findings 2, 3, 6, 10, 15). Deepest structural lift, annual-only cadence, independent-evaluator sign-off — the moat. Highest analytical value for juniors specifically, so its priority rises with the junior share of the client base.

5. **Downstream / integrated-segment read (NEW-PROFILE, narrowest).** Segment-note extraction (Finding 18) so an integrated (SU/IMO/CVE) is no longer modeled backwards as pure upstream, plus crack-spread/refining-margin framing. Lowest WCSB pure-play demand; sequence last, but note it also *fixes the integrateds*, which are core WCSB names — so its value is partly upstream-large, not only downstream.

**Shared-infrastructure summary (the reason this sequence is cheap):** one **MD&A fetcher** serves upstream Tier-2, midstream DCF/fee-based, and downstream refining-margin simultaneously (∥ mining/banking/REIT). The **CB-034 hedging-note extractor** shape is the proven Bucket-A pattern and, per the refutation, already reads the correct document. The **NI 51-101 reserves document class** is shared with mining's NI 43-101. The **non-GAAP-with-receipt badge** (now 4× — upstream FFO/free-funds-flow, corporate breakeven, midstream distributable cash flow, fee-based EBITDA-%) is one reusable discipline: capture the definition string, trace to the MD&A, never lift as a statement line. The only genuinely *new* build the value chain forces is **sector-profile routing for midstream/downstream** — and that is the same REIT/insurance fork FinLens has already executed twice.
