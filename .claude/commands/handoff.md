Print session resume context for a model picking up FinLens cold.

Read-only — no file edits, no commits, no analysis, just print.

1. Print the full contents of `docs/SESSION_HANDOFF.md` verbatim.
2. Run `git log --oneline -20` and print the output.
3. Print the `Open queue` section from `docs/SESSION_HANDOFF.md` separately for emphasis.
4. (Added 2026-07-10.) If the doc is too large to print verbatim in one response: say so explicitly, print the `Last updated` header + the Open queue + the git log instead, and flag that `/handoff-prune` is due. Never silently truncate.
