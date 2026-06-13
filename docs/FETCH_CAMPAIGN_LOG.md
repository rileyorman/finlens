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
1. Check company IR page for annual financial statements PDF
2. Attempt SEDAR+ fetch first — if Radware CAPTCHA blocks, fall back to issuer-hosted
3. Download PDF directly from IR page
4. Document in fixture source_provenance: PDF origin URL, retrieval date, whether SEDAR+ was attempted and blocked
5. Flag mid/small cap filers that don't self-publish as a known gap

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

## Campaign-Wide Flags

- SEDAR+ CAPTCHA is a campaign-wide concern.
- SEDAR+ access strategy is established — see above. Revisit triggers: QuoteMedia (first paying users), SEDAR+ official API (12-18 months), human-in-the-loop CAPTCHA solver (post-commercial — see Access Strategy above).
