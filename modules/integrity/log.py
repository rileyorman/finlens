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
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from config import LIBRARY_DIR

if TYPE_CHECKING:
    from .engine import ValidationResult
    from .cross_validate import CrossValidationResult
    from .cross_extractor import CrossCheckResult

_DEFAULT_LOG = LIBRARY_DIR / "integrity_log.jsonl"

# How many trailing lines to reverse-scan for the idempotency check.
# Covers typical batch sizes without reading the entire log on every append.
_SCAN_WINDOW = 50

CROSS_EXTRACTOR_DISPOSITIONS = {
    "finlens_correct",
    "checker_error",
    "deliberate_mapping_decision",
    "structural_absence",
    "gemini_miss_field_present",
    "other",
}
CROSS_EXTRACTOR_TRIAGE_STATUSES = {"CONFLICT", "GEMINI_MISSING"}


@dataclass(frozen=True)
class LogReadDiagnostics:
    path: str
    physical_lines: int = 0
    records_parsed: int = 0
    records_returned: int = 0
    unparseable_lines: int = 0
    unparseable_line_numbers: tuple[int, ...] = ()


_LAST_READ_LOG_DIAGNOSTICS = LogReadDiagnostics(path=str(_DEFAULT_LOG))


def get_last_read_log_diagnostics() -> LogReadDiagnostics:
    """Return diagnostics for the most recent read_log() call in this process."""
    return _LAST_READ_LOG_DIAGNOSTICS


def _set_last_read_log_diagnostics(diagnostics: LogReadDiagnostics) -> None:
    global _LAST_READ_LOG_DIAGNOSTICS
    _LAST_READ_LOG_DIAGNOSTICS = diagnostics


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
        with open(path, encoding="utf-8-sig") as fh:
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


def _cv_checker_version(record: dict) -> str:
    """Return the cross-validation checker version; legacy records are v1."""
    return str(record.get("checker_version") or "1")


def _cv_already_logged(path: Path, key: str) -> bool:
    """Return True if a cross-validation record with the given cv| key already exists."""
    if not path.exists():
        return False
    try:
        with open(path, encoding="utf-8-sig") as fh:
            lines = fh.readlines()
        for line in reversed(lines[-_SCAN_WINDOW:]):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                if record.get("record_type") != "cross_validation":
                    continue
                yr_m = re.search(r"(\d{4})", str(record.get("fiscal_year", "")))
                yr_s = yr_m.group(1) if yr_m else str(record.get("fiscal_year", ""))
                rkey = (
                    f"cv|{record.get('ticker', '')}|{yr_s}"
                    f"|v{_cv_checker_version(record)}"
                )
                if rkey == key:
                    return bool(record.get("fmp_fetch_reason"))
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return False


def append_cv_to_log(
    result: "CrossValidationResult",
    log_path: Path | str | None = None,
) -> Path:
    """
    Append a CrossValidationResult record to the integrity log.

    Idempotent: skips the write silently if a cross-validation record for the
    same ticker + fiscal year + checker_version already exists in the log.

    Returns the path the record was written to (or would have been written to).
    """
    path = Path(log_path) if log_path else _DEFAULT_LOG
    path.parent.mkdir(parents=True, exist_ok=True)

    yr_m = re.search(r"(\d{4})", str(result.fiscal_year or ""))
    yr_s = yr_m.group(1) if yr_m else str(result.fiscal_year or "")
    checker_version = str(getattr(result, "checker_version", None) or "1")
    key  = f"cv|{result.ticker}|{yr_s}|v{checker_version}"

    if _cv_already_logged(path, key):
        return path

    line = json.dumps(result.to_dict(), ensure_ascii=False, default=str)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")

    return path


def _cross_extractor_checker_version(record: dict) -> str:
    """Return the checker version for a cross-extractor record; legacy is v1."""
    return str(record.get("checker_version") or "1")


def _cross_extractor_definitive_logged(
    path: Path,
    key: str,
    checker_version: str,
) -> bool:
    """
    Return True if a definitive cross-extractor record exists for this filing
    key and checker behavior version.
    """
    if not path.exists():
        return False
    try:
        with open(path, encoding="utf-8-sig") as fh:
            lines = fh.readlines()
        for line in reversed(lines[-_SCAN_WINDOW:]):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                if record.get("record_type") != "cross_extractor_agreement":
                    continue
                if (
                    str(record.get("filing_accession") or "") == key
                    and _cross_extractor_checker_version(record) == checker_version
                    and record.get("state") != "UNCHECKED"
                ):
                    return True
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return False


def append_cross_extractor_to_log(
    result: "CrossCheckResult",
    log_path: Path | str | None = None,
) -> Path:
    """
    Append a Gemini second-extractor agreement record to the integrity log.

    Idempotent: skips the write silently if a definitive cross-extractor record
    for the same filing_accession and checker_version already exists in the log.
    UNCHECKED records are re-runnable so a later fixed key/transport can append
    a definitive outcome. Different checker versions append a new record.

    Returns the path the record was written to (or would have been written to).
    """
    path = Path(log_path) if log_path else _DEFAULT_LOG
    path.parent.mkdir(parents=True, exist_ok=True)

    key = str(result.filing_accession or "")
    checker_version = str(getattr(result, "checker_version", None) or "1")
    if _cross_extractor_definitive_logged(path, key, checker_version):
        return path

    line = json.dumps(result.to_dict(), ensure_ascii=False, default=str)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")

    return path


def _cross_extractor_target_exists(
    path: Path,
    filing_accession: str,
    field: str,
    checker_version: str,
) -> bool:
    for record in read_log(path):
        if record.get("record_type") != "cross_extractor_agreement":
            continue
        if str(record.get("filing_accession") or "") != filing_accession:
            continue
        if _cross_extractor_checker_version(record) != checker_version:
            continue
        if record.get("state") not in ("FLAGGED", "PARTIAL"):
            continue
        for item in record.get("cross_extractor_fields", []):
            if (
                str(item.get("canonical_field") or "") == field
                and item.get("status") in CROSS_EXTRACTOR_TRIAGE_STATUSES
            ):
                return True
    return False


def append_cross_extractor_disposition_to_log(
    *,
    filing_accession: str,
    ticker: str,
    fiscal_year: str,
    field: str,
    checker_version: str,
    disposition: str,
    rationale: str,
    author: str = "riley",
    timestamp: str | None = None,
    log_path: Path | str | None = None,
) -> Path:
    """
    Append a human triage disposition for a cross-extractor field.

    Linkage is by filing_accession + field + checker_version. Dispositions are
    append-only: duplicates are retained, and readers use the latest timestamp.
    """
    path = Path(log_path) if log_path else _DEFAULT_LOG
    path.parent.mkdir(parents=True, exist_ok=True)

    accession = str(filing_accession or "").strip()
    target_field = str(field or "").strip()
    version = str(checker_version or "").strip()
    disposition_value = str(disposition or "").strip()
    rationale_text = str(rationale or "").strip()
    required = {
        "filing_accession": accession,
        "ticker": str(ticker or "").strip(),
        "fiscal_year": str(fiscal_year or "").strip(),
        "field": target_field,
        "checker_version": version,
        "rationale": rationale_text,
        "author": str(author or "").strip(),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError(f"Missing required disposition field(s): {', '.join(missing)}")
    if disposition_value not in CROSS_EXTRACTOR_DISPOSITIONS:
        allowed = ", ".join(sorted(CROSS_EXTRACTOR_DISPOSITIONS))
        raise ValueError(f"Invalid disposition {disposition_value!r}; expected one of: {allowed}")
    if not _cross_extractor_target_exists(path, accession, target_field, version):
        raise ValueError(
            "No matching cross_extractor_agreement triage target for "
            f"{accession} field={target_field} checker_version={version}"
        )

    record = {
        "record_type": "cross_extractor_disposition",
        "filing_accession": accession,
        "ticker": required["ticker"],
        "fiscal_year": required["fiscal_year"],
        "field": target_field,
        "checker_version": version,
        "disposition": disposition_value,
        "rationale": rationale_text,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "author": required["author"],
    }

    line = json.dumps(record, ensure_ascii=False, default=str)
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
        _set_last_read_log_diagnostics(LogReadDiagnostics(path=str(path)))
        return []

    records: list[dict] = []
    physical_lines = 0
    records_parsed = 0
    unparseable_line_numbers: list[int] = []
    with open(path, encoding="utf-8-sig") as fh:
        for line_number, line in enumerate(fh, start=1):
            physical_lines += 1
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                records_parsed += 1
                if ticker is None or record.get("ticker") == ticker:
                    records.append(record)
            except json.JSONDecodeError:
                unparseable_line_numbers.append(line_number)

    records.reverse()
    returned = records[:limit] if limit else records
    _set_last_read_log_diagnostics(
        LogReadDiagnostics(
            path=str(path),
            physical_lines=physical_lines,
            records_parsed=records_parsed,
            records_returned=len(returned),
            unparseable_lines=len(unparseable_line_numbers),
            unparseable_line_numbers=tuple(unparseable_line_numbers),
        )
    )
    return returned
