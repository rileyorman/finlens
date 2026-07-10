"""Machine-enforce the handoff-doc size ceiling (added 2026-07-10).

docs/SESSION_HANDOFF.md drifted to ~180KB (~75K tokens) by 2026-07-10 --
past the point where /handoff could print it in one response, degrading the
cold-start resume procedure. This test is the machine-enforced tier of the
fix: when the doc crosses the ceiling, run /handoff-prune
(.claude/commands/handoff-prune.md) -- closed items and old session blocks
move VERBATIM to SESSION_HANDOFF_ARCHIVE.md, never lossily summarized.

Do NOT fix a failure here by deleting handoff content or by casually raising
the ceiling; the fix is the prune. (Post-prune baseline 2026-07-10: ~88KB.)
"""
from __future__ import annotations

from pathlib import Path

HANDOFF_SIZE_CEILING_BYTES = 100_000

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_session_handoff_stays_prunable():
    handoff = _REPO_ROOT / "docs" / "SESSION_HANDOFF.md"
    assert handoff.exists(), "docs/SESSION_HANDOFF.md is missing"
    size = handoff.stat().st_size
    assert size <= HANDOFF_SIZE_CEILING_BYTES, (
        f"docs/SESSION_HANDOFF.md is {size:,} bytes "
        f"(ceiling {HANDOFF_SIZE_CEILING_BYTES:,}). Run /handoff-prune "
        f"(.claude/commands/handoff-prune.md): move closed items + old "
        f"session blocks verbatim to SESSION_HANDOFF_ARCHIVE.md. Do not "
        f"delete content or raise the ceiling to make this pass."
    )


def test_session_handoff_archive_exists():
    # The prune target must exist; a prune that "fixes" size by deleting the
    # archive would be worse than the drift.
    archive = _REPO_ROOT / "docs" / "SESSION_HANDOFF_ARCHIVE.md"
    assert archive.exists(), "docs/SESSION_HANDOFF_ARCHIVE.md is missing"
