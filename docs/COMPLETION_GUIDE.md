# FinLens Completion Guide

**Written 2026-07-06 (end of the fifteenth session, ratified by Riley).
This is the map from the current state to "done." It sequences; it does
not restate. Sources of truth it points into: SESSION_HANDOFF.md (state +
open queue), CLAUDE.md (enforcement copy), ADJUDICATION_CASEBOOK.md
(rulings), SEDAR_EXTRACTION_DESIGN.md (settled architecture),
FinLens_Roadmap_Addendum.md (post-gate feature tiers).**

---

## How progress is protected (read before changing ANYTHING)

Progress cannot be silently reversed while these hold. Any session — any
model, any tool — must keep them holding:

1. **The test suite is the floor.** 379 green as of 2026-07-06. Every
   casebook ruling is pinned by tests. NEVER weaken, delete, or skip a
   pinning test to make a change pass — a failing pin means the CHANGE is
   wrong or a new design session is needed, not the test.
2. **Settled decisions are settled.** CLAUDE.md + the casebook +
   SEDAR_EXTRACTION_DESIGN.md are not to be relitigated without Riley's
   explicit sign-off. Empirical evidence > documentation (CLAUDE.md
   principle): never replace working code with "theoretically more
   correct" code.
3. **Every session starts with `/handoff`.** The handoff doc is the only
   authoritative "where are we"; this guide is the only authoritative
   "what order."
4. **The change ritual is fixed:** evidence assembled → options stated
   fairly → Riley ratifies → ship with tests + casebook entry in the SAME
   commit → full suite + registry regen when mapped_counts change →
   integrity-log evidence for analysis-path changes → commit cites the CB
   id. No ad-hoc builds of anything marked "design session needed."
5. **The moat log is append-only and singular.** Only the canonical
   pipeline on this machine writes integrity records. Sterling never does.
6. **Both branches live on GitHub** (rileyorman/finlens); dev ==
   main == origin at session close. Nothing exists only on this laptop.

---

## The path to done (in order)

### Phase 1 — Close the correctness gate (the current phase)
The #1 gate: FinLens is shown to no one until extraction is provably
correct and cold loads degrade honestly. Status: **the five-slot dry-run
set is CLOSED (2026-07-06)** — producer / REIT / financial-or-insurer
PASS, edge resolved-with-accepted-residuals, explorer served. Remaining:
item 4 only.
1. ~~**Financial-or-insurer cold slot**~~ — **DONE (TD FY2025, FAIL →
   PASS same session 2026-07-06; slot record in SESSION_HANDOFF.md,
   rulings in CB-018).**
2. ~~**Explorer slot decision**~~ — **DONE (ratified 2026-07-06): SERVED
   by SIG's human ground-truth stamp (mapping layer, shape n=2) + NGEx's
   cold app-path run (display layer).**
3. ~~**NGEx edge-slot residuals**~~ — **DONE (ratified 2026-07-06):
   explicitly accepted as non-blocking** (column order → Phase 2.2
   header/receipts UI work; explorer red-flag sector-awareness → small
   design decision, queued).
4. **Founder cold-load gate** — Riley narrates CNQ + Suncor panel-by-panel
   unaided (FOUNDER_COLDLOAD_PREP; his gate on himself). No external
   conversation before this passes. **This is now the ONLY remaining
   Phase-1 item.**

### Phase 2 — Post-gate hardening (converts craft into a compounding asset)
Order ratified in the moat notes: ingestion scale jumps the feature queue.
1. **Sterling ingestion volume** (now unblocked) — campaign pipeline cheap
   per filer; every new filer compounds the corpus + casebook.
2. **Header/receipts UI** (Allied findings #1–#4): company identity strip
   (name from filing + logo + prominent period·currency) and the
   **mapped-fields receipt view** — per-figure provenance a skeptic can
   audit in 60 seconds. This is the legibility half of the moat.
3. **Legacy scrape retirement** (doctrine rule 1): inventory remaining
   `_lookup`/label-scrape consumers in excel_exporter/app.py and route
   them through canonical fields; the Allied incident class dies for good.
4. Remaining queued engineering: analysis-cache mapper-version stamp
   ("re-map without re-analyse" heals cached entries free), engine ctx
   net_income mapped-fallback, re-analyse filing-date carry, CSU
   cover-date, Option A full-corpus re-extraction.

### Phase 3 — Market validation (ask, don't demo)
Sequencing principle (settled 2026-06-15): correctness before market.
1. One real fund-manager/family-office conversation: would validated
   Canadian-filing fundamentals with per-figure receipts be worth paying
   for? ASK — do not demo the product.
2. ~5 real test users (finance students / value investors) — the
   falsifiable answer to the Step-7 "unfalsifiable frame" critique.
3. Persona check: fund-manager lane holds only if a real signal appears;
   revisit honestly if it doesn't.

### Phase 4 — Commercial build-out (only after Phase 3 signal)
Per the roadmap addendum tiers + the trust-tiered on-demand model:
validated corpus answers instantly (VERIFIED + receipts); long tail
fetched on demand by the productized worker, honestly badged
UNCHECKED/PARTIAL → upgraded after triage. Build order there:
FinLens_Roadmap_Addendum.md (lot-level positions → Catalyst Calendar →
Memo Builder → Filing Diff → Curriculum Mode), re-weighed against the
fund-manager persona at that time.

### Standing, phase-independent
- Sunday audit ritual (+ deferred Steps 7/8 re-weigh).
- The six-rule engineering doctrine (memory: engineering-doctrine) governs
  all new code.
- Columbia course (Jul 14+): dogfooding deliberately deferred until after;
  FinLens remains craft + learning vehicle until then.

**Definition of done (v1):** gate closed (Phase 1), receipts UI live
(Phase 2.2), one honest market signal (Phase 3). Everything after that is
a business, not a project.
