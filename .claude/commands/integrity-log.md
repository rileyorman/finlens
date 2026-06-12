Read-only integrity log review. Do not commit. Do not modify files. Do not call external APIs.

Read `C:\Users\riley\.finlens\integrity_log.jsonl` and find the newest filing validation entry. Then print:

- Ticker, fiscal year, filing source, filing accession, sector, overall status, and `gross_profit_derived`.
- Every rule in the newest validation entry with:
  - rule_id
  - observed value
  - threshold
  - result: PASS, FLAG, or SKIP
  - skip reason when present
  - message
- The newest matching cross-validation record for the same ticker and fiscal year, if present, as a table:
  - field
  - FinLens value
  - FMP value
  - pct_diff
  - status
- Notable findings:
  - any fired rules
  - any sector exclusions
  - any field_unavailable skips
  - any cross-validation DISAGREE or UNMATCHED fields
  - whether gross profit was derived

If the log file is missing or empty, report that plainly and stop.
