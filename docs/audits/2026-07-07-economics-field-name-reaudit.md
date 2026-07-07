# Economics-Module Field-Name Contract — Re-Audit (2026-07-07)

**Purpose.** The open-queue item "Economics-module field-name contract audit"
(surfaced by the CNQ live check, 2026-07-02) asked: audit every input key
`resource_economics` expects against the mapper's actual canonical field names,
and list which filers silently fail which derived metric. The original audit
(`docs/audits/2026-07-02-economics-contract-audit.md`) predates the Task A
rename (`resource_sector total_revenue → default revenue`, 1b8d584). This
re-audit re-runs the full contract against the current mapper and states
which gaps survive.

**Method.** Read both sides of the contract directly:
- Consumer side: `modules/economics/resource_economics.py` — every field read
  via `_extract_field` (mapper-canonical) and `_extract_text` (extraction
  metadata).
- Producer side: `modules/integrity/sedar_aliases.json` — canonical field
  names per sector profile.
- Empirical: dumped `mapping.mapped` keys from every `*_sedar.json` fixture and
  cross-checked against the consumer's expected names (matrix below).
- Panel gate: `app.py:8368` — the economics panel renders **only** for
  `resource_sector` and `mining_sector`. `mining_exploration_sector` is gated
  off (explorer economics deliberately suppressed).

## The contract

`resource_economics` reads these **mapper-canonical** fields (`_extract_field`):

| Field | Used by | In `missing_inputs`? |
|---|---|---|
| `revenue` | `revenue_to_market_cap`, `net_margin` (displayed) | yes |
| `net_income` | `earnings_yield`, `net_margin` (displayed) | yes |
| `production_costs` | cost-structure waterfall only | **yes** |
| `mine_development_amortization` | cost-structure waterfall only | **yes** |
| `exploration_expense` | cost-structure waterfall only | no |
| `royalties` | cost-structure waterfall only | no |
| `operating_expense` | cost-structure waterfall only | no |
| `depletion_depreciation_amortization` | cost-structure waterfall only | no |

It also reads `scale`, `sector_inferred`, `currency`, `fiscal_year_end` via
`_extract_text` — these come from **extraction metadata, not the mapper**, so
they are a separate contract and are out of scope for the name audit (all
populated correctly; the currency guard and scale factor both function live).

The three **displayed** Tier-1 ratios and their inputs:
- `earnings_yield` = net_income / market_cap
- `revenue_to_market_cap` = revenue / market_cap
- `net_margin` = net_income / revenue

So the only load-bearing mapper-name inputs to a displayed number are
**`revenue`** and **`net_income`** (plus `market_cap`, which is yfinance, not
the mapper).

## Empirical coverage matrix (fixtures, `mapping.mapped` keys)

Panel-showing sectors only (`YES` = field present in `mapping.mapped`):

| Filer | Sector | revenue | net_income | production_costs | mine_dev_amort | exploration_exp | royalties | operating_exp | DD&A |
|---|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| CNQ | resource_sector | YES | YES | — | — | — | YES | YES | YES |
| AEM | mining_sector | YES | YES | YES | YES | YES | — | — | — |
| TECK.B | mining_sector | YES | YES | — | — | — | — | — | — |

Explorer (panel gated off, shown for completeness): NFG maps only
`exploration_expense`; SIG maps none of these (both route to
`mining_exploration_sector` → no economics panel).

## Findings

### F1 — Tier-1 ratios are contract-CLEAN; the CNQ bug is closed. (headline)
`revenue` and `net_income` map for **every** panel-showing filer. The 2026-07-02
CNQ failure (`net_margin` / `revenue_to_market_cap` showing "missing required
inputs: revenue" because CNQ's top line was canonicalized `total_revenue` while
the module expected `revenue`) is genuinely fixed by Task A. No filer silently
loses a **displayed** economics ratio to a mapper-name mismatch. (Market-cap
ratios can still be suppressed by the FX currency guard on CAD-filing/USD-listed
filers — that is deliberate, documented, and not a name gap.)

### F2 — `production_costs` (mining) vs `operating_expense` (resource): same concept, two names. (benign)
The "Production" cost line canonicalizes to `production_costs` under
`mining_sector` (AEM, K) but to `operating_expense` under `resource_sector`
(CNQ "Production"). **No display impact:** the cost-structure waterfall
(`app.py:8768` `_CS_ITEMS`) lists *both* names and renders whichever is present
(`app.py:8781` `if _cs.get(key)`). Each sector's real cost line renders under its
own row. NOTE these may be genuinely distinct concepts (mining production cost
of sales vs O&G production operating expense) — do **not** unify blindly; a
merge is a SEDAR-semantics decision, not a mechanical rename.

### F3 — `mine_development_amortization` (mining) vs `depletion_depreciation_amortization` (resource): same concept, two names. (benign)
Same shape as F2 for the D&A line. Waterfall handles both ("Mine D&A" vs "DD&A"
rows). No display impact.

### F4 — `missing_inputs` provenance line falsely flags the mining-named fields on O&G filers. (minor, user-visible)
`production_costs` and `mine_development_amortization` sit in `raw_values`
(`resource_economics.py:486`), so they enter `missing_inputs` whenever absent.
For every `resource_sector` (O&G) filer they are **permanently** absent-by-name
(CNQ maps the same concepts as `operating_expense` + `depletion_depreciation_amortization`).
`missing_inputs` is rendered to the user in the "Data provenance & coverage"
expander (`app.py:8881-8883`, "**Missing inputs:** …"). So a skeptic opening
CNQ's coverage footer sees `production_costs, mine_development_amortization`
listed as missing — when those exact concepts were mapped and rendered in the
waterfall. Misleading, but: (a) it is in a collapsed expander, and (b) **no
displayed ratio's reason string references these fields** (`_reason()` calls at
`resource_economics.py:565-572` only cite net_income / revenue / market_cap /
commodity), so no ratio card shows a wrong "missing input" reason.

**Self-inconsistency note:** the module's own comment
(`resource_economics.py:505-507`) states the extra cost fields are "Kept
separate from `raw_values` so `missing_inputs` semantics stay scoped to the
Tier 1 ratio inputs." But `production_costs` and `mine_development_amortization`
are cost-structure-only inputs (no displayed Tier-1 ratio consumes them) and are
in `raw_values` anyway — they violate the module's documented scoping intent.
They are the two fields F4 is about.

## Recommendation

**Option B (minimal, recommended):** remove `production_costs` and
`mine_development_amortization` from `raw_values` / `missing_inputs`; read them
only for the cost-structure waterfall (as the other four cost fields already
are). This (a) kills the false "Missing inputs" noise on every O&G filer, (b)
aligns the code with its own documented intent (comment at :505-507), and (c)
touches nothing in the mapper — zero fixture drift, zero risk to a displayed
number. Cost-structure rendering is unchanged (it reads `cost_structure`, not
`raw_values`). ~5-line change in `resource_economics.py` + a pinning test that
CNQ's `missing_inputs` no longer contains the two mining-named fields.

**Option A (accept):** treat F4 as cosmetic and leave it. Defensible — it is a
collapsed-expander label, and F1 confirms no displayed number is wrong.

**Not recommended: unifying the F2/F3 names.** production_costs vs
operating_expense (and the two D&A names) may be genuinely distinct sector
concepts; a merge needs a semantics ruling (casebook-class), not a rename, and
buys nothing today because the waterfall already renders both correctly.

## Bottom line
The metric this audit item was opened for — CNQ's silently-absent `net_margin` /
`revenue_to_market_cap` — is **closed**. No panel-showing filer silently fails a
displayed economics ratio on a mapper-name mismatch. The only surviving artifact
is the F4 provenance-footer noise, fixable in ~5 lines (Option B) or acceptable
as-is (Option A). Riley's call.
