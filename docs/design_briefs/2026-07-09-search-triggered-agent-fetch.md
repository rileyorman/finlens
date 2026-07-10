# Design Brief — Search-Triggered Agent Fetch (2026-07-09)

<!--
CC-first design session (workflow rule, ratified 2026-07-07): CC writes this
brief + the ruling doc directly; ask_fable.py reserved for high-powered calls.
Riley ratifies before any build. Faithful-transcription rule applies.
-->

## The question

How should FinLens let a user **search for a company + filing and have the
agent fetch it into the Upload Financial Statements flow**, so the user then
clicks analyze — without weakening a single existing gate? This is the
client-demand-flywheel front door (the commercial thesis's usage-driven
ingestion, CLAUDE.md "Corpus Flywheel"). Riley's ratified UX, verbatim
(2026-07-09): *"search a company and a filing and have OpenClaw fetch it and
load it into the Upload Financial Statements section so I can then click
analyze."* Build order: after the TOU+ARX triage session (done same day —
CB-025/026/027; both bundles PROMOTED; ARX VERIFIED 12/12).

## Evidence pack

**Upload flow mechanics (the convergence target).** The upload zone is an
expander at app.py:5725 ("📄 Upload Financial Statements (PDF or Word)")
holding `st.file_uploader` (app.py:5729, key `pdf_uploader_{uploader_key}`)
and the "Canadian filing (SEDAR+ / IFRS)" checkbox (app.py:5736,
key `canadian_sedar_upload`). EVERYTHING downstream consumes the single
`uploaded_file` object via `.name`, `.size`, `.getvalue()`:
- app.py:6167 — 20 MB size guard
- app.py:6177–6178 — `pdf_bytes = uploaded_file.getvalue()`; docx branch off
  `.name`
- app.py:6214+ — cache key / analysis cache; CB-015 document-class gate fires
  BEFORE Claude spend on this path
- app.py:6285 — `extract_text_from_pdf(uploaded_file)` (non-SEDAR branch)
- app.py:6382, 6442, 6465, 6486 — cache save, last_filename, library entry
An object with those three members entering at the `uploaded_file` variable
inherits the ENTIRE gate chain (document class → extraction → mapper →
engine → moat log → library) by construction.

**Agent transport (live, verified 2026-07-09, twenty-first session).** CC→
Sterling gateway HTTP over `tailscale serve`: POST
`https://mac-mini.local/v1/chat/completions`, header
`Authorization: Bearer <gateway_auth_token>` (working copy
`%USERPROFILE%\.secrets\openclaw_gateway_token`; NEVER printed/hardcoded),
header `x-openclaw-session-key: agent:main:telegram:direct:<chat-id>`
(routes the exchange into Riley's Telegram — visibility rule satisfied
automatically). Ops notes from the runbook (docs/OPENCLAW_OPS_RUNBOOK.md):
agent turns take 60s+ (ARX fetch turn was minutes); 401 = token problem;
connection-refused = serve/gateway down; root path `/` times out (normal).

**The stitched chain already works (2026-07-09, ARX FY2025):** Sterling
fetched the PDF from arcresources.com → handed the URL over the gateway
channel → the X1 worker independently re-fetched (sha256 MATCHED d6a50819…)
→ extract → map → review gate. Zero human actions. The app feature is this
chain with the app replacing the worker's fetch-side and converging on the
upload path instead of a candidate bundle.

**Provenance pattern (established, n=4 filers):** the fetch side returns a
URL; the receiving side re-fetches the bytes ITSELF and records
{url, sha256, byte_size, retrieval_timestamp_utc, retrieval_method}
(candidates/*/provenance.json shape, worker v1). TOU's PDF now has 5
independent byte-identical fetches on record; ARX 3.

**Failure precedents:** IR pages can be Cloudflare-blocked (AEM precedent —
CLAUDE.md flywheel caveats: "agent-fetch reliability is an operational
dependency"). SEDAR+ has a Radware CAPTCHA — automation of it is BANNED
(standing rule, docs/INGESTION_WORKER_SPEC.md); issuer-hosted / EDGAR only.

**Secrets pattern:** no plaintext .env (SOPS migration 2026-07-08); app reads
env via os.getenv; run.bat injects via `sops exec-env`. GEMINI_API_KEY was
LOST in that migration and rediscovered missing only when needed
(twenty-second session) — new env vars must be added to the store AND
documented in .env.example the same commit.

**Graceful-degradation precedent:** supabase_storage.py fails gracefully when
credentials are missing (CLAUDE.md) — same posture required here.

## Constraints

- **Integrity-first / zero silent errors:** every fetched byte-stream goes
  through the EXACT gates a manual upload gets (CB-015 document class before
  any Claude spend; extraction; mapper; engine; moat log). The fetched-bytes
  path must not fork the upload path (Change Propagation Rule — the docx
  6-location incident is the cautionary tale).
- **Moat-log boundary unchanged:** Sterling never writes integrity records;
  the app-side pipeline writes them exactly as it does for manual uploads.
- **No SEDAR+ CAPTCHA automation.** Issuer IR pages / EDGAR only.
- **Visibility rule:** agent tasks land in Riley's Telegram (the session-key
  header does this automatically on the current channel).
- **Budget:** each search = one Sterling agent turn (his capped key) + the
  normal extraction cost on analyze. Pre-commercial, the clicker IS Riley,
  so per-click authorization is inherent; no unattended loops.
- **Secrets:** gateway URL/token/session-key enter ONLY via env (SOPS store);
  missing config → feature disabled with an honest caption, never a crash.
- **Not up for relitigation:** the ratified UX sentence itself; the
  CC-first → Riley-ratifies workflow; the provenance re-fetch pattern.

## Requested output

Rulings + rationale, implementation spec (app-side; no Sterling-side config
changes should be needed), acceptance tests, open questions with
recommendations. Topic-specific asks: (1) the exact agent output contract
(JSON shape + how strictly to parse); (2) the UploadedFile-shim convergence
mechanism; (3) the honest async-state UX inside Streamlit's rerun model;
(4) failure taxonomy (not-found / blocked / timeout / bad-bytes) with
user-facing copy; (5) what provenance is recorded where.
