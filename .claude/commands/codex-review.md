Review the Codex completion summary that Riley has pasted. Follow every step below in order — do not skip steps, do not treat pasted output as proof of anything.

**Step 1 — Identify and read all changed files.**
Parse the summary for every file Codex created or modified. Read each file in full from the working tree using the Read tool. The working tree is the source of truth; the summary's prose description is not.

**Step 2 — Locate the governing spec.**
Check the summary and recent conversation context for a named design doc (e.g. docs/*.md). If one is named, read it. If no spec is named, stop and ask Riley exactly one question: "Which spec or instruction governs this work?" — then wait for the answer before continuing.

**Step 3 — Review code against spec.**
Check each of the following and report findings:
- Requirements met: every spec requirement either implemented or explicitly noted as out-of-scope.
- Scope guard: list any files touched that are outside the stated scope (flag, do not auto-approve).
- FinLens mandatory patterns — check all that apply to the changed files:
  - `trust_env=False` present on any httpx client construction.
  - Avast SSL helper reused from `modules/claude_analyzer.py` (not replaced with certifi or create_default_context).
  - Persistent storage written to `~/.finlens/` or the AppData cache path — never `%TEMP%\FinLens\` or inside OneDrive folders.
  - API key loaded via the same pattern as `modules/claude_analyzer.py` (not hardcoded, not a different env-var name).
  - Number formatters cover K / M / B / T magnitude range (test mentally: 500 → "500", 3_700_000_000 → "3.70B", 4_600_000_000_000 → "4.60T").
  - Claude analyst text is never hard-truncated with `[:N]` slicing in display paths.
  - Any docs or inline commands use PowerShell semicolons (`;`) not `&&` for chained commands.

**Step 4 — Run tests live.**
Run the relevant test suite using the actual Python binary:

```
.\venv\Scripts\python.exe -m pytest <relevant test files> -v
```

If no test files are obviously relevant, run `.\venv\Scripts\python.exe -m pytest tests/ -v`. Report the actual output. Never accept pasted test output from the summary as proof — the live run is required.

**Step 5 — UI and engine gates.**
- If the change touches any UI path or `app.py` flow: state explicitly "Visual run required" and ask Riley to share a screenshot of the affected screen before approval.
- If the change touches `engine.py` or `rules.py`: state explicitly that `/detection-test` then `/integrity-log` are required next steps before the verdict is issued.

**Step 6 — Verdict.**
Choose one:

- **PASS** — all spec requirements met, scope clean, mandatory patterns present, tests green, UI/engine gates satisfied. Run `git checkout dev` if not already on dev, then commit with a conventional message (`feat:` / `fix:` / `docs:` / `test:` prefix). Report the commit hash.
- **FAIL** — do not commit. Report every finding as a numbered list with `file:line` references. Format the list so Riley can paste it directly back to Codex as a correction brief.

**Step 7 — Next step.**
End the review with exactly one line beginning "Next step:" that tells Riley what to do immediately after reading this review (e.g. share a screenshot, run /detection-test, paste findings back to Codex, or move to the next build-order item).
