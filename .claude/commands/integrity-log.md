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
- If `cross_extractor_agreement` records exist, print the Gemini second-extractor section from the integrity-log analysis:
  - log parse check, including unparseable JSON line count
  - agreement counts by `checker_version`
  - latest definitive state counts by accession
  - FLAGGED severity breakdown (`hard` / `soft` / `unclassified`)
  - model + checker_version stamps
  - per-CONFLICT detail: field, FinLens value, Gemini value, FinLens label, Gemini label, severity
  - triage status for each latest FLAGGED/PARTIAL target field: `OPEN` or dispositioned with disposition + rationale
  - open triage target count
- Notable findings:
  - any fired rules
  - any sector exclusions
  - any field_unavailable skips
  - any cross-validation DISAGREE or UNMATCHED fields
  - any cross-extractor OPEN triage targets
  - whether gross profit was derived

This command remains read-only by default. To write a cross-extractor human triage disposition only when explicitly requested, use:

`.\venv\Scripts\python.exe scripts\write_cross_disposition.py --filing-accession <accession> --ticker <ticker> --fiscal-year <FY####> --field <canonical_field> --checker-version <version> --disposition <finlens_correct|checker_error|deliberate_mapping_decision|structural_absence|gemini_miss_field_present|other> --rationale "<required rationale>"`

Disposition linkage is `filing_accession + field + checker_version`; dispositions do not carry across checker-version bumps.

If the log file is missing or empty, report that plainly and stop.
