# How Analysts Value REITs — and Where FinLens's Coverage Stands

**Date: 2026-07-11**
**Companion to the O&G, mining, and banking coverage-gap reports. Same method, same bucketed structure, same purpose: locate the gap by SOURCE DOCUMENT, not by metric cleverness.**

---

## Method

This report sweeps how sell-side and buy-side analysts actually value real estate investment trusts across four angles — asset-value/NAV valuation, FFO/AFFO earnings, NOI/leasing operations, and capital structure — and asks a single downstream question for each claim: **which document does the number come from, and does FinLens ingest that document today?**

Primary sources were real filings from both accounting regimes: Canadian IFRS filers (RioCan REI.UN, CAPREIT CAR.UN, Dream Industrial DIR.UN, Northview NRR.UN, Choice CHP.UN, Granite, Allied, Morguard MRG/MNR) and US-GAAP filers (Realty Income O, Prologis PLD, EPR, Federal Realty, NNN, Plymouth), plus the governing standard/regulator texts (IAS 40, IFRS 13, IFRS 7, IFRS 16 / ASC 820, ASC 842, ASC 470; the REALPAC White Paper on FFO & AFFO for IFRS (Jan 2022) and its ACFO paper; the NAREIT FFO White Paper (2018 Restatement); and the non-GAAP disclosure rules CSA NI 52-112 and SEC Reg G / Item 10(e)).

**Tally: 24 substantive claims tested → 19 CONFIRMED, 5 REFUTED, 0 unverified.** Every refutation broke on the same axis it was stress-tested on: the source-document attribution. Nothing in this report is left flagged as unverified.

---

## The headline

The REIT gap is **not** that FinLens computes REIT metrics wrongly. It is that the numbers a REIT analyst quotes *first* — FFO and AFFO per unit, AFFO payout ratio, same-property NOI growth, occupancy, NAV per unit, implied cap rate, leasing spreads, WALT — are **structurally absent from the audited financial statements FinLens's mapper keys on.** They are non-GAAP measures that securities rules (NI 52-112 in Canada, Reg G / Item 10(e) in the US) *prohibit* from the audited statements and force into the **MD&A** and the **quarterly supplementary/investor package**. The audited statements supply only the *anchor lines* every per-unit metric reconciles back from: `rental_revenue`, `net_operating_income`, `investment_property_fair_value_delta`, and the balance-sheet spine.

There is one REIT-specific mercy the other sectors don't get: for **IFRS filers**, the single most decision-critical valuation input — the **weighted-average capitalization rate** — is disclosed, audited, in the IFRS 13 / IAS 40 investment-property fair-value **note**, with a range and a sensitivity table. That is a receipt mining's ore-grade assumptions never provide (they live in a separate NI 43-101 technical report). So REIT NAV is *partly* extractable from documents FinLens already ingests — a genuine structural advantage over the mining gap.

And FFO/AFFO is the **fourth instance of a pattern this program has now hit four times**: a company-defined, non-standardized, non-GAAP earnings metric that must be receipted to its own reconciliation and captioned as issuer-defined — after **O&G funds-flow/netback**, **mining AISC**, and **banking adjusted-EPS**. The REIT case is the *most* company-defined of the four: NAREIT explicitly declines to define AFFO at all.

---

## Confirmed findings

### Valuation

**1. IFRS REITs already carry property at fair value on the balance sheet — so "reported NAV" ≈ book equity, and the cap rate is IN the notes.** Unlike US-GAAP REITs (historical cost less depreciation, book value meaningless for NAV), IAS 40 filers revalue investment property each period through profit. *Evidence:* CAPREIT's audited "Valuation of investment properties" Key Audit Matter states investment property fair value of $14,732M "represents 97% of total assets"; the **notes** disclose the market-assumption table (Canada apartments cap rate min 3.66% / max 6.60% / **weighted-average 4.53%**) plus a full sensitivity table (−0.50% → +$1,818,690; +0.50% → −$1,456,151). This is the closest thing to a management-blessed cap rate that exists in any filing. *Caveat (already hedged):* headline "NAV/unit" ($56 at CAPREIT Dec-31-2025) re-adjusts for exchangeable units, deferred tax, and fair value of debt, so it is not literally book equity ÷ units — but the gap to book is far smaller than for a US REIT.

**2. P/FFO and P/AFFO are the relative multiples (the REIT P/E).** P/AFFO is the stricter one because AFFO deducts maintenance capex and straight-line-rent. *Evidence:* RioCan reports "Core FFO per unit – diluted" as a non-GAAP supplemental measure; sector context, RBC ~15× 2025 AFFO for Canadian REITs vs ~17× for US. These live in the MD&A non-GAAP section / supplement, never the audited statements.

**3. Implied cap rate is the back-solve from the traded price** = forward NOI / (market cap + total debt − non-RE assets). A market-implied cap rate *above* the private-transaction cap rate signals a discount to NAV. *Evidence:* RBC (2025) — Canadian REITs 7.1% implied vs US 6.4%, quantifying a ~19% discount. **Two of three inputs (market cap, comp cap rate) have no filed receipt** — this is the ARX-style wrong-issuer trap applied to REITs; forward NOI is itself often analyst-derived. Permanent badge case.

**4. P/NAV premium/discount is the summary judgment** (unit price ÷ modeled NAV/unit), cross-checked against P/FFO, P/AFFO, and yield rather than used alone. *Evidence:* RBC pegged Canadian REITs ~19% below NAV in 2025; RioCan cited units "trading at a significant discount to NAV" as buyback rationale (5.5M units at ~$17.99). It is **model-on-model over market price** — the weakest-link trust surface; never show it without exposing the cap-rate assumption and the price source. *Caveat:* the "persistent double-digit discount" characterization is period- and cap-tier-dependent — large/mid-caps had narrowed to single-digit discounts by Dec 2025; small/micro caps sat at ~25-33%.

**5. The REIT framework deliberately discards the industrial stack** (P/E, EV/EBITDA, standalone DCF). EPS is distorted — US-GAAP depreciation understates it; IFRS fair-value swings make it volatile — so FFO/AFFO replace EPS; the balance sheet (NAV) is the anchor, not the income statement; the market cap rate substitutes for a firm-wide WACC-DCF (DCF/DDM demoted to a secondary check). *Evidence:* NAREIT created FFO in 1991 precisely to reverse historical-cost depreciation; RioCan runs fair-value changes through P&L. This confirms FinLens's existing sector-suppression instinct — a generic EBITDA/EPS or DCF template on a REIT produces a meaningless answer.

**6. Same-property NOI is what feeds forward NAV — and it is supplementary/MD&A-only.** Analysts capitalize *stabilized, same-property* NOI (constant portfolio, excluding acquisitions/dispositions/development) and its YoY growth, not blended income-statement NOI. *Evidence:* RioCan FY2025 3.6% commercial same-property NOI growth, 98.5% occupancy, 37.3% leasing spread — all in the supplement/release, none in the audited statements. This is CB-012 territory's forward twin: CB-012 derives rental-only NOI from *statement* lines; the analyst-grade input is a *different, curated subset* that only exists in the MD&A/supplement (Tier-2 fetcher). *Caveat:* segment NOI itself may sit in the audited IFRS 8 / ASC 280 segment note (Prologis reconciles from Note 18); it is the *same-property cut* specifically that is non-GAAP and MD&A-only.

### FFO / earnings

**7. FFO (NAREIT, US-GAAP) = GAAP net income + real-estate D&A + impairments − property-sale gains.** Its core job is adding depreciation back. *Evidence:* NAREIT 2018 White Paper Restatement, verbatim; Federal Realty and Elme present NAREIT-FFO reconciliations in 8-K exhibit 99.1, not the audited statements. NAREIT itself warns FFO "may not be comparable to FFO reported by other REITs" — standardized in definition, **not enforced in practice**.

**8. REALPAC FFO (Canada, IFRS) is a *different calculation* — its dominant adjustment is reversing unrealized fair-value change, not depreciation.** *Evidence:* REALPAC White Paper (Jan 2022): FFO "should reconcile to IFRS profit or loss" and adjust for "unrealized changes in the fair value of the investment properties." Because IAS 40 does not depreciate investment property, there is no depreciation add-back — the opposite mechanical problem from NAREIT. **NAREIT FFO and REALPAC FFO are not the same metric and are not comparable across the border.** Load-bearing for FinLens's SEDAR focus: a US-trained "add back depreciation" assumption is *wrong* for the IFRS filers FinLens actually maps.

**9. AFFO / ACFO / CAD is company-defined and the least comparable number in the whole filing.** AFFO ≈ FFO − maintenance capex − leasing costs (TI + commissions) − straight-line-rent. *Evidence:* NAREIT explicitly declines to define AFFO ("not adequate consensus… to allow agreement on a single definition"); US synonyms CAD/FAD; Canadian filers add ACFO (REALPAC's IFRS cash-flow measure). CAPREIT reports ACFO and an ACFO payout ratio; Realty Income notes peers use CAD/FAD. Because the maintenance-capex split is a management judgment, **comparing REIT-A's AFFO to REIT-B's without checking each reconciliation produces false peer rankings** — the earnings-side "trust is page-level" problem.

**10. AFFO/ACFO payout ratio (distributions ÷ AFFO/ACFO) is the dividend-sustainability test** — and it lives in the supplement, not the statements. Below 100% = covered by recurring cash; near/above = funded by leverage or capital. *Evidence:* RioCan AIF defines the payout ratios as "measures of a REIT's distribution paying capacity… dividing total Unitholder distributions paid by FFO and AFFO"; Realty Income Q1-2026 "dividend represented 71.7% of diluted AFFO per share"; per-unit metrics are **always diluted**. For a REIT, distribution coverage — not EPS or P/E — is the headline risk metric; FinLens's REIT distress logic should key on payout trending toward 100%.

**11. IFRS net income is misleading for REITs because unrealized fair-value swings flow straight through profit.** *Evidence:* RioCan's own MD&A: "IFRS net income includes items such as fair value changes of investment property… not representative of recurring operating performance." A market-driven revaluation can swing reported net income by hundreds of millions, dwarfing the rental result. This is *the* reason FinLens's REIT profile centers on rental NOI and (eventually) FFO rather than net income — and it validates the CB-012 rental-only design. US-GAAP has the mirror-image problem (net income depressed by non-cash depreciation).

**12. Placement rule — FFO/AFFO are *prohibited* from audited statements; NI 52-112 forces them into the MD&A with an IFRS reconciliation.** *Evidence:* NI 52-112 clause 6(1)(e)(ii)(C) requires a quantitative reconciliation to "the most directly comparable financial measure presented in the primary financial statements" in *both* annual and interim MD&A; US Reg G / Item 10(e)(1)(ii)(C) prohibits non-GAAP measures on the face of the statements or notes. The *only* piece of the FFO reconciliation that lives in the audited statements is the net-income/IFRS-profit anchor. **This is the concrete case where the MD&A fetcher is a hard prerequisite, not a nice-to-have, for REIT earnings coverage** — a statements-only extractor cannot produce any REIT earnings metric.

### NOI / operations

**13. Same-property NOI growth is a non-GAAP MD&A measure, reconciled to IFRS NOI, headlined in the release.** *Evidence:* RioCan release *titles* — "3.6% Commercial Same Property NOI Growth" (FY2025), "4.7%" (Q1-2026). The audited statements carry total portfolio NOI; the same-property subset (stripping acquisitions/dispositions/development) is built only in the non-GAAP disclosure. Treating audited NOI as same-property would be wrong by exactly the acquisition/disposition/development delta. *Routing note:* for US filers the MD&A is Item 7 *inside* the 10-K (a distinct unaudited section), and the detailed reconciliation often lives in the 8-K supplemental — so the fetch target is MD&A **+ earnings release + supplemental**, not MD&A alone.

**14. Leasing spreads split into new / renewal / blended** — three distinct MD&A + supplement numbers, absent from the statements. *Evidence:* RioCan Q1-2026: blended 25.8% (record), **new 58.5%, renewal 20.1%.** The split matters because a high blended spread can be driven by a small volume of new deals while renewals (the bulk of the portfolio) grow slowly — the blended 25.8% sits near the renewal figure, proving renewals dominate volume. FinLens should surface all three with a receipt, never just the flattering blended figure.

**15. In-place vs market rent (mark-to-market upside) is an MD&A/deck management estimate.** *Evidence:* Dream Industrial Dec-31-2025 — estimated market rents exceeded in-place/committed rents by **16.2% (Canada) / 4.1% (Europe)**, with the express caveat that these "are management's estimates… subject to various assumptions and uncertainties." This is the embedded-NOI-growth thesis for industrial/residential REITs but has no filed source for "market rent" → **permanent BADGE case**. *Correction carried:* for IFRS filers the underlying market-rent *estimate* does surface in the audited fair-value note as a Level-3 valuation input; it is the mark-to-market *spread framing* (the "16.2% above in-place" construct) that is MD&A/deck-only.

**16. Tenant retention ratio qualifies the leasing-spread headline** (share of expiring GLA renewed with the existing tenant). *Evidence:* RioCan FY2025 93.1% retention, presented alongside spreads and occupancy; it is a leasing-activity ratio, not a monetary amount, so it falls outside audit scope by construction. Strong spreads at low retention signal churn/downtime; high retention with positive spreads is the ideal. Measurement basis varies (GLA vs tenant count vs rent) — caption accordingly.

### Capital structure

**17. Debt-to-Gross-Book-Value is the Canadian REIT leverage staple — but the binding cap lives in the Declaration of Trust (summarized in the AIF), not IFRS.** *Evidence:* CAPREIT lists "Total Debt to Gross Book Value" among non-IFRS ratios disclosed "in the MD&A"; CT REIT's DoT "limit[s] indebtedness to a maximum of 60% of gross book value, excluding convertible debentures, and 65% including"; RioCan frames its cap as 60% of total-asset book cost. **A parser reading only the audited statements computes a debt/asset ratio that does NOT match the covenant ratio** — GBV, the convertible-debenture treatment (full principal, contradicting IFRS split accounting), and the numerator scope are DoT-defined. To badge covenant headroom, FinLens must lift the ratio and cap from the MD&A/DoT.

**18. Net debt / Adjusted EBITDAFV — the "FV" explicitly strips fair-value gains, defined only in the MD&A Non-IFRS section.** *Evidence:* Choice Properties defines EBITDAFV verbatim as "earnings before interest, taxes, depreciation, amortization, **and fair value**," targeting Adjusted Debt/EBITDAFV below 7.5×; Dream Industrial reports net-total-debt/normalized-adjusted-EBITDAFV (7.3× Q1-2026). **This is a direct hit on CB-023:** FinLens's net-debt/EBITDA metric would be *wrong* for an IFRS REIT if EBITDA is taken raw, because IAS 40 fair-value swings sit inside REIT net income — the FV add-back is the whole point. US-GAAP REITs use NAREIT's EBITDAre instead (depreciated cost → no FV gains to strip).

**19. Interest coverage and Debt-Service Coverage are distinct MD&A/supplemental non-IFRS ratios; DSCR (adds scheduled principal) diverges from plain interest cover.** *Evidence:* Northview NRR.UN Q1-2026 — interest coverage (TTM) 2.2× vs **DSCR (TTM) 1.5×**, the ~0.7× gap being amortization. **CB-023's Interest Cover (EBIT/interest) is *not* DSCR** — for a mortgage-heavy REIT the principal-inclusive DSCR is often the covenant that binds; reporting only interest cover overstates debt-service capacity. *Caveat:* "DSCR adds principal / DSCR binds" holds for secured mortgage REITs; large unsecured investment-grade issuers (Realty Income DSCR 4.5× vs 1.5× floor) label an EBITDA/interest covenant "DSCR" and are bound instead by leverage/unencumbered-asset tests.

---

## Corrections — refuted claims

All five refutations broke on **source-document attribution**, and every one broke on the **IFRS/US-GAAP split** — which is exactly why that split is treated as a first-class axis in the gap analysis below.

**R1. "The cap rate has no receipt in any filing — it is purely the analyst's assumption." REFUTED (categorical error).** True for **US-GAAP** REITs (O, PLD carry real estate at depreciated cost, disclose no portfolio fair value or valuation cap rate — the analyst must supply it from CBRE/JLL surveys). **False for the IFRS filers FinLens actually ingests:** under IAS 40 + IFRS 13, RioCan/CAPREIT/Dream *must* disclose the weighted-average cap rate, range, and stabilized NOI in the audited notes (RioCan attributes fair-value moves explicitly to "capitalization rate assumptions" and "stabilized NOI"). **The NAV methodology and the cap-rate sensitivity math (−50bp on $10M NOI = +9%) are both correct; only the attribution needed the regime fork.** For a Canadian REIT, do *not* badge the cap rate as "not in any filing" — treat the filed weighted-average cap rate as a receipt-backed input.

**R2. "Occupancy never appears in the audited statements because it is not an accounting figure." REFUTED (false absolute).** Headline operating occupancy (RioCan 97.8% portfolio / 98.5% retail committed) is indeed MD&A/supplement-only. But a *stabilized-occupancy / vacancy* figure **does** appear in the audited notes as a Level-3 unobservable input to investment-property fair value (Hines Global stabilized occupancy 90.0%; Logistic Properties of the Americas 98.1-98.2%; Dream Office vacancy assumptions). Keep the operative attribution (operating occupancy → MD&A) but drop the "not an accounting figure" reasoning — it *is* a valuation input in IFRS fair-value-model notes.

**R3. "WALT and the lease-expiry schedule live PRIMARILY in the supplement." REFUTED (regime-dependent).** Correct for Canadian IFRS REITs (supplemental package primary). **Wrong for US-GAAP REITs:** Realty Income and Prologis disclose the year-by-year lease-expiry schedule in **Item 2 "Properties"** and portfolio WALT in **Item 1 "Business"** of the 10-K itself — US REITs generally issue no Canadian-style standalone supplement. Both regimes report on a contractual-expiry basis (no assumed renewals) and both sit *outside* the audited statements — so "absent from audited statements" stands. Caveat: lessor accounting notes (IFRS 16.97 / ASC 842) do carry a dollar-value lease-payment maturity table, distinct from the WALT/expiry-percentage/tenant-concentration risk disclosures.

**R4. "Weighted-average interest rate, WA term, and the maturity ladder exist ONLY in the MD&A/supplement." REFUTED (false exclusivity).** Morguard MNR Note 5 "Mortgages Payable" (a statements-only PDF — everything in it is a *note*) discloses WA interest rate 3.91%, WA term to maturity 5.3 years, *and* a full year-by-year maturity ladder with per-year weighted-average contractual rate. Under IFRS the notes carry both the IFRS 7 liquidity-risk contractual-maturity table *and* the debt-note ladder with WA rate/term and secured/unsecured detail; US-GAAP requires the five-year maturity schedule and WA rate in the notes under Reg S-X / ASC 470. **Genuinely MD&A-only:** the fixed-vs-floating hedge mix, convenience roll-ups, and the refinancing-risk narrative — not the WA rate/term/ladder.

**R5. "The unencumbered asset pool is measured by the percentage of NOI generated, not book value." REFUTED (disclosure-form error).** The definition, its non-GAAP MD&A/supplement home, its role underpinning unsecured covenants, and eligibility rules living in the credit agreements are all **confirmed**. But the *disclosed* metric is book-value-based: RioCan $9.4B dollar pool; Dream Industrial "84.2% of total investment-properties value." The NOI basis ("Unencumbered Pool NOI") is a **covenant-computation** concept inside the unsecured credit agreements (and US bond indentures — Realty Income requires Total Unencumbered Assets ≥ 150% of unsecured debt, a *book* test), not the public headline. Drop "percentage of NOI generated."

**Unverified: none.** Every claim resolved to CONFIRMED or REFUTED against a real filing.

---

## Gap analysis — findings mapped to the FinLens inventory

FinLens's REIT coverage today is a **3-filer, IFRS-only, Canadian-SEDAR v1 baseline** (CAR.UN, DIR.UN, REI.UN), self-described in `sedar_mapper.py` as "a living hypothesis, not a frozen answer." Four sector-specific canonical fields exist — `rental_revenue`, `net_operating_income`, `property_operating_costs`, `investment_property_fair_value_delta` — all tagged `["IFRS"]`; everything else comes from the default profile. The named US fixtures (O, PLD, APLE) **do not exist anywhere in the repo** — so "US-GAAP-vs-IFRS handling for O/PLD" is itself the finding: FinLens has **zero US-GAAP REIT coverage.**

Each finding below is classed **covered / covered-by-CB-012/013 / uncovered**, then bucketed by source document:
- **Bucket A** — already-ingested audited statements + notes (cheap wins, *including the IFRS 13 cap-rate note*)
- **Bucket B** — MD&A-gated (needs the shared MD&A fetcher)
- **Bucket C** — supplementary-package-gated or new-document-class / cross-standard

| # | Finding | FinLens status | Bucket / source document |
|---|---|---|---|
| 5 | Framework discards EPS/EBITDA/DCF | **Covered** (sector suppression instinct exists) | — |
| — | Rental-only NOI + property operating costs | **Covered by CB-012** (lift-vs-derive; REI.UN derived, NOI identity closes) | A (statements) |
| — | total_equity grand-total / total_liabilities as-printed | **Covered by CB-013** (DIR.UN attributable-vs-grand trap handled) | A (statements) |
| 11 | IFRS net income misleading; FV-delta is the noise | **Covered** — `investment_property_fair_value_delta` maps on all 3 | A (statements) |
| 1 | IFRS fair-value cap rate is in the notes → reported NAV ≈ book equity | **Uncovered** — notes not extracted | **A — IFRS 13/IAS 40 fair-value NOTE** (cap rate, range, sensitivity) — the REIT advantage over mining |
| 17 | Debt/GBV + DoT covenant cap | **Partly uncovered** — DIR.UN has debt fields; CAR.UN/REI.UN map no debt | A (statement debt lines) + AIF/DoT for the cap |
| 18 | Net debt / EBITDAFV (FV-stripped) | **Miscovered** — CB-023 raw EBITDA is wrong for a REIT | A (add FV-strip) + B (issuer-defined ratio) |
| 19 | Interest cover vs DSCR | **Partly covered** — CB-023 interest cover ≠ DSCR | A (interest line) + B (DSCR definition) |
| 2 | P/FFO, P/AFFO multiples | **Uncovered** | **B — MD&A non-GAAP** |
| 7,8 | FFO (NAREIT) / FFO (REALPAC, IFRS) | **Entirely absent** (grep: zero FFO aliases) | **B — MD&A reconciliation** |
| 9 | AFFO / ACFO / CAD | **Absent** | **B — MD&A + supplement** |
| 10 | AFFO payout ratio (distress signal) | **Absent** | **B — MD&A + supplement** |
| 12 | Non-GAAP placement rule (NI 52-112) | n/a — *this is why B needs the fetcher* | **B (definitional)** |
| 6,13 | Same-property NOI growth | **Uncovered** (distinct from CB-012 statement NOI) | **B/C — MD&A + supplement** |
| 14 | Leasing spreads (new/renewal/blended) | **Absent** | **B/C — supplement** |
| 15 | Mark-to-market (in-place vs market rent) | **Absent** — BADGE case | **B/C — MD&A/deck** |
| 16 | Tenant retention ratio | **Absent** | **B/C — supplement** |
| 3 | Implied cap rate (back-solve) | **Absent** — 2/3 inputs unreceipted | C (market data + MD&A NOI) — BADGE |
| 4 | P/NAV premium/discount | **Absent** — model-on-model | C (analyst NAV + market price) — BADGE |
| — | US-GAAP REIT support (O, PLD, APLE) | **Absent — largest structural gap** | **C — new document class / cross-standard fork** |

**Statement/notes cheap wins already visible in the fixtures (Bucket A):** CAR.UN and REI.UN map **no debt fields** (D/E unavailable) and CAR.UN maps **no `pretax_income`**; CAR.UN's "Interest expense on debt and other financing costs" −220,162 is unmapped (`interest_expense` alias gap). `red_flag_detector.py`'s `SECTOR_FLAG_RULES` has **no `reit_sector` entry** — REITs get the generic flag set, which will misfire on REIT-normal items (fair-value swings, high leverage-to-assets, negative "net income" in FV-loss years). `equity_accounted_income` and `fair_value_adjustments_financial_instruments` are parked promotion candidates awaiting a 4th REIT.

---

## The cross-standard split, head-on

This is the axis every refutation broke on, and it changes *what FinLens can extract per filer*:

- **Canadian / IFRS REITs (IAS 40 fair-value model):** investment property is carried at **fair value**, revalued each period through profit. The balance sheet is already a mark-to-market NAV; the **weighted-average cap rate is disclosed in the audited notes** (IFRS 13 Level-3), with a range and a sensitivity table. `investment_property_fair_value_delta` is a core, mappable line. NAV is *partly receipt-backed* from documents FinLens already ingests. This is FinLens's current and only REIT reality — all three fixtures, all four sector aliases.

- **US-GAAP REITs (O, PLD, APLE — depreciated cost model):** real estate sits at **historical cost less accumulated depreciation** (Realty Income's Schedule III). There is **no carried portfolio fair value and no disclosed valuation cap rate** — NAV must be **analyst-built** from scratch, and the cap rate genuinely *is* an external assumption (BADGE). `investment_property_fair_value_delta` is structurally **N/A**; the FFO calculation flips from "strip fair-value change" to "add depreciation back"; leverage flips from EBITDAFV to EBITDAre. **A US REIT today would route to `reit_sector` on the "real estate"/"reit" tokens, then fail to match every IFRS rental/NOI/cost alias, find no FV-delta line, and get no FFO path.** This is a **net-new design fork, not an alias extension** — the single largest structural REIT gap.

---

## What FinLens already covers well

The audited IFRS **spine** is solid and honestly disciplined: `rental_revenue`, rental-only NOI and property operating costs via **CB-012**'s lift-vs-derive rule (REI.UN correctly derived, NOI identity closing to the dollar; CAR.UN/DIR.UN lifted), the fair-value delta on all three filers, the balance-sheet spine and the attributable-vs-grand-total equity trap via **CB-013** (DIR.UN's attributable 3,399,261 correctly parked in `unmapped[]`, grand 4,731,073 mapped), D/E where debt maps, and the **CB-014** derived-field discipline that keeps REI.UN at VERIFIED (8/8 line-item-backed fields byte-exact) without sending derived fields to Gemini. Blended subtotals are preserved in `unmapped[]` rather than silently dropped. The mapper's own "living hypothesis" comment is the right posture for an n=3 baseline.

---

## Honest caveats

No paywalled sell-side notes were read; multiples (P/FFO, P/AFFO, discount-to-NAV) are time-varying and cited as illustrative, not current. The build-order ranking below is a build-economics judgment, not a correctness claim. The corpus is **n=3, IFRS-only, all Canadian** — every conclusion about US-GAAP behavior is inferred from real US filings, not from a FinLens fixture that has ever exercised the path.

---

## Open questions for ratification

1. **US-GAAP REIT fork priority** — is it a v2 objective, or deferred until a paying client actually searches O/PLD? (Cold-start vs scaling: the flywheel says the first US-REIT search pays for the fork once.)
2. **FFO reconciliation trust-bridge** — when the MD&A fetcher lands, does a scraped FFO/AFFO number get a VERIFIED path (reconciled back to the mapped net-income anchor it starts from), or is it permanently BADGED as issuer-defined non-GAAP?
3. **Cap-rate-note cross-read as an earnings-quality flag** — a filer whose fair-value gain is driven by *lowering* its cap-rate assumption (not by higher NOI) is a soft red flag; the IFRS note has both levers. Worth a `reit_sector` red-flag rule?
4. **4th-REIT promotion decisions** — `equity_accounted_income` and `fair_value_adjustments_financial_instruments` await a fourth filer; which one, and does it break any CB-012/013 assumption?
5. **Hospitality (APLE room revenue) and triple-net (O straight-line rent) sub-shapes** — untested revenue-recognition patterns even within US-GAAP.

---

## Implications for build order (CC's read, for Riley's ratification)

The REIT gap has the **same shape as O&G, mining, and banking** — the audited statements give the anchor, the analyst's headline number lives in the MD&A/supplement — with one structural bonus (the IFRS cap-rate note is already ingested) and one structural penalty (a whole second accounting standard is missing). FFO/AFFO is the **fourth "company-defined non-GAAP earnings needs a receipt/caption" instance**, after O&G funds-flow/netback, mining AISC, and banking adjusted-EPS; it is the most company-defined of the four, so the caption discipline matters most here.

**Recommended sequence, cheapest-first, maximizing shared infrastructure:**

1. **Bucket A cheap wins now (no new document class).** Add REIT debt-label aliases (mortgages payable, debentures, credit facilities, exchangeable/Class B LP units) so CAR.UN and REI.UN get D/E; add the CAR.UN `interest_expense` and `pretax_income` aliases; add a `reit_sector` entry to `SECTOR_FLAG_RULES` so fair-value swings and negative FV-year "net income" stop misfiring the generic flags; correct the CB-023 leverage metric to strip fair-value change (EBITDAFV) for REITs. **CB-012/013 already cover the NOI + equity core** — these are alias/label extensions on an existing spine.

2. **CB-034-style notes extraction for the IFRS 13 cap-rate / fair-value note.** This is a **reusable notes-extraction build** and the REIT-specific advantage: the weighted-average cap rate, range, and sensitivity table are *already in a document FinLens ingests*. It gives REIT NAV a receipt-backed assumption lever no other sector's technical inputs provide, and the same notes-extraction machinery serves the debt-maturity ladder (R4) and the Level-3 occupancy input (R2).

3. **The shared MD&A fetcher (same build as O&G/mining) unlocks Bucket B.** FFO, AFFO, AFFO payout (the distress signal), same-property NOI growth, occupancy, and leasing spreads all land together the moment the fetcher exists — and NI 52-112 guarantees a *reconciliation* is present, so each number can be receipted to its MD&A table and captioned as issuer-defined. **This is the flagship Tier-2 REIT output.** Every metric here rides infrastructure already justified by three other sectors.

4. **US-GAAP REIT fork + full NAV engine (Bucket C) last.** The depreciated-cost model, depreciation-add-back FFO, EBITDAre, and analyst-built NAV with **badged** cap-rate assumptions are the largest structural build and the least reusable. Under the corpus-flywheel model, the first client search for O/PLD/APLE pays for this fork once — so gate it on demand rather than building it speculatively into a thin corpus.

**The seven-REIT peer set** the task envisioned does not exist yet (only three fixtures do); building toward it — one US-GAAP filer, one hospitality, one triple-net — is the natural way to pressure-test steps 1-4 and to force the 4th-REIT promotion decisions (open question 4). Shared infrastructure means the marginal cost of REIT coverage is low *if* it is sequenced behind the O&G/mining MD&A fetcher rather than ahead of it.
