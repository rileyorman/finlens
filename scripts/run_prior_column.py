"""
Prior-Column Continuity Checker -- Batch Runner
================================================
Scans the analysis cache directory, runs the prior-column continuity check
for every payload found, prints a summary table, and appends records to the
integrity log.

Usage
-----
    python scripts/run_prior_column.py [--dry-run] [--analysis-dir PATH] [--log-path PATH]

Options
-------
    --dry-run       Print results WITHOUT writing to the integrity log.
                    Default OFF; the first live write-run happens on Riley's
                    machine via CC with /integrity-log evidence.
    --analysis-dir  Override the analysis cache directory (default: production).
    --log-path      Override the integrity log path (default: production).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure the project root is importable when run directly.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.integrity.prior_column import check_prior_column


def _load_payloads(analysis_dir: Path) -> list[tuple[str, dict]]:
    """Return (filename, payload) pairs for all readable JSON files in analysis_dir."""
    payloads: list[tuple[str, dict]] = []
    if not analysis_dir.exists():
        return payloads
    for path in sorted(analysis_dir.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and data.get("financial_data"):
                payloads.append((path.name, data))
        except Exception:
            pass  # unreadable files are skipped
    return payloads


def _fmt_state(state: str) -> str:
    labels = {
        "VERIFIED":  "VERIFIED ",
        "PARTIAL":   "PARTIAL  ",
        "FLAGGED":   "FLAGGED  ",
        "UNCHECKED": "UNCHECKED",
    }
    return labels.get(state, state[:9].ljust(9))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run prior-column continuity checks over the analysis cache."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print results without writing to the integrity log.",
    )
    parser.add_argument(
        "--analysis-dir",
        metavar="PATH",
        help="Analysis cache directory (default: production ~/.finlens/analysis/).",
    )
    parser.add_argument(
        "--log-path",
        metavar="PATH",
        help="Integrity log path (default: production ~/.finlens/integrity_log.jsonl).",
    )
    args = parser.parse_args()

    # --- Resolve directories ---
    if args.analysis_dir:
        analysis_dir = Path(args.analysis_dir)
    else:
        try:
            from config import ANALYSIS_CACHE_DIR
            analysis_dir = ANALYSIS_CACHE_DIR
        except Exception:
            analysis_dir = Path.home() / ".finlens" / "analysis"

    if args.log_path:
        log_path: Path | None = Path(args.log_path)
    elif args.dry_run:
        log_path = None  # will not be used
    else:
        try:
            from config import LIBRARY_DIR
            log_path = LIBRARY_DIR / "integrity_log.jsonl"
        except Exception:
            log_path = Path.home() / ".finlens" / "integrity_log.jsonl"

    print(f"Analysis dir : {analysis_dir}")
    print(f"Log path     : {log_path if not args.dry_run else '(dry-run -- no write)'}")
    print()

    payloads = _load_payloads(analysis_dir)
    if not payloads:
        print("No analysis cache files found.  Run some analyses first.")
        return

    print(f"Found {len(payloads)} payload(s).  Running checks...")
    print()

    # Column header
    col_file = 36
    col_fy   = 8
    col_pfy  = 8
    print(
        f"  {'file':<{col_file}}  {'ticker':<6}  {'FY':<{col_fy}}  "
        f"{'prior FY':<{col_pfy}}  state      conflicts"
    )
    print(
        f"  {'-'*col_file}  {'-'*6}  {'-'*col_fy}  "
        f"{'-'*col_pfy}  {'-'*9}  {'-'*40}"
    )

    state_totals: dict[str, int] = {"VERIFIED": 0, "PARTIAL": 0, "FLAGGED": 0, "UNCHECKED": 0}

    for filename, payload in payloads:
        # Pass None for log_path in dry-run so check_prior_column won't write.
        effective_log = None if args.dry_run else log_path
        record = check_prior_column(
            payload,
            analysis_dir=analysis_dir,
            log_path=effective_log,
        )

        state = record.get("state", "UNCHECKED")
        state_totals[state] = state_totals.get(state, 0) + 1

        ticker = str(record.get("ticker") or "?")
        fy = str(record.get("fiscal_year") or "?")[-8:]
        pfy = str(record.get("prior_fiscal_year") or "?")[-8:]

        conflicts = [
            f.get("canonical_field", "?")
            for f in record.get("fields", [])
            if f.get("status") == "CONFLICT"
        ]
        conflict_str = ", ".join(conflicts) if conflicts else ""
        if state == "UNCHECKED":
            conflict_str = record.get("reason") or ""

        short_file = filename[:col_file]
        print(
            f"  {short_file:<{col_file}}  {ticker:<6}  {fy:<{col_fy}}  "
            f"{pfy:<{col_pfy}}  {_fmt_state(state)}  {conflict_str}"
        )

    # Summary
    print()
    print("  Summary:")
    for state, count in sorted(state_totals.items()):
        print(f"    {state:<10}  {count}")

    if args.dry_run:
        print()
        print("  [dry-run] No records written to the integrity log.")
    else:
        print()
        print(f"  Records appended to: {log_path}")


if __name__ == "__main__":
    main()
