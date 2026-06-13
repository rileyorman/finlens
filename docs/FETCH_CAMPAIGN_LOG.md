# Fetch Campaign Log

Scannable provenance log for campaign filer source handling.

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
- A SEDAR+ access strategy is needed before filer #8 proceeds.
