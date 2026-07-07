# Design Brief — Sector-aware red flags (2026-07-07)

<!-- Pilot brief for the three-agent pipeline (Fable designs, Sterling
implements, CC reviews/commits, Riley ratifies). Run with:
.\venv\Scripts\python.exe scripts\ask_fable.py docs\design_briefs\2026-07-07-sector-aware-red-flags.md -->

## The question

Should FinLens's red-flag detector be sector-aware — and if so, which flags
are suppressed or reframed for which sector profiles, and how is that
suppression kept honest (visible, never silent)? This is NGEx cold-load
finding #3 (2026-06-17), accepted as a non-blocking residual when the
Phase-1 dry-run set closed (2026-07-06) and queued as "a small sector-aware
red-flag design decision."

## Evidence pack

**Current behavior (`modules/red_flag_detector.py`, sector-blind):**
`detect_flags(financial_data)` scores `_calc_summary_metrics()` output
against fixed thresholds and returns flags plus an optional signal override.
The eight checks:

| Check | Red | Yellow |
|---|---|---|
| YoY revenue growth | < −10% | < 0% |
| Gross margin | < 0% | < 20% |
| Operating income | < 0 | — |
| Net income | — | < 0 |
| Free cash flow | — | < 0 |
| Current ratio | < 1.0x | < 1.5x |
| Net debt / EBITDA | > 5.0x | > 3.0x |
| Interest coverage | < 1.5x | < 3.0x |

Override: 2+ red → DECLINE; 1 red or 3+ yellow → INVESTIGATE; else None.
Checks skip honestly when a metric is None (no data → no flag).

**The motivating finding (NGEx FY2025 cold load, 2026-06-17, finding #3):**
"'Negative free cash flow' flagged yellow on a pre-revenue explorer, where
negative FCF is expected by design." NGEx routes to
`mining_exploration_sector`. For a pre-revenue explorer, negative FCF,
negative operating income, and negative net income are the *expected shape
of the business*, not distress signals — the flags read as false signals to
a knowledgeable reader and erode credibility.

**Counter-evidence that flags are working (do not over-suppress):**
- Allied (REIT, FY2025 re-run): "Negative net income −1,327,532,000" yellow
  was graded an HONEST flag — a real net loss on a real income-producing
  REIT. The slot PASS record also verified current ratio 0.53x and interest
  coverage 2.34x as arithmetically correct.
- TD (bank, FY2025 re-run): Red Flags CLEAN — correct outcome.

**Sector signal available:** `financial_data["mapping"]["meta"]["sector_profile"]`
(set by `modules/integrity/sedar_mapper.py` routing, lines ~175–216). Values:
`mining_exploration_sector`, `mining_sector`, `resource_sector`,
`reit_sector`, `financial_sector`, `insurance_sector`, or None (default
corporate). EDGAR/US filings have NO mapping and therefore no
sector_profile — sector is unknown on that path today.

**House precedents for sector-aware honesty:**
- The Economics panel is gated off entirely for `mining_exploration_sector`
  (honest sector suppression at the display layer — NGEx renders it as a
  deliberate absence, part of the slot's honest-degradation pass).
- The integrity engine's `CheckResult` has `skip_reason="sector_excluded"`
  (`modules/integrity/engine.py:34`) — an existing vocabulary for "this
  check does not apply to this sector."
- The mapper's `unmapped[]` pattern: rejected/unused data stays VISIBLE,
  never silently dropped (CB-012's blended subtotals, CB-013's NCI-excluding
  lines). Any suppressed flag should have an analogous visible record.

**Possible sector questions beyond the explorer case (flagging, not
pre-judging):** REITs routinely run current ratios below 1.0x by design
(Allied 0.53x — arithmetic correct, but is a red "Poor liquidity" the right
*read* for the sector?); banks/insurers have balance-sheet shapes where
current ratio and ND/EBITDA are conceptually shaky (TD came out CLEAN only
because those metrics were unavailable — honest skip, not sector logic).
n=1 per shape: evidence here is thin and the design should say what is
decidable now vs. what needs more filers.

## Constraints

- **Integrity-first / no silent behavior:** a suppressed flag must remain
  visible somewhere (e.g. a `suppressed[]` list with the sector rationale),
  mirroring `unmapped[]` and `skip_reason`. Zero silent errors is the gate
  standard; zero silent *suppressions* is the same principle.
- **Deterministic:** sector logic is table/threshold logic, no model calls.
- **The detector stays a pure module:** `detect_flags` consumes
  `financial_data` and returns a dict; Streamlit rendering stays in app.py.
- **Sector-unknown = current behavior:** EDGAR filers and any SEDAR filer
  routed to the default profile keep today's flags unchanged. This design
  must not alter non-SEDAR behavior.
- **Implementer boundary:** Sterling works offline in the sandbox repo — no
  live API calls, no `~/.finlens` access, no integrity-log writes. The
  module + pytest coverage is his deliverable; app.py wiring, live evidence,
  and any moat-log surface are CC's.
- **Not up for relitigation:** the eight existing thresholds for the default
  profile; the override rules; the honest-skip-on-None behavior.

## Requested output

Rulings + rationale, spec for the implementer, acceptance tests, open
questions — per the standard format. Topic-specific asks:
1. Propose the exact return-shape change (e.g. `suppressed` key) and its
   backward-compatibility story for existing consumers of `detect_flags`.
2. Rule explicitly per sector profile × per check: fire / suppress /
   reframe (e.g. downgrade red→yellow), with rationale; where evidence is
   n=1 or absent, say "insufficient evidence — default behavior" rather
   than inventing sector rules.
3. Say how the signal override interacts with suppression (can a suppressed
   flag still count toward DECLINE/INVESTIGATE? presumably no — confirm).
4. Say what the UI should show for suppressed flags (one-line concept is
   enough; CC designs the rendering).
