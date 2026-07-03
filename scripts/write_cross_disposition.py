from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.integrity.log import (
    CROSS_EXTRACTOR_DISPOSITIONS,
    append_cross_extractor_disposition_to_log,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Append a cross-extractor human triage disposition.",
    )
    parser.add_argument("--filing-accession", required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--fiscal-year", required=True)
    parser.add_argument("--field", required=True)
    parser.add_argument("--checker-version", required=True)
    parser.add_argument(
        "--disposition",
        required=True,
        choices=sorted(CROSS_EXTRACTOR_DISPOSITIONS),
    )
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--author", default="riley")
    parser.add_argument("--log-path")
    return parser


def main() -> None:
    args = _parser().parse_args()
    path = append_cross_extractor_disposition_to_log(
        filing_accession=args.filing_accession,
        ticker=args.ticker,
        fiscal_year=args.fiscal_year,
        field=args.field,
        checker_version=args.checker_version,
        disposition=args.disposition,
        rationale=args.rationale,
        author=args.author,
        log_path=args.log_path,
    )
    print(
        "Appended cross_extractor_disposition "
        f"{args.filing_accession} field={args.field} "
        f"checker_version={args.checker_version} to {path}"
    )


if __name__ == "__main__":
    main()
