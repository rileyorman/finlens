"""
FinLens Data Integrity Engine -- Structured Log
===============================================
Every validation run is appended as a JSON-lines record to
~/.finlens/integrity_log.jsonl.

Schema is deliberately Supabase-ready:
  - Top-level scalars are direct columns.
  - checks is a JSONB array of per-rule records.

Intended Supabase DDL (for future migration):
    CREATE TABLE integrity_log (
        id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        timestamp     timestamptz NOT NULL,
        ticker        text NOT NULL,
        sector        text,
        sector_was_unknown boolean,
        fiscal_year   text,
        overall_status text NOT NULL,
        filing_accession text,
        filing_source text,
        rules_run     int,
        rules_passed  int,
        rules_failed  int,
        rules_skipped int,
        checks        jsonb
    );

Querying failed rules across all filings:
    SELECT ticker, fiscal_year, check->>'rule_id', check->>'observed_value'
    FROM integrity_log,
         jsonb_array_elements(checks) AS check
    WHERE (check->>'passed')::boolean = false
    ORDER BY timestamp DESC;
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import ValidationResult

_DEFAULT_LOG = Path.home() / ".finlens" / "integrity_log.jsonl"

# How many trailing lines to reverse-scan for the idempotency check.
# Covers typical batch sizes without reading the entire log on every append.
_SCAN_WINDOW = 50


def _result_key(result: "ValidationResult") -> str:
    """Compute a stable identity key for a ValidationResult."""
    if result.filing_accession:
        return result.filing_accession
    # Fallback: composite of ticker + fiscal year + source + hash of observed values.
    vals = sorted(
        f"{c.rule_id}:{c.observed_value}"
        for c in result.checks
        if c.observed_value is not None
    )
    h = hashlib.md5("|".join(vals).encode()).hexdigest()[:8]
    return f"{result.ticker}|{result.fiscal_year}|{result.filing_source or ''}|{h}"


def _record_key(record: dict) -> str:
    """Extract the same identity key from a deserialized log record dict."""
    accn = record.get("filing_accession")
    if accn:
        return accn
    vals = sorted(
        f"{c['rule_id']}:{c.get('observed_value')}"
        for c in record.get("checks", [])
        if c.get("observed_value") is not None
    )
    h = hashlib.md5("|".join(vals).encode()).hexdigest()[:8]
    return (
        f"{record.get('ticker')}|{record.get('fiscal_year')}"
        f"|{record.get('filing_source', '')}|{h}"
    )


def _already_logged(path: Path, key: str) -> bool:
    """
    Return True if a record with the given identity key already exists.
    Scans the last _SCAN_WINDOW lines to keep the check lightweight.
    """
    if not path.exists():
        return False
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
        for line in reversed(lines[-_SCAN_WINDOW:]):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                if _record_key(record) == key:
                    return True
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return False


def append_to_log(
    result: "ValidationResult",
    log_path: Path | str | None = None,
) -> Path:
    """
    Append a single ValidationResult record to the integrity log.
    Creates the log file and parent directories if they don't exist.

    Idempotent: if a record with the same filing_accession (or composite
    fallback key) already exists in the log, the write is silently skipped.

    Returns the path the record was written to (or would have been written to).
    """
    path = Path(log_path) if log_path else _DEFAULT_LOG
    path.parent.mkdir(parents=True, exist_ok=True)

    key = _result_key(result)
    if _already_logged(path, key):
        return path

    line = json.dumps(result.to_dict(), ensure_ascii=False, default=str)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")

    return path


def read_log(
    log_path: Path | str | None = None,
    ticker: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """
    Read records from the integrity log, optionally filtered by ticker.
    Returns records in reverse-chronological order (newest first).
    """
    path = Path(log_path) if log_path else _DEFAULT_LOG
    if not path.exists():
        return []

    records: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                if ticker is None or record.get("ticker") == ticker:
                    records.append(record)
            except json.JSONDecodeError:
                continue

    records.reverse()
    return records[:limit] if limit else records
