"""Machine-enforce the handoff-doc size ceilings (added 2026-07-10;
two-doc structure ratified by Riley 2026-07-13).

docs/SESSION_HANDOFF.md drifted to ~180KB (~75K tokens) by 2026-07-10 --
past the point where /handoff could print it in one response, degrading the
cold-start resume procedure. The 2026-07-13 structural split moved the
STANDING sections (gates, ground-truth, how-to-work, moat, campaign state)
verbatim into docs/SESSION_REFERENCE.md so the resume doc stays small and
printable; this test enforces both ceilings.

When the RESUME doc crosses its ceiling, run /handoff-prune
(.claude/commands/handoff-prune.md) -- closed items and old session blocks
move VERBATIM to SESSION_HANDOFF_ARCHIVE.md, never lossily summarized.
When the REFERENCE doc crosses its ceiling, tighten in place and archive
superseded text verbatim.

Do NOT fix a failure here by deleting content or by casually raising a
ceiling. (Post-split baselines 2026-07-13: resume ~60KB, reference ~33KB.)
"""
from __future__ import annotations

from pathlib import Path

RESUME_SIZE_CEILING_BYTES = 80_000
REFERENCE_SIZE_CEILING_BYTES = 60_000

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_session_handoff_stays_printable():
    handoff = _REPO_ROOT / "docs" / "SESSION_HANDOFF.md"
    assert handoff.exists(), "docs/SESSION_HANDOFF.md is missing"
    size = handoff.stat().st_size
    assert size <= RESUME_SIZE_CEILING_BYTES, (
        f"docs/SESSION_HANDOFF.md is {size:,} bytes "
        f"(ceiling {RESUME_SIZE_CEILING_BYTES:,}). Run /handoff-prune "
        f"(.claude/commands/handoff-prune.md): move closed items + old "
        f"session blocks verbatim to SESSION_HANDOFF_ARCHIVE.md. Do not "
        f"delete content or raise the ceiling to make this pass."
    )


def test_session_reference_stays_lean():
    reference = _REPO_ROOT / "docs" / "SESSION_REFERENCE.md"
    assert reference.exists(), (
        "docs/SESSION_REFERENCE.md is missing (the standing-sections doc "
        "from the 2026-07-13 two-doc split)"
    )
    size = reference.stat().st_size
    assert size <= REFERENCE_SIZE_CEILING_BYTES, (
        f"docs/SESSION_REFERENCE.md is {size:,} bytes "
        f"(ceiling {REFERENCE_SIZE_CEILING_BYTES:,}). Tighten standing "
        f"sections in place, archiving superseded text verbatim to "
        f"SESSION_HANDOFF_ARCHIVE.md. Do not delete content or raise the "
        f"ceiling to make this pass."
    )


def test_session_handoff_archive_exists():
    # The prune target must exist; a prune that "fixes" size by deleting the
    # archive would be worse than the drift.
    archive = _REPO_ROOT / "docs" / "SESSION_HANDOFF_ARCHIVE.md"
    assert archive.exists(), "docs/SESSION_HANDOFF_ARCHIVE.md is missing"
