Print session resume context for a model picking up FinLens cold.

Read-only — no file edits, no commits, no analysis, just print.

1. Print the full contents of `docs/SESSION_HANDOFF.md` verbatim (the RESUME doc — since the 2026-07-13 two-doc split it stays small enough to print in one response).
2. Run `git log --oneline -20` and print the output.
3. Print the `Open queue` section from `docs/SESSION_HANDOFF.md` separately for emphasis.
4. (Added 2026-07-13, the two-doc split.) Do NOT print these, but say in one line where they live: standing sections are in `docs/SESSION_REFERENCE.md` (gates, ground-truth, how-to-work, persona, moat, campaign state — read before writing code); closed history is in `docs/SESSION_HANDOFF_ARCHIVE.md` (do not read at cold start).
5. (Added 2026-07-10.) If the resume doc is somehow too large to print verbatim in one response: say so explicitly, print the `Last updated` header + the Open queue + the git log instead, and flag that `/handoff-prune` is due. Never silently truncate.
