# Fetch Campaign Log

Scannable provenance log for campaign filer source handling.

## SEDAR+ Access Strategy

**Status:** Established post-CNQ filer #7 (2026-06-13)

**Official SEDAR+ API:** Does not exist yet. CSA IT Systems Office lists it as a longer-term objective. Revisit in 12-18 months.

**Third-party options:**
- QuoteMedia API: exists, provides getCompanyFilings + PDF links for SEDAR filings. Enterprise pricing — revisit post-revenue as a legitimate business expense.
- Avantis AI: direct CSA real-time feed partnership. Enterprise-only, post-commercial.

**Campaign fetch protocol — Manual Issuer Download (primary):**

Steps for each new filer:
1. Riley downloads the PDF directly from the company's issuer IR page in his browser. This sails through Cloudflare/Radware challenges that block automated fetch, keeps provenance clean (issuer-hosted), and wastes zero fetch cycles. Save to C:\Users\riley\.finlens\pdfs\.
2. Codex extracts from the local file — Codex does NOT fetch. Rationale: Codex cold-starts each session (no learning from prior fetches), repeatedly defaults to SEDAR+-first, and reaches for third-party mirrors that break the audit trail. Fetching is Riley's job; extraction is Codex's.
3. source_provenance must record: pdf_origin_url (real issuer IR URL), retrieval_method ('manual browser download from issuer IR'), document_note, future_pattern.
4. Do NOT use third-party mirrors (annualreports.com etc.) for committed fixtures — design-evidence only, never a fixture source.
5. Do NOT attempt SEDAR+ — Radware CAPTCHA-blocked; awaiting access strategy.
6. Automated issuer-IR fetch stays documented only for the eventual commercial product, where end users can't hand-download.

**Audit trail:** source_provenance field in fixture JSON is mandatory for all filers where SEDAR+ is not the actual source. Pattern established with CNQ filer #7 (be3c4c0).

**Human-in-the-loop CAPTCHA solver:** In backlog. Fetcher hits CAPTCHA wall → FinLens prompts user to complete in browser → captures session cookie → resumes fetch. Non-trivial in Streamlit; Radware fingerprints browser behavior. Build post-commercial after investigating SEDAR+ official API first.

**QuoteMedia trigger:** Revisit when first paying users arrive — becomes a deductible business expense and unlocks mid/small cap coverage.

## CNQ Filer #7 - Complete

- Company: Canadian Natural Resources Limited
- Ticker: CNQ
- Fiscal year: FY2024
- Fixture: `tests/fixtures/cnq_fy2024_sedar.json`
- Source: issuer-hosted Q4 financial statements
- Source URL: https://www.cnrl.com/content/uploads/2025/03/12.31.2024-Q4-FS.pdf
- Source note: SEDAR+ Radware CAPTCHA blocked the canonical-source path.
- Document note: `12.31.2024-Q4-FS.pdf` is Q4 financial statements, not the annual report wrapper. The `Year Ended Dec 31 2024` columns carry the correct FY2024 figures.
- Fixture audit trail: `source_provenance` records the issuer-hosted URL and SEDAR+ access limitation.
- CSU + REI.UN filing_date NULL: diagnosed 2026-06-13. Fix designed (Option A: prepend cover pages 0-3). Pending empirical verification via reextract_sedar_fixtures.py next session.

## CAR.UN Filer #8 - Complete (e012859)

- Company: Canadian Apartment Properties REIT (CAPREIT)
- Ticker: CAR.UN
- Fiscal year: FY2024
- Fixture: `tests/fixtures/CARUN_FY2024_sedar.json`
- Source: issuer-hosted FY2024 annual report
- Source URL: https://www.capreit.ca/wp-content/uploads/2025/02/CAPREIT-Q4-2024-Annual-Report-web-optimized.pdf
- Source note: SEDAR+ Radware CAPTCHA blocked the canonical-source path.
- Document note: full annual report PDF; user-specified `capreit.ca/investors/` URL returned 404, working URL captured above.
- Fixture audit trail: `source_provenance` records the issuer-hosted URL and SEDAR+ access limitation.

## DIR.UN Filer #9 - Complete (24cf477)

- Company: Dream Industrial REIT
- Ticker: DIR.UN
- Fiscal year: FY2024
- Fixture: `tests/fixtures/DIRUN_FY2024_sedar.json`
- Source: issuer-hosted FY2024 annual report
- Source URL: https://investors.dream.ca/wp-content/uploads/2025/02/2024-DIR-Annual-Report-FINAL.pdf
- Source note: SEDAR+ Radware CAPTCHA blocked the canonical-source path.
- Document note: full annual report PDF (131 pages); user-specified `dreamindustrial.com/investors` URL didn't resolve, working IR domain `investors.dream.ca` captured above.
- Fixture audit trail: `source_provenance` records the issuer-hosted URL and SEDAR+ access limitation.

## IFC Filer #12 - Complete

- Company: Intact Financial Corporation
- Ticker: IFC
- Fiscal year: FY2025
- Fixture: `tests/fixtures/IFC_FY2025_sedar.json`
- Source: issuer-hosted Q4 2025 financial statements (manual browser download from issuer IR)
- Source URL: https://www.intactfc.com/presentations/Q4_2025_Financial-Statements.pdf
- filing_date: 2026-02-10 (visually verified — management sign-off date above CEO/CFO signatures on the Management's Responsibility page).
- Mapping: net_income only (3,365). No insurance_sector profile built; no insurance lines forced into financial_sector or any existing canonical field.
- KNOWN FINDING — sector profile gap: sector_inferred "Property and Casualty Insurance" currently routes to `financial_sector` via token match, but `financial_sector` is bank-shaped and maps nothing useful for an insurer (only the default net_income resolves). The full IFRS 17 unmapped[] (insurance revenue, insurance service expense/result, reinsurance lines, net investment return, net insurance financial result, IFRS 17 balance-sheet lines) is preserved as-is — it is the evidence base for a future dedicated `insurance_sector` profile. Deferred until filer #2 (a second insurer) confirms the IFRS 17 label pattern is not Intact-specific.

## SLF Filer #13 - Complete

- Company: Sun Life Financial Inc.
- Ticker: SLF
- Fiscal year: FY2025
- Fixture: `tests/fixtures/SLF_FY2025_sedar.json`
- Source: standalone Q4 2025 Consolidated Financial Statements (Deloitte LLP auditor; footer "Sun Life Financial Inc. December 31, 2025 — Consolidated Financial Statements"), manual browser download from issuer IR. An earlier extraction read the wrong 247-page annual report; the committed fixture is the corrected re-extraction from the 109-page standalone statements PDF.
- Source URL: https://www.sunlife.com/content/dam/sunlife/regional/global-marketing/documents/com/pa-e-q425-2025-fin-stats.pdf
- filing_date: 2026-02-11 (visually verified — management sign-off date under the CEO/CFO signatures on the "Financial Reporting Responsibilities" page, page 1 / 0-indexed).
- Mapping: maps NOTHING via defaults. SLF's net income label "Total net income (loss)" is not a current default net_income alias, so it is left UNMAPPED here — no alias added, no insurance_sector built, no line forced into a canonical field. Full IFRS 17 unmapped[] preserved.
- KNOWN FINDING — insurance_sector now JUSTIFIED (second insurer, first LIFE insurer): the IFRS 17 income-statement CORE is confirmed structural across P&C (IFC) and Life (SLF) — same spine, label variants only ("Net insurance service result" vs IFC "Insurance service result"; "Net investment result" vs "Net investment return"; plural "expenses"). The unmapped[] (insurance revenue / insurance service expenses / net insurance service result / insurance finance lines / net investment result / segregated-fund and participating-account life-specific lines) completes the second-filer evidence base.
- KNOWN FINDING — default-tier gap: "Total net income (loss)" is a generic IFRS label (not insurance-specific) that should be added to the default net_income aliases during the profile build.
- KNOWN FINDING — sector mis-route confirmed on TWO insurers: sector_inferred "Insurance and Financial Services" routes to bank-shaped `financial_sector` via token match. Fix during the insurance_sector build.

## Campaign-Wide Flags

- Manual issuer download (Riley, browser) is the established primary fetch path — not a fallback. Codex does not fetch; Codex extracts from the local file Riley supplies. Empirical drivers: SEDAR+ Radware CAPTCHA-blocked on all filers; issuer IR pages can also be Cloudflare-blocked (AEM, 2026-06-13); third-party mirrors break the source-provenance audit trail.
- SEDAR+ access strategy is established — see above. Revisit triggers: QuoteMedia (first paying users), SEDAR+ official API (12-18 months), human-in-the-loop CAPTCHA solver (post-commercial — see Access Strategy above). Strategy still needed for mid/small caps that don't self-publish.
