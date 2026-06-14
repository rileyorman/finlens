# Learn Mode — Design Sketch (v1, pressure-test before building)

**Status:** v1 design sketch from a conversation, NOT yet finalized. Pressure-test the flow before building. Revise freely.
**Date:** 2026-06-13

## Purpose
A clean, simple, GUIDED investing-learning experience that sits ALONGSIDE the full FinLens app (non-destructive toggle — "Learn mode" vs "full mode"). Strips the builder/commercial chrome (registry, integrity badges, model selectors, multi-fetch paths, sector internals, half-built stubs) and centers the value-investing decision path.

## Audience
A finance-LITERATE beginner INVESTOR (Riley). Reads financial statements fine (working-capital base, CFO-EA background). New to INVESTMENT JUDGMENT — valuing a business, fair price, downside. So: do NOT re-teach accounting; teach investing DECISIONS on top of accounting already known.

## Scope decision (settled)
Public-stock value investing ONLY for v1. Startup-equity valuation is a SEPARATE, later thing (different tool/skill — cap tables, dilution, scenario modeling). Explicitly deferred. Don't build both at once — that recreates the sprawl Learn Mode exists to escape.

## The flow — 5 steps, one question each (linear SUGGESTED, not forced — Riley is capable, can jump)

1. **"What does this company do, and is it a good business?"**
   Load a company (one simple entry). Plain-language business summary + 3-4 QUALITY signals framed as judgment, not raw numbers (e.g. not "ROE 15%" but "ROE 15% — earns a solid return on owners' capital; >~12% generally healthy; consistently high can signal durable advantage"). Teaches: business quality before price (Munger "great business first").

2. **"Can I understand the financials?"**
   The 3 statements, CURATED to the 5-6 decision-relevant lines, each with a "why an investor cares" note. Reinforcement + investor-framing, NOT an accounting lesson. Teaches: which numbers drive value (owner earnings, debt, cash generation) vs noise.

3. **"What's it worth?" (DCF + intrinsic value)**
   DCF with ASSUMPTIONS foregrounded and explained (the lesson of DCF is it's only as good as inputs). User sets growth/discount; explain what each means + sensitivity. Output: intrinsic value vs price. Teaches: valuation is a RANGE built on assumptions, not a precise number. Humility about inputs.

4. **"Where's my margin of safety, and how could I lose money?" (the heart)**
   Margin of safety (intrinsic value vs price, plainly) + the Munger Inversion (now DCF-anchored via 31545b5 — quantified margin of safety + how it evaporates in the failure scenario). Teaches: downside FIRST — the single most important value-investing habit. This is where the tool earns its keep as a LEARNING tool.

5. **"So what do I think?"**
   A simple structured prompt for RILEY to form a view (Good business? Fair price? Acceptable downside?) with space for his own notes. Teaches: the tool INFORMS; the human DECIDES. Builds judgment, not dependence.

## Three principles holding it together
1. One path, always forward (load → quality → financials → value → downside → decide). No branching maze.
2. "Why it matters" everywhere, definitions nowhere (he knows what ROE IS; he's learning what it MEANS for a decision).
3. The tool informs, YOU decide. Never says "buy." Teaches reasoning.

## AI vs free (settled)
Free, deterministic metrics + plain-language "why it matters" explanations are the SPINE (they make you think). The Munger Inversion is the ONE deliberate paid AI step (pay-once design), invoked at the downside stage. Reasons: a learner who reaches their OWN conclusion learns more than one handed an AI verdict; free spine = run on many companies without cost anxiety; avoids the false-confidence trap of mistaking fluent AI output for truth.

## Companies (settled)
Teaching examples first, then your own. Pre-loaded examples chosen for CONTRASTING lessons (e.g. a high-quality compounder at a fair price vs a statistically cheap stock that's cheap for a reason — teaches opposite halves of value investing). Then "load your own" for real personal use. Worked example → independent practice. Optionally mirror the Columbia course's case-study companies so Learn Mode reinforces coursework.

## Approach (settled)
Build as a focused "Learn mode" ALONGSIDE the full app (non-destructive toggle), NOT a restructure of the existing app (destructive, risky, loses builder tools Riley still uses). The discipline that makes it work: RESTRAINT — it must feel calm and guided, one question per screen, not feature-rich. If it becomes another cluttered tab, it fails.

## Open questions to pressure-test before building
- Is the 5-step sequence actually right, or does real use suggest a different order?
- What exactly are the 2 contrasting teaching-example companies?
- How much "why it matters" explanation is enough vs patronizing for a finance-literate user?
- Does Step 4 need the DCF-into-inversion panel wiring done first (deferred CC follow-up from 31545b5)? Likely yes.
