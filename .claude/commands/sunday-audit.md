Run the full FinLens Sunday audit in order. Complete every step before moving to the next. Today's date is available in the system context — use it for file names.

---

**Step 1 — Data Integrity Engine audit (CC report card)**

**Hook portability check (run first):** run `git config core.hooksPath`. If the output is not `.githooks`, flag it: "Pre-commit hook is inactive on this clone. Run `git config core.hooksPath .githooks` to re-enable." Do not block the rest of the audit, but include this in the Step 6 summary.

If `docs/audits/INTEGRITY_AUDIT_PROMPT.md` does not exist, run `/audit-create` first. Then run `/audit-run`. The audit writes a dated report to `docs/audits/integrity_audit_YYYYMMDD.md` with a PASS/FAIL header and a prioritized findings list. That report is the CC report card — save the file path; Step 6 and Step 7 reference it.

---

**Step 2 — Memory cross-check**

Read `CLAUDE.md` and `CODEX_MEMORY.md` in full. Check two things:

A. **CLAUDE.md → CODEX_MEMORY.md drift.** Diff the engineering conventions section by section. Any rule present in `CLAUDE.md` that is absent from, stale in, or contradicted by `CODEX_MEMORY.md` must be synced: update `CODEX_MEMORY.md` in this audit session so it reflects the current `CLAUDE.md` content. List every synced item in the audit report. `CODEX_MEMORY.md` is downstream of `CLAUDE.md`; the reverse is never true.

B. **Session memory files.** Check `C:\Users\riley\.claude\projects\C--Users-riley-OneDrive-Documents-Python-Project-finlens\memory\` for stale or contradicted entries. Update or flag any that conflict with current `CLAUDE.md` or working-tree state.

Report: list of synced items, or "No drift found."

---

**Step 3 — Schema and cache health**

Read `modules/analysis_cache.py` and find `CURRENT_SCHEMA_VERSION`. Check `git log --since="7 days ago" --oneline` for any commits that touch `normalize_financial_data`, library schema, or data shapes. If any such commits exist and `CURRENT_SCHEMA_VERSION` was not bumped, flag it as a required follow-up (do not auto-bump without Riley's sign-off). Report: current version + whether it is consistent with the week's changes.

---

**Step 4 — Test suite run**

Run the full test suite:

```
.\venv\Scripts\python.exe -m pytest tests/ -v
```

Report: number of tests collected, pass/fail counts, and any failing test names with their error message. Never accept a cached or previously pasted result — live run only.

---

**Step 5 — Build-order alignment**

Read `docs/FinLens_Roadmap_Addendum.md`. State the item currently at the top of the build queue. Check `git log --since="7 days ago" --oneline` and report whether this week's commits were aligned with that item. If work drifted to lower-priority items without an explicit rationale, flag it. This step is observational — do not block the audit for drift, just document it.

---

**Step 6 — Weekly summary**

Compile a weekly summary section and append it to the Step 1 report file (`docs/audits/integrity_audit_YYYYMMDD.md`). The section should include:

- Step 1 verdict (PASS / FAIL)
- Step 2: list of CODEX_MEMORY.md items synced (or "No drift found")
- Step 3: schema version status
- Step 4: test pass rate (e.g., "12/12 passed")
- Step 5: build-order alignment (aligned / drifted)
- Overall week status: **PASS** / **PASS WITH NOTES** / **FAIL**

Commit the updated report file and any CODEX_MEMORY.md changes to `dev` with message `chore: Sunday audit YYYY-MM-DD`. Report the commit hash.

---

**Step 7 — Opus strategic review**

Follow the instructions in `docs/audits/STEP_7_OPUS_REVIEW_PROMPT.md`. Open a new claude.ai chat, set the model to the most capable Opus available, attach the files listed in that prompt plus the CC report card from Step 1, and paste the review prompt. After receiving the review, save the response to `docs/audits/YYYY-MM-DD-opus-review.md` and commit to `dev`.
