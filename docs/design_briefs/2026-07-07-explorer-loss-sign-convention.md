# Design Brief — Explorer / loss-form net-income sign convention (2026-07-07)

<!-- Second brief for the three-agent pipeline (Fable designs, Sterling
implements, CC reviews/commits, Riley ratifies). Run with:
.\venv\Scripts\python.exe scripts\ask_fable.py docs\design_briefs\2026-07-07-explorer-loss-sign-convention.md
The response lands UNRATIFIED in docs/design_sessions/; ratified rulings get
casebook entry CB-020. Faithful-transcription rule applies — evidence quoted
here matches the repo/cache verbatim; where a value is inferred or not yet
confirmed by a fresh extraction, it says so. -->

## The question

FinLens can display a **profit where the filer reported a loss**, because the
net-income sign convention is inconsistent across two ways filers present a
loss. Some filers print the bottom line parenthetically negative — Allied
"Net loss and comprehensive loss" `$(1,327,532)` — and the "as-presented"
rule (CB-017) stores the correct negative. Others print the loss as a
**positive magnitude under a "Net loss" label** — NGEx (a pre-revenue mining
explorer) prints `Net loss = 123,335,862` positive — and the same
"as-presented" rule stores `+123,335,862`, i.e. a $123.3M *profit*. What is
the canonical sign convention for net income, how does the mapper (and the
legacy summary-card scrape) derive the correct sign from a loss-form label,
and what must the Net Income card display for a loss? This is the CB-020
candidate flagged when CB-019 shipped, and it is the prerequisite that makes
CB-019's explorer suppression actually fire on real NGEx data (today it is
pinned only by a synthetic T1 fixture — see Evidence).

## Evidence pack

### The confirmed defect (NGEx FY2025 cached analysis, read live from `~/.finlens/analysis`)

File `NGEX_Year_ended_December_31__2025_claude-sonnet-4-6.json`
(schema_version 6, written 2026-07-02, currency CAD, sector_profile
`mining_exploration_sector`). Verbatim from the cache:

- Top-level `financial_data.net_income` is **empty/None**.
- `financial_data.mapping.mapped` keys = `cash, total_assets, interest_expense`
  — **no canonical net field is mapped** (this cache predates CB-017, which
  added the `net_income`/`net_loss` aliases).
- Income-statement rows (value | line_item):
  - `123335862 | Net loss`  ← **positive magnitude, loss label**
  - `-5898385 | Interest income`  ← **negative** (income item shown as a
    deduction toward the loss total)

The two signs together indicate NGEx presents its income statement in
**loss-buildup orientation**: income items carry a negative sign (they reduce
the loss) and the `Net loss` total is a positive magnitude — the mirror image
of the standard profit-oriented convention. Scope of that inversion beyond
these two lines is NOT yet confirmed (the full statement was not
re-transcribed for this brief — see Open questions / the required fresh
extraction).

### How the wrong number is produced (`modules/excel_exporter.py`)

`_calc_summary_metrics` derives `ni_c` (the Net Income card + margin value),
lines 632–634:

```python
ni_c = financial_data.get("net_income")
if not isinstance(ni_c, (int, float)) or isinstance(ni_c, bool):
    ni_c = _lookup2(is_rows, _NI_LABELS, "value", exclude=_NI_EXCLUDE)
```

`_NI_LABELS` (lines 483–484) includes `"net loss"`:

```python
_NI_LABELS  = ["net income", "net earnings", "net loss", "net income (loss)",
               "net earnings (loss)", "profit for the period", "profit for the year", "net profit"]
```

`_lookup2` / `_lookup` (lines 210–255) return the row's raw `value` with **no
sign transformation** — first substring match wins. So on the NGEx cache:
`financial_data.get("net_income")` is None → the scrape matches the
`"Net loss"` row → **`ni_c = +123,335,862`**. The Net Income card
(`app.py:7887`, `st.metric("Net Income", _fmt_num(ni_c), _fmt_pct(ni_m))`)
therefore renders **+123.3M** and a positive net margin for a company that
lost $123.3M.

### Why the red-flag layer stays silent (`modules/red_flag_detector.py:154–159`)

```python
ni_c = m.get("ni_c")
if ni_c is not None and ni_c < 0:
    _yellow("net_income", "Negative net income",
            f"Net income is {ni_c:,.0f}.", ni_c, "< 0")
```

Because `ni_c` is **positive**, the negative-net-income check never fires.
This is precisely why the June cold run flagged only FCF, and why CB-019's
explorer suppression has nothing to suppress on the real NGEx data — the
suppression is currently evidenced only by the synthetic T1 fixture, not by
NGEx itself (CB-019 real-data note, casebook line ~852–857).

### Prior rulings that constrain the answer

- **CB-017 (net_income / net_loss aliases + as-presented sign):** DEFAULT
  `net_income` gained alias `"net loss and comprehensive loss"` stored
  **"as-presented negative"** — which was correct for AP.UN because AP.UN
  prints the loss parenthetically `$(1,327,532)`. The explorer profile's
  same-label `net_loss` alias carries `prefer_profile: true` (explorers keep
  their net_loss spine). CB-017's as-presented rule is the exact rule that
  mis-signs NGEx: a `"Net loss"` line whose value is a positive magnitude
  stores positive. **Likely consequence (to confirm by fresh extraction):
  under the current mapper NGEx's net_income maps to +123.3M — the bug is
  live in the canonical path, not only the stale scrape.**
- **CB-011 (net_income = consolidated incl. NCI):** the canonical net_income
  on a profit-year filer is stored **positive** (TECK.B "profit for the year"
  = 1,072). So the implied convention is *signed*: profit positive, loss
  negative. A loss stored positive breaks this convention silently.
- **CB-018 (canonical-first summary layer):** `ni_c` reads the promoted
  canonical field first, scrape as the guarded fallback for non-mapped paths.
  So fixing the sign at the mapper boundary fixes the canonical path; the
  scrape fallback still needs its own sign guard for old caches / EDGAR /
  any non-mapped filer.
- **CB-019 (explorer suppression):** suppresses operating_income, net_income,
  and free_cash_flow negatives for `mining_exploration_sector`. It assumes
  `ni_c` is correctly negative to begin with — CB-020 is upstream of it.
- **CLAUDE.md sign precedents:** `royalties` is stored **negative**
  (as-presented deduction); display consumers negate for a positive cost.
  The house pattern is "normalize at the boundary, not in consumers" — a sign
  rule belongs at the mapper, with the scrape guard as the fallback for paths
  the mapper doesn't reach.

### Counter-evidence (do not over-correct into a new wrong sign)

- AP.UN's parenthetical `$(1,327,532)` already stores correctly negative —
  any new rule must **not** double-negate the already-negative
  parenthetical/loss-label form into a positive.
- Profit-year filers (TECK.B +1,072, and every profit filer in the corpus)
  must stay positive — a blanket "loss label ⇒ negate" must key on the label
  being a loss label AND the presented value being positive, not on the label
  alone.

## Constraints

- **Integrity-first / zero silent wrong numbers:** a displayed profit on a
  loss-year filer is exactly the confident-wrong-number the cold-load gate
  forbids. The fix must be deterministic, not a model call.
- **Normalize at the boundary:** prefer a mapper-side canonical sign rule
  (the value promoted to `financial_data["net_income"]` carries the correct
  sign), with a summary-scrape sign guard as the fallback for non-mapped
  paths (old caches, EDGAR). Consumers (cards, red flags, margins) must not
  each re-derive sign.
- **Must not regress the parenthetical form:** AP.UN and every already-correct
  negative loss must stay negative; every profit must stay positive.
- **Schema versioning:** existing schema_version-6 caches store
  `net_income=None` and a positive `"Net loss"` row. Per the CLAUDE.md
  schema-versioning principle, decide whether a scrape-side sign fix silently
  "heals" old caches (changes a displayed number under the same schema — the
  exact silent-mismatch trap the principle warns about) or whether a schema
  bump + Re-Analyse prompt is required.
- **Implementer boundary (Sterling, sandbox, offline):** no live API calls,
  no `~/.finlens` access, no integrity-log writes, no fresh extraction. His
  deliverable is the mapper/scrape sign logic + pytest coverage against
  transcribed fixtures. The fresh NGEx re-extraction, live evidence, app.py
  card wiring, and any moat-log surface are CC's.
- **Not up for relitigation:** CB-011 (net_income = consolidated incl. NCI),
  CB-017's alias set and prefer_profile mechanism (the *sign* is in scope;
  the alias membership is not), CB-018 canonical-first ordering, CB-019's
  suppression rules.

## Requested output

Rulings + rationale, spec for the implementer, acceptance tests, and open
questions — per the standard `ask_fable.py` format. Topic-specific asks:

1. **State the canonical sign convention for `net_income`** in one sentence
   (profit positive / loss negative, consolidated incl. NCI per CB-011), and
   make it explicit enough to add to CLAUDE.md's field definitions.
2. **Give the deterministic rule that assigns the correct sign** to a
   loss-form bottom line, distinguishing (a) parenthetical/already-negative
   loss (AP.UN — keep negative, do not double-negate) from (b) positive
   magnitude under a "Net loss"/"loss" label (NGEx — store negative). Say
   where it lives — mapper boundary, scrape fallback, or both — and how it
   avoids negating a genuine profit.
3. **Rule on the summary-scrape fallback** (`_lookup2` on `_NI_LABELS`): should
   a match on a loss-form label with a positive value be negated in the
   scrape, or should the scrape stop claiming net income for loss-form labels
   and let the card render honest "—" until the canonical field is mapped?
4. **Rule on old-cache handling:** heal-in-place vs. schema bump + Re-Analyse,
   with the reasoning against the silent-mismatch trap.
5. **Scope of the inversion:** NGEx also prints `Interest income = −5,898,385`
   (negative). Rule on whether CB-020 is (a) net-income-only, or (b) must
   detect a statement-wide loss-buildup/inverted presentation and how — or
   whether that is a separate future decision pending a full re-transcription.
   Where the evidence is n=1, say "insufficient evidence — net-income-only,
   revisit on a second inverted filer" rather than inventing a
   statement-wide detector.
6. **Interaction with CB-019:** confirm that once the sign is correct, NGEx's
   negative net_income and negative FCF flow into CB-019's explorer
   suppression exactly as the T1 fixture models (false INVESTIGATE → honest
   None), and that nothing in CB-020 needs to change CB-019.
7. **What the Net Income card should display for a loss:** signed `−123.3M`,
   accounting-style `(123.3M)`, or a loss indicator (one-line concept is
   enough; CC designs the rendering).
