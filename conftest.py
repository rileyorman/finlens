"""Pytest session isolation — no test may touch real app data (2026-07-09).

FINLENS_DATA_DIR is redirected to a throwaway directory BEFORE any project
module is imported: pytest loads this rootdir conftest ahead of collection,
and config.py resolves _APP_BASE (→ LIBRARY_DIR → the integrity log, PDF
root, caches) from the env var at first import. With this guard no test —
present or future — can read or write the real ~/.finlens.

WHY (found 2026-07-09, twenty-second session): 25 "Mastech Digital"
extraction_figure_presence records had accumulated in the PRODUCTION moat
log since 2026-07-07 — test_run.py (a root-level demo SCRIPT, not a test)
was being imported at pytest collection, executing its module-level live
pipeline and logging through the production path on every full-suite run.
~11% of the moat log was test noise. The script itself stays runnable
manually (python test_run.py); pyproject's testpaths now stops pytest from
collecting it. This conftest is the defense-in-depth layer: even a future
test that reaches a logging path lands in the throwaway directory.

Machine-enforced tier (Minimize Human Error). CI evidence of safety: the
suite is green on ubuntu runners whose home has no .finlens at all, so no
test legitimately depends on real user data.
"""
import os
import tempfile

_TEST_DATA_DIR = tempfile.mkdtemp(prefix="finlens_test_data_")
os.environ["FINLENS_DATA_DIR"] = _TEST_DATA_DIR
