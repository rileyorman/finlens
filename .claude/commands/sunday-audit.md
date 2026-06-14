Run the full FinLens Sunday audit in order. Complete every step before moving to the next. Today's date is available in the system context — use it for file names.

---

**Step 1 — Data Integrity Engine audit (CC report card)**

**Hook portability check (run first):** run `git config core.hooksPath`. If the output is not `.githooks`, flag it: "Pre-commit hook is inactive on this clone. Run `git config core.hooksPath .githooks` to re-enable." Do not block the rest of the audit, but include the finding in the Step 6 summary.

If `docs/audits/INTEGRITY_AUDIT_PROMPT.md` does not exist, run `/audit-create` first. Then run `/audit-run`. The audit writes a dated report to `docs/audits/integrity_audit_YYYYMMDD.md` with a PASS/FAIL header and a prioritized findings list. That report is the CC report card — save the file path; Step 6 and Step 8 reference it.

**Schema and cache health (sub-check):** Read `modules/analysis_cache.py` and find `CURRENT_SCHEMA_VERSION`. Check `git log --since="7 days ago" --oneline` for any commits that touch `normalize_financial_data`, library schema, or data shapes. If any such commits exist and `CURRENT_SCHEMA_VERSION` was not bumped, flag it as a required follow-up (do not auto-bump without Riley's sign-off). Include: current version + whether it is consistent with the week's changes.

**Test suite (sub-check):** Run the full test suite:

```
.\venv\Scripts\python.exe -m pytest tests/ -v
```

Report: number of tests collected, pass/fail counts, and any failing test names with their error message. Never accept a cached or previously pasted result — live run only.

---

**Step 2 — Memory cross-check**

Read `CLAUDE.md` and `CODEX_MEMORY.md` in full. Check two things:

A. **CLAUDE.md → CODEX_MEMORY.md drift.** Diff the engineering conventions section by section. Any rule present in `CLAUDE.md` that is absent from, stale in, or contradicted by `CODEX_MEMORY.md` must be synced: update `CODEX_MEMORY.md` in this audit session so it reflects the current `CLAUDE.md` content. List every synced item in the audit report. `CODEX_MEMORY.md` is downstream of `CLAUDE.md`; the reverse is never true.

B. **Session memory files.** Check `C:\Users\riley\.claude\projects\C--Users-riley-OneDrive-Documents-Python-Project-finlens\memory\` for stale or contradicted entries. Update or flag any that conflict with current `CLAUDE.md` or working-tree state.

Report: list of synced items, or "No drift found."

---

**Step 3 — Release radar**

Search for updates across the full FinLens stack released in the past week:

- Anthropic / Claude: new models, API changes, prompt-caching TTL or pricing changes, deprecations
- Streamlit: new releases, breaking changes, deprecation notices
- FMP (Financial Modeling Prep): API changes, endpoint deprecations, pricing tier changes
- EDGAR / SEDAR+: schema changes, rate-limit policy updates, new filing types
- Any other dependency in `requirements.txt` with a security advisory or breaking release

For each item found: state the change, the affected FinLens component, and whether action is required before next deploy. If nothing found for a category, state "No changes."

---

**Step 4 — Cost audit**

Review API spend patterns for the past week:

- Anthropic API: estimated token usage by model tier (Haiku vs Sonnet vs Opus), cache hit rate (cache_read_input_tokens vs cache_creation_input_tokens), any unexpectedly large calls
- Identify any extraction or analysis path that is not using prompt caching when it could be
- Flag any model-tier mismatches (e.g., Sonnet used where Haiku would suffice, or vice versa per the architecture in CLAUDE.md)

Source: check `logs/` or any cost tracking artifacts available. If no cost data is accessible, state that explicitly and recommend the tracking mechanism to add.

---

**Step 5 — Live app health check**

Verify that the deployed app at https://finlens-ai.streamlit.app is healthy and matches dev expectations:

- Confirm the app loads without error
- Check that the deployed version matches the current `main` branch (check the about/version indicator if present, or note the last merge-to-main commit hash)
- Note any visible regressions vs the local dev state
- If the app is down or shows an error, flag as a blocker

Report: app status (UP / DOWN / DEGRADED), version alignment (aligned / behind by N commits), any regressions noted.

---

**Step 6 — Roadmap priority review**

Read `docs/FinLens_Roadmap_Addendum.md`. State the item currently at the top of the build queue. Check `git log --since="7 days ago" --oneline` and report whether this week's commits were aligned with that item. If work drifted to lower-priority items without an explicit rationale, flag it. This step is observational — do not block the audit for drift, just document it.

**Weekly summary (sub-check):** Compile a weekly summary section and append it to the Step 1 report file (`docs/audits/integrity_audit_YYYYMMDD.md`). The section should include:

- Step 1 verdict (PASS / FAIL), schema version status, test pass rate (e.g., "12/12 passed"), hook portability status
- Step 2: list of CODEX_MEMORY.md items synced (or "No drift found")
- Step 3: release radar findings (or "No actionable changes")
- Step 4: cost audit summary
- Step 5: live app status
- Step 6: build-order alignment (aligned / drifted)
- Overall week status: **PASS** / **PASS WITH NOTES** / **FAIL**

Commit the updated report file and any CODEX_MEMORY.md changes to `dev` with message `chore: Sunday audit YYYY-MM-DD`. Report the commit hash.

---

**Step 7 — Sector Profile Review (data-layer health check)**

For each sector profile (financial_sector, resource_sector, reit_sector, and any future profiles), scan the unmapped[] lists across all fixtures belonging to that sector and surface:
(a) High-frequency unmapped labels — any label appearing in 2+ filers of the same sector is a candidate for promotion to a canonical field (this is how the 4 universal REIT fields were found).
(b) 'Common, not universal' promotion candidates — fields currently at 2/3 coverage that a new filer could push to universal. Known pending: equity_accounted_income and fair_value_adjustments_financial_instruments (REIT, both 2/3, awaiting a 4th REIT).
(c) New label variants — existing canonical fields picking up new alias spellings from recently added filers.
(d) Cross-sector leakage — a label that should map but doesn't because its alias lives in the wrong profile.
Note: only has teeth once a sector has 2+ filers. Currently qualifying: reit_sector (3 filers), resource_sector (1, will qualify when a 2nd resource filer lands). This step systematizes the 'Feed the Loop' discipline on the campaign corpus — the same review that will later run automatically on user uploads (network-effects flywheel).

Rationale: Steps 1-7 are now all CC operational work. Step 8 runs the Opus handoff in a new chat last so the human is not bouncing between the Opus chat and CC mid-audit.

---

**Step 8 — Opus strategic review**

Follow the instructions in `docs/audits/STEP_7_OPUS_REVIEW_PROMPT.md`. Note: this remains the filename for compatibility even though the Opus review is now audit Step 8. Open a new claude.ai chat, set the model to the most capable Opus available, attach the files listed in that prompt plus the CC report card from Step 1, and paste the review prompt. After receiving the review, save the response to `docs/audits/YYYY-MM-DD-opus-review.md` and commit to `dev`.
