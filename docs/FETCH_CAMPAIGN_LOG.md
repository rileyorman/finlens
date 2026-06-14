# Fetch Campaign Log

Scannable provenance log for campaign filer source handling.

## SEDAR+ Access Strategy

**Status:** Established post-CNQ filer #7 (2026-06-13)

**Official SEDAR+ API:** Does not exist yet. CSA IT Systems Office lists it as a longer-term objective. Revisit in 12-18 months.

**Third-party options:**
- QuoteMedia API: exists, provides getCompanyFilings + PDF links for SEDAR filings. Enterprise pricing — revisit post-revenue as a legitimate business expense.
- Avantis AI: direct CSA real-time feed partnership. Enterprise-only, post-commercial.

**Current campaign protocol — Issuer-Hosted PDF (default):**
All major TSX companies publish clean annual financial statement PDFs on their investor relations pages. This is the default sourcing method for all campaign filers until QuoteMedia becomes viable.

Steps for each new filer:
1. Go directly to the company IR page for annual financial statements PDF — issuer-hosted is the PRIMARY path.
2. Do NOT attempt SEDAR+ first. Empirical finding: SEDAR+ has been Radware CAPTCHA-blocked on every campaign filer to date (CNQ, CAR.UN, DIR.UN). Attempting it wastes a fetch cycle on a known wall. Revisit SEDAR+ as a source only once an access strategy exists (QuoteMedia, official API, or human-in-the-loop solver — see triggers above).
3. Download PDF directly from IR page. If annual report is CID-encoded/unreadable, fall back to Q4 financial statements PDF and document the artifact-tier deviation in document_note.
4. Document in fixture source_provenance: pdf_origin_url, sedar_access_note (record that SEDAR+ was skipped per CAPTCHA finding), document_note, future_pattern.
5. Flag mid/small-cap filers that don't self-publish as a known gap (these are the filers that will need the SEDAR+ access strategy).

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

## Campaign-Wide Flags

- SEDAR+ Radware CAPTCHA confirmed blocking on all filers — issuer-hosted is now the established primary source, not a fallback. SEDAR+ access strategy still needed for mid/small caps that don't self-publish.
- SEDAR+ access strategy is established — see above. Revisit triggers: QuoteMedia (first paying users), SEDAR+ official API (12-18 months), human-in-the-loop CAPTCHA solver (post-commercial — see Access Strategy above).
