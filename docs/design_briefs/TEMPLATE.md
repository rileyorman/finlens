# Design Brief — <topic> (<YYYY-MM-DD>)

<!--
How to use: copy this file, fill every section, then run
  .\venv\Scripts\python.exe scripts\ask_fable.py docs\design_briefs\<this-file>.md
The response lands in docs/design_sessions/. Rulings are UNRATIFIED until
Riley signs off; ratified rulings get a casebook entry (CB-xxx) as usual.

The brief IS the design session's quality ceiling: Fable only sees what is
in this file. Faithful-transcription rule applies — evidence quoted here
must match the repo verbatim; if you can't find it, say so, don't
reconstruct.
-->

## The question

One paragraph. What decision is being asked for, and why now.

## Evidence pack

The facts Fable needs, quoted or summarized WITH file:line references:
- Current behavior (code paths, thresholds, shapes)
- Real-filer evidence (which filers hit this, with values)
- Prior rulings that constrain the answer (CB-xxx entries, CLAUDE.md
  principles)
- What the dry-runs / moat log showed

## Constraints

- Inviolable rules this design must not break (integrity-first, no silent
  behavior, honest absence > vacuous validation, etc.)
- Boundaries of the implementer seat (Sterling works offline in the sandbox
  repo: no live API calls, no ~/.finlens access, no integrity-log writes)
- Anything already decided that is NOT up for relitigation

## Requested output

Rulings + rationale, spec for the implementer, acceptance tests, open
questions — per the ask_fable.py system prompt. Add topic-specific asks here
(e.g. "propose the JSON shape for X").
