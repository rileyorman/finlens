# Cross Extractor Spec

## Purpose

The cross extractor is a non-blocking integrity signal for campaign/library
filings. It independently re-extracts the same canonical mapped fields from the
same source PDF using Gemini, compares those values against FinLens `mapped[]`,
and writes a typed record to the integrity log.

It is a signal only. It never gates analysis and never auto-corrects FinLens
values.

## Scope

V1 covers campaign/library filers only. It does not run on user uploads, and it
has no UI badge or app wiring. The manual runner is
`scripts/run_cross_extractor.py`.

The compared field set is per-filer: exactly the keys present in that filing's
`mapped` dict. There is no fixed headline list.

## Resolution

The source PDF is resolved only with
`modules.campaign_pdf.resolve_campaign_pdf(registry_entry)`. Resolver `None`
returns an explicit `UNCHECKED` result with reason `pdf_unresolvable`.

## Native Units

The comparison is in filing-native units: same source PDF, same filing currency,
same filing scale. There is no normalization, no FX conversion, and no FMP.

This is the reason Gemini is used instead of FMP for SEDAR filers. FMP can have
currency mismatches and Canadian coverage gaps; Gemini re-extracts from the same
source PDF.

## Field Status

Per-field status reuses the spike tolerance:

- `AGREE`: values are same-sign and within 0.5% relative difference.
- `CONFLICT`: values differ beyond tolerance, signs differ, or FinLens has no
  value while Gemini returned one.
- `GEMINI_MISSING`: Gemini omitted the field.

Each field record captures both raw labels:

- `finlens_label`
- `gemini_label`

## Filing State

The filing-level state is exact:

- `FLAGGED`: any field is `CONFLICT`.
- `PARTIAL`: no conflicts and one or more `GEMINI_MISSING`.
- `VERIFIED`: all fields `AGREE`, zero missing.
- `UNCHECKED`: no comparison was possible.

Amendment, 2026-07-03: `PARTIAL` is the ratified fourth state, amending the
original #7 three-state model. Rationale: honest Gemini abstention on a
legitimately absent field, such as the SLF `insurance_finance_result` precedent,
is neither `VERIFIED` because the field was not verified, nor `FLAGGED` because
abstention is not disagreement. `PARTIAL` preserves the distinction between
needs re-run (`UNCHECKED`, transport/key/PDF failure) and fine, field absent
(`PARTIAL`, structural abstention).

Amendment to decision 4, 2026-07-02 (ratified by Riley via /codex-review): the original line "value mismatch =
hard flag, label-scope mismatch alone = soft flag" is amended to: value
mismatch on the same normalized source label = hard; value mismatch across
all differing normalized source labels = soft (scope-mismatch). Soft flags
remain triage-required; severity orders attention only, and it never waives
triage. Proof case: ATD `interest_expense` - FinLens 690.8 from statement
line "Financial expenses (Note 9)", Gemini 159.3 from the Note 9
lease-interest component. Different lines -> soft. Caveat: a wrong-line
mapping classifies soft; this is acceptable only while soft retains
triage-required status - severity orders attention, it never waives triage.

`FLAGGED` remains the filing-level state for any `CONFLICT`. Severity is a
sub-classification inside `FLAGGED`, not a fifth state.

For each `CONFLICT` field in a `FLAGGED` record, `severity` is:

- `hard`: value mismatch on the same normalized source label.
- `soft`: value mismatch across differing normalized source labels, or a
  missing/empty Gemini label where same-line reading cannot be confirmed.

`UNCHECKED` reasons are:

- `pdf_unresolvable`
- `no_key`
- `no_mapped_fields`
- `gemini_error`
- `parse_error`

Every failure path returns and logs an explicit `UNCHECKED` result. The module
never silently returns `VERIFIED`, silently omits a record, or continues without a
typed outcome.

## Integrity Log

Records use `record_type="cross_extractor_agreement"` and are idempotent on
`filing_accession` plus `checker_version` for definitive states only.
`VERIFIED`, `PARTIAL`, and `FLAGGED` are write-once per checker version.
`UNCHECKED` records remain appendable so a later run after fixing a key,
transport, or PDF issue can persist the upgraded definitive result. The log is
append-only: later records never replace earlier records.

`checker_version` represents checker behavior: classifier semantics and prompt
scoping. Version `1` is the implicit legacy version for the 2026-07-03 corpus
run and for any historical record without a `checker_version` key. Version `2`
comprises the severity classifier and tightened consolidated-statement prompt.
Bump `checker_version` on any future checker behavior change. Readers collapse
multiple definitive records for the same `filing_accession` to the highest
`checker_version`, with record `timestamp` as the tie-breaker. Pre-version-2
corpus results (10 VERIFIED / 0 PARTIAL / 4 FLAGGED / 0 UNCHECKED) are not
comparable baselines for version-2 runs.

Each record includes:

- `timestamp`
- `ticker`
- `fiscal_year`
- `filing_accession`
- `model`
- `state`
- `reason`
- `cross_extractor_fields`
- `checker_version`

Each field contains `canonical_field`, `finlens_value`, `gemini_value`,
`status`, `finlens_label`, and `gemini_label`. `CONFLICT` fields in newly
written `FLAGGED` records also contain `severity` (`hard` or `soft`). Legacy
`FLAGGED` records without `severity` are valid historical records and must be
rendered as `unclassified`, never defaulted to `hard` or `soft`.

## SSL Hardening Finding

Empirical check against the installed `google-genai` package showed
`genai.Client` accepts `http_options=types.HttpOptions(httpx_client=...)`.
That allows the FinLens HTTPS hardening pattern to be applied:

- `trust_env=False`
- Windows system certificate store loaded into an `ssl.SSLContext`

The module constructs Gemini clients with a custom `httpx.Client`, using the
Windows cert-store context on Windows and `trust_env=False` on all platforms.

## Deferred

- UI badge / app wiring
- User-upload path
- Per-field tolerance tiers
- Restatement auto-detection
- FMP or FX/normalization logic
