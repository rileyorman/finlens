# Economics-Module Field-Name Contract Audit — 2026-07-02

**Status:** Investigation report only. No mapper, module, fixture, or test behavior was changed in this session. The fix is its own gated task after Claude.ai review.

**Trigger:** CNQ's Economics Snapshot (live check, 2026-07-02) showed revenue_to_market_cap and net_margin as "missing required inputs: revenue" while AEM's computed — same code path, same `revenue` input key. Root question recorded in SESSION_HANDOFF (4469b87): WHY does the mapper canonicalize the same economic concept under different names for different filers?

---

## 1. Answer to the root question

**Classification: sector-profile canonical-naming divergence — a design inconsistency in how sector profiles were authored, NOT a FIRST-WIN ordering effect and NOT a label accident in the mapper code.**

Concrete trace of both filers' top-line canonicalization:

- **AEM** (mining_sector): its top line "Revenues from mining operations" is an alias defined **under the DEFAULT canonical name `revenue`** inside the mining_sector profile (sedar_aliases.json `sector_profiles.mining_sector.canonical_fields.revenue`). The OVERRIDE merge in `_iter_target_fields` (sedar_mapper.py:212-235) appends profile aliases to the default field at the same canonical name. Result: AEM's top line lands in `mapped["revenue"]` → economics module finds `revenue` → metrics compute.
- **CNQ** (resource_sector): its top line "Product sales" is an alias defined **under a NEW sector-minted canonical name `total_revenue`** (`sector_profiles.resource_sector.canonical_fields.total_revenue`). No default alias matches any CNQ line (defaults are "total revenue" / "total revenues" / "revenue total" / "revenues"; CNQ's own net line is bare "Revenue", which matches nothing — see §6). Result: CNQ's top line lands in `mapped["total_revenue"]`, `mapped["revenue"]` stays empty → economics module finds nothing → metrics fail with an honest missing-input reason.

No alias-label collision exists between the two names (labels are disjoint), so the FIRST-WIN mechanism never fires here. The two profiles simply chose different canonical homes for the same concept: mining_sector followed the augment-the-default pattern; resource_sector minted a new name.

The same divergence exists a second time in the same two profiles: the label **"Production"** maps to `production_costs` in mining_sector but to `operating_expense` in resource_sector — same label, different canonical names. Today this is latent (only Tier 2 AISC would consume production_costs), but it is the same defect class.

Full top-line naming census across profiles:

| Profile | Top-line canonical name | Pattern |
|---|---|---|
| (default) | `revenue` | — |
| mining_sector | `revenue` (augments default) | ✅ augment-default |
| resource_sector | `total_revenue` (new name) | ❌ sector-minted |
| reit_sector | `rental_revenue` (new name) | deliberate — rental-only concept (NOI rule); arguably a *different* concept |
| insurance_sector | `insurance_revenue` (new name) | deliberate — IFRS 17 insurance revenue is conceptually distinct |
| financial_sector | `total_revenue_bank` (new name, dead) | ❌ sector-minted AND suppressed (see §5) |
| mining_exploration_sector | none | by design (pre-revenue) |

## 2. Economics-module input contract (enumerated)

`modules/economics/resource_economics.py` is the only module in `modules/economics/`. Its filing-side inputs, read via `_extract_field` from `mapping.mapped` (the app panel passes only `{mapping, sector_inferred, currency, scale, fiscal_year_end}` — promoted top-level keys are NOT in the panel's path):

| Input key (raw_values, :355-361) | Consumed by |
|---|---|
| `net_income` | earnings_yield (÷ market_cap), net_margin (numerator) |
| `revenue` | revenue_to_market_cap (÷ market_cap), net_margin (denominator) |
| `production_costs` | **no Tier 1 metric** — collected for the Tier 2 AISC slot; appears in missing_inputs |
| `mine_development_amortization` | **no Tier 1 metric** — same as above |

Market-side inputs: market_cap + listing currency (yfinance), commodity spot (proxy). Metadata: sector_inferred (commodity inference), currency (filing side of the currency guard), scale, fiscal_year_end.

## 3. Full matrix — filer × metric (from stored fixtures' mapping.mapped)

Panel = whether the Economics tab renders (`sector_profile in {mining_sector, resource_sector}`, app.py gate). Metric status assumes market-side inputs available and currency guard passing; FAIL(key) = filing-side key absent from mapped[].

| Filer | Profile | Panel renders | Top-line name in mapped[] | earnings_yield | revenue_to_market_cap | net_margin |
|---|---|---|---|---|---|---|
| AEM | mining_sector | **YES** | `revenue` | OK | OK | OK |
| TECK.B | mining_sector | **YES** | — none — | **FAIL (net_income)** | **FAIL (revenue)** | **FAIL (both)** |
| CNQ | resource_sector | **YES** | `total_revenue` | OK | **FAIL (revenue)** | **FAIL (revenue)** |
| NFG | mining_exploration_sector | no (gated) | none (pre-revenue, by design) | FAIL (net_income¹) | FAIL (revenue¹) | FAIL (both¹) |
| RY | financial_sector | no | `revenue` (default alias won) | OK | OK | OK |
| REI.UN | reit_sector | no | `rental_revenue` AND `revenue`² | OK | OK | OK |
| CAR.UN | reit_sector | no | `rental_revenue` only | OK | FAIL (revenue) | FAIL (revenue) |
| DIR.UN | reit_sector | no | `rental_revenue` only | OK | FAIL (revenue) | FAIL (revenue) |
| IFC | insurance_sector | no | `insurance_revenue` only | OK | FAIL (revenue) | FAIL (revenue) |
| SLF | insurance_sector | no | `insurance_revenue` only | OK | FAIL (revenue) | FAIL (revenue) |
| CSU | (none) | no | `revenue` | OK | OK | OK |
| CNR | (none) | no | `revenue` | OK | OK | OK |
| ATD | (none) | no | `revenue` | OK | OK | OK |
| SHOP | (none) | no | `revenue` | OK | OK | OK |

¹ NFG maps `net_loss`, not `net_income` — the explorer profile deliberately uses loss-shaped names; its panel is gated off, so no user-visible gap.
² REI.UN carries BOTH names because RioCan's statement has a literal "Total revenue" line (1,436,571 — the blended total) that the default alias catches, alongside profile `rental_revenue` (1,176,428). Note these are different values for different concepts — a consumer naively reading `revenue` for a REIT gets the blended total including inventory sales.

**User-visible today (panel renders): TECK.B and CNQ.** TECK.B is the worse case — all three metric cards show missing-input reasons on a rendering panel. CNQ shows two of three.

## 4. TECK.B — new finding, different root cause (alias-coverage gap, not naming)

TECK.B maps only `gross_profit` + `total_assets` (known in handoff as "profile-extension review pending"). Its unmapped[] shows why:

- Top line: **"Revenue (Note 6)"** → normalizes to bare `revenue` — no default alias covers the bare label "revenue" (defaults require "total revenue(s)"/"revenues"), and mining_sector's alias is the AEM-specific "revenues from mining operations".
- Bottom line: **"Profit for the year"** (1,072) — no net_income alias covers "profit for the year" (defaults cover "net income…"/"net earnings" variants only).

So TECK.B's failures are **coverage** (labels match nothing), while CNQ's are **naming** (label matches, but into a divergent canonical name). Both surface identically to the user as missing metrics. Any fix plan must treat them separately.

## 5. Adjacent queued item — financial_sector `total_revenue_bank`: same class, different mechanism, opposite outcome

Confirmed related but DISTINCT. RY's "Total revenue" label collides with the default `revenue` alias; `_build_match_indexes` first-write-wins (defaults iterate first, sedar_mapper.py:253-265) gives the label to default `revenue`, so `total_revenue_bank` never maps (verified: RY carries `revenue`; test_sedar_mapper.py:183 asserts total_revenue_bank absent). Outcome: the DEFAULT name wins → economics module works for RY → the sector name is dead code (cleanup item stands).

CNQ is the mirror image: NO collision (disjoint labels), so first-write-wins never engages and the sector-minted name captures the concept → default slot empty → module fails. **Same design freedom is the root of both** (sector profiles may mint arbitrary canonical names for concepts the defaults already name); the collision case is self-defusing, the disjoint-label case is not.

## 6. Semantic nuance — a rename is NOT mechanical for CNQ

CNQ's statement contains BOTH a gross "Product sales" (41,509 → currently `total_revenue`) and a net "Revenue" (35,656, after royalties — currently unmapped). The 2026-06-17 ground-truth decision deliberately chose GROSS Product sales as the canonical top line. Two consequences for any fix:

1. Renaming resource_sector `total_revenue` → `revenue` puts the GROSS value under `revenue` while CNQ's own statement has a "Revenue"-labeled line with a DIFFERENT (net) value. Defensible (it matches the ground-truth decision) but must be documented — a skeptic reconciling against the filing will hit it.
2. Adding a bare-"revenue" DEFAULT alias (the natural fix for TECK.B's top line) would map CNQ's NET Revenue line into default `revenue`, colliding conceptually with the renamed gross value. **The TECK.B coverage fix and the CNQ naming fix interact and must be decided together**, likely with resource_sector-scoped handling rather than a blanket default alias.

## 7. Evidence the divergence is already leaking: consumer-side patches exist

`modules/analysis/munger_inversion.py:191-193` already reads revenue as `("revenue", "total_revenue")` — a per-consumer fallback chain patched around this exact mapper divergence. This is the scattered-patch failure mode the Normalize-at-the-Boundary principle predicts: every new consumer (economics module was the next one) re-discovers the mismatch. The Gemini cross-check spike prompts (scripts/spike_gemini_crosscheck.py:35-54) also enumerate the divergent names — the #7 comparison contract currently bakes them in.

## 8. Fix direction (proposal only — no changes made)

**Recommended: mapper-side canonical-name unification for same-concept fields, module unchanged; TECK.B coverage handled as a separate, deliberate alias pass.**

- **resource_sector `total_revenue` → fills default `revenue`** (move the "product sales" alias under a `revenue` entry in the resource_sector profile, exactly the mining_sector pattern). Document that for royalty-deducting filers, canonical revenue = gross product sales per ground truth (§6).
- **`rental_revenue` and `insurance_revenue` stay as-is** — they are deliberately different concepts (rental-only per the NOI rule; IFRS 17 insurance revenue), their panels don't render economics, and REI.UN shows the default alias already captures a blended "Total revenue" where one exists. Unifying them would DESTROY meaning, not restore it.
- **`total_revenue_bank`**: delete when next touching financial_sector (existing cleanup item; dead by first-write-wins).
- **"Production" divergence** (`production_costs` vs `operating_expense`): decide at the same time — Tier 2 AISC will consume `production_costs`, so CNQ's production line should probably unify there; same evidence-based review as the revenue rename.
- **TECK.B**: separate alias-coverage pass ("profit for the year" for net_income; the top line needs the §6 joint decision). Not a rename — new aliases, evidence-based per the profile-extension review already queued.
- **Module-side fallback chains (Option B) are NOT recommended** as the primary fix: munger_inversion's existing `("revenue", "total_revenue")` chain shows where that road leads — per-consumer variance handling, the documented anti-pattern. After mapper unification, that chain becomes removable (flag it in the fix task).
- **#7 sequencing note:** do the rename BEFORE productionizing the Gemini cross-check — its comparison contract compares "post-mapper canonical values" and needs canonical names to actually be canonical, or it inherits a migration later.

**Blast radius of the recommended direction (what the fix task must touch):**

| Surface | Impact |
|---|---|
| sedar_aliases.json | resource_sector: total_revenue → revenue (alias move); later TECK.B aliases |
| CNQ fixture | mapped key renames (`total_revenue`→`revenue`); mapped_count UNCHANGED (5 + total_assets) |
| filing_registry.json | regen required (stored mapping changes even though counts don't) — per the fixture/registry rule, full suite including test_filing_registry |
| test_sedar_mapper.py | CNQ assertions name `total_revenue` (:592-615) — update |
| test_sedar_value_snapshot / test_sedar_production_path | will FAIL until the fixture is re-stored — this is the machine-enforced catch working as designed |
| tests/test_sedar_scaling_whitelist.py + claude_analyzer whitelist | `total_revenue` leaves the canonical set (claude_analyzer.py:129) — classification test forces the whitelist update; `revenue` handling already exists |
| app.py top-level promotion | promoted key name changes for CNQ; grep for top-level `total_revenue` consumers at fix time (munger_inversion is one — its fallback becomes removable) |
| Cached analyses | old caches keep `total_revenue` → metrics stay honestly absent (not wrong) until re-analyse. Schema bump = judgment call: absence is honest, so a forced corpus-wide paid re-analyse may be disproportionate (same reasoning as ed38b38's no-bump). Riley decides. |
| Economics module | zero changes |

**What the guards catch:** test_sedar_value_snapshot (stored mapped == live mapper, all 14), test_sedar_production_path (production attach_mapping reproduces stored), registry sync tests, and the scaling-whitelist classification test all fail loudly on an incomplete fix — the rename cannot ship half-done silently.

---

*Method: read sedar_aliases.json + sedar_mapper.py in full; matrix built by script over all stored fixtures' mapping.mapped (tests/fixtures/*_sedar.json; NVDA_FY2026.json excluded — non-campaign EDGAR fixture with no SEDAR mapping); TECK.B/CNQ unmapped labels inspected directly; consumer grep for total_revenue/rental_revenue/insurance_revenue across *.py. No live app interaction and no behavior changes in this session.*
