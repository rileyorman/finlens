"""
FinLens Data Integrity Engine -- Log Analysis Tool
====================================================
Reads ~/.finlens/integrity_log.jsonl and produces a plain-text report
summarising patterns across all logged validation runs.

Runs on demand -- it never writes to or mutates the log.

Usage
-----
    python -m modules.integrity.analyze
    python -m modules.integrity.analyze /path/to/custom.jsonl

Programmatic
    from modules.integrity.analyze import analyze_log
    print(analyze_log())
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .log import read_log, _DEFAULT_LOG


LOW_SAMPLE_THRESHOLD = 10
HIGH_FIRE_RATE_PCT   = 30       # flag a rule if this % of its runs are failures

# Rules where the observed_value is a ratio / growth rate worth plotting.
# Ordered as they appear in rules.py so the report reads top-to-bottom.
DISTRIBUTION_RULES = [
    "gross_margin_range",
    "net_margin_ceiling",
    "revenue_growth_sanity",
]


# ---------------------------------------------------------------------------
# Small helpers -- all output is pure ASCII
# ---------------------------------------------------------------------------

def _pct(n: int, total: int) -> str:
    return f"{n / total * 100:5.1f}%" if total else "   n/a"


def _bar(n: int, total: int, width: int = 16) -> str:
    if not total:
        return " " * width
    filled = round(n / total * width)
    return "#" * filled + "." * (width - filled)


def _date(ts: str) -> str:
    return ts[:10] if ts else "?"


def _trunc(items: list[str], cap: int = 6) -> str:
    if len(items) <= cap:
        return ", ".join(items)
    return ", ".join(items[:cap]) + f" ... (+{len(items) - cap} more)"


def _fmt_ratio(v: float) -> str:
    return f"{v * 100:.1f}%"


def _fmt_growth(v: float) -> str:
    return f"{v * 100:+.1f}%"


def _fmt_val(v: float, rule_id: str) -> str:
    if "growth" in rule_id:
        return _fmt_growth(v)
    return _fmt_ratio(v)


# ---------------------------------------------------------------------------
# Per-rule statistics aggregated from log records
# ---------------------------------------------------------------------------

def _all_rule_ids(records: list[dict]) -> list[str]:
    """Return rule IDs in first-seen order across all records."""
    seen: list[str] = []
    for rec in records:
        for c in rec.get("checks", []):
            rid = c.get("rule_id", "")
            if rid and rid not in seen:
                seen.append(rid)
    return seen


def _rule_stats(rule_id: str, records: list[dict]) -> dict:
    """Aggregate check outcomes for one rule across all records."""
    ran = passed = failed = skipped_sector = skipped_field = skipped_other = 0
    values: list[float] = []
    thresholds: dict = {}

    for rec in records:
        for c in rec.get("checks", []):
            if c.get("rule_id") != rule_id:
                continue
            if c.get("skipped"):
                sr = (c.get("skip_reason") or "").lower()
                if "sector" in sr:
                    skipped_sector += 1
                elif "field" in sr:
                    skipped_field += 1
                else:
                    skipped_other += 1
            else:
                ran += 1
                if c.get("passed"):
                    passed += 1
                else:
                    failed += 1
                v = c.get("observed_value")
                if v is not None:
                    values.append(float(v))
                if not thresholds and c.get("threshold"):
                    thresholds = c["threshold"]

    return {
        "ran": ran, "passed": passed, "failed": failed,
        "skipped_sector": skipped_sector,
        "skipped_field":  skipped_field,
        "skipped_other":  skipped_other,
        "values": values,
        "thresholds": thresholds,
    }


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------

def _section_summary(records: list[dict], n: int) -> str:
    status_counts: dict[str, int] = defaultdict(int)
    for rec in records:
        status_counts[rec.get("overall_status", "unknown")] += 1

    tss = [rec.get("timestamp", "") for rec in records if rec.get("timestamp")]
    date_min = _date(min(tss)) if tss else "?"
    date_max = _date(max(tss)) if tss else "?"

    lines = [
        f"  Total filings logged   :  {n}",
        f"  Date range             :  {date_min}  to  {date_max}",
        "",
        "  By status:",
    ]
    for status in ("clean", "warnings", "info_only", "unknown"):
        cnt = status_counts.get(status, 0)
        lines.append(
            f"    {status:<12}  :  {cnt:3d}  ({_pct(cnt, n)})  {_bar(cnt, n)}"
        )
    return "\n".join(lines)


def _section_by_sector(records: list[dict]) -> str:
    by_sector: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        key = rec.get("sector") or "(unknown sector)"
        by_sector[key].append(rec)

    lines: list[str] = []
    for sector, recs in sorted(by_sector.items()):
        filing_labels = [
            f"{r.get('ticker','?')} {r.get('fiscal_year','?')}" for r in recs
        ]
        lines.append(
            f"  {sector}  ({len(recs)} filing{'s' if len(recs) != 1 else ''}:  "
            f"{_trunc(filing_labels)})"
        )

        # Aggregate checks for this sector
        rule_ran:   dict[str, int] = defaultdict(int)
        rule_pass:  dict[str, int] = defaultdict(int)
        rule_fail:  dict[str, int] = defaultdict(int)
        skip_sect:  dict[str, int] = defaultdict(int)
        skip_field: dict[str, int] = defaultdict(int)

        for rec in recs:
            for c in rec.get("checks", []):
                rid = c.get("rule_id", "")
                if c.get("skipped"):
                    sr = (c.get("skip_reason") or "").lower()
                    if "sector" in sr:
                        skip_sect[rid] += 1
                    else:
                        skip_field[rid] += 1
                else:
                    rule_ran[rid] += 1
                    if c.get("passed"):
                        rule_pass[rid] += 1
                    else:
                        rule_fail[rid] += 1

        total_ran  = sum(rule_ran.values())
        total_pass = sum(rule_pass.values())
        total_fail = sum(rule_fail.values())

        if total_ran:
            lines.append(
                f"    Rules ran     : {total_ran} check{'s' if total_ran != 1 else ''} -- "
                f"{total_pass} passed, {total_fail} failed"
            )
            lines.append(f"    Rule IDs      : {', '.join(sorted(rule_ran))}")

        if skip_sect:
            names = sorted(skip_sect)
            total_ss = sum(skip_sect.values())
            lines.append(
                f"    Sector-skipped: {total_ss} check{'s' if total_ss != 1 else ''} "
                f"(sector_excluded) -- {', '.join(names)}"
            )
        if skip_field:
            names = sorted(skip_field)
            total_sf = sum(skip_field.values())
            lines.append(
                f"    Field-skipped : {total_sf} check{'s' if total_sf != 1 else ''} "
                f"(field_unavailable) -- {', '.join(names)}"
            )
        if total_fail:
            bad = sorted(r for r, cnt in rule_fail.items() if cnt > 0)
            lines.append(f"    [!] Failures  : {', '.join(bad)}")

        lines.append("")

    return "\n".join(lines)


def _section_by_rule(records: list[dict], n: int) -> str:
    rule_ids = _all_rule_ids(records)
    if not rule_ids:
        return "  No rule data found.\n"

    col = 30
    lines = [
        f"  {'rule_id':<{col}}  {'ran':>4}  {'pass':>4}  {'fail':>4}  "
        f"{'skip':>5}  (sect / field)",
        f"  {'-'*col}  {'-'*4}  {'-'*4}  {'-'*4}  {'-'*5}  {'-'*13}",
    ]

    never_warned: list[str] = []
    high_fire_rate: list[tuple[str, float]] = []

    for rid in rule_ids:
        st = _rule_stats(rid, records)
        ran, passed, failed = st["ran"], st["passed"], st["failed"]
        ss, sf, so = st["skipped_sector"], st["skipped_field"], st["skipped_other"]
        total_skip = ss + sf + so
        lines.append(
            f"  {rid:<{col}}  {ran:>4}  {passed:>4}  {failed:>4}  "
            f"{total_skip:>5}  ({ss} / {sf})"
        )
        if ran >= 1 and failed == 0:
            never_warned.append(rid)
        if ran >= 1 and (failed / ran * 100) >= HIGH_FIRE_RATE_PCT:
            high_fire_rate.append((rid, failed / ran * 100))

    lines.append("")
    lines.append("  Flags:")

    if never_warned:
        lines.append(
            "    Never warned (0 failures -- candidate: threshold too loose, or untested):"
        )
        for rid in never_warned:
            lines.append(f"      {rid}")
        if n < LOW_SAMPLE_THRESHOLD:
            lines.append(
                f"    Note: with only {n} filings, 0 failures is expected -- "
                f"not a tuning signal yet."
            )
    else:
        lines.append("    Never warned: (none -- all rules have fired at least once)")

    if high_fire_rate:
        lines.append(
            f"    High fire rate (>= {HIGH_FIRE_RATE_PCT}% failures -- "
            f"candidate: too strict or sector-blind):"
        )
        for rid, pct in high_fire_rate:
            lines.append(f"      {rid}  ({pct:.0f}% of runs failed)")
    else:
        lines.append(
            f"    High fire rate (>= {HIGH_FIRE_RATE_PCT}%): (none)"
        )

    return "\n".join(lines)


def _section_distributions(records: list[dict]) -> str:
    lines: list[str] = []
    for rid in DISTRIBUTION_RULES:
        st = _rule_stats(rid, records)
        values = st["values"]
        thresholds = st["thresholds"]

        is_growth = "growth" in rid
        fmt = _fmt_growth if is_growth else _fmt_ratio
        unit = "ratio YoY" if is_growth else "ratio 0-1"

        lines.append(f"  {rid}  ({unit})")

        if not values:
            lines.append(
                "    No observations (rule may have been skipped for all filings in log)."
            )
            lines.append("")
            continue

        n      = len(values)
        min_v  = min(values)
        max_v  = max(values)
        mean_v = sum(values) / n

        lines.append(
            f"    n={n}   min={fmt(min_v)}   max={fmt(max_v)}   mean={fmt(mean_v)}"
        )

        # Threshold display
        thresh_min = thresholds.get("min")
        thresh_max = thresholds.get("max")
        parts: list[str] = []
        if thresh_min is not None:
            parts.append(f"floor={fmt(thresh_min)}")
        if thresh_max is not None:
            parts.append(f"ceiling={fmt(thresh_max)}")
        if parts:
            lines.append(f"    threshold: {', '.join(parts)}")

        # Headroom commentary
        if thresh_max is not None:
            headroom = thresh_max - max_v
            if headroom < 0:
                lines.append(
                    f"    [!] Max observation {fmt(max_v)} EXCEEDS ceiling {fmt(thresh_max)} "
                    f"-- this should have flagged"
                )
            else:
                lines.append(
                    f"    Headroom to ceiling : {fmt(headroom)} "
                    f"(closest obs {fmt(max_v)})"
                )
        if thresh_min is not None:
            headroom_floor = min_v - thresh_min
            if headroom_floor < 0:
                lines.append(
                    f"    [!] Min observation {fmt(min_v)} BELOW floor {fmt(thresh_min)} "
                    f"-- this should have flagged"
                )
            else:
                lines.append(
                    f"    Headroom above floor: {fmt(headroom_floor)} "
                    f"(closest obs {fmt(min_v)})"
                )
        lines.append("")

    return "\n".join(lines)


def _section_divergence_stub() -> str:
    return (
        "  [STUB -- cross-validation data not yet collected]\n"
        "\n"
        "  This section will compare FinLens EDGAR values against a second\n"
        "  source (FMP) for the same ticker/period and flag divergences > 5%.\n"
        "\n"
        "  When cross-validation is wired, each log record will gain:\n"
        "    fmp_revenue, fmp_gross_profit, fmp_net_income\n"
        "    finlens_revenue, finlens_gross_profit, finlens_net_income\n"
        "    revenue_divergence_pct, gross_profit_divergence_pct\n"
        "\n"
        "  Patterns this section will surface:\n"
        "    - Tickers where FinLens and FMP consistently disagree\n"
        "    - Sectors with systematic divergence\n"
        "      (e.g. banks: interest income concept vs revenue concept)\n"
        "    - Cases where integrity rules pass but cross-source values differ\n"
        "      significantly (silent normalization mismatch)"
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyze_log(log_path: Path | str | None = None) -> str:
    """
    Read the integrity log and return a plain-text report.

    Parameters
    ----------
    log_path  Override the default log path.  None uses ~/.finlens/integrity_log.jsonl.
    """
    records = read_log(log_path)
    n = len(records)

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    path_label = str(Path(log_path) if log_path else _DEFAULT_LOG)

    SEP  = "=" * 70
    THIN = "-" * 70

    out: list[str] = []

    # Header
    out += [
        SEP,
        "  FINLENS DATA INTEGRITY LOG REPORT",
        f"  Generated : {now_utc}",
        f"  Log file  : {path_label}",
        SEP,
    ]

    if n == 0:
        out += [
            "",
            "  Log is empty.  Run some EDGAR analyses to populate it.",
            "",
            SEP,
        ]
        return "\n".join(out)

    if n < LOW_SAMPLE_THRESHOLD:
        out += [
            "",
            f"  NOTE: Only {n} filing{'s' if n != 1 else ''} in log "
            f"(fewer than {LOW_SAMPLE_THRESHOLD}).",
            "  Patterns are not yet meaningful -- accumulate more filings",
            "  before drawing conclusions about threshold calibration.",
        ]

    # 1. Summary
    out += ["", THIN, "  1. SUMMARY", THIN, ""]
    out.append(_section_summary(records, n))

    # 2. By sector
    out += ["", THIN, "  2. BY SECTOR", THIN, ""]
    out.append(_section_by_sector(records))

    # 3. By rule
    out += [THIN, "  3. BY RULE", THIN, ""]
    out.append(_section_by_rule(records, n))

    # 4. Distributions
    out += ["", THIN, "  4. OBSERVED-VALUE DISTRIBUTIONS", THIN, ""]
    out.append(_section_distributions(records))

    # 5. Divergence stub
    out += [THIN, "  5. CROSS-VALIDATION DIVERGENCES", THIN, ""]
    out.append(_section_divergence_stub())

    # Footer
    out += ["", SEP, "  END OF REPORT", SEP]

    return "\n".join(out)


def main() -> None:
    log_path = sys.argv[1] if len(sys.argv) > 1 else None
    print(analyze_log(log_path))


if __name__ == "__main__":
    main()
