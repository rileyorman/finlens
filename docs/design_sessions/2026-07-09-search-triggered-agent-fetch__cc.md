# Design Session — Search-Triggered Agent Fetch (2026-07-09) — CC ruling

**Status: UNRATIFIED until Riley signs off.** Brief:
docs/design_briefs/2026-07-09-search-triggered-agent-fetch.md. CC-first seat
per the 2026-07-07 workflow revision. Ratified rulings get casebook entry
CB-028.

---

## R1 — UI: a "Fetch from the web" panel INSIDE the Upload expander

The Upload Financial Statements expander (app.py:5725) gains a second intake
lane under the file_uploader: two text inputs — **Company** (e.g.
"Tourmaline Oil") and **Filing** (e.g. "FY2025 annual financial
statements") — plus a **"Canadian filing (SEDAR+/IFRS)"** checkbox
(default **True** — the flywheel is SEDAR-first; the manual uploader's
checkbox stays independent) and a **Fetch** button. RATIONALE: the ratified
UX says "load it into the Upload Financial Statements section" — the fetch
lane lives where its result lands, not in a new tab.

## R2 — Async states: honest, blocking, staged via st.status

Streamlit's rerun model makes a blocking call with a staged `st.status`
container the simplest HONEST v1 (background threads + polling add real
failure modes for zero user value at n=1 users). Stages shown live:
1. `AGENT SEARCHING…` — the gateway turn (60s–3min; timeout **240s**)
2. `VERIFYING + FETCHING…` — the app re-fetches the returned URL itself
   (timeout 120s, size cap 20MB to mirror the upload guard)
3. `LOADED — ready to analyze` → the file lands in the upload flow
Every terminal failure state renders an honest message AND the manual-upload
fallback line ("Download the PDF in your browser and drop it above — same
pipeline."). The page being blocked ~1–3 min is acceptable and DISCLOSED in
the button help text.

## R3 — Agent output contract: one strict JSON object, fetch-only

The gateway prompt instructs Sterling: find the issuer-hosted (or EDGAR)
direct-PDF URL for the named company + filing; do NOT download-and-relay
content; do NOT attempt SEDAR+ (CAPTCHA — banned); reply with EXACTLY one
JSON object, no prose:

```json
{"status": "found" | "not_found" | "blocked",
 "url": "<direct PDF url or null>",
 "notes": "<one line: what was searched / why blocked>"}
```

Parsing: extract the first `{...}` block; malformed reply → terminal state
`AGENT_REPLY_UNPARSEABLE` (honest error, no retry loop in v1). `blocked` =
the Cloudflare/AEM class — surfaced verbatim with the manual fallback.
RATIONALE: strict contract = the Sterling-flags-instead-of-improvises
lesson from the CB-019 pilot; URL-not-bytes = the provenance pattern.

## R4 — Provenance: the app re-fetches bytes itself and records the receipt

The app NEVER trusts relayed content: it httpx-GETs the returned URL,
computes sha256, and records
`{url, sha256, byte_size, retrieval_timestamp_utc,
retrieval_method: "app_agent_fetch", agent_channel: "openclaw_gateway"}`.
The dict rides in session state and is written into the library entry
ADDITIVELY on save (read-side .get defaults — no schema bump; absence on
old entries is honest). Bytes are also cached to
`~/.finlens/pdfs/_fetched/<Company>_<Filing>.pdf` so Re-Analyse works later
(the registry-entry dead-end lesson). Non-PDF content-type or >20MB →
terminal `BAD_BYTES` state, nothing enters the pipeline.

## R5 — Convergence: an UploadedFile shim assigned to the SAME variable

The load step wraps the fetched bytes in a tiny shim exposing exactly what
the downstream flow consumes — `.name`, `.size`, `.getvalue()` — and stores
it in session state; immediately after the file_uploader (app.py:5729) the
intake code does `uploaded_file = uploaded_file or _fetched_shim` and, when
the fetch lane's Canadian checkbox is set, drives the SEDAR routing the same
way the manual checkbox does. CONSEQUENCE (the point of the design): the 20MB
guard, docx branch, cache key, CB-015 document-class gate, extraction,
mapper, engine, moat log, and library save all fire UNCHANGED BY
CONSTRUCTION — there is no second path to drift (Change Propagation Rule
satisfied structurally, not by checklist). The user then clicks analyze
exactly as if they had dragged the file in.

## R6 — No auto-analyze, no auto-spend

Fetch ends at LOADED. The analyze click — and its Claude spend — stays with
the user (the ratified UX's "so I can then click analyze" is load-bearing).
The only cost a fetch itself incurs is one Sterling gateway turn (his capped
key) — and the clicker is Riley pre-commercial, so per-click authorization
is inherent. No retries without a fresh click; one fetch in flight at a time.

## R7 — Config: three env vars via SOPS, graceful degradation

`OPENCLAW_GATEWAY_URL`, `OPENCLAW_GATEWAY_TOKEN`,
`OPENCLAW_GATEWAY_SESSION_KEY` — read via os.getenv, added to the SOPS store
AND .env.example in the same commit (the GEMINI-key-lost-in-migration lesson,
twenty-second session). Any missing → the fetch lane renders disabled with
an honest caption ("Agent fetch not configured on this machine"), never a
crash (supabase_storage posture). Token value never logged, printed, or
committed.

## R8 — Evidence gate (review requirements for the build)

(a) Live end-to-end demo on a real filer NOT already cached, driven through
the real UI; (b) the resulting analysis writes its moat-log validation
record exactly as a manual upload does — shown as the JSONL line per the CC
review checklist; (c) provenance dict verified on the library entry;
(d) failure states exercised live: not_found (gibberish company), blocked or
timeout (whichever is reproducible), missing-config (env var unset).
Sibling paths to check at review: manual upload unchanged; Re-Analyse on a
fetched entry resolves the `_fetched` PDF; library display of the new
provenance fields has safe defaults.

---

## Open questions for Riley (each with a recommendation)

**OQ1 — Session key: reuse the Telegram-routed key, or mint a dedicated
`agent:main:telegram:...` session for app fetches?** REC: **reuse** for v1 —
every app-triggered fetch lands visibly in your Telegram thread (the
visibility rule for free); revisit when there is a second user.

**OQ2 — Should the fetch lane ALSO work for US/EDGAR filings, or SEDAR-only
v1?** REC: **accept both** (the agent contract already allows EDGAR URLs;
the Canadian checkbox routes extraction correctly either way), but the
button copy says "best for Canadian filings" — EDGAR already has a native
fetch path in the app.

**OQ3 — Timeout: 240s for the agent turn?** REC: **yes** — ARX's fetch turn
ran minutes; 240s covers the observed range; the status line counts.

**OQ4 — Should a successful fetch auto-check "Canadian filing" on the MANUAL
uploader too?** REC: **no** — the lanes stay independent; the fetch lane has
its own checkbox (R1). Less spooky action.

---

## Acceptance tests (for the build's pinning suite)

T1 shim exposes name/size/getvalue and byte-identical content;
T2 missing env vars → lane disabled, no exception, honest caption;
T3 agent reply parsing: found/not_found/blocked/malformed → correct states;
T4 re-fetch sha256 recorded; non-PDF content-type → BAD_BYTES, pipeline
untouched; T5 size cap enforced (20MB, mirrors app.py:6167);
T6 provenance dict lands additively on the library entry, absent-safe reads;
T7 one-fetch-at-a-time guard; T8 SEDAR routing flag honored end-to-end
(mapping present on the resulting analysis).
