# FinLens Data Integrity Engine - Audit Prompt

- Run after each batch of ~7 filings, OR after adding meaningful sector variety (a bank, REIT, insurer, or foreign filer each warrant an audit even at lower counts)
- Run with: Opus 4.8
- Save output to: docs/audits/integrity_audit_YYYYMMDD.md
- Principle: the engine must CATCH bad data and LEARN from volume. Test its judgment, not its uptime. A gate that runs cleanly but misses errors is worse than none.

## PART 1 - DETECTION TEST (poisoned fixtures) - most important, never skip

- Load a known-good filing (default: NVDA FY2026)
- Create poisoned copies, one corruption each, run validate_filing() on each:
  - Swap Revenue and Cost of Revenue -> expect revenue_reconciliation, gross_margin_range
  - Set fiscal year to 2010 -> expect fiscal_year_recency
  - Inflate gross margin above 100% -> expect gross_margin_range
  - Set net income > revenue -> expect net_margin_ceiling
  - Set revenue growth to +300% -> expect revenue_growth_sanity
- For each: report PASS (flagged) or FAIL (passed silently) and which rule(s) fired
- ANY silent pass = CRITICAL failure, report at top of audit
- Keep fixtures scripted/reproducible so this re-runs identically every audit

## PART 2 - LOG-LEARNING REVIEW

- Run analyze_log()
- Report rules that NEVER fired a warning (too loose, or untested - say which)
- Report rules that fired on a HIGH proportion of filings (too strict or sector-blind)
- Report observed-value ranges for numeric rules (gross_margin, net_margin, revenue_growth) vs current thresholds
- Name any threshold that legitimate data is approaching
- Every tuning recommendation must cite log evidence - no recommendation without data

## PART 3 - CROSS-VALIDATION REVIEW (once divergence data exists)

- From FinLens vs FMP divergence records:
  - Which fields agree tightly, which diverge, by how much
  - Any SYSTEMATIC divergence on a specific field + hypothesis (classification difference vs real error)
  - Where sources disagree, note which appears correct where determinable (build per-field reliability picture)
  - Do NOT auto-resolve - surface for judgment

## PART 4 - COVERAGE GAPS

- List sectors actually tested (from the log)
- Name what's missing (no insurer / REIT / foreign filer / thin-margin retailer / etc.)
- Confidence is only as broad as sectors tested, regardless of how clean results look
- Set next deliberate fetch targets to fill the biggest gaps

## PART 5 - REGRESSION CONFIRMATION

- Re-run validate_filing() on baseline set: MSFT FY2025, NVDA FY2026, AAPL FY2025, JPM FY2025
- Confirm each returns the same status and same per-rule results as last known-good audit
- Any drift = regression to investigate before anything else

## OUTPUT

- Write dated report to docs/audits/integrity_audit_YYYYMMDD.md
- PASS/FAIL at the top (FAIL if any poisoned fixture passed silently OR any baseline regressed)
- Then the five sections
- End with a prioritized list of tuning actions, each tied to its evidence
