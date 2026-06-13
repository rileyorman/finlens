from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sedar_extractor import extract_sedar_filing


PDF_PATHS = {
    "ATD": Path(r"C:\Users\riley\.finlens\sedar\filings\ATD_FY2025_annual_financials.pdf"),
    "CNR": Path(r"C:\Users\riley\.finlens\sedar\filings\CNR_FY2025_annual_financials.pdf.pdf"),
    "CSU": Path(r"C:\Users\riley\.finlens\sedar\filings\CSU_FY2025_annual_financials.pdf.pdf"),
    "REIUN": Path(r"C:\Users\riley\.finlens\sedar\filings\RioCan_FY2025_annual_financials.pdf.pdf"),
    "RY": Path(r"C:\Users\riley\.finlens\sedar\filings\RY_FY2025_annual_financials.pdf.pdf"),
    "SHOP": Path(r"C:\Users\riley\.finlens\sedar\filings\SHOP_FY2025_annual_financials.pdf"),
}

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures"


def _output_path(ticker: str) -> Path:
    return FIXTURE_DIR / f"{ticker}_FY2025_sedar.json.NEW"


def main() -> int:
    rows = []

    for ticker, pdf_path in PDF_PATHS.items():
        try:
            result = extract_sedar_filing(pdf_path)
            output_path = _output_path(ticker)
            output_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
            rows.append(
                {
                    "ticker": ticker,
                    "schema_version": result.get("schema_version"),
                    "filing_date": result.get("filing_date") or "NULL",
                }
            )
        except Exception as exc:
            print(f"{ticker}: {type(exc).__name__}: {exc}")
            rows.append(
                {
                    "ticker": ticker,
                    "schema_version": "ERROR",
                    "filing_date": "NULL",
                }
            )

    print("ticker | schema_version | filing_date")
    print("--- | --- | ---")
    for row in rows:
        print(f"{row['ticker']} | {row['schema_version']} | {row['filing_date']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
