# Design Session — Explorer / loss-form net-income sign convention

**Status: RATIFIED** by Riley 2026-07-07 → casebook CB-020 (all rulings as recommended)
**Topic:** loss-form net-income sign convention (NGEx cold-load finding)
**Brief:** `docs/design_briefs/2026-07-07-explorer-loss-sign-convention.md`
**Date:** 2026-07-07

## Provenance — first CC-authored design session (CC-first workflow test)

This is the FIRST design ruling produced by CC (Opus 4.8) directly, rather
than by Fable via `ask_fable.py`. Per Riley's 2026-07-07 workflow decision:
CC takes the first crack at well-evidenced, deterministic, prior-ruling-
constrained design decisions; Fable stays in reserve for high-powered /
genuinely ambiguous calls. Riley remains the ratifier — the load-bearing
human check is unchanged. Where evidence is thin, this ruling says so as an
open question rather than inventing doctrine (the same discipline Fable's
seat enforced on CB-019).

**Independence caveat (stated honestly):** CC wrote both the brief and this
ruling, so it lacks the adversarial separation Fable's cold read provides.
The mitigation is Riley's ratification plus the codebase-grounded evidence
below. If any ruling reads as rationalization rather than reasoning, kick it
to Fable.

## What the codebase investigation changed vs. the brief

Reading the actual aliases, mapper, and tests (not just the cached analysis)
surfaced two facts the brief did not have, one of which corrects the brief:

1. **CORRECTION to the brief's "likely live in the mapper" claim.** The brief
   hedged that CB-017's as-presented rule "would store +123.3M — the bug is
   likely live in the canonical path." It is NOT. Bare `"Net loss"` (NGEx's
   label) matches **no** mapper alias: default `net_income` aliases are
   `net income`, `net income (loss)`, `net earnings`, `net loss and
   comprehensive loss`, `profit for the year`
   (`sedar_aliases.json:71–108`); explorer `net_loss` aliases are `loss and
   comprehensive loss for the year` and `net loss and comprehensive loss`
   (`sedar_aliases.json:454–468`). So a fresh NGEx extraction leaves BOTH
   `net_income` and `net_loss` unmapped. **The bug lives entirely in the
   summary-card scrape, not the mapper.**

2. **SIG/NFG display correctly only by coincidence.** Explorers map their
   bottom line to a SEPARATE canonical field `net_loss` (not `net_income`),
   and existing tests pin those values NEGATIVE — `net_loss == -50,268,354`
   (NFG, `test_sedar_mapper.py:905–906`), `-3,417,435` (SIG,
   `:1110`/`:1699`). But `_calc_summary_metrics` reads
   `financial_data["net_income"]`, which is None for explorers, so the card
   is fed by the SCRAPE, not the canonical `net_loss`. SIG/NFG happen to
   render the right sign because they present the loss PARENTHETICALLY (their
   row value is already negative), so the scrape's raw-value return is
   negative. NGEx presents a POSITIVE magnitude under a `"Net loss"` label,
   so the identical scrape returns the wrong sign. The differentiator is
   purely the filer's presentation format — which is exactly what a
   sign-normalization rule must neutralize.

## Rulings

### R1 — Canonical sign convention (make it explicit; add to CLAUDE.md)

`net_income` is a **signed** field: **profit positive, loss negative**,
consolidated including NCI (consistent with CB-011's `net_income` = TECK.B
"profit for the year" +1,072). The explorer-profile `net_loss` field holds
the **same concept under a loss-year name** and is **stored negative** — the
field name describes the expected year, not a positive magnitude (same
discipline as `royalties`, stored negative as an as-presented deduction).
A loss displayed as a positive number is a confident-wrong-number and fails
the cold-load gate.

### R2 — The deterministic sign rule (loss-declaring-label test)

Wherever a bottom-line value is assigned from a statement label, apply:

> **LOSS-DECLARING label** = the normalized label contains `"loss"` AND
> contains **none** of `"income"`, `"profit"`, `"earnings"`.
> - Loss-declaring → store **−abs(value)**.
> - Otherwise → store the value **as-presented** (unchanged).

Worked against every evidence point:

| Label | Raw value | Rule | Result | Correct? |
|---|---|---|---|---|
| `Net loss` (NGEx) | +123,335,862 | loss-declaring → −abs | **−123,335,862** | ✓ |
| `Net loss and comprehensive loss` (AP.UN) | −1,327,532 | loss-declaring → −abs | −1,327,532 | ✓ no double-negate |
| `loss and comprehensive loss for the year` (NFG) | −50,268,354 | loss-declaring → −abs | −50,268,354 | ✓ unchanged |
| `net loss and comprehensive loss` (SIG) | −3,417,435 | loss-declaring → −abs | −3,417,435 | ✓ unchanged |
| `profit for the year` (TECK.B) | +1,072 | not loss-declaring | +1,072 | ✓ |
| `net income` (RY) | +20,369 | not loss-declaring | +20,369 | ✓ |
| `Net income (loss)` — profit year | +5,000 | has "income" → as-presented | +5,000 | ✓ |
| `Net income (loss)` — loss year | −3,000 | has "income" → as-presented | −3,000 | ✓ filer signed it |

The `"income"/"profit"/"earnings"` exclusion is what prevents the template
label `"Net income (loss)"` (used by filers in BOTH profit and loss years,
where the value's own sign is authoritative) from being wrongly flipped. The
`−abs` form (not a plain negate) is what prevents double-negating a filer
that already presents the loss parenthetically.

### R3 — Where the rule lives (two sites; the scrape is load-bearing)

1. **Summary-scrape fallback (`_calc_summary_metrics`, load-bearing today):**
   the fallback that matches `_NI_LABELS` must apply R2 to the matched label.
   This is the fix that actually heals NGEx (whose bottom line is unmapped)
   and every future explorer with a bare `"Net loss"` positive-magnitude row.
2. **Mapper boundary (`sedar_mapper`, defense-in-depth):** when assigning the
   `net_income` and `net_loss` canonical fields, apply R2 so any mapped
   bottom line is correctly signed. This has **no current firing filer** (all
   corpus loss filers present parenthetically, so −abs is a no-op for them) —
   it is a guard that future-proofs the canonical path against a
   positive-magnitude long-form loss, and it makes the convention
   machine-enforced at the boundary (house "normalize at the boundary"
   principle). Honest framing: this site is a guard, not a live corpus fix.

### R4 — Summary layer reads `net_loss` as a canonical fallback (CB-018 extension)

`ni_c` resolution order becomes: `financial_data["net_income"]` →
`financial_data["net_loss"]` (the explorer canonical field) → scrape. This
extends CB-018 canonical-first to the explorer bottom line, so SIG/NFG use
their canonical `net_loss` (−3.4M / −50.2M) instead of a scrape coincidence.
No display change for them (same value); it just makes the path principled.
NGEx still falls through to the scrape (its `net_loss` is unmapped), where R3
site 1 corrects the sign.

### R5 — The scrape negates; it does NOT render "—"

Answer to brief ask #3: a loss-form scrape match is **negated** (R2), not
dropped to honest "—". Rationale: the net loss IS knowable — it is printed on
the statement. Honest absence is reserved for genuinely-unknowable values
(REIT capex definitional ambiguity, a missing line). Rendering "—" on a loss
that is right there on the page would be an honesty regression in the wrong
direction, and it would leave CB-019's explorer suppression with nothing to
suppress on real data.

### R6 — Old-cache handling: NO schema bump; heals in-place on next render

`ni_c` is **computed at render time** from the cached statement rows; it is
not a stored field. The stored data (NGEx's `"Net loss" = +123,335,862` row)
is **unchanged and correct as-extracted** — only the buggy derivation that
interprets it is corrected (wrong → right). This is the same class as every
prior `_fmt_num` / summary-metric fix that healed on next render (PLD, the
Palantir/Snowflake magnitude fixes). The schema-versioning principle governs
the SHAPE of stored data; the shape is identical here, so no bump is required
and no Re-Analyse prompt is warranted. The silent-mismatch trap the principle
warns about is a STORED value gaining a new meaning under a new render path —
not present here (stored value stable, derivation corrected).

### R7 — Scope: net-income-only; the negative `Interest income` is NOT ruled on

CB-020 covers the **bottom-line sign only**. NGEx also prints
`Interest income = −5,898,385` (negative), which hints at a statement-wide
loss-buildup presentation (income items negative, loss total positive). This
is **insufficient evidence (n=1, two lines observed)** to build a
statement-wide inversion detector, and building one off this would be exactly
the n=1 doctrine the CB-019 session refused. It is also low-risk to leave:
an explorer's other line items either don't map (unmapped, honest) or are
suppressed by CB-019 (operating_income, FCF), so the bottom line is the only
visible wrong-number surface. **Deferred** — revisit on a second inverted
filer or after a full NGEx statement re-transcription (an open question below,
not a ruling).

### R8 — CB-019 interaction: confirmed, no change to CB-019

Once `ni_c` reads −123.3M for `mining_exploration_sector`, CB-019 suppresses
the net_income and free_cash_flow negatives with visible `suppressed[]`
records, and the false INVESTIGATE flips to honest None — exactly as CB-019's
T1 fixture models. CB-020 is strictly upstream: it makes the real NGEx data
produce the negative that the T1 fixture currently supplies synthetically.
Nothing in CB-019's `SECTOR_FLAG_RULES` / `detect_flags` changes.

### R9 — Card display: signed is sufficient (optional accounting-parentheses polish)

`_fmt_num` (`app.py:7864`) already renders a negative value as `-123.3M`
(the sign is preserved through `f"{v / 1_000_000:,.1f}M"`). So once `ni_c` is
correct, the Net Income card is correct with **no card change required**.
Optional polish for the finance persona: accounting-style parentheses
`(123.3M)` for negatives — CC's call at wiring, not part of the ruling.

## Implementer spec (Sterling — sandbox, offline, module + tests only)

Two deterministic changes plus a shared predicate. No live API, no
`~/.finlens`, no integrity-log writes.

**S1 — shared predicate** (put it where both consumers can import it; suggest
`modules/excel_exporter.py` alongside the label constants, or a small shared
helper — CC will confirm the import site at wiring):

```python
def _is_loss_declaring_label(label: str) -> bool:
    """A label that unambiguously declares a loss: contains 'loss' and none
    of the profit words. 'Net income (loss)' is a profit-or-loss TEMPLATE —
    the value's own sign is authoritative — so it is NOT loss-declaring."""
    li = (label or "").lower()
    if "loss" not in li:
        return False
    return not any(w in li for w in ("income", "profit", "earnings"))

def _signed_bottom_line(label: str, value):
    """Apply the canonical net-income sign convention (R1/R2)."""
    if value is None:
        return None
    return -abs(value) if _is_loss_declaring_label(label) else value
```

**S2 — scrape fallback** (`_calc_summary_metrics`, the load-bearing fix): the
net-income fallback must know WHICH label matched so it can sign it. Today
`_lookup2` returns only the value. Add a variant that returns
`(value, matched_label)` (or a dedicated `_lookup_signed_net_income`) and
apply `_signed_bottom_line`. Keep the canonical-first order from R4:

```python
ni_c = financial_data.get("net_income")
if not isinstance(ni_c, (int, float)) or isinstance(ni_c, bool):
    ni_c = financial_data.get("net_loss")          # R4: explorer canonical field
if not isinstance(ni_c, (int, float)) or isinstance(ni_c, bool):
    value, label = _lookup2_with_label(is_rows, _NI_LABELS, "value",
                                       exclude=_NI_EXCLUDE)
    ni_c = _signed_bottom_line(label, value)       # R2/R3-site-1
```

(The canonical `net_loss` from R4 is already signed by the mapper, so it is
NOT re-passed through `_signed_bottom_line`; only the raw scrape is.)

**S3 — mapper boundary** (`sedar_mapper`, defense-in-depth): when assigning
the `net_income` and `net_loss` canonical fields, pass the value through
`_signed_bottom_line(source_label, value)`. Scope this to those two fields
only — do NOT apply it in the generic `_mapped_item` (would wrongly touch
unrelated fields). No-op for all current corpus filers (regression-safe).

## Acceptance tests (Sterling)

Predicate + scrape + mapper + a CB-019 regression guard.

- **T1** `_is_loss_declaring_label`: True for `"Net loss"`, `"Net loss and
  comprehensive loss"`, `"loss and comprehensive loss for the year"`; False
  for `"net income"`, `"profit for the year"`, `"net income (loss)"`,
  `"net earnings (loss)"`.
- **T2** scrape, NGEx shape: `net_income=None`, `net_loss` absent,
  income row `{"line_item": "Net loss", "value": 123335862}` →
  `ni_c == -123335862`.
- **T3** scrape, parenthetical loss (SIG/AP.UN shape): row
  `{"line_item": "Net loss and comprehensive loss", "value": -3417435}` →
  `ni_c == -3417435` (no double-negate).
- **T4** scrape, profit template: row
  `{"line_item": "Net income (loss)", "value": 5000}` → `ni_c == 5000`.
- **T5** scrape, loss template: row
  `{"line_item": "Net income (loss)", "value": -3000}` → `ni_c == -3000`.
- **T6** R4 canonical `net_loss` fallback: `net_income=None`,
  `financial_data["net_loss"] = -50268354` → `ni_c == -50268354`
  (canonical used, scrape not consulted).
- **T7** canonical-first unchanged: `financial_data["net_income"] = -123335862`
  → `ni_c == -123335862`.
- **T8** profit regression: `net_income=20369` (or scrape `"net income"`
  20369) → `ni_c == 20369`.
- **T9** mapper defense-in-depth: a synthetic filer whose mapped bottom-line
  label is `"net loss and comprehensive loss"` with value **+7,000** →
  `mapped["net_income"]["value"] == -7000` (positive-magnitude long-form loss
  is normalized at the boundary).
- **T10** mapper no-op regression: existing SIG/NFG net_loss pins still hold
  (`-3417435`, `-50268354`) and TECK.B `net_income` +1,072 unchanged — the
  sign rule must not perturb any current fixture (registry regen only if a
  fixture mapped_count changes; it should not).
- **T11** CB-019 still fires where it should (regression): `ni_c=-1327532`
  with `reit_sector` → net_income negative flag FIRES yellow (Allied) — CB-020
  must not over-suppress; and `ni_c=-123335862` with
  `mining_exploration_sector` → net_income flag SUPPRESSED with a
  `suppressed[]` record (CB-019 T1 behavior, now driven by a real sign).

## CC's tasks (live — not Sterling's) — IMPLEMENTED 2026-07-07

Riley chose CC-direct implementation (minimize Sterling's metered cost on a
small deterministic change). Outcome:

1. ~~Fresh NGEx re-extraction as the integrity-log evidence gate~~ **NOT
   NEEDED.** On implementation it became clear the gate is not triggered: the
   load-bearing fix is a render-layer summary/chart derivation (not engine
   input) and the mapper post-pass is a proven no-op on all current data
   (engine behavior unchanged) — same reasoning as CB-019. And the heal needs
   no re-extraction: per R6 the fix is applied at render time from the
   UNCHANGED cached rows, so the existing 7/2 cache renders correctly now.
   VERIFIED live: the real NGEx cache yields ni_c = −123,335,862 through both
   `_calc_summary_metrics` (card) and `two_year_statement_pairs` (charts).
2. **SIBLING-PATH FINDING (Change Propagation Rule).** `two_year_statement_pairs`
   ("Net Income", the dashboard charts) fell to an UNSIGNED scrape and would
   have shown +123.3M while the card showed −123.3M. Fixed in the same pass
   (`_net_income_pair`, mirroring `_calc_summary_metrics`: net_income →
   net_loss → signed scrape, prior column signed by the same row label).
   Pinned by a card/chart-agreement test. This is exactly the class the rule
   exists to catch — CB-017 had already flagged the two paths share matchers.
3. Accounting-parentheses polish (R9): deferred as optional — `_fmt_num`
   already renders the signed `-123.3M`, so the card is correct without it.
4. CLAUDE.md net_income/net_loss sign-convention note (R1) added; casebook
   CB-020 recorded with the actual "Enforced by" implementation.
5. Bare `"net loss"` as an explorer alias + NGEx fixture (OQ2): deferred per
   the ruling (needs a fixture + registry regen; the scrape guard already
   makes the display correct).

## Open questions / thin evidence (honest)

- **OQ1 — statement-wide inversion (R7).** The negative `Interest income` is
  the only evidence beyond the bottom line. Is NGEx's entire income statement
  loss-oriented (all income items negative), or is that one line an
  extraction artifact / a genuine contra-presentation? Needs a full NGEx
  statement re-transcription. Ruling deliberately scoped to net-income-only
  until then.
- **OQ2 — should bare `"net loss"` become a canonical explorer alias?** Doing
  so would map NGEx's bottom line canonically (visible to the moat log /
  cross-check / receipts, instead of invisible as today) and let R4's
  canonical path — not the scrape — feed the card. DEFERRED from v1 because
  it changes a fixture mapped_count (needs an NGEx fixture + registry regen
  per the CLAUDE.md rule) and the scrape guard already makes the DISPLAY
  correct. Recommended as the immediate CB-020 follow-up, not part of the
  shippable v1.
- **OQ3 — confidence in the profit-word exclusion set.** `{income, profit,
  earnings}` covers every corpus label. A filer using an unusual profit word
  (e.g. "surplus", "gain for the year") would fall through to loss-declaring
  = False only if it lacks "loss" — which it would. Low risk, but flagged:
  the exclusion set is evidence-bounded, extend on a counterexample.

## Deferred follow-ups (not this task)

1. Promote bare `"net loss"` to a canonical explorer alias + NGEx fixture
   (OQ2).
2. Statement-wide inversion detection (OQ1 / R7) — pending a second inverted
   filer.
3. The standing Phase-2 legacy-scrape retirement (tracked separately) would
   eventually remove R3 site 1 in favor of pure canonical-first; until then
   the scrape guard is load-bearing.
