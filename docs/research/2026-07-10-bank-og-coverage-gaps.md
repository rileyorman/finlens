# How Banks Analyze O&G Filings vs FinLens Coverage — Research Report (2026-07-10)

Deep-research run (Riley's ask, 2026-07-10): how sell-side E&P analysts at the
big banks (RBC/TD/BMO/Scotiabank/CIBC + US majors) analyze oil & gas filings,
and where FinLens's current coverage falls short. Method: 5-angle web sweep →
21 sources fetched → 95 claims extracted → top 25 adversarially verified
(3-verifier panels, primary-PDF text extraction). **12 confirmed, 0 refuted,
13 unverified (verifier rate-limits, not refutation).**

Primary sources verified against: Tourmaline FY2025 MD&A + audited statements,
ARC Resources Q1 2026 Quarterly Book, ARC Q1 2026 investor presentation,
CNQ 2025 AIF, Cardinal Energy Q1 2026 MD&A, ASC Companion Policy 51-101CP,
Obsidian 2025 reserves release (SEC 6-K corroborated).

## The headline (confirmed, unanimous votes)

The gap structure is about SOURCE DOCUMENTS, not metrics cleverness. The most
load-bearing numbers in a bank note live outside the audited financial
statements FinLens extracts:

1. **Production volumes & commodity mix — MD&A only.** TOU FY2025: 638,196
   boe/d; ARX Q1 2026: 110,954 bbl/d crude+condensate / 1,533 MMcf/d gas /
   52,083 bbl/d NGLs. Adversarial full-text scans of both issuers' statement
   sections found NO production disclosures (the only physical volumes in the
   statements are hedge notionals). **Gap priority #1 — the denominator for
   the entire per-boe family.**
2. **Per-boe operating netback — MD&A-only non-GAAP ratio.** TOU FY2025:
   $28.30 revenue − $2.21 royalties − $5.14 transportation − $4.93 opex =
   **$16.02/boe** (MD&A p.31); ARX Q1 2026: $44.05 − $4.34 − $5.57 − $5.00 =
   **$29.14/boe** (Tables 12/12a, arithmetic ties exactly). FinLens's CB-024
   netback MARGIN % uses the same components but cannot produce the $/boe
   figure banks quote. **Priority #2 (depends on #1).**
3. **Reserves / NAV inputs — AIF (NI 51-101 Form 51-101F1) only.** 2P/1P/PDP
   volumes, NPV of future net revenue at five discount rates, F&D costs,
   recycle ratio, RLI, reserve replacement — the raw inputs to NAV-per-share
   and EV/2P, the anchor valuation methodology in Canadian bank E&P notes.
   Regulator-verified (ASC 51-101CP) + issuer-verified (Obsidian: F&D
   $25.70/$19.44/$20.68 per boe, recycle 1.1x/1.4x/1.3x PDP/1P/2P).
   **Priority #3 — deepest structural lift (new document class, annual-only).**
4. **Hedging book — ALREADY INSIDE the statements FinLens ingests, in the
   NOTES.** TOU's audited Note tables (PDF p.65): derivatives by year
   2026–2030 with volumes, strikes, $223.7M fair value. ARX Note 11: WTI
   collars/swaps/swaptions, AECO collars/swaps, AECO–Henry Hub basis sold
   swaps (−$1.05 US/MMBtu), FX collars — by instrument, price, volume, year.
   **Priority #4 but the CHEAPEST win — needs notes-layer extraction, not a
   new document.** (Both verifications ran on the same combined PDFs the
   TOU/ARX corpus fixtures came from.)
5. **Company-defined FFO / free funds flow / net-debt-to-FFO — MD&A + the
   statements' capital-management note.** ARX Q1 2026: FFO $967M, FFF $459M,
   net debt 0.9x FFO, 56% of FFF returned. FinLens's statements-derived FCF
   (CFO − capex ≈ $543M) differs from company-defined FFF ($459M) by ~$84M in
   ONE quarter (working-capital exclusion) — banks quote the company-defined
   figures. **Priority #5 — partial fix from statements Note 10; full fix
   needs MD&A.**
6. **Differentials (WCS–WTI, AECO–Henry Hub) & benchmark/realized price
   tables — MD&A** (supporting claims unverified due to rate limits, but
   ARX's Note-11 AECO-basis hedge table independently confirms basis
   differentials are analyst-relevant). **Priority #6.**
7. **Per-boe cost guidance + price-deck sensitivities — investor
   presentations/MD&A** (unverified tier). **Priority #7.**

## What FinLens already covers well (from statements — confirmed adequate)

Gross revenue / royalties split (CB-025), DD&A incl. impairment (CB-026),
OCF, capex PP&E+E&E (CB-021/029), EBITDA / leverage / interest cover
(CB-022/023), netback margin % (CB-024/030), balance-sheet spine + identity,
net debt/OCF peer comparison, commodity benchmark linkage (CB-027).

## Honest caveats (recorded verbatim from the run)

- **No actual bank research notes were sourced — they're paywalled.** The
  "standard bank metric set" is reconstructed from issuer disclosure practice,
  regulatory requirements, and disclosure structure, not from the notes
  themselves. The valuation-methodology weighting question (risked NAV vs
  EV/DACF vs FCF-yield) is answered only indirectly.
- 13 of 25 claims unverified (verifier infrastructure/rate-limit errors; none
  refuted) — including the CNQ AIF NPV tables (2P BT NPV10 $191,012M) and the
  Cardinal WCS–WTI differential line (US$(14.17)/bbl).
- ARX evidence is Q1 2026 interim; disclosure-location findings generalize to
  annual packages but weren't re-verified there.
- Prioritization ranking is judgment (medium confidence), built on the
  confirmed disclosure structure.

## Open questions the run surfaced (good future-session material)

1. Bank-note weighting among risked 2P NAV / EV/DACF / FCF-yield target
   prices — unverifiable without the paywalled notes (a professor/practitioner
   ASK candidate post-Columbia).
2. Can Form 51-101F1 NPV/reserves tables be machine-parsed reliably across
   evaluators (GLJ/Sproule/McDaniel)?
3. Netback component definitions are explicitly non-standardized ("no
   standardized meaning under IFRS") — does cross-filer comparison need a
   canonical netback definition ruling (CB-024 extension) before it's honest?
4. Are differentials uniformly MD&A-located across WCSB filers, or do some
   push them to presentations (a third document class)?

## Implications for the build order (CC's read, for Riley's ratification)

- **Validates the MD&A fetcher as the single biggest coverage unlock** (it was
  already the recorded Tier-2 gate for $/boe netback — this run shows it also
  gates volumes, differentials, FFO-family metrics, i.e. priorities #1, #2,
  #5, #6).
- **New near-term candidate: hedging-book extraction from the statement notes**
  — the only top-5 gap reachable from documents already in the corpus. Needs
  its own design session (notes tables are a different extraction shape than
  statement line items).
- **AIF/reserves ingestion is the deep moat play** (NAV inputs nobody
  aggregates well) but a new document class — post-MD&A.
- The FFO-vs-FCF definitional divergence (#5) is a DISCLOSURE candidate today:
  a caption noting FinLens FCF ≠ company-defined FFF would prevent a
  false-comparison read at zero build cost.

Run stats: 103 agents, 5 angles, 21 sources, 95 claims, 12 confirmed / 0
refuted / 13 unverified. Full machine output preserved in the session task
record (wf_651ef218-036).
