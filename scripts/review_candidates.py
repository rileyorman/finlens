"""
FinLens Candidate Review Runner (CC-side)
=========================================
Given a candidate bundle produced by ingest_worker.py, the review runner:

  1. Re-fetches the PDF from provenance.json's URL.
  2. Verifies the sha256 matches.  Mismatch or dead URL -> REJECTED.
  3. Compares Sterling's extraction.json against the caller-supplied canonical
     extraction (or notes that canonical extraction is needed from CC's machine).
  4. Surfaces Sterling's questions.md items.
  5. Outputs a per-candidate disposition: PROMOTED / NEEDS_TRIAGE / REJECTED.

Usage (CC-side, after fetching the ingest/ branch)
-----
    python scripts/review_candidates.py \\
        --bundle-dir candidates/TOU_FY2024 \\
        [--canonical-extraction /path/to/canonical_extraction.json]

If --canonical-extraction is omitted, the runner skips the field comparison
step and marks the candidate NEEDS_TRIAGE with a note.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Add repo root to sys.path so 'modules.*' is importable when the script
# is invoked directly (python scripts/review_candidates.py).  Running via
# 'PYTHONPATH=. python ...' or 'python -m pytest' already covers this;
# the explicit insert is a safety net for direct invocation.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from modules.integrity.field_aliases import FIELD_ALIASES, FIELD_STATEMENT  # noqa: E402

REVIEWER_VERSION = "1"


# ---------------------------------------------------------------------------
# Bundle loading
# ---------------------------------------------------------------------------

class BundleError(Exception):
    """Raised when the bundle is missing required files."""


def load_bundle(bundle_dir: Path) -> dict:
    """Load all required artifact files from bundle_dir.

    Returns a dict with keys: provenance, extraction, mapping, worker_meta,
    questions_text.
    Raises BundleError if any required file is absent or unparseable.
    """
    required_json = ("provenance.json", "extraction.json", "mapping.json", "worker_meta.json")
    data: dict = {}
    for filename in required_json:
        path = bundle_dir / filename
        if not path.exists():
            raise BundleError(f"Missing required artifact: {filename}")
        try:
            data[filename.replace(".json", "")] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise BundleError(f"Cannot parse {filename}: {exc}") from exc

    questions_path = bundle_dir / "questions.md"
    data["questions_text"] = (
        questions_path.read_text(encoding="utf-8") if questions_path.exists() else ""
    )
    return data


# ---------------------------------------------------------------------------
# Provenance verification
# ---------------------------------------------------------------------------

def verify_provenance(provenance: dict) -> tuple[bytes | None, str]:
    """Re-fetch the PDF from provenance['url'] and verify sha256.

    Returns (pdf_bytes, status_message).
    pdf_bytes is None on fetch failure.
    status_message is human-readable (PASS / MISMATCH / FETCH_FAILED).
    """
    import httpx

    url = provenance.get("url", "")
    expected_sha256 = provenance.get("sha256", "")

    if not url:
        return None, "FETCH_FAILED: no URL in provenance record"

    try:
        resp = httpx.get(url, follow_redirects=True, timeout=120)
        resp.raise_for_status()
        pdf_bytes = resp.content
    except Exception as exc:
        return None, f"FETCH_FAILED: {exc}"

    actual_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    if actual_sha256 == expected_sha256:
        return pdf_bytes, f"PASS (sha256={actual_sha256[:16]}...)"
    return None, (
        f"MISMATCH: expected {expected_sha256[:16]}...  "
        f"got {actual_sha256[:16]}..."
    )


# ---------------------------------------------------------------------------
# Field comparison (Sterling candidate vs canonical extraction)
# ---------------------------------------------------------------------------

def _extract_field_value(financial_data: dict, canonical: str) -> float | None:
    """Pull a value for a canonical field from a financial_data dict.

    Alias table sourced from modules.integrity.field_aliases (shared with
    prior_column.py).  Add new aliases there, not here.
    """
    aliases = FIELD_ALIASES
    statements = FIELD_STATEMENT
    # Try mapping.mapped first (SEDAR).
    mapped = (financial_data.get("mapping") or {}).get("mapped") or {}
    if canonical in mapped:
        v = mapped[canonical].get("value")
        return float(v) if v is not None else None
    # Fall back to statement rows.
    stmt_key = statements.get(canonical)
    if not stmt_key:
        return None
    for row in financial_data.get(stmt_key) or []:
        if row.get("line_item") in (aliases.get(canonical) or []):
            v = row.get("value")
            return float(v) if v is not None else None
    return None


def compare_extractions(candidate: dict, canonical: dict) -> list[dict]:
    """Compare five headline fields between candidate and canonical extractions.

    Returns a list of per-field comparison dicts:
      {field, candidate_value, canonical_value, pct_diff, status}
    status: AGREE (<2%), MINOR (<10%), DIVERGE (>=10%), MISSING.
    """
    fields = ["revenue", "net_income", "total_assets", "operating_cash_flow", "capex"]
    results = []
    for field in fields:
        cand_v = _extract_field_value(candidate, field)
        canon_v = _extract_field_value(canonical, field)
        if cand_v is None or canon_v is None:
            results.append({
                "field": field,
                "candidate_value": cand_v,
                "canonical_value": canon_v,
                "pct_diff": None,
                "status": "MISSING",
            })
            continue
        denom = max(abs(cand_v), abs(canon_v))
        diff = abs(cand_v - canon_v) / denom if denom else 0.0
        pct = round(diff * 100, 2)
        status = "AGREE" if diff < 0.02 else ("MINOR" if diff < 0.10 else "DIVERGE")
        results.append({
            "field": field,
            "candidate_value": cand_v,
            "canonical_value": canon_v,
            "pct_diff": pct,
            "status": status,
        })
    return results


# ---------------------------------------------------------------------------
# Disposition logic
# ---------------------------------------------------------------------------

def determine_disposition(
    provenance_status: str,
    questions_text: str,
    field_comparison: list[dict] | None,
) -> str:
    """Return PROMOTED, NEEDS_TRIAGE, or REJECTED with a brief reason."""
    if "FETCH_FAILED" in provenance_status or "MISMATCH" in provenance_status:
        return f"REJECTED: provenance verification failed ({provenance_status})"

    if field_comparison is not None:
        diverged = [f for f in field_comparison if f["status"] == "DIVERGE"]
        if diverged:
            fields_str = ", ".join(f["field"] for f in diverged)
            return f"NEEDS_TRIAGE: field divergence on {fields_str}"

    has_questions = bool(
        questions_text.strip()
        and "_No judgment questions raised._" not in questions_text
        # questions.md always has a header; check for actual items
        and any(line.strip().startswith(("1.", "2.", "3.", "4.", "5.")) for line in questions_text.splitlines())
    )
    if has_questions:
        return "NEEDS_TRIAGE: judgment questions require Riley/CC resolution"

    if field_comparison is None:
        return "NEEDS_TRIAGE: canonical extraction not supplied -- run on CC machine"

    return "PROMOTED"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="FinLens candidate review runner (CC-side)."
    )
    parser.add_argument(
        "--bundle-dir",
        required=True,
        help="Path to a candidate bundle directory (e.g. candidates/TOU_FY2024).",
    )
    parser.add_argument(
        "--canonical-extraction",
        metavar="PATH",
        help=(
            "Path to canonical extraction JSON from CC's own pipeline run. "
            "Omit to skip the field comparison step."
        ),
    )
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        default=False,
        help="Skip PDF re-fetch (useful for offline testing; canonical path only).",
    )
    args = parser.parse_args(argv)

    bundle_dir = Path(args.bundle_dir)
    if not bundle_dir.exists():
        print(f"ERROR: bundle directory not found: {bundle_dir}", file=sys.stderr)
        return 1

    # --- Load bundle ---
    try:
        bundle = load_bundle(bundle_dir)
    except BundleError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    provenance = bundle["provenance"]
    extraction = bundle["extraction"]
    worker_meta = bundle["worker_meta"]
    questions_text = bundle["questions_text"]

    ticker = provenance.get("ticker", "?")
    fy = provenance.get("fiscal_year", "?")

    print(f"[review_candidates v{REVIEWER_VERSION}]  {ticker} {fy}")
    print(f"  Bundle      : {bundle_dir}")
    print(f"  Source type : {provenance.get('source_type', '?')}")
    print(f"  Worker      : v{worker_meta.get('worker_version', '?')}  "
          f"model={worker_meta.get('model_used', '?')}")
    print(f"  Guard       : {worker_meta.get('guard_verdict', '?')}")
    print()

    # --- Provenance verification ---
    if args.skip_fetch:
        provenance_status = "SKIPPED (--skip-fetch)"
        print(f"  Provenance  : {provenance_status}")
    else:
        print("Verifying provenance (re-fetching PDF)...", flush=True)
        _, provenance_status = verify_provenance(provenance)
        print(f"  Provenance  : {provenance_status}")
    print()

    # --- Field comparison ---
    field_comparison: list[dict] | None = None
    if args.canonical_extraction:
        canon_path = Path(args.canonical_extraction)
        if not canon_path.exists():
            print(f"ERROR: --canonical-extraction not found: {canon_path}", file=sys.stderr)
            return 1
        try:
            canonical_data = json.loads(canon_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"ERROR: cannot parse canonical extraction: {exc}", file=sys.stderr)
            return 1
        field_comparison = compare_extractions(extraction, canonical_data)
        print("Field comparison (candidate vs canonical):")
        print(
            f"  {'field':<22}  {'candidate':>16}  {'canonical':>16}  {'diff%':>7}  status"
        )
        print(f"  {'-'*22}  {'-'*16}  {'-'*16}  {'-'*7}  {'-'*10}")
        for fc in field_comparison:
            cv = fc["candidate_value"]
            kv = fc["canonical_value"]
            pct = fc["pct_diff"]
            cv_str = f"{cv:,.0f}" if cv is not None else "n/a"
            kv_str = f"{kv:,.0f}" if kv is not None else "n/a"
            pct_str = f"{pct:.2f}%" if pct is not None else "n/a"
            print(
                f"  {fc['field']:<22}  {cv_str:>16}  {kv_str:>16}  {pct_str:>7}  {fc['status']}"
            )
        print()
    else:
        print("  [note] --canonical-extraction not supplied.")
        print("  Run canonical extraction on CC machine, then rerun with that path.")
        print()

    # --- Questions ---
    if questions_text:
        print("Sterling judgment questions:")
        print(questions_text)
    else:
        print("  questions.md: (absent)")
    print()

    # --- Disposition ---
    disposition = determine_disposition(provenance_status, questions_text, field_comparison)
    print(f"Disposition: {disposition}")
    print()
    print("Next steps for PROMOTED: run canonical guards + cross-extractor, write moat record.")
    print("Next steps for NEEDS_TRIAGE: resolve flags with Riley, then re-run.")
    print("Next steps for REJECTED: return to Sterling with reason.")

    return 0 if not disposition.startswith("REJECTED") else 2


if __name__ == "__main__":
    sys.exit(main())
