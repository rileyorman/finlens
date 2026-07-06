"""One-shot regression evidence for the OVERRIDE switchover.

Prints, for each of the six campaign SEDAR fixtures, the mapped output the
live mapper produces with sector=None — which must equal the pre-OVERRIDE
output (no sector profile ever resolved in production for these fixtures).
Then prints RY's mapped output with sector="Financial Services" to prove
the trap is defused (default revenue + net_income survive).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.integrity.sedar_mapper import map_line_items


FIXTURES = ["CSU", "CNR", "RY", "REIUN", "SHOP", "ATD"]
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures"


def _line_items(data: dict) -> list[dict]:
    rows = []
    for item in data["statements"]["income_statement"]:
        values = item.get("values") or {}
        rows.append({
            "label": item["label"],
            "value": next(iter(values.values()), None),
            "confidence": item.get("confidence"),
        })
    return rows


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{name}_FY2025_sedar.json").read_text(encoding="utf-8"))


def _summary(mapped: dict) -> dict:
    out = {}
    for k, v in mapped.items():
        out[k] = {"value": v.get("value"), "source_label": v.get("source_label"), "derived": v.get("derived", False)}
    return out


print("=" * 70)
print("6-FILER REGRESSION — sector=None (production state)")
print("=" * 70)
for ticker in FIXTURES:
    data = _load(ticker)
    result = map_line_items(_line_items(data), data["accounting_standard"], sector=None)
    meta = result["meta"]
    print(f"\n{ticker} ({data['accounting_standard']}): "
          f"mapped_count={meta['mapped_count']}, "
          f"sector_profile={meta['sector_profile']}, "
          f"gross_profit_derived={meta['gross_profit_derived']}")
    for field, info in _summary(result["mapped"]).items():
        tag = " (derived)" if info["derived"] else ""
        print(f"  {field}{tag}: {info['value']} <- '{info['source_label']}'")

print()
print("=" * 70)
print("RY TRAP DEFUSAL — sector='Financial Services'")
print("=" * 70)
data = _load("RY")
result = map_line_items(_line_items(data), data["accounting_standard"], sector="Financial Services")
meta = result["meta"]
print(f"\nRY: mapped_count={meta['mapped_count']}, sector_profile={meta['sector_profile']}")
for field, info in _summary(result["mapped"]).items():
    print(f"  {field}: {info['value']} <- '{info['source_label']}'")

print()
print("Defaults preserved?")
print(f"  revenue       = 66605?  {result['mapped'].get('revenue', {}).get('value') == 66605}")
print(f"  net_income    = 20369?  {result['mapped'].get('net_income', {}).get('value') == 20369}")
print("  Sector adds present?")
print(f"  net_interest_income          = 33000? "
      f"{result['mapped'].get('net_interest_income', {}).get('value') == 33000}")
print(f"  provision_for_credit_losses  = 4362?  "
      f"{result['mapped'].get('provision_for_credit_losses', {}).get('value') == 4362}")
print(f"  total_revenue_bank suppressed by first-write-wins? "
      f"{'total_revenue_bank' not in result['mapped']}")
