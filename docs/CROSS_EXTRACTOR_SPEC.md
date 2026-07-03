# Cross Extractor V1 Spec

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

V1 records labels only. It does not classify label mismatches.

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
`filing_accession` for definitive states only. `VERIFIED`, `PARTIAL`, and
`FLAGGED` are write-once. `UNCHECKED` records remain appendable so a later run
after fixing a key, transport, or PDF issue can persist the upgraded definitive
result. V1 appends the later record rather than replacing the earlier
`UNCHECKED` audit trail.

Each record includes:

- `timestamp`
- `ticker`
- `fiscal_year`
- `filing_accession`
- `model`
- `state`
- `reason`
- `cross_extractor_fields`

Each field contains `canonical_field`, `finlens_value`, `gemini_value`,
`status`, `finlens_label`, and `gemini_label`.

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
- Label-mismatch classification
- Per-field tolerance tiers
- Restatement auto-detection
- FMP or FX/normalization logic
