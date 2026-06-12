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
  - **Before issuing FAIL on any mandatory-pattern check:** verify the pattern against the current `CLAUDE.md` — `CODEX_MEMORY.md` may be stale. If the two files conflict, `CLAUDE.md` wins; flag the drift so the Sunday audit Step 2 can sync it.

**Step 4 — Change Propagation check.**
Source: CLAUDE.md "Change Propagation Rule" — quoted verbatim below. A review without this list is incomplete — do not issue PASS.

> Whenever a feature is added or modified, identify ALL code paths that touch the same data or functionality — not just the path addressed in the current task.
>
> **Known path pairs that must be checked together:**
>
> - Fresh upload flow AND Filing Library Load/Re-Analyse — both consume stored filing entries and stored bytes. Changes to upload extraction (e.g. adding docx support) must be mirrored in the Re-Analyse fallback path.
> - Single Analysis AND Filing Comparison AND Portfolio Manager — all consume `financial_data` / `summary_data` from session state or the library. Schema changes to those dicts affect all three.
> - Anything that writes library entries AND the sidebar rendering that reads them — new fields written by `lib_add` must have safe read-side defaults, and any display logic (labels, buttons) must handle the new field.
>
> **Before finishing any task, explicitly state:**
>
> 1. Which sibling paths were checked.
> 2. Whether each needed the same change or was unaffected. "Checked, not affected" is an acceptable answer — silence is not.
> 3. When a data schema changes (new field in library entries, `financial_data`, `positions.json`, etc.), how existing stored records without the new field are handled (default value, migration, or schema version bump).

For this review: list every sibling code path relevant to the changed code and state per path: **verified** or **not applicable** with a one-line reason. If the change touches none of the known pairs, state that explicitly.

**Step 5 — Run tests live.**
Run the relevant test suite using the actual Python binary:

```
.\venv\Scripts\python.exe -m pytest <relevant test files> -v
```

If no test files are obviously relevant, run `.\venv\Scripts\python.exe -m pytest tests/ -v`. Report the actual output. Never accept pasted test output from the summary as proof — the live run is required.

**Step 6 — UI and engine gates.**
- If the change touches any UI path or `app.py` flow: state explicitly "Visual run required" and ask Riley to share a screenshot of the affected screen before approval.
- If the change touches `engine.py` or `rules.py`: state explicitly that `/detection-test` then `/integrity-log` are required next steps before the verdict is issued.

**Step 7 — Verdict.**
Choose one:

- **PASS** — all spec requirements met, scope clean, mandatory patterns present, change propagation confirmed, tests green, UI/engine gates satisfied. Run `git checkout dev` if not already on dev, then commit with a conventional message (`feat:` / `fix:` / `docs:` / `test:` prefix). Report the commit hash.
- **FAIL** — do not commit. Report every finding as a numbered list with `file:line` references. Format the list so Riley can paste it directly back to Codex as a correction brief.

**Step 8 — Next step.**
End the review with exactly one line beginning "Next step:" that tells Riley what to do immediately after reading this review (e.g. share a screenshot, run /detection-test, paste findings back to Codex, or move to the next build-order item).
