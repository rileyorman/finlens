# How Bank Research Analysts Analyze Mining Filings — and Where FinLens's Coverage Stands

**Research report — 2026-07-11**

This report is the mining-sector companion to `docs/research/2026-07-10-bank-og-coverage-gaps.md`. The ask: reconstruct how sell-side mining desks (BMO, RBC, Scotia, CIBC, NBF, Canaccord) actually value and monitor gold and base-metals issuers, then map every load-bearing metric to the document class it lives in — and to what FinLens ingests today. Method: a four-angle sweep (valuation, costs, reserves, operations) fanned out across sell-side/IB valuation references, regulator texts (NI 43-101, Form 51-102F2, CIM Definition Standards, IFRS 6/15), the World Gold Council Guidance Note, and the primary filings of real Canadian/IFRS miners; each claim was then adversarially verified — with the source-document attribution attacked hardest — against issuer disclosures. Tally: **20 confirmed, 4 refuted (corrected below), 0 unverified.**

Primary sources verified against (real filers): **Agnico Eagle (AEM)** FY2024/FY2025 Annual Report, AIF, 40-F Ex-99.1, MD&A, Q3 2025 / Q4-FY2025 news releases; **Barrick** FY2021–FY2025 40-F/6-K MD&A and reserves releases; **Teck Resources** 2024/2025 MD&A and 40-F; **Hudbay, Lundin, First Quantum, Capstone, Freeport, Hecla, B2Gold, Goldcorp, Newmont** MD&A/6-K/8-K exhibits; **New Gold, Franco-Nevada, Wheaton, Royal Gold** (streamer/royalty); NI 43-101 technical reports (Cartier Chimo PEA, Silvercorp Ying, NioCorp, Revival, Newcore). Non-issuer references: CFI, Sell Side Handbook, Wood Mackenzie/CRU cost-curve product pages, Cassels/OSC NI 43-101 guidance.

## The headline (confirmed)

The gap structure is identical to the O&G finding: **it is about SOURCE DOCUMENTS, not metric cleverness.** For a miner, the numbers a bank analyst quotes first — P/NAV, AISC, cash cost, EV/oz, reserves, per-mine production and grade — are *structurally absent from the audited financial statements*. They live in three document classes FinLens does not yet fully ingest: the **MD&A** (non-GAAP cost/operating tables), the **AIF** (annual reserve & resource tables), and the standalone **NI 43-101 technical report** (mine plan, price deck, LOM DCF). The audited statements provide only the anchor line (`cost of sales` / `production costs`) that every per-unit metric is *reconciled from* — and the balance-sheet overlay (net debt) that bridges market cap to enterprise value. FinLens maps the anchor and the overlay well; it captures almost none of the derived layer.

## Confirmed findings (20)

Each finding: **title — source document.** Short verified evidence with real figures follows.

**Valuation**

**1. P/NAV is the primary framework; NAV = sum-of-parts of mine-by-mine after-tax DCFs — NI 43-101 technical report (physical inputs) + audited balance sheet / MD&A (net-debt & G&A overlay).** CFI: "P/NAV is the most important mining valuation metric, period"; NAV = Σ per-mine LOM after-tax DCF − net debt − PV of corporate G&A. The load-bearing inputs (reserve grade, LOM schedule, recoveries, strip ratio, unit capex/opex) originate in the technical report — none are in the audited statements. Corroborated by BMO/RBC fairness-opinion methodology in Coeur/Newmont DEFM14A (PV of after-tax FCF, less PV of G&A, ± cash and debt).

**2. The commodity price deck is analyst-set (forward-curve then flat), distinct from the company's conservative reserve price — analyst house forecast vs AIF/40-F annual reserve statement (and per-asset NI 43-101 pit-optimization price).** First 2–3 years off the strip, then a flat long-term "incentive"/marginal-cost price. This is deliberately *higher* than the company reserve price: AEM booked Dec-31-2024 reserves at **$1,450/oz** base ($1,350–$1,400 for some assets) vs ~$2,600–2,900 spot; Barrick's reserve price ladder ran $1,300→$1,500 (2022–2025) with *resources* priced higher ($1,700→$2,000). Conflating the two misstates NAV.

**3. EV/oz and EV/lb value developers and explorers off reserve/resource counts — AIF/MD&A R&R tables (mirrored from NI 43-101); net debt from audited balance sheet.** Confirmed ranges: junior gold **US$20–50/oz** M&I, advanced development **US$80–150/oz** (dealstream "Gold Mining Rules of Thumb"); copper $0.05–0.15/lb resources → $0.20–0.40/lb reserves. The ounce/pound denominator never touches the statements — IFRS 6 explicitly scopes reserve *quantities* out; statements carry only dollar amounts.

**4. Producers add P/CF (~9x) and EV/EBITDA (~7–8x); AISC is the first-quoted cost and it is MD&A-only — audited cash-flow statement (CFPS) + income statement/D&A note (EBITDA); AISC = MD&A non-GAAP reconciliation.** AEM FY2025 operating cash flow $6,817M ($13.58/sh); EV/EBITDA observed 5.5x–8.8x on Barrick 2024–2025. AEM's Q3 2025 release states verbatim that AISC "are non-GAAP ratios that are not standardized financial measures under IFRS," reconciled *to* production costs — i.e. AISC is derived, never a statement line.

**5. P/NAV multiples are subsector-tiered — analyst market judgment; NAV inputs still trace to NI 43-101 / (for streamers) AIF + statement notes.** Producers ~0.6–1.0x (seniors toward/above 1.0x), developers/explorers ~0.3–0.5x, royalty/streamers at a premium >1.0x (BMO Jan 2026: royalties 1.5–2.0x, Franco-Nevada 1.8x, vs miners 0.7–0.9x). Wheaton CEO framing: streaming cash flow ~15x FCF vs base-metals production ~6x. NI 43-101 s.9.2 *exempts* streamers from filing a technical report — their stream terms sit in the AIF and notes instead, so a streamer is a distinct valuation regime (mirrors how FinLens routes REIT/insurance).

**Costs**

**6. AISC/AIC are non-GAAP measures defined by the World Gold Council Guidance Note, reconciled from the IFRS cost line in the MD&A — MD&A "Non-GAAP Financial Measures" section + earnings/guidance press releases.** WGC Guidance Note (2013, upd. 2018) requires "a numerical reconciliation… between the… IFRS financial statement line items and the costs included in AISC and AIC." AEM builds AISC = cash costs + sustaining capex + G&A + reclamation, per WGC 2018 — never an audited line.

**7. Total cash cost per ounce is disclosed on BOTH a by-product and a co-product basis — a purely MD&A presentation choice that moves the number materially — MD&A non-GAAP section, each reconciled to the IFRS production-costs line.** AEM FY2025: **$979/oz by-product vs $1,035/oz co-product** (~$56/oz, ~5.7% swing from presentation alone); on copper-primary miners the by-product-credit swing is far larger. By-product deducts secondary-metal revenue; co-product allocates cost by relative value with no deduction (Goldcorp MD&A). The audited statement holds only the single combined cost figure.

**8. Base-metals cost ladder: only C1 (net of by-product credits) is an issuer disclosure; C2/C3 are third-party/analyst constructs — C1 = MD&A non-GAAP, reconciled to cost of sales; C2/C3 not in filings (Wood Mackenzie/Brook Hunt lineage); DD&A (the C1→C2 bridge) in the notes.** Teck FY2025 copper "net cash unit cost" ~US$2.67/lb (net of by-product credits), explicitly non-GAAP; Hudbay/Lundin/First Quantum stop at C1 + AISC. A targeted search for issuer-disclosed "C2/C3" returned only cost-service products — confirming they are reconstructions.

**9. The by-product-credit netting convention itself lives in the MD&A reconciliation — audited revenue/cost are gross; the netting that makes unit cost low is MD&A-only.** Teck Q1 2026: copper by-product credits US$0.54/lb (up from $0.44), zinc credits US$0.20/lb (up from $0.02) — a swing larger than most opex moves, invisible in the statements. Hecla's SEC comment-letter correspondence is decisive: staff objected that by-product netting "materially distorts your actual production costs" and must stay a *non-GAAP* adjustment, confirming GAAP cost of sales is gross.

**10. Cost per tonne milled ("minesite cost per tonne") is a non-GAAP operating statistic in the MD&A — MD&A operating-statistics + non-GAAP section, reconciled to production costs (ex-amortization); the tonnage denominator is MD&A-only.** AEM: "minesite costs per tonne… dividing by tonnes of ore milled… not a recognized measure under US GAAP." Physical tonnes never appear in IFRS statements. Per-tonne cost is the cleanest cross-mine efficiency comparator (strips out grade/by-product noise) yet both numerator reconciliation and denominator are MD&A-only.

**11. The only audited anchor is `cost of sales` / `production costs`; every per-unit metric is derived from it in the MD&A — audited income statement (anchor) + notes (components: DD&A, IFRIC 20 stripping); all per-unit metrics MD&A-derived.** Barrick reconciles "from cost of sales"; AEM "to production costs in accordance with IFRS"; Teck via "Use of Non-GAAP Financial Measures." The notes give inputs (DD&A for the C1→C2 bridge, capitalized stripping) but never the unit-cost metric. This defines the extraction architecture: pull the anchor from statements, but you *must* parse the MD&A reconciliation to obtain — and trust-check — any cost metric an analyst quotes.

**Reserves**

**12. The AIF is the canonical annual home of the reserve & resource TABLES (tonnes × grade × contained metal) — AIF, Item 5.4 of Form 51-102F2; filed on SEDAR+ and as Exhibit 99.1 to Form 40-F; NOT the financial statements.** Verified in-browser: AEM's 2024 40-F Ex-99.1 *is* the AIF, carrying "Detailed Mineral Reserve and Mineral Resource Data" by property (M&I resource 43.0 Moz = 1,167 Mt at 1.14 g/t Au), prepared per NI 43-101 / CIM Definition Standards / Form 51-102F2. (Wording nuance: these are QP-certified and board-approved, not financial-statement-audited.)

**13. The standalone NI 43-101 technical report — not the AIF — holds the price deck, cut-off grades, recoveries, LOM plan and NPV/IRR sensitivity that let you rebuild reserves — NI 43-101 technical report (feasibility/PFS), filed on SEDAR+ when a trigger fires.** Form 43-101F1 mandates annual cash-flow forecasts, metal-price assumptions, economic cut-off grades, recovery/conversion factors, LOM discussion, and price/grade/capex/opex sensitivities. The AIF reports the *result* and cross-references the report. Filing generally contemporaneous with the triggering disclosure (45 days where the trigger is a press release). Reserves are only interpretable against the deck they were run at.

**14. Reserve price-deck SENSITIVITY (% reserves per ~10% price move) is disclosed per-property in the AIF reserve notes — AIF mineral-reserve estimate discussion.** Fetched from AEM's 2024 AIF and text-extracted: LaRonde (6.03 g/t) shows only ~2.1%/3.5% elasticity per ±$145 (10%) gold move; the lower-grade LZ5 (2.21 g/t) shows ~8.7%/7.9% — higher elasticity = more marginal/near-cut-off ore, exactly as theory predicts. It is per-asset, not one consolidated line; a strong reserve-quality signal an aggregator never carries.

**15. Audited statement NOTES carry reserve-driven DEPLETION and the impairment PRICE DECK — but not reserve tonnage — accounting-policy / PP&E / impairment notes.** Depletion = units-of-production over P&P reserves (AEM/Barrick PP&E notes); impairment tests disclose the metal-price curve (Barrick FY2021 short-/long-term gold $1,700/$1,500, long-term copper $3.00/lb, ±$100/oz sensitivity). A gap between the notes' impairment deck and the AIF's *lower* reserve-declaration price is a legitimate earnings-quality cross-read — two documents, reconciled by the analyst.

**Operations**

**16. Per-mine gold production, mill throughput, and head grade live in the MD&A operating-statistics tables, never in the audited statements — MD&A / quarterly operational news release.** AEM Q3 2025: Detour Lake 176,539 oz @ 79,902 tpd @ 0.82 g/t; Macassa 78,832 oz @ 1,446 tpd @ 18.95 g/t (high-grade underground); the financial tables carry only dollars (net income, cash from ops, capex). This is the single most load-bearing gap for a statements-first tool — the entire quarter-over-quarter operating model is built from a document class the mapper does not parse.

**17. Metallurgical recovery (%) is an operational-narrative metric, often absent even there — MD&A / news-release narrative; fullest in the NI 43-101 report; NOT statements or notes.** AEM Q3 2025 tabulated production/throughput/grade but printed no per-mine recovery column; AEM Q4-2024 gave recovery only qualitatively ("lower throughput and recovery"). Recovery closes the identity contained-metal (throughput × grade) → produced ounces, so a forecast pipeline may have to fall back to the technical report — it cannot be reliably scraped from one quarterly document.

**18. Realized metal price vs benchmark (LBMA/LME) is a non-GAAP MD&A reconciliation, not a statements line — MD&A non-GAAP / operating-results section.** AEM Q3 2025 realized gold US$3,476/oz; realized price = metal revenue ÷ units sold, "a non-GAAP financial performance measure which excludes… treatment and refining charges" (Barrick 40-F MD&A). The benchmark comparison is inherently MD&A — the benchmark is third-party market data never in the statements. (Terminology: the "London PM Fix" was replaced by the LBMA Gold Price in 2015.)

**19. Total cash cost and AISC per oz/lb are non-GAAP measures reconciled in the MD&A, not statement line items — MD&A non-GAAP reconciliation to cost of sales.** AEM Q3 2025 total cash cost US$994/oz, AISC US$1,373/oz; Teck copper "net cash unit cost… There is no similar financial measure in our consolidated financial statements with which to compare." The reconciliation *to* the audited cost line is precisely the trust-bridge FinLens's mapper would need to validate them.

**20. TC/RCs and by-product credits are netted into base-metal unit cost and revenue — the gross split is MD&A + revenue note, not a standalone statement line — MD&A cash-cost bridge + statement revenue-recognition note (IFRS 15).** Under IFRS 15, concentrate revenue is recorded *net of* treatment/refining charges (SEC full-text: 33 filings with "revenues, net of treatment and refining charges" — Newmont, Goldcorp, Yamana, Coeur, Taseko…); TC/RCs have no standalone expense line. Teck Q4 2025 flagged the copper TC/RC benchmark set to 0 (record low) — a swing factor structurally hidden by the statement top line. (Precision: TC/RCs reduce revenue in the statements; by-product credits are recognized *as* revenue and only net against unit cost in the MD&A bridge.)

## Corrections — refuted claims (4)

Four plausible-sounding analyst claims were **refuted** on their source-document attribution and are corrected here. (No claims landed unverified.)

**C1. "The NAV discount rate appears in NO company document." — REFUTED.** The rate *tiers* are right (~5% real Tier-1 operating gold, 7–9% Tier-1 developers, 10–15% for Ghana/Mali/DRC; the gold price absorbs much of the risk WACC captures). But NI 43-101 technical reports *do* disclose a base-case discount rate, conventionally 5% for gold, quoted throughout as "NPV5%" with sensitivity NPVs at other rates (Freeman Lemhi, Revival Beartrack-Arnett, Newcore Enchi, First Mining). **Correction:** the ~5% anchor derives *from* the technical-report convention; only the rate in the analyst's *own* proprietary model (which may adjust the 5% by jurisdiction/stage) is a non-disclosed analyst assumption.

**C2. "Cost-curve quartile positioning is NOT in any filing." — REFUTED.** The underlying peer *dataset* is indeed a proprietary third-party construct (Wood Mackenzie / CRU "Global gold AISC curve," "Global copper mine cost curve"), cited in investor presentations with attribution. But an issuer's statement of where its *own* mine sits appears routinely in the MD&A: Alamos Gold's FY2025 MD&A states "Lynn Lake… first quartile mine-site AISC of $829 per ounce" — unattributed, the company's own claim; "first quartile" + AISC hits 10 distinct 40-F filings. **Correction:** the quartile *benchmark* is third-party/proprietary (badge as external), but the issuer's own quartile *positioning* is a normal MD&A/AIF disclosure — point mine-level positioning to the MD&A first.

**C3. "Reserve replacement ratio and depletion are analyst-derived — no filing prints them." — REFUTED.** The definitional mechanic is right (RRR = additions ÷ depletion; >1.0 = mine life extending), but issuers *print* both. Replacement % by name: AEM Odyssey 110%, Macassa 86%, Fosterville 86%; Newmont's release is headlined "Replacing 80 Percent of Depletion"; Barrick ">180%." Depletion is an explicit line in the reserve reconciliation table (Barrick 3.7 Moz; Newmont 7.5 Moz). **Correction:** the primary source is the **year-end reserves & resources news release + the reserve reconciliation in the 40-F/annual report** (NI 43-101 tables also in the AIF) — not a self-derivation from consecutive AIFs + MD&A production. An analyst only back-solves when a specific issuer omits the outright figure. The "≥1.15 buffer target" is **unverified** — disclosed norm is simply >1.0.

**C4. "The annual reserve update press release front-runs the AIF and is headline-only." — REFUTED (timing right, content wrong).** Timing confirmed: AEM's reserve release (Feb 13 2025, bundled with exploration) precedes its AIF (Feb 26 2025); Barrick's release Feb 6 2025 precedes the 40-F. But the release is **not** a headline teaser — fetching AEM's text shows it already carries the full per-property reserve/resource tables (LaRonde 2,081 koz @ 6.03 g/t, Detour, Macassa, Hope Bay, Meliadine with prior-year comparatives), the complete price deck ($1,450/oz base, $1,400 Detour open pit, $1,650 Amaruq), *and* the reserve sensitivity ("gold price 10% higher → ~13% increase"). **Correction:** the AIF and NI 43-101 reports add deeper granularity (per-deposit cut-offs, block-model detail), not the first appearance of per-property tables/deck/sensitivity. Also, these are QP-certified NI 43-101 news releases, not necessarily Form 51-102F3 material-change reports.

## Gap analysis — findings mapped to the FinLens inventory

Each finding is classified **covered today / planned / uncovered**, and — critically — bucketed by the **source document** its data lives in. The buckets set the build economics: Bucket A is cheap (documents already ingested), Bucket B waits on the MD&A fetcher, Bucket C is a new document class.

### Bucket A — already-ingested statements + notes (cheap wins, no new document class)

| Finding | Data | FinLens status |
|---|---|---|
| 11 (anchor) | `cost of sales` / `production costs` | **Covered.** `mining_sector.production_costs` (AEM 3,340,684); default `cost_of_revenue` (Teck −8,099). CB-011. |
| — | Revenue, net_income, balance-sheet spine, DD&A | **Covered.** AEM maps 11 fields incl. revenue 11,907,851, net_income 4,461,461, total_assets/liabilities/equity, `mine_development_amortization` 1,645,297. Identity + EBITDA-family from defaults. |
| 8 (bridge), 15 | DD&A / depletion note; capitalized stripping (IFRIC 20) | **Partly covered / uncovered.** AEM DD&A maps; **Teck's "Depreciation and amortization" 1,757 and "Capitalized stripping costs" −224 sit unmapped** (Teck prints different labels). Statement-level alias gap → cheap win. |
| 15 | Units-of-production depletion mechanism; impairment price deck | **Uncovered (notes-prose).** Lives in accounting-policy/PP&E/impairment notes — an already-ingested class, but requires notes-prose parsing, not line mapping. Enables the notes-vs-AIF price-deck cross-read. |
| 5, 20 | Streamer stream terms; IFRS 15 "net of TC/RC" revenue policy | **Uncovered (notes-prose).** Revenue-recognition note + stream-contract notes; already-ingested class. |
| 9 (gross inputs) | Gross revenue / gross cost (the by-product bridge's statement inputs) | **Covered as gross;** the netting itself is Bucket B. |
| **CB-034 analog** | Commodity/FX **derivative & hedge notes** | **Uncovered but reusable-now.** AEM's "(Gain) loss on derivative financial instruments" −223,960 sits in unmapped[]; CB-034's `extract_hedging_note` + `realized_derivative_gains` is **shipped but O&G-evidenced only** (PEY, TOU) — never exercised on a miner. Direct reuse. |
| **Reclamation/ARO** | Reclamation provisions | **Uncovered but cheap.** AEM "Reclamation provision" 144,537 + 1,318,476 unmapped; same note-extraction pattern as hedging. |
| **Producer capex** | Additions to PP&E and mine development | **Uncovered — statement-level gap.** AEM "Additions to property, plant and mine development" −2,418,200 unmapped; **there is no mining producer capex alias.** Unlike O&G (capex covered via CB-021 PP&E+E&E), the *producer* side has no FCF capex input. Cheapest single fix. |
| **Producer red flags** | Sector-aware suppression for producers | **Uncovered.** `SECTOR_FLAG_RULES` keys only `mining_exploration_sector` (CB-019); **no `mining_sector` (producer) doctrine.** |
| **Commodity proxies** | Zinc, nickel, potash, lithium, PGM, moly overlays | **Uncovered.** `COMMODITY_PROXIES` has gold/copper/silver/uranium/crude/gas only — **Teck (zinc) and any PGM/battery-metals producer get no price overlay.** Tier-1 cheap win. |

### Bucket B — MD&A-gated (blocked on the MD&A fetcher; shared with the ratified O&G Tier 2)

Every headline cost and operating metric is here. All are **uncovered today, planned via Resource Economics Snapshot Tier 2**, which the spec explicitly gates on MD&A/HTML text extraction ("currently blocked") and notes AISC building blocks are "empirically absent from Agnico's consolidated income statement."

- **AISC / AIC per oz** (findings 4, 6, 19) — the first-quoted mining number. MD&A non-GAAP. *This is the mining analog of O&G netback — the flagship Tier-2 output.*
- **Total cash cost, by-product & co-product basis** (findings 7, 9) — including the by-product-credit netting.
- **Cost per tonne milled + tonnes-milled denominator** (finding 10).
- **C1 net cash unit cost per lb** (finding 8).
- **Per-mine production oz / throughput tpd / head grade** (finding 16) — the entire operating model.
- **Metallurgical recovery %** (finding 17) — MD&A/narrative, with NI 43-101 fallback.
- **Realized price vs benchmark** (finding 18) — MD&A non-GAAP.
- **TC/RC** (finding 20) — MD&A bridge (revenue-policy half is Bucket A).
- **Issuer's own cost-curve quartile positioning** (correction C2) — MD&A.
- **Reserve replacement % + depletion** (correction C3) — year-end reserves news release + 40-F reconciliation (press-release class, MD&A-adjacent).

### Bucket C — AIF / NI 43-101-gated (new document class; deep moat; O&G Tier-3 analog)

**Uncovered; planned only as Resource Economics Snapshot Tier 3** ("reserve data often PDF-table/technical-report sourced — distinct extraction problem"). This is the NAV engine.

- **Contained oz/lb** for EV/oz and EV/lb denominators (finding 3) — AIF R&R tables.
- **Consolidated per-property reserve/resource tables** (finding 12) — AIF Item 5.4 / 40-F Ex-99.1.
- **Company reserve price** vs analyst deck (finding 2) — AIF/40-F annual reserve statement.
- **Reserve price-deck sensitivity** (finding 14) — AIF reserve notes.
- **Per-mine LOM schedule, cut-off grade, recoveries, unit capex/opex, NPV/IRR sensitivity** (findings 1, 13) — NI 43-101 technical report; the SOTP DCF inputs.
- **Base-case discount rate (NPV5%)** (correction C1) — NI 43-101 (with the analyst's own rate badged as an assumption).

## What FinLens already covers well (from statements — confirmed adequate)

FinLens maps the audited spine of a miner solidly and honestly. On real fixtures: **AEM** maps 11 fields (revenue, `production_costs`, `exploration_expense`, `mine_development_amortization`, interest_expense, net_income, the full balance-sheet spine incl. `total_equity` 24,742,464 consolidated per CB-013); **Teck** maps 7 (revenue, cost_of_revenue, gross_profit, net_income 1,072 consolidated-incl-NCI per CB-011, spine); **NFG** and **SIG** map the pre-revenue explorer shape (`net_loss`, `operating_loss`, `exploration_expense`, `capitalized_exploration_additions` cash-flow-scoped per CB-009, `cash`, `net_cash_used_in_operating_activities`) with explorer red-flag suppression (CB-019) and loss-sign discipline (CB-020). The balance-sheet identity, EBITDA-family, Debt/Equity and FCF scaffolding all come from the default profile and apply to producers. The audited **anchor line** every cost metric reconciles from (`cost of sales` / `production costs`) is exactly what the mapper captures — so FinLens holds the receipt end of every non-GAAP bridge, even though it cannot yet read the bridge itself. This mirrors the O&G finding precisely.

## Honest caveats (recorded verbatim from the run)

- **No paywalled bank research was sourced.** Methodology is reconstructed from public IB/valuation references, regulator texts, the WGC Guidance Note, and issuer primary filings — not from an actual BMO/RBC/Scotia mining note.
- **SEC EDGAR HTML repeatedly 403'd direct fetch.** Several primary-filing details (Barrick 40-F, AEM 6-K) were recovered via search-engine extraction of the same documents plus issuer-hosted PDFs (AEM Annual Report, AIF; Teck MD&A; B2Gold release fetched directly). Corroboration is consistent across independent filers, but a handful of exact figures rest on indexed excerpts rather than full-text fetch.
- **Valuation multiples are time-varying.** P/CF ~9x, EV/EBITDA ~7–8x, P/NAV tier bands, and price decks are current-environment central tendencies, appropriately hedged; they will move with the cycle.
- **Ranking is judgment-based.** The Bucket A/B/C prioritization is CC's read of build economics, not a measured ROI.
- **Kinross (K) is not a stored fixture** — it was a CB-011 pilot bundle only. Producer coverage is machine-verified on AEM + Teck; a third producer fixture would strengthen `mining_sector`.

## Open questions the run surfaced (good future-session material)

1. **Notes-vs-AIF price-deck cross-read (finding 15):** is a miner testing impairment at a materially different price than it declares reserves at? Cheap earnings-quality flag once both notes and AIF are parsed — no analog in the O&G work.
2. **By-product/co-product basis flag (finding 7):** which basis does each issuer headline, and can the caption auto-disclose it? A near-zero by-product cash cost on a copper-gold mine is the single biggest apples-to-oranges trap.
3. **Reserve-quality signal from sensitivity (finding 14):** can FinLens surface per-property elasticity (LZ5 ~8.7% vs LaRonde ~2.1%) as a marginal-ounce badge?
4. **Streamer routing (finding 5):** should FinLens mint a `royalty_streaming_sector` profile (premium P/NAV regime, stream-terms-from-notes), mirroring REIT/insurance routing?
5. **Producer red-flag doctrine:** what is the `mining_sector` (not explorer) suppression/keep set? CB-019 covers explorers only.
6. **Third producer fixture:** add Kinross or Barrick to pin `mining_sector` beyond n=2.

## Implications for the build order (CC's read, for Riley's ratification)

The mining sequence tracks the ratified O&G sequence and **shares its infrastructure at every step** — build once, branch by sector.

1. **Statement/notes cheap wins now (Bucket A, no new document class).** In rough order: (a) **add a mining producer capex alias** — the only statement-level FCF input missing (AEM −2,418,200 unmapped); (b) **add Teck's `cost of sales` / `depreciation and amortization` / `debt` aliases** so producers beyond AEM map their cost and leverage lines; (c) **run the shipped CB-034 hedging-note extractor on a miner** — AEM's derivative/FX notes are the reuse case the extractor was built for but never exercised on; (d) extend the same note-extraction pattern to **reclamation/ARO provisions**; (e) add a **`mining_sector` producer red-flag profile**; (f) add **zinc/nickel/PGM/battery-metals commodity proxies** so Teck and diversified miners get an overlay. None require a new fetcher.

2. **MD&A fetcher — the single biggest unlock, and it is the same build as O&G's next step.** It converts Bucket B from uncovered to covered: AISC, total cash cost (by-product/co-product), cost per tonne milled, C1, per-mine oz/tpd/grade, realized price vs benchmark, TC/RC, and issuer quartile positioning. This is Resource Economics Snapshot **Tier 2**, and the fetch+parse infrastructure is shared with the O&G netback flow — one MD&A fetcher serves both sectors. **Priority: immediately after the Bucket A wins, exactly as ratified for O&G.**

3. **Reserves layer (Bucket C, phase 1) — year-end reserves release + AIF/40-F reserve reconciliation.** Corrections C3/C4 change the economics here: replacement %, depletion, per-property R&R tables, price deck, and sensitivity are **directly printed** in the reserves news release and the 40-F reconciliation — so this is a *parse* target, not a multi-year self-derivation. That makes the reserves-release/AIF a cheaper entry into Bucket C than the technical report, and it feeds EV/oz, reserve life, and reserve-quality badges. FinLens's corpus (storing prior-year reserves) can automate YoY deltas no aggregator provides.

4. **NI 43-101 technical report (Bucket C, phase 2) — the deep moat, the NAV engine.** Rebuild the mine-level LOM DCF skeleton (schedule, cut-off, recoveries, unit capex/opex) from the technical report; expose **discount rate and price deck as user-set assumptions** and badge the NAV as assumption-driven, not filing-derived (**Trust-Is-Page-Level** — the two biggest NAV levers are analyst inputs). This is the direct analog of the O&G **NI 51-101** reserve-report work: treat "reserve report" as one new document class with a mining (43-101) and an O&G (51-101) branch.

5. **Zero-cost disclosure captions in parallel.** The Snapshot already carries sector-aware captions (Netback→AISC). Add: a **by-product/co-product basis flag**, a **realized-price-vs-benchmark** caption, and an **external/aggregator badge on cost-curve quartile** (the peer dataset is proprietary and unreconcilable — a "number without a receipt"). These need no fetcher and directly serve the Trust-Is-Page-Level principle.

Shared-infrastructure summary: **MD&A fetcher** (one build, both sectors), **CB-034 hedging-note extractor** (shipped, reusable for miners' derivative/streaming/impairment/ARO notes), **reserve-report document class** (NI 43-101 ∥ NI 51-101), and **assumption-badging** for analyst-input NAV levers. The mining side adds one wrinkle O&G lacks — **producer capex is not even mapped at the statement level** — which is the cheapest fix on the entire list and should ship first.

---

*Run stats: 4-angle sweep (valuation / costs / reserves / operations); 20 confirmed, 4 refuted (corrected), 0 unverified; primary sources = Agnico Eagle, Barrick, Teck, Hudbay, Lundin, First Quantum, Capstone, Freeport, Hecla, B2Gold, Goldcorp, Newmont, New Gold, Franco-Nevada, Wheaton, Royal Gold filings + NI 43-101 / Form 51-102F2 / IFRS 6&15 / WGC Guidance Note. Companion to docs/research/2026-07-10-bank-og-coverage-gaps.md; source-document classification cross-checked against the FinLens mining-sector inventory (mapper fixtures AEM/TECKB/NFG/SIG, CB-009/011/019/020/034, Resource Economics Snapshot Tiers 1–3).*
