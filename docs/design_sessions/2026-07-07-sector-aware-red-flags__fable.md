# Fable design session — 2026-07-07-sector-aware-red-flags.md

- **Date:** 2026-07-07
- **Model:** claude-fable-5
- **Tokens:** 2,828 in / 12,673 out
- **Status:** UNRATIFIED — rulings take effect only after Riley ratifies them (casebook rule)

---

# FinLens Design Session — Sector-Aware Red Flags

## 1. RULINGS

**R1. Yes — make the detector sector-aware, but only where we have direct evidence. In v1 that is exactly one profile: `mining_exploration_sector`.**
WHY: The NGEx finding (#3, 2026-06-17) is direct evidence that sector-blind flags produce false signals on explorers — negative FCF, operating income, and net income are the expected shape of a pre-revenue explorer, and flagging them erodes credibility with knowledgeable readers. Meanwhile the counter-evidence (Allied's honest net-income yellow; TD's correct CLEAN) proves the default flags are doing real work everywhere else. Every other profile is n=1 or n=0 on the specific question of *wrong reads*, so per the brief's own instruction they get "insufficient evidence — default behavior," not invented rules.

**R2. Per-profile × per-check ruling table (v1):**

| Check | `mining_exploration_sector` | `mining_sector` / `resource_sector` | `reit_sector` | `financial_sector` / `insurance_sector` | None / EDGAR |
|---|---|---|---|---|---|
| YoY revenue growth | fire (default) | fire | fire | fire | fire |
| Gross margin | fire (default) | fire | fire | fire | fire |
| Operating income < 0 | **SUPPRESS** | fire | fire | fire | fire |
| Net income < 0 | **SUPPRESS** | fire | fire | fire | fire |
| Free cash flow < 0 | **SUPPRESS** | fire | fire | fire | fire |
| Current ratio | fire | fire | fire *(open Q1)* | fire *(open Q2)* | fire |
| Net debt / EBITDA | fire | fire | fire | fire *(open Q2)* | fire |
| Interest coverage | fire | fire | fire | fire *(open Q2)* | fire |

WHY, per cell that deviates or is contentious:
- **Explorer op income / net income / FCF → suppress.** The finding names FCF directly, and the brief's evidence pack states all three are "the expected shape of the business" for a pre-revenue explorer. Suppressing all three is one coherent ruling, not three separate inferences.
- **Explorer revenue growth & gross margin → default.** A pre-revenue explorer has `None` revenue, so these skip honestly already — no rule needed. If an explorer *has* revenue and it's collapsing, that's informative; insufficient evidence to suppress.
- **Explorer current ratio → keep firing.** Cash runway is the *primary* distress axis for a pre-revenue company. Suppressing liquidity flags for explorers would be over-suppression of exactly the signal that matters most.
- **Explorer ND/EBITDA & interest coverage → keep firing (n=0, default).** A debt-carrying explorer with no earnings to service interest is a genuine risk. Note: negative EBITDA/EBIT interacts oddly with these ratios; no evidence in the pack of it firing on an explorer, so no rule — see Open Q3.
- **REIT current ratio → default, escalated to Riley.** Allied at 0.53x is n=1. The brief's "REITs routinely run below 1.0x by design" is plausible domain knowledge, but the house rule is not to encode sector doctrine off one filer. Note Allied's net-income yellow was graded HONEST — the REIT profile's flags are partly *working*, which raises the cost of guessing wrong.
- **Banks/insurers → default, escalated to Riley.** Current ratio, ND/EBITDA, and interest coverage are conceptually shaky for these balance-sheet shapes, but TD came out CLEAN only via honest None-skips — we have **zero observed firings** to calibrate against. Today's None-skip behavior masks the problem; the ruling stays default until Riley decides on Q2.

**R3. Suppressed flags do NOT count toward the DECLINE/INVESTIGATE override. Confirmed.**
WHY: A flag we've ruled "expected shape, not distress" cannot honestly drive a distress signal. Counting it would be silent influence — suppressed from the display but alive in the verdict — which violates the same principle as silent suppression. The override is computed from surviving flags only. Consequence to accept explicitly: NGEx-shaped input that previously produced INVESTIGATE (1 red: operating income) now produces override `None`. That is the *intended* correction of the false signal.

**R4. Suppression is post-evaluation, never pre-evaluation, and every suppression produces a visible record.**
WHY: Mirrors the mapper's `unmapped[]` pattern (CB-012, CB-013) and the engine's `skip_reason="sector_excluded"` vocabulary. Each check evaluates normally against the (unchanged) default thresholds; if it fires and the sector table says suppress, the fired flag moves into a `suppressed[]` list carrying the value, the threshold it breached, the severity it *would* have had, and the sector rationale. Critically: **skip ≠ suppress.** A `None` metric is a skip (no data → no flag → not in `suppressed[]`), exactly as today. Only a flag that *would have fired* appears in `suppressed[]`.

**R5. Return shape: two additive keys — `suppressed` (always present, possibly empty) and `sector_profile` (echo of the profile used, or `None`).**
WHY: Additive keys are the safest backward-compatibility story: consumers reading the existing flag lists and override are untouched. The one intentional behavioral change — three flags moving out of the flag lists for `mining_exploration_sector` filers — is the point of the design, not a compatibility break. **Evidence gap, stated honestly:** the brief describes the current return as "flags plus an optional signal override" but does not pin the exact key names. The spec below is written as "preserve all existing keys byte-for-byte; add these two." CC must verify at review time that no consumer does strict schema validation that would reject new keys.

**R6. Sector-unknown = today's behavior, guaranteed.**
WHY: Hard constraint in the brief. EDGAR filers have no `mapping` key at all, so profile resolution must be a safe nested get that tolerates the key's total absence — not just a `None` value — and yields the default profile. Output for these filers: identical flags and override, plus `suppressed: []` and `sector_profile: None`.

**R7. UI: suppressed flags render as a deliberate, visible absence — following the Economics-panel precedent for NGEx.**
One-line concept for CC: a collapsed **"Sector-adjusted flags (3)"** strip under the red-flags panel, each entry reading like *"Negative free cash flow (yellow) — suppressed: expected shape for a pre-revenue explorer (`mining_exploration_sector`); not counted toward signal."* Zero suppressions → the strip does not render (empty list is honest absence, not a suppression).

**R8. The rule table itself is a casebook artifact.**
WHY: Every judgment call gets recorded with rationale. The `SECTOR_FLAG_RULES` table encodes exactly one ruling in v1 with its evidence pointer (NGEx finding #3). Casebook entry assignment is CC's surface (Sterling has no integrity-log access) — see Open Q5.

---

## 2. SPEC FOR THE IMPLEMENTER (Sterling)

**Module:** extend `modules/red_flag_detector.py` in place. Pure module: consumes `financial_data`, returns a dict. No I/O, no logging writes, no model calls, no Streamlit.

**Not to be touched:** the eight default thresholds, the override rules (2+ red → DECLINE; 1 red or 3+ yellow → INVESTIGATE; else None), the skip-on-None behavior, and `_calc_summary_metrics()`.

### Constants

```
CHECK_IDS = (
    "revenue_growth_yoy", "gross_margin", "operating_income",
    "net_income", "free_cash_flow", "current_ratio",
    "net_debt_to_ebitda", "interest_coverage",
)

SECTOR_FLAG_RULES: dict[str, dict[str, dict]] = {
    "mining_exploration_sector": {
        "operating_income": {
            "action": "suppress",
            "reason_code": "sector_expected_shape",
            "rationale": "Negative operating income is the expected shape of a "
                         "pre-revenue explorer (NGEx cold-load finding #3, 2026-06-17).",
        },
        "net_income":       { ...same shape, same reason_code... },
        "free_cash_flow":   { ...same shape, same reason_code... },
    },
}
```

- Table-driven and deterministic. `"action"` is `"suppress"` for every v1 rule; the field exists so a future `"downgrade"` (red→yellow reframe, pending Riley on Q1) is a table edit plus a small handler, not a redesign. **Do not implement a downgrade path in v1** — no active rule needs it, and unused code paths are untestable code paths.
- `reason_code` vocabulary: `"sector_expected_shape"` (v1, used); `"sector_inapplicable"` reserved (aligns with the engine's `skip_reason="sector_excluded"` at `modules/integrity/engine.py:34`), pending Q2.

### Functions

```
_resolve_sector_profile(financial_data: dict) -> str | None
```
Safe nested read of `financial_data["mapping"]["meta"]["sector_profile"]`. Must return `None` when `mapping` is absent entirely (EDGAR path), when `meta` is absent, or when the value is `None`. A profile string with no entry in `SECTOR_FLAG_RULES` (e.g. `reit_sector`, or a future profile the mapper adds) resolves normally but yields no rules → default behavior. No exceptions raised for missing keys, ever.

```
detect_flags(financial_data: dict) -> dict
```
Flow:
1. Compute metrics via `_calc_summary_metrics()` (unchanged).
2. Evaluate all eight checks against the existing default thresholds. `None` metric → skip, exactly as today.
3. Resolve `profile = _resolve_sector_profile(financial_data)`.
4. For each **fired** flag, look up `SECTOR_FLAG_RULES.get(profile, {}).get(check_id)`. If a suppress rule exists, the flag does not enter the red/yellow flag lists; instead append a suppression record (shape below) to `suppressed`.
5. Compute the signal override from **surviving flags only**.
6. Return: **all existing keys, names and shapes unchanged**, plus:
   - `"suppressed"`: list of suppression records, `[]` when none (key always present),
   - `"sector_profile"`: the resolved profile string or `None`.

### Suppression record shape

```
{
    "check": "free_cash_flow",              # from CHECK_IDS
    "severity_suppressed": "yellow",         # what it WOULD have been
    "metric_value": -14200000,               # the actual value that breached
    "threshold": "< 0",                      # human-readable rule it breached
    "sector_profile": "mining_exploration_sector",
    "action": "suppress",
    "reason_code": "sector_expected_shape",
    "rationale": "<verbatim from SECTOR_FLAG_RULES>",
}
```

### Edge cases (behavior is part of the spec)

| Case | Required behavior |
|---|---|
| No `mapping` key at all (EDGAR) | Default flags, `suppressed: []`, `sector_profile: None`. No KeyError. |
| `sector_profile` is `None` (SEDAR default) | Same as above but sector_profile echoes `None`. |
| Profile string not in rules table | Default flags; profile still echoed in `sector_profile`. |
| Explorer with metric = `None` on a suppressible check | Skip, as today. **Not** a `suppressed` entry — skips and suppressions never mix. |
| Explorer whose suppressible metrics are all positive | Nothing fires → `suppressed: []`. Suppression records only flags that would have fired. |
| Explorer with a real liquidity red surviving | Flag fires normally; override counts it (1 red → INVESTIGATE). |
| Suppressed flags alone would have met an override threshold | Override is `None`. Suppressed flags never count. |
| Same input called twice | Byte-identical output. Deterministic, no randomness, no state. |

**Deliverable:** the module plus pytest coverage of the acceptance tests below. Sandbox only — no live API calls, no `~/.finlens`, no integrity-log writes. app.py wiring and any moat-log surface are CC's.

---

## 3. ACCEPTANCE TESTS

Fixtures are minimal `financial_data` dicts with the metric inputs `_calc_summary_metrics()` needs pinned to produce the stated metrics; where a metric is stated as `None`, the underlying data is absent.

**T1 — NGEx shape (the motivating case).** Profile `mining_exploration_sector`; operating income < 0, net income < 0, FCF < 0; revenue `None`; current ratio 3.2x; debt metrics `None`.
→ Red flags: none. Yellow flags: none. `suppressed`: exactly 3 records (`operating_income` severity red, `net_income` severity yellow, `free_cash_flow` severity yellow), each with `reason_code="sector_expected_shape"` and the profile string. Override: `None` (previously INVESTIGATE via the op-income red — the correction is the point).

**T2 — Explorer with a real liquidity problem.** As T1 but current ratio 0.4x.
→ `current_ratio` red fires normally; `suppressed` still has the 3 records; override: INVESTIGATE (1 surviving red).

**T3 — Explorer near insolvency.** As T1 but current ratio 0.4x and interest coverage 0.8x.
→ 2 surviving reds; override: DECLINE. Suppressed records do not inflate the count, and their absence from the count doesn't rescue the verdict.

**T4 — Allied (REIT, unchanged).** Profile `reit_sector`; net income −1,327,532,000; current ratio 0.53x; interest coverage 2.34x.
→ Net-income yellow fires (HONEST flag preserved); current-ratio red fires; interest-coverage yellow fires; `suppressed: []`; override: INVESTIGATE (1 red). Identical flag set to today.

**T5 — TD (bank, unchanged).** Profile `financial_sector`; current ratio, ND/EBITDA, interest coverage all `None`; profitability metrics healthy.
→ CLEAN; `suppressed: []`; skips behave exactly as today (None-skip, not suppression).

**T6 — EDGAR filer, no mapping key.** `financial_data` with no `"mapping"` key; gross margin 12%.
→ No exception. Gross-margin yellow fires exactly as today; `suppressed: []`; `sector_profile: None`.

**T7 — Skip ≠ suppress.** Profile `mining_exploration_sector`; FCF `None`; net income < 0.
→ `suppressed` contains exactly 1 record (`net_income`); FCF appears nowhere — not flagged, not suppressed.

**T8 — Healthy explorer.** Profile `mining_exploration_sector`; all metrics positive/healthy.
→ CLEAN; `suppressed: []`.

**T9 — Unknown future profile string.** `sector_profile: "utilities_sector"` (not in table); operating income < 0.
→ Op-income red fires (default behavior); `sector_profile: "utilities_sector"` echoed; `suppressed: []`.

**T10 — Determinism.** Call `detect_flags` twice on the T1 fixture → results compare equal.

**T11 — Backward-compat shape.** For T4–T6, every pre-existing key of the return dict is present with unchanged name and value type; the only additions are `suppressed` and `sector_profile`.

---

## 4. OPEN QUESTIONS (for Riley)

**Q1 — REIT current ratio (Allied 0.53x red).** Is a red "Poor liquidity" the right read for a REIT? Evidence is n=1. Options: (a) keep default until ≥2–3 more REIT filers accumulate; (b) ratify a domain-knowledge downgrade red→yellow now (the table's reserved `"downgrade"` action makes this a small follow-up, not a redesign). I recommend (a) unless Riley is willing to ratify sector doctrine on domain knowledge alone — that ratification, not the code, is the actual decision.

**Q2 — Banks/insurers: current ratio, ND/EBITDA, interest coverage.** These are arguably *conceptually inapplicable* (reason_code `sector_inapplicable`, matching the engine's `sector_excluded` vocabulary) rather than miscalibrated. But TD is n=1 and those metrics have never actually *fired* on a bank in our evidence — the None-skip currently masks the question. Decision: pre-emptively suppress on conceptual grounds, or wait for a bank/insurer where these metrics compute? Note the risk of waiting: the first such filer ships a nonsense red before we fix it.

**Q3 — Explorer leverage checks with negative EBITDA/EBIT.** n=0. A debt-carrying explorer will mechanically red-flag interest coverage (negative EBIT < 1.5x). Real risk or false signal? No evidence either way; v1 keeps default. Flag for review when the first leveraged explorer loads.

**Q4 — Should explorer suppression be gated on revenue actually being absent/≈0?** v1 suppresses by profile alone. An explorer routed to `mining_exploration_sector` that *does* book material revenue would still get the three suppressions, and the "pre-revenue expected shape" rationale wouldn't strictly hold. Adding a revenue guard requires inventing a materiality threshold — which is why I didn't. Riley to decide whether profile-only is acceptable until a counterexample appears.

**Q5 — Casebook mechanics.** The `SECTOR_FLAG_RULES` table is a recorded judgment call. Who assigns its CB number, and does the `suppressed[]` output need to carry the CB reference in each record (CC's moat-log surface)?

**Q6 — EDGAR sector inference.** Confirming the standing position: US filers stay sector-unknown → default flags indefinitely, until a deliberate EDGAR sector-routing design exists. This design deliberately does nothing for them.

**Evidence gap flagged, not designed around:** the brief does not pin the exact current return-shape key names of `detect_flags`. The spec handles this via "preserve all existing keys exactly, add two" (R5, T11), but CC should confirm no downstream consumer performs strict schema validation before commit.