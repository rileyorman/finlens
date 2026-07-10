"""Pin the pytest data-dir isolation guard (conftest.py, 2026-07-09).

If either assertion ever fails, tests have regained access to the real
~/.finlens — the condition that let 25 Mastech figure-presence records
pollute the production moat log between 2026-07-07 and 2026-07-09.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from modules.integrity import log as integrity_log  # noqa: E402


def test_data_dir_is_redirected_away_from_real_finlens():
    redirected = os.environ.get("FINLENS_DATA_DIR", "")
    assert redirected, "conftest.py must set FINLENS_DATA_DIR before imports"
    real = Path.home() / ".finlens"
    assert Path(redirected).resolve() != real.resolve()
    # config resolved its paths from the redirected env var.
    assert Path(redirected).resolve() in Path(config.LIBRARY_DIR).resolve().parents or (
        Path(config.LIBRARY_DIR).resolve() == Path(redirected).resolve()
    )
    assert real.resolve() not in Path(config.LIBRARY_DIR).resolve().parents
    assert Path(config.LIBRARY_DIR).resolve() != real.resolve()


def test_integrity_log_default_path_is_isolated():
    default_log = Path(integrity_log._DEFAULT_LOG).resolve()
    real_log = (Path.home() / ".finlens" / "integrity_log.jsonl").resolve()
    assert default_log != real_log, (
        "the integrity log default path must never point at the real moat "
        "log during tests"
    )
