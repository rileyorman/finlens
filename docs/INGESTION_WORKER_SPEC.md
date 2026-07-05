# Ingestion Worker — Build Spec (v1 DRAFT)

**Status:** DRAFT 2026-07-05 — design ratified in principle by Riley
(Sterling as fetcher-and-extractor); PILOT is the acceptance test.
FULL-SCALE VOLUME RUNS REMAIN GATED behind the #1 correctness gate per the
ratified sequencing and the handoff "Moat thinking" note (ingestion jumps
the queue WHEN the gate is met — not before).
**Builder:** Sterling (sandbox). **Reviewer/committer/analyst-of-record:** CC.
**Queue position:** task #3, behind the prior-column continuity checker.

## Purpose and the one inviolable rule

Sterling turns filings into REVIEWABLE CANDIDATE ARTIFACTS at machine speed.
He is a fetcher-and-extractor, NEVER the analyst-of-record:

- THE MOAT LOG IS SINGULAR. Integrity records are written ONLY on Riley's
  Windows machine by the canonical pipeline. Nothing Sterling produces is
  moat data until it crosses the CC review gate. A fragmented moat log is
  not a moat.
- Judgment never delegates: new aliases, sector routing, canonical-field
  questions come back as FLAGGED QUESTIONS, never as decisions made by the
  worker (augment-don't-mint discipline; the adjudication casebook stays
  human-authored).

## Architecture

Sterling (Mac mini, sandbox repo)          CC (Windows, canonical repo)
  fetch PDF (issuer IR / EDGAR)              re-fetch PDF by recorded URL
  extract with STERLING'S OWN key    ==>     verify sha256 matches
  map deterministically (mapper)     git     re-run CANONICAL extraction
  bundle artifacts on ingest/ branch ==>     compare vs Sterling's candidate
  flag judgment questions                    run guards + cross-extractor
                                             write integrity records (moat)
                                             triage flags with Riley

## Part A — Sterling-side worker (sandbox: scripts/ingest_worker.py)

### Sourcing rules (hard constraints)

- Sources: issuer investor-relations pages and SEC EDGAR only. SEDAR+
  CAPTCHA circumvention is PROHIBITED — the campaign default is
  issuer-hosted PDFs (docs/FETCH_CAMPAIGN_LOG.md precedent). If a filing is
  only obtainable through SEDAR+ interactively, flag it for Riley's manual
  browser download; do not automate around access controls.
- Record full provenance at fetch time: origin URL, retrieval method,
  retrieval timestamp (UTC), PDF sha256, byte size, original filename.

### Extraction run

- Headless: import the existing modules (pdf_extractor, claude_analyzer,
  sedar_extractor/mapper) — no Streamlit, no app.py changes.
- API key: Sterling's OWN spend-capped Anthropic key via env var
  FINLENS_INGEST_API_KEY. FinLens production keys never exist on the mini.
- Data dir isolation: the worker MUST point all FinLens data writes
  (cache, logs) at a scratch dir via FINLENS_DATA_DIR. Any integrity-log
  lines produced on the mini (e.g. the figure-presence guard's append) are
  SCRATCH DIAGNOSTICS — shipped inside the bundle for CC's information,
  never merged into the moat log. BUILD NOTE: if any log/cache helper is
  found not honoring FINLENS_DATA_DIR, parameterizing it is in scope for
  this build (flag it in the report).

### Candidate artifact bundle (committed to branch ingest/<TICKER>-<FY>)

candidates/<TICKER>_<FY>/
- extraction.json    — financial_data as returned (incl. figure_presence)
- mapping.json       — attach_mapping output for SEDAR filers (mapped,
                       unmapped, meta), or a note that the filer is EDGAR/XBRL
- provenance.json    — the sourcing record above (URL, sha256, timestamps)
- worker_meta.json   — model used, key LABEL (never the key), guard verdict,
                       scratch-log lines, runtime, worker version
- questions.md       — judgment flags (see below); empty file if none
- THE PDF IS NOT COMMITTED — size and copyright discipline. sha256 + URL
  stand in for it; CC re-fetches independently (which doubles as a
  provenance check).

### Judgment flags (questions.md), mandatory triggers

- mapped_count below the sector's typical range, or zero
- sector routing ambiguous (multiple token-ladder candidates, or the filer
  self-describes outside known shapes — e.g. gas-weighted "Oil & Gas")
- an unmapped label that LOOKS like an existing canonical concept (alias
  candidate — report it, do NOT add it)
- figure-presence verdict FABRICATED or ratio below 0.6
- currency ambiguity, mixed-period statements, missing statement sections
- anything requiring a canonical-definition interpretation

## Part B — CC-side review runner (canonical: scripts/review_candidates.py)

Given a fetched ingest/ branch:
1. Re-fetch the PDF from provenance.json's URL; verify sha256. Mismatch or
   dead URL → candidate REJECTED back to Sterling with reason (integrity
   first: no artifact without verifiable source).
2. Run the CANONICAL extraction on this machine (production config/keys).
   Sterling's extraction.json is never promoted directly — it serves as an
   independent-agreement witness: compare canonical vs candidate per field,
   report divergences (a free second-extractor-style signal alongside the
   Gemini check).
3. Run the full canonical path: mapper, guards, integrity engine,
   cross-extractor where applicable. Integrity records land in the real
   moat log HERE — /integrity-log evidence per the standing gate.
4. Surface Sterling's questions.md items + any canonical/candidate
   divergences as the triage list for Riley.
5. Output a per-candidate disposition: PROMOTED (fixture/library candidate),
   NEEDS_TRIAGE, or REJECTED (with reason, returned to the sandbox).

## Cost and throughput expectations

- Sterling-side extraction: roughly $0.10–0.30 per filing on his capped key
  (~$25/mo cap supports 100+ candidates — cap raises are Riley's call).
- Canonical re-extraction doubles the per-filing extraction cost by design:
  two independent reads are the point, not waste.
- Post-gate target: 2–5 promoted filings/day without Riley in the fetch loop.

## Pilot = acceptance test (the only pre-gate run authorized)

- Scope: 2–3 filers from ONE vertical Riley picks (recommend REIT or
  resource — deepest adjudication casebook).
- Sterling produces bundles; CC runs the review side end-to-end; at least
  one candidate should surface a real judgment question (if none do, probe
  why — silence is suspicious at this corpus size).
- Success = integrity records written canonically with /integrity-log
  evidence, provenance re-fetch verification working, divergence comparison
  producing sane output, and a spec v2 list of what the pilot proved wrong.
- After the pilot: STOP. Volume waits for the gate, per ratified sequencing.

## Out of scope for v1

- Any app.py/UI changes (CC-side, later)
- New sector profiles or aliases minted by the worker (flag-only)
- SEDAR+ automation of any kind
- Automatic promotion to fixtures/registry (human + CC step, unchanged)
- Scheduling/cron (pilot is manually triggered end to end)

## Deliverables

Branch feat/ingestion-worker in the sandbox: the worker script, the review
runner, tests (tmp_path everything; a fake-bundle fixture for the runner;
zero network in tests — fetch functions mocked), plus a WORKER_RUNBOOK
section appended to this doc describing exact invocation. Standard report:
files, test summary, ruff, 3–5 sentences. CC reviews, runs the pilot
jointly with Riley, commits.
