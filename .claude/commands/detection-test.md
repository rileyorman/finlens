Prefer running `python -m pytest tests/test_integrity_detection.py -v` and reporting results; fall back to the manual steps below only if the test file is missing.

Run the Data Integrity Engine detection test. This proves the gate catches corrupted data. Follow these steps in order:

STEP 1 - Load a known-good filing
- Load NVDA FY2026 normalized data from the library or the repo fixture (the confirmed-clean baseline).

STEP 2 - Create poisoned copies
- Make 5 separate copies of the NVDA data, each with ONE corruption injected:
  - Copy 1: swap Revenue and Cost of Revenue
  - Copy 2: set fiscal year to 2010
  - Copy 3: inflate gross margin above 100% (set CoR negative, or Revenue tiny)
  - Copy 4: set Net Income greater than Revenue (net margin > 100%)
  - Copy 5: set revenue growth to +300%

STEP 3 - Run the engine on each
- Run validate_filing() on each of the 5 poisoned copies.
- For each copy, record: did the engine FLAG it (PASS) or did it pass silently (FAIL), and which rule(s) fired.

STEP 4 - Expected results (confirm each)
- Copy 1 (swap Rev/CoR): should fire revenue_reconciliation AND/OR gross_margin_range
- Copy 2 (FY2010): should fire fiscal_year_recency
- Copy 3 (margin >100%): should fire gross_margin_range
- Copy 4 (net margin >100%): should fire net_margin_ceiling
- Copy 5 (+300% growth): should fire revenue_growth_sanity

STEP 5 - Report
- Print a table: corruption | caught? (PASS/FAIL) | rule(s) that fired
- If ANY copy passed silently (FAIL), flag it at the TOP as a CRITICAL blind spot.

STEP 6 - Make it reproducible
- Keep the poisoned-fixture logic in tests/test_integrity_detection.py so this exact test re-runs on demand.
- Do NOT pollute the real integrity log. Run these against the engine in isolation.
