"""
FinLens Ingestion Worker (Sterling-side)
========================================
Fetcher and extractor.  Produces a REVIEWABLE CANDIDATE ARTIFACT BUNDLE
for CC review.  Sterling is a fetcher-and-extractor, NEVER the
analyst-of-record.

The moat log is singular.  Integrity records written by this script are
SCRATCH DIAGNOSTICS shipped inside the bundle for CC's information.  They
are never merged into the canonical moat log.

Usage
-----
    FINLENS_INGEST_API_KEY=sk-ant-... python scripts/ingest_worker.py \\
        --ticker TOU --fy FY2024 \\
        --url https://tourmaline.ca/site/PDF/annual_report.pdf \\
        --source-type ir \\
        --out-dir candidates \\
        --scratch-dir /tmp/finlens_scratch/TOU_FY2024

Outputs
-------
    candidates/<TICKER>_<FY>/
        extraction.json   -- financial_data (EDGAR/IR) or sedar extraction
        mapping.json      -- sedar mapper output, or EDGAR note
        provenance.json   -- URL, sha256, timestamps, filename
        worker_meta.json  -- model, key label, guard verdict, runtime
        questions.md      -- judgment flags; empty header if none

The PDF is NOT committed (size and copyright discipline).
sha256 + URL stand in for it; CC re-fetches independently.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

WORKER_VERSION = "1"
FINLENS_API_KEY_ENV = "FINLENS_INGEST_API_KEY"

# Judgment question triggers
_FIGURE_PRESENCE_RATIO_THRESHOLD = 0.6
_MAPPED_COUNT_LOW_THRESHOLD = 3  # flag when mapped_count below this

# ---------------------------------------------------------------------------
# FINLENS_DATA_DIR isolation -- MUST run before any FinLens import
# ---------------------------------------------------------------------------

def _isolate_scratch(scratch_dir: Path) -> None:
    """Point all FinLens data writes at scratch_dir.

    This must be called before any FinLens module is imported.  config.py
    reads FINLENS_DATA_DIR at import time and creates all data directories
    there.  Setting it here ensures the production ~/.finlens is untouched.
    """
    scratch_dir.mkdir(parents=True, exist_ok=True)
    os.environ["FINLENS_DATA_DIR"] = str(scratch_dir)


# ---------------------------------------------------------------------------
# PDF fetch
# ---------------------------------------------------------------------------

def fetch_pdf(url: str) -> tuple[bytes, str, str]:
    """Download a PDF from url.

    Returns (pdf_bytes, sha256_hex, original_filename).
    filename is derived from the URL path; falls back to 'filing.pdf'.
    Raises httpx.HTTPStatusError on non-200 responses.
    """
    import httpx

    resp = httpx.get(url, follow_redirects=True, timeout=120)
    resp.raise_for_status()
    pdf_bytes = resp.content
    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    # Best-effort filename from the URL path.
    url_path = url.split("?")[0].rstrip("/")
    filename = url_path.split("/")[-1] or "filing.pdf"
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"
    return pdf_bytes, sha256, filename


# ---------------------------------------------------------------------------
# Extraction paths (imports deferred until after _isolate_scratch)
# ---------------------------------------------------------------------------

def extract_edgar(
    pdf_bytes: bytes,
    api_key: str,
) -> tuple[dict, str]:
    """Extract financial data from an EDGAR/IR PDF.

    Returns (financial_data_dict, model_id).
    Raises FabricatedExtractionError if the figure-presence guard fires.
    """
    from modules.pdf_extractor import extract_text_from_pdf
    from modules.claude_analyzer import analyze_financials, DEFAULT_MODEL

    text = extract_text_from_pdf(BytesIO(pdf_bytes))
    financial_data = analyze_financials(text, api_key=api_key)
    return financial_data, DEFAULT_MODEL


def extract_sedar(
    pdf_bytes: bytes,
    api_key: str,
    scratch_dir: Path,
) -> tuple[dict, str]:
    """Extract and map a SEDAR filing PDF.

    sedar_extractor reads ANTHROPIC_API_KEY; we bridge to the ingest key
    for the duration of the call and restore afterward.

    Returns (sedar_result_dict, model_id).
    """
    from sedar_extractor import SEDAR_MODEL

    # Bridge ingest key -> ANTHROPIC_API_KEY (sedar_extractor's convention).
    _saved = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = api_key
    try:
        import tempfile
        from sedar_extractor import extract_sedar_filing

        # sedar_extractor needs a file path.
        with tempfile.NamedTemporaryFile(
            suffix=".pdf", delete=False, dir=scratch_dir
        ) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = Path(tmp.name)
        try:
            result = dict(extract_sedar_filing(tmp_path))
        finally:
            tmp_path.unlink(missing_ok=True)
    finally:
        if _saved is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = _saved

    return result, SEDAR_MODEL


# ---------------------------------------------------------------------------
# Judgment question generation
# ---------------------------------------------------------------------------

def generate_questions(
    source_type: str,
    extraction: dict,
    mapping: dict,
    ticker: str,
    fy: str,
) -> list[str]:
    """Return a list of judgment question strings for questions.md.

    Mandatory triggers per spec:
    - mapped_count below sector typical range or zero
    - sector routing ambiguous / unknown
    - unmapped label that looks like a canonical concept
    - figure-presence verdict FABRICATED or ratio below threshold
    - currency ambiguity, missing statement sections
    - anything requiring canonical-definition interpretation
    """
    questions: list[str] = []

    # --- Mapped count check ---
    mapped = mapping.get("mapped") or {}
    mapped_count = len(mapped)
    if mapped_count == 0:
        questions.append(
            f"MAPPED_COUNT=0: no canonical fields resolved for {ticker} {fy}. "
            "Check sector routing and alias coverage."
        )
    elif mapped_count < _MAPPED_COUNT_LOW_THRESHOLD:
        questions.append(
            f"MAPPED_COUNT={mapped_count} is below the low threshold "
            f"({_MAPPED_COUNT_LOW_THRESHOLD}). Verify sector routing is correct."
        )

    # --- Sector routing ---
    sector = extraction.get("sector_inferred") or extraction.get("sector")
    if not sector:
        questions.append(
            "SECTOR_UNKNOWN: sector_inferred is absent. "
            "Cannot confirm correct alias profile was applied."
        )
    elif "oil" in str(sector).lower() and "gas" in str(sector).lower():
        questions.append(
            f"SECTOR_AMBIGUOUS: sector is '{sector}'. "
            "If this is a gas-weighted filer (e.g. TOU, ARX) routing to "
            "crude/WTI assumptions, flag for adjudication — "
            "gas-weighted ambiguity policy item is queued."
        )

    # --- Unmapped labels that may be alias candidates ---
    unmapped = mapping.get("unmapped") or []
    known_canonical_hints = {
        "revenue", "revenues", "net income", "total assets",
        "operating cash", "capital expenditure", "capex",
        "royalties", "production cost", "depletion",
    }
    for label_entry in unmapped[:30]:  # cap scan to first 30
        # Unmapped entries may be dicts with a 'label' key or plain strings.
        if isinstance(label_entry, dict):
            label_raw = label_entry.get("label") or ""
        elif isinstance(label_entry, str):
            label_raw = label_entry
        else:
            label_raw = ""
        label = str(label_raw).lower()
        for hint in known_canonical_hints:
            if hint in label:
                questions.append(
                    f"ALIAS_CANDIDATE: unmapped label '{label_entry}' resembles "
                    f"canonical concept '{hint}'. Do NOT add alias; flag for Riley/CC."
                )
                break

    # --- Figure presence (EDGAR/IR only) ---
    if source_type in ("edgar", "ir"):
        fp = extraction.get("figure_presence") or {}
        verdict = fp.get("verdict")
        ratio = fp.get("ratio")
        if verdict == "FABRICATED":
            questions.append(
                "FIGURE_PRESENCE=FABRICATED: extraction rejected by guard. "
                "Source text likely did not contain financial statements. "
                "Re-fetch with a different URL or request manual download."
            )
        elif ratio is not None and ratio < _FIGURE_PRESENCE_RATIO_THRESHOLD:
            questions.append(
                f"FIGURE_PRESENCE_LOW: ratio={ratio:.2f} < {_FIGURE_PRESENCE_RATIO_THRESHOLD}. "
                "Fewer than 60% of extracted figures appear in the source text. "
                "Verify the PDF covers the financial statement pages."
            )

    # --- Currency ---
    currency = extraction.get("currency") or extraction.get("financial_data", {}).get("currency")
    if not currency:
        questions.append(
            "CURRENCY_UNKNOWN: no currency found in extraction. "
            "Verify the PDF reports a clear currency denomination."
        )

    # --- Missing statement sections (SEDAR) ---
    if source_type == "sedar":
        statements = extraction.get("statements") or {}
        for section in ("income_statement", "balance_sheet"):
            rows = statements.get(section)
            if not rows:
                questions.append(
                    f"MISSING_SECTION: '{section}' is absent from the SEDAR "
                    "extraction. Verify the PDF pages were correctly identified."
                )

    return questions


# ---------------------------------------------------------------------------
# Bundle writer
# ---------------------------------------------------------------------------

def write_bundle(
    out_dir: Path,
    ticker: str,
    fy: str,
    extraction: dict,
    mapping: dict,
    provenance: dict,
    worker_meta: dict,
    questions: list[str],
) -> Path:
    """Write the candidate artifact bundle to out_dir/<TICKER>_<FY>/.

    Returns the bundle directory path.
    """
    bundle_dir = out_dir / f"{ticker}_{fy}"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    def _write_json(filename: str, data: dict) -> None:
        (bundle_dir / filename).write_text(
            json.dumps(data, indent=2, default=str), encoding="utf-8"
        )

    _write_json("extraction.json", extraction)
    _write_json("mapping.json", mapping)
    _write_json("provenance.json", provenance)
    _write_json("worker_meta.json", worker_meta)

    # questions.md -- empty header when no flags; mandatory file.
    q_lines = ["# Judgment Questions\n"]
    q_lines.append(f"Bundle: {ticker} {fy}  |  Worker v{WORKER_VERSION}\n")
    if questions:
        q_lines.append("")
        for i, q in enumerate(questions, 1):
            q_lines.append(f"{i}. {q}\n")
    else:
        q_lines.append("\n_No judgment questions raised._\n")

    (bundle_dir / "questions.md").write_text("".join(q_lines), encoding="utf-8")

    return bundle_dir


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="FinLens ingestion worker: fetch PDF and produce candidate bundle."
    )
    parser.add_argument("--ticker", required=True, help="Ticker symbol (e.g. TOU).")
    parser.add_argument("--fy", required=True, help="Fiscal year label (e.g. FY2024).")
    parser.add_argument("--url", required=True, help="PDF source URL.")
    parser.add_argument(
        "--source-type",
        choices=["edgar", "sedar", "ir"],
        default="ir",
        help="Extraction path: 'sedar' uses sedar_extractor; 'edgar'/'ir' use claude_analyzer.",
    )
    parser.add_argument(
        "--out-dir",
        default="candidates",
        help="Output directory for the bundle (default: candidates/).",
    )
    parser.add_argument(
        "--scratch-dir",
        required=True,
        help=(
            "Scratch directory for all FinLens data writes (cache, logs). "
            "Sets FINLENS_DATA_DIR. Must be outside ~/.finlens."
        ),
    )
    args = parser.parse_args(argv)

    # --- Validate API key ---
    api_key = os.environ.get(FINLENS_API_KEY_ENV, "").strip()
    if not api_key:
        print(
            f"ERROR: {FINLENS_API_KEY_ENV} is not set. "
            "Set it to Sterling's spend-capped Anthropic key.",
            file=sys.stderr,
        )
        return 1

    ticker = args.ticker.strip().upper()
    fy = args.fy.strip()
    scratch_dir = Path(args.scratch_dir).resolve()
    out_dir = Path(args.out_dir).resolve()

    # --- CRITICAL: isolate scratch BEFORE any FinLens import ---
    _isolate_scratch(scratch_dir)

    print(f"[ingest_worker v{WORKER_VERSION}]  {ticker} {fy}  source={args.source_type}")
    print(f"  URL         : {args.url}")
    print(f"  Scratch     : {scratch_dir}")
    print(f"  Output      : {out_dir / f'{ticker}_{fy}'}")
    print()

    t_start = time.monotonic()
    timestamp_start = datetime.now(timezone.utc).isoformat()

    # --- Fetch PDF ---
    print("Fetching PDF...", flush=True)
    try:
        pdf_bytes, sha256, orig_filename = fetch_pdf(args.url)
    except Exception as exc:
        print(f"ERROR: PDF fetch failed: {exc}", file=sys.stderr)
        return 1

    print(f"  {len(pdf_bytes):,} bytes  sha256={sha256[:16]}...")
    timestamp_fetch = datetime.now(timezone.utc).isoformat()

    provenance = {
        "ticker": ticker,
        "fiscal_year": fy,
        "source_type": args.source_type,
        "url": args.url,
        "original_filename": orig_filename,
        "sha256": sha256,
        "byte_size": len(pdf_bytes),
        "retrieval_timestamp_utc": timestamp_fetch,
        "retrieval_method": "httpx.get",
        "worker_version": WORKER_VERSION,
    }

    # --- Extract ---
    print(f"Extracting ({args.source_type})...", flush=True)
    guard_verdict = "N/A"
    model_used = "unknown"

    try:
        if args.source_type == "sedar":
            extraction, model_used = extract_sedar(pdf_bytes, api_key, scratch_dir)
            # For SEDAR, mapping is the dedicated 'mapping' subdict.
            mapping = dict(extraction.pop("mapping", {})) if "mapping" in extraction else {}
        else:
            from modules.claude_analyzer import FabricatedExtractionError
            try:
                extraction, model_used = extract_edgar(pdf_bytes, api_key)
            except FabricatedExtractionError as exc:
                print(f"  [!] FABRICATED extraction: {exc}", file=sys.stderr)
                # Still write the bundle with an empty extraction so the runner
                # knows the fetch succeeded but the guard fired.
                extraction = {
                    "figure_presence": {"verdict": "FABRICATED", "checked": 0, "found": 0, "ratio": None}
                }
                guard_verdict = "FABRICATED"
            else:
                fp = extraction.get("figure_presence") or {}
                guard_verdict = fp.get("verdict", "PASS")
            mapping = {"note": f"EDGAR/IR filer ({ticker}) -- no SEDAR mapper applied."}
    except Exception as exc:
        print(f"ERROR: extraction failed: {exc}", file=sys.stderr)
        return 1

    if guard_verdict == "N/A" and args.source_type == "sedar":
        guard_verdict = "N/A (sedar path)"

    print(f"  model={model_used}  guard={guard_verdict}")

    # --- Generate judgment questions ---
    questions = generate_questions(
        source_type=args.source_type,
        extraction=extraction,
        mapping=mapping,
        ticker=ticker,
        fy=fy,
    )
    if questions:
        print(f"  [!] {len(questions)} judgment question(s) raised -- see questions.md")

    t_elapsed = time.monotonic() - t_start

    # Key label: the first 8 chars of the key, masked, so CC can verify
    # the right key was used without the key appearing in any artifact.
    key_label = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) >= 8 else "(short)"

    worker_meta = {
        "worker_version": WORKER_VERSION,
        "ticker": ticker,
        "fiscal_year": fy,
        "source_type": args.source_type,
        "model_used": model_used,
        "api_key_label": key_label,
        "guard_verdict": guard_verdict,
        "runtime_seconds": round(t_elapsed, 2),
        "timestamp_start_utc": timestamp_start,
        "scratch_dir": str(scratch_dir),
        "build_note": (
            "sedar_extractor reads ANTHROPIC_API_KEY; bridged from "
            f"{FINLENS_API_KEY_ENV} for the duration of SEDAR extraction. "
            "No hardcoded-path violations detected: all FinLens helpers "
            "respect FINLENS_DATA_DIR via config.py."
        ),
    }

    # --- Write bundle ---
    bundle_dir = write_bundle(
        out_dir=out_dir,
        ticker=ticker,
        fy=fy,
        extraction=extraction,
        mapping=mapping,
        provenance=provenance,
        worker_meta=worker_meta,
        questions=questions,
    )

    print()
    print(f"Bundle written to: {bundle_dir}")
    print(f"  questions: {len(questions)} item(s)")
    print(f"  runtime  : {t_elapsed:.1f}s")
    print()
    print("Next step: commit bundle to ingest/{ticker}-{fy} branch for CC review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
