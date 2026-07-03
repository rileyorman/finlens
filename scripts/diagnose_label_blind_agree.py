from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.integrity.cross_extractor import (  # noqa: E402
    CROSS_EXTRACTOR_VERSION,
    normalize_source_label,
)
from modules.integrity.log import _DEFAULT_LOG, read_log  # noqa: E402


REGISTRY_PATH = ROOT / "tests" / "fixtures" / "filing_registry.json"


def _checker_version(record: dict[str, Any]) -> str:
    return str(record.get("checker_version") or "1")


def _record_key(record: dict[str, Any], fallback: int) -> str:
    accession = str(record.get("filing_accession") or "").strip()
    if accession:
        return accession
    return (
        f"{record.get('ticker') or '?'}|{record.get('fiscal_year') or '?'}|"
        f"{_checker_version(record)}|{fallback}"
    )


def _latest_cross_extractor_records(
    records: list[dict[str, Any]],
    checker_version: str,
) -> list[dict[str, Any]]:
    """Return one latest record per filing accession for the selected checker version."""
    latest: dict[str, dict[str, Any]] = {}
    for idx, record in enumerate(records):
        if record.get("record_type") != "cross_extractor_agreement":
            continue
        if _checker_version(record) != checker_version:
            continue
        if record.get("state") == "UNCHECKED":
            continue
        key = _record_key(record, idx)
        current = latest.get(key)
        if current is None or str(record.get("timestamp") or "") > str(current.get("timestamp") or ""):
            latest[key] = record
    return sorted(latest.values(), key=lambda r: (str(r.get("ticker") or ""), str(r.get("fiscal_year") or "")))


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _delta(finlens_value: Any, gemini_value: Any) -> tuple[float | None, float | None]:
    finlens = _to_float(finlens_value)
    gemini = _to_float(gemini_value)
    if finlens is None or gemini is None:
        return None, None
    absolute = gemini - finlens
    relative_pct = abs(absolute) / max(abs(finlens), 1.0) * 100
    return absolute, relative_pct


def _agree_label_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        for field in record.get("cross_extractor_fields", []):
            if field.get("status") != "AGREE":
                continue
            finlens_label = str(field.get("finlens_label") or "")
            gemini_label = str(field.get("gemini_label") or "")
            finlens_normalized = normalize_source_label(finlens_label)
            gemini_normalized = normalize_source_label(gemini_label)
            absolute_delta, relative_delta_pct = _delta(
                field.get("finlens_value"),
                field.get("gemini_value"),
            )
            rows.append({
                "ticker": record.get("ticker") or "?",
                "fiscal_year": record.get("fiscal_year") or "?",
                "field": field.get("canonical_field") or "?",
                "finlens_label": finlens_label,
                "gemini_label": gemini_label,
                "finlens_normalized": finlens_normalized,
                "gemini_normalized": gemini_normalized,
                "finlens_value": field.get("finlens_value"),
                "gemini_value": field.get("gemini_value"),
                "absolute_delta": absolute_delta,
                "relative_delta_pct": relative_delta_pct,
                "labels_match": finlens_normalized == gemini_normalized,
            })
    return rows


def _expected_corpus_count() -> int | None:
    try:
        import json

        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        return sum(
            1
            for filing in registry.get("filings", [])
            if filing.get("source") == "sedar" and filing.get("fixture_path")
        )
    except Exception:
        return None


def _fmt_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _fmt_delta(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+g}"


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}%"


def _print_report(
    rows: list[dict[str, Any]],
    *,
    source_path: Path,
    checker_version: str,
    record_count: int,
) -> None:
    differing = [row for row in rows if not row["labels_match"]]
    same_label = len(rows) - len(differing)

    print("Label-blind AGREE diagnostic")
    print(f"Source: existing cross_extractor_agreement records in {source_path}")
    print("Re-run: no; this diagnostic is read-only and does not call Gemini or write the integrity log.")
    print(f"Checker version measured: v{checker_version}")
    print(f"Frozen records analyzed: {record_count}")
    expected = _expected_corpus_count()
    if expected is not None and expected != record_count:
        print(f"Corpus coverage warning: registry has {expected} SEDAR fixture(s); analyzed {record_count} record(s).")
    print()

    if differing:
        print("Differing-label AGREEs")
        for row in differing:
            print(
                f"- {row['ticker']} {row['fiscal_year']} {row['field']}: "
                f"FinLens={_fmt_value(row['finlens_value'])} "
                f"Gemini={_fmt_value(row['gemini_value'])} "
                f"delta={_fmt_delta(row['absolute_delta'])} "
                f"relative_delta={_fmt_pct(row['relative_delta_pct'])}"
            )
            print(f"  FinLens label raw      : {row['finlens_label']}")
            print(f"  Gemini label raw       : {row['gemini_label']}")
            print(f"  FinLens label normalized: {row['finlens_normalized']}")
            print(f"  Gemini label normalized : {row['gemini_normalized']}")
    else:
        print("Differing-label AGREEs: none")

    print()
    print("Summary")
    print(f"total AGREEs      : {len(rows)}")
    print(f"same-label AGREEs : {same_label}")
    print(f"differing-label AGREEs: {len(differing)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose cross-extractor AGREE rows whose source labels differ after production normalization."
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        default=_DEFAULT_LOG,
        help="Integrity log JSONL path to read. Defaults to the FinLens integrity log.",
    )
    parser.add_argument(
        "--checker-version",
        default=CROSS_EXTRACTOR_VERSION,
        help="cross_extractor_agreement checker_version to measure.",
    )
    args = parser.parse_args(argv)

    records = read_log(args.log_path)
    latest = _latest_cross_extractor_records(records, str(args.checker_version))
    rows = _agree_label_rows(latest)

    if not latest:
        print("Label-blind AGREE diagnostic")
        print(f"Source: existing cross_extractor_agreement records in {args.log_path}")
        print("Re-run: no; this diagnostic is read-only and does not call Gemini or write the integrity log.")
        print(f"Checker version measured: v{args.checker_version}")
        print("Frozen records analyzed: 0")
        print()
        print(
            "No frozen records were available to read directly. A corpus re-run would be "
            "required to generate source data, but this script intentionally does not do that."
        )
        return 1

    _print_report(
        rows,
        source_path=args.log_path,
        checker_version=str(args.checker_version),
        record_count=len(latest),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
