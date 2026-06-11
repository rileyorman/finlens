# FinLens FMP Fetch Campaign Log

Tracks cross-validation fetch outcomes for each audit campaign ticker.
One section per ticker, updated after each audit run.

---

## JPM — FY2025

**Sector:** Financial Services
**Filing accession:** 0001628280-26-008131
**Audit date:** 2026-06-05

### Rules

| rule_id | Result | Why |
|---|---|---|
| `gross_margin_range` | SKIP (`sector_excluded`) | Financial Services sector exclusion |
| `net_margin_ceiling` | PASS | 31.3% within ceiling |
| `revenue_reconciliation` | SKIP (`sector_excluded`) | Financial Services sector exclusion |
| `fiscal_year_recency` | PASS | FY2025 filed 2026, lag 1 year ≤ 2 |
| `revenue_growth_sanity` | PASS | 2.8% growth in range |

3 rules run, 2 skipped (sector exclusion).

### Cross-Validation

| Field | FinLens | FMP | pct_diff | Status |
|---|---|---|---|---|
| revenue | $182.45B | $279.75B | 34.78% | DISAGREE |
| net_income | $57.05B | $57.05B | 0.0% | AGREE |
| total_assets | $4,424.9B | $4,424.9B | 0.0% | AGREE |
| operating_cash_flow | -$147.78B | $100.87B | 246.51% | DISAGREE |

Overall: **disagreement**. FMP fetch succeeded.

### Lessons

- **Revenue definition mismatch:** FinLens extracts "net revenue" from the EDGAR filing (net interest income + non-interest income = $182B); FMP uses gross interest income ($279B). Both are defensible; the divergence is definitional, not a data error.
- **Operating cash flow sign:** Bank operating cash flows regularly swing negative due to trading asset movements; FMP and EDGAR filings can classify these differently. Flag-and-show logic is correct here — never auto-correct.
- **Sector exclusions work correctly:** `gross_margin_range` and `revenue_reconciliation` excluded as expected for Financial Services.

---

## COST — FY2025

**Sector:** Specialty Retail
**Filing accession:** 0000909832-25-000101
**Audit date:** 2026-06-10

### Rules

| rule_id | Result | Why |
|---|---|---|
| `gross_margin_range` | SKIP (`field_unavailable`) | `gross_profit` not in extracted data |
| `net_margin_ceiling` | PASS | 2.9% within ceiling |
| `revenue_reconciliation` | SKIP (`field_unavailable`) | `gross_profit` not in extracted data |
| `fiscal_year_recency` | PASS | FY2025 filed 2025, lag 0 years |
| `revenue_growth_sanity` | PASS | 8.2% growth in range |

3 rules run, 2 skipped (field_unavailable — missing gross_profit).

### Cross-Validation

All fields UNMATCHED. `fmp_fetch_success: false`. FMP stable API returned a failure at audit time.

### Findings (post-audit investigation)

**COST's cv_cache failure is stale.** Current FMP response for COST:

- HTTP 200, list len=3
- FY2025 entry present: `fiscalYear=2025`, `date=2025-08-31`, revenue=$275.235B (exact match to FinLens value)
- `_find_year_entry(data, 2025)` would match correctly

**Root cause of audit-time failure:** Transient issue (API outage or rate limit) at 2026-06-10T21:02:32 UTC. The cache persisted the failure as `{fmp_vals: null, fmp_fetch_success: false}` and will not retry.

### Lessons

- **August year-end was a red herring:** FMP labels Costco FY2025 as `fiscalYear=2025` (fiscal year ending 2025-08-31). The `_parse_year` helper matches correctly.
- **Stale failure caching:** `cv_cache.json` caches failures permanently. A transient 402/outage at audit time poisons the cache entry. The fix (when ready) is either a cache TTL for failure entries or a manual cache-clear for `COST|2025`.
- **Gross profit derivation:** The `field_unavailable` skips for `gross_margin_range` and `revenue_reconciliation` triggered a backfill feature — gross profit can now be derived from `revenue − cost_of_revenue` when the `gross_profit` field is absent from extraction.

---

## MKL — FY2025

**Sector:** Specialty Insurance and Diversified Holding Company
**Filing accession:** null (not resolved at audit time)
**Audit date:** 2026-06-10

### Rules

All 5 rules SKIPPED.

| rule_id | Result | Why |
|---|---|---|
| `gross_margin_range` | SKIP (`sector_excluded`) | Insurance sector exclusion |
| `net_margin_ceiling` | SKIP (`field_unavailable`) | `revenue` not extracted |
| `revenue_reconciliation` | SKIP (`sector_excluded`) | Insurance sector exclusion |
| `fiscal_year_recency` | SKIP (`field_unavailable`) | `filing_year_int` not available |
| `revenue_growth_sanity` | SKIP (`field_unavailable`) | `revenue` and `revenue_prior` not extracted |

0 rules run, 5 skipped.

### Cross-Validation

All fields UNMATCHED. `fmp_fetch_success: false`. FMP stable API returned HTTP 402 for MKL.

**Confirmed by reproduction:** `https://financialmodelingprep.com/stable/income-statement?symbol=MKL...` → HTTP 402 Payment Required. MKL is a premium-tier symbol not available under the current FMP subscription.

### Lessons

- **Revenue alias gap (fixed):** Markel reports revenue under a non-standard label in EDGAR filings. Fixed in commit `26b56a2` — revenue alias mapping added so future MKL analyses extract the revenue field correctly.
- **MKL is FMP premium:** HTTP 402 means the stable API requires an upgraded subscription for this ticker. Not a code bug. Affects both `income-statement` and other endpoints.
- **Zero rules executed:** When `rules_run: 0`, the audit passes trivially (no evidence of integrity, no failures). This is a signal to investigate data extraction quality, not a clean bill of health.
- **Filing accession was null:** Suggests the filing was analyzed from an uploaded PDF rather than fetched from EDGAR, which is why `filing_accession` is absent.

---

## O (Realty Income) — FY2025

**Sector:** Net Lease REIT
**Filing accession:** 0000726728-26-000011
**Audit date:** 2026-06-11

### Rules

| rule_id | Result | Why |
|---|---|---|
| `gross_margin_range` | SKIP (`field_unavailable`) | `gross_profit` not in extracted data |
| `net_margin_ceiling` | PASS | 18.4% within ceiling |
| `revenue_reconciliation` | SKIP (`field_unavailable`) | `cost_of_revenue` and `gross_profit` absent |
| `fiscal_year_recency` | PASS | FY2025 filed 2026, lag 1 year ≤ 2 |
| `revenue_growth_sanity` | PASS | 9.1% growth in range |

3 rules run, 2 skipped (field_unavailable). `gross_profit_derived: false`.

### Cross-Validation

All fields UNMATCHED. `fmp_fetch_success: false`. FMP stable API returned HTTP 402 for all three endpoints.

**Reproduction evidence:**

```
O  income-statement          HTTP 402  type=parse_error
O  balance-sheet-statement   HTTP 402  type=parse_error
O  cash-flow-statement       HTTP 402  type=parse_error
```

Response body: plain text "Premium Query Parameter: 'Special Endpoint: This value set for 'symbol' is not available under your current subscription..." — body is not valid JSON, so `resp.json()` raises a parse error in addition to the 402.

**Failure trace:**
`HTTP 402` → `status_code != 200` → `_get_statement_list` returns `None` → `income_list is None` → `_fetch_fmp_raw` returns `(None, False)` → `fmp_fetch_success: False` → cached as permanent failure.

### What it is NOT

- **Not a single-letter ticker bug.** No code in FinLens filters or validates ticker length. The URL `?symbol=O&...` is constructed identically to `?symbol=MSFT&...`. The 402 is server-side.
- **Not a rate limit.** HTTP 402 is a payment/subscription error, not 429 (Too Many Requests). No 429s observed anywhere in this investigation.
- **Not an SSL problem.** `fmp.py` uses `session.verify = False` (bypasses SSL entirely). No certificate errors possible.
- **Not a REIT year-end issue.** Realty Income has a December 31 year-end — FMP's stable API would have calendar-year data for this. The 402 fires before any year-matching logic.

### Lessons

- **REIT field skips are data-driven, not sector-ruled.** REITs don't report `gross_profit` or `cost_of_revenue` in the traditional sense. The `field_unavailable` guard fires correctly. This is distinct from Financial Services, where skips are explicit `sector_excluded` rules. Consider adding a REIT sector exclusion rule to make intent explicit rather than relying on field absence.
- **FMP subscription gap:** "O" and MKL are premium-tier tickers on the current FMP plan. The stable API returns HTTP 402 for them consistently. MSFT, NVDA, AAPL, JPM all return 200. Before running future audit campaigns, check whether the target ticker is accessible under the current FMP key.
- **Cache poisons on failure:** The `cv_cache.json` entry `O|2025` is now permanently `{fmp_vals: null, fmp_fetch_success: false}`. Any future re-analysis of Realty Income FY2025 will read from cache and skip FMP. Failure entries need a TTL or a manual invalidation path.
