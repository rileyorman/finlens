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
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .log import read_log, _DEFAULT_LOG, get_last_read_log_diagnostics
from .cross_validate import FMP_PREMIUM_BLOCKED


LOW_SAMPLE_THRESHOLD = 10
HIGH_FIRE_RATE_PCT   = 30       # flag a rule if this % of its runs are failures

# Rules where the observed_value is a ratio / growth rate worth plotting.
# Ordered as they appear in rules.py so the report reads top-to-bottom.
DISTRIBUTION_RULES = [
    "gross_margin_range",
    "net_margin_ceiling",
    "revenue_growth_sanity",
]
FLAG_SEVERITIES = ("hard", "soft", "unclassified")
CX_TRIAGE_STATUSES = ("CONFLICT", "GEMINI_MISSING")


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


def _fmt_bn(v: float | None) -> str:
    """Format a raw-USD value as T/B/M/K for the report."""
    if v is None:
        return "n/a"
    if abs(v) >= 1e12:
        return f"${v / 1e12:.2f}T"
    if abs(v) >= 1e9:
        return f"${v / 1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"${v / 1e6:.1f}M"
    return f"${v:,.0f}"


def _fmt_cv_fmp_status(rec: dict) -> str:
    if rec.get("fmp_fetch_success"):
        return "available"
    if rec.get("fmp_fetch_reason") == FMP_PREMIUM_BLOCKED:
        return "unavailable at current FMP tier"
    return "transient failure"


def _section_divergence(cv_records: list[dict]) -> str:
    if not cv_records:
        return (
            "  No cross-validation runs recorded yet.\n"
            "  Trigger a cross-validation check from the FinLens UI ($)\n"
            "  to compare FinLens EDGAR values against FMP."
        )

    lines: list[str] = []

    # --- Summary table ---
    lines += [
        f"  {'ticker':<6}  {'fiscal_year':<11}  {'overall_status':<22}  {'fmp_status':<32}",
        f"  {'-'*6}  {'-'*11}  {'-'*22}  {'-'*32}",
    ]
    for rec in sorted(cv_records, key=lambda r: (r.get("ticker", ""), r.get("fiscal_year", ""))):
        fmp_status = _fmt_cv_fmp_status(rec)
        lines.append(
            f"  {rec.get('ticker', '?'):<6}  "
            f"{rec.get('fiscal_year', '?'):<11}  "
            f"{rec.get('overall_status', '?'):<22}  "
            f"{fmp_status:<32}"
        )

    # --- Per-field breakdown ---
    lines += [
        "",
        "  Per-field breakdown:",
        f"  {'ticker':<5}  {'year':<6}  {'field':<22}  "
        f"{'finlens':>14}  {'fmp':>14}  {'diff%':>7}  status",
        f"  {'-'*5}  {'-'*6}  {'-'*22}  "
        f"{'-'*14}  {'-'*14}  {'-'*7}  {'-'*18}",
    ]
    for rec in sorted(cv_records, key=lambda r: (r.get("ticker", ""), r.get("fiscal_year", ""))):
        ticker = rec.get("ticker", "?")
        fy     = str(rec.get("fiscal_year", "?"))[-6:]
        for fld in rec.get("cv_fields", []):
            fl_v    = fld.get("finlens_value")
            fm_v    = fld.get("fmp_value")
            pct     = fld.get("pct_diff")
            fl_str  = _fmt_bn(fl_v)
            fm_str  = _fmt_bn(fm_v)
            pct_str = f"{pct:.1f}%" if pct is not None else "n/a"
            status  = fld.get("status", "?")
            flag    = " [!]" if status in ("DISAGREE", "MINOR_DIVERGENCE") else "    "
            lines.append(
                f"  {ticker:<5}  {fy:<6}  {fld.get('field', '?'):<22}  "
                f"{fl_str:>14}  {fm_str:>14}  {pct_str:>7}  {status}{flag}"
            )

    # --- Flags ---
    disagree = [
        f"{r.get('ticker')} {fld.get('field')}"
        for r in cv_records
        for fld in r.get("cv_fields", [])
        if fld.get("status") == "DISAGREE"
    ]
    minor = [
        f"{r.get('ticker')} {fld.get('field')}"
        for r in cv_records
        for fld in r.get("cv_fields", [])
        if fld.get("status") == "MINOR_DIVERGENCE"
    ]
    premium_blocked = [
        f"{r.get('ticker')} {r.get('fiscal_year')}"
        for r in cv_records
        if r.get("fmp_fetch_reason") == FMP_PREMIUM_BLOCKED
    ]
    unmatched = [
        f"{r.get('ticker')} {fld.get('field')}"
        for r in cv_records
        for fld in r.get("cv_fields", [])
        if fld.get("status") == "UNMATCHED"
    ]

    lines.append("")
    if disagree:
        lines.append(f"  [!] Disagreements (>10%)    : {_trunc(disagree)}")
    if minor:
        lines.append(f"  Minor divergences (2-10%)   : {_trunc(minor)}")
    if premium_blocked:
        lines.append(
            f"  Corroboration unavailable at current FMP tier: {_trunc(premium_blocked)}"
        )
    if unmatched:
        lines.append(f"  Unmatched (no FMP period)   : {_trunc(unmatched)}")
    if not disagree and not minor and not unmatched:
        lines.append("  All compared fields agree (<2% divergence).")

    return "\n".join(lines)


def _cx_checker_version_label(record: dict) -> str:
    return str(record.get("checker_version") or "1")


def _cx_checker_version(record: dict) -> int:
    raw = record.get("checker_version")
    if raw in (None, ""):
        return 1
    try:
        return int(str(raw))
    except ValueError:
        return 1


def _cx_is_definitive(record: dict) -> bool:
    return record.get("state") != "UNCHECKED"


def _cx_latest_sort_key(record: dict) -> tuple[int, str]:
    return (_cx_checker_version(record), str(record.get("timestamp") or ""))


def _cx_latest_records(records: list[dict]) -> list[dict]:
    latest_definitive: dict[str, dict] = {}
    retained: list[dict] = []
    for idx, record in enumerate(records):
        if not _cx_is_definitive(record):
            retained.append(record)
            continue

        accession = str(record.get("filing_accession") or "")
        key = accession if accession else f"__missing_accession_{idx}"
        current = latest_definitive.get(key)
        if current is None or _cx_latest_sort_key(record) > _cx_latest_sort_key(current):
            latest_definitive[key] = record

    selected = retained + list(latest_definitive.values())
    return sorted(selected, key=lambda r: str(r.get("timestamp") or ""), reverse=True)


def _cx_field_severity(field: dict) -> str:
    severity = field.get("severity")
    return severity if severity in ("hard", "soft") else "unclassified"


def _cx_record_flagged_severity(record: dict) -> str:
    severities = [
        _cx_field_severity(field)
        for field in record.get("cross_extractor_fields", [])
        if field.get("status") == "CONFLICT"
    ]
    if "hard" in severities:
        return "hard"
    if "soft" in severities:
        return "soft"
    return "unclassified"


def _cx_flagged_label(record: dict) -> str:
    ticker = record.get("ticker", "?")
    fiscal_year = record.get("fiscal_year", "?")
    return f"{ticker} {fiscal_year} ({_cx_record_flagged_severity(record)})"


def _cx_disposition_key(record: dict, field: dict | None = None) -> tuple[str, str, str]:
    field_name = (
        str(field.get("canonical_field") or "")
        if field is not None
        else str(record.get("field") or "")
    )
    return (
        str(record.get("filing_accession") or ""),
        field_name,
        _cx_checker_version_label(record),
    )


def _cx_latest_dispositions(dispositions: list[dict]) -> dict[tuple[str, str, str], dict]:
    latest: dict[tuple[str, str, str], dict] = {}
    for record in dispositions:
        key = _cx_disposition_key(record)
        if not all(key):
            continue
        current = latest.get(key)
        if current is None or str(record.get("timestamp") or "") > str(current.get("timestamp") or ""):
            latest[key] = record
    return latest


def _cx_triage_targets(records: list[dict]) -> list[tuple[dict, dict]]:
    targets: list[tuple[dict, dict]] = []
    for record in records:
        if record.get("state") not in ("FLAGGED", "PARTIAL"):
            continue
        for field in record.get("cross_extractor_fields", []):
            if field.get("status") in CX_TRIAGE_STATUSES:
                targets.append((record, field))
    return targets


def _cx_fmt_value(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _cx_clip(value: object, cap: int = 64) -> str:
    text = str(value if value is not None else "")
    return text if len(text) <= cap else text[: cap - 4] + " ..."


def _cx_disposition_text(disposition: dict | None) -> str:
    if not disposition:
        return "OPEN"
    return f"DISPOSITIONED {disposition.get('disposition', '?')} - {_cx_clip(disposition.get('rationale'), 72)}"


def _cx_version_sort(version: str) -> tuple[int, str]:
    try:
        return (int(version), version)
    except ValueError:
        return (1, version)


def _cx_version_summary(records: list[dict]) -> list[str]:
    version_states: dict[str, Counter] = defaultdict(Counter)
    version_models: dict[str, Counter] = defaultdict(Counter)
    legacy_without_key = 0
    for record in records:
        version = _cx_checker_version_label(record)
        version_states[version][record.get("state", "UNKNOWN")] += 1
        version_models[version][record.get("model") or "unknown"] += 1
        if record.get("checker_version") in (None, ""):
            legacy_without_key += 1

    lines = ["  Agreement records by checker_version:"]
    if not version_states:
        lines.append("    (none)")
        return lines

    for version in sorted(version_states, key=_cx_version_sort):
        state_text = ", ".join(
            f"{state}={count}" for state, count in sorted(version_states[version].items())
        )
        model_text = ", ".join(
            f"{model}={count}" for model, count in sorted(version_models[version].items())
        )
        lines.append(f"    v{version}: {sum(version_states[version].values())} record(s); {state_text}; models: {model_text}")
    lines.append(f"  Legacy agreements without checker_version: {legacy_without_key}")
    return lines


def _section_cross_extractor(
    records: list[dict],
    dispositions: list[dict],
    total_records_parsed: int,
    unparseable_lines: int,
) -> str:
    lines = [
        "  Log parse check:",
        f"    Parsed records          : {total_records_parsed}",
        f"    Unparseable JSON lines  : {unparseable_lines}",
    ]

    if not records:
        lines += [
            "",
            "  No Gemini second-extractor runs recorded yet.",
            "  Run scripts/run_cross_extractor.py manually for campaign filers ($).",
        ]
        return "\n".join(lines)

    lines += [""] + _cx_version_summary(records)
    latest_records = _cx_latest_records(records)
    latest_dispositions = _cx_latest_dispositions(dispositions)

    state_counts: dict[str, int] = defaultdict(int)
    for rec in latest_records:
        state = rec.get("state", "UNKNOWN")
        state_counts[state] += 1

    flagged_severity_counts: dict[str, int] = defaultdict(int)
    for rec in latest_records:
        if rec.get("state") == "FLAGGED":
            flagged_severity_counts[_cx_record_flagged_severity(rec)] += 1

    lines += ["", "  Latest definitive/accession view by state:"]
    total = len(latest_records)
    for state in ("VERIFIED", "PARTIAL", "FLAGGED", "UNCHECKED"):
        cnt = state_counts.get(state, 0)
        line = (
            f"    {state:<10}  :  {cnt:3d}  ({_pct(cnt, total)})  {_bar(cnt, total)}"
        )
        if state == "FLAGGED":
            severity_text = " / ".join(
                f"{flagged_severity_counts.get(severity, 0)} {severity}"
                for severity in FLAG_SEVERITIES
            )
            line += f"  ({severity_text})"
        lines.append(line)

    flagged = [
        _cx_flagged_label(r)
        for r in latest_records
        if r.get("state") == "FLAGGED"
    ]
    unchecked_reasons: dict[str, int] = defaultdict(int)
    for rec in latest_records:
        if rec.get("state") == "UNCHECKED":
            unchecked_reasons[rec.get("reason") or "unknown"] += 1

    lines.append("")
    lines.append(
        f"  [!] Flagged filings       : {_trunc(flagged) if flagged else '(none)'}"
    )
    if unchecked_reasons:
        reason_text = ", ".join(
            f"{reason}={count}" for reason, count in sorted(unchecked_reasons.items())
        )
        lines.append(f"  Unchecked reasons       : {reason_text}")

    triage_targets = _cx_triage_targets(latest_records)
    open_targets = [
        (record, field)
        for record, field in triage_targets
        if _cx_disposition_key(record, field) not in latest_dispositions
    ]
    lines += [
        "",
        "  Triage status:",
        f"    Disposition records    : {len(dispositions)}",
        f"    Triage target fields   : {len(triage_targets)}",
        f"    Open triage targets    : {len(open_targets)}",
    ]

    if triage_targets:
        lines += [
            "",
            f"  {'ticker':<6}  {'year':<8}  {'ver':<4}  {'field':<26}  {'status':<14}  triage",
            f"  {'-'*6}  {'-'*8}  {'-'*4}  {'-'*26}  {'-'*14}  {'-'*48}",
        ]
        for record, field in triage_targets:
            disposition = latest_dispositions.get(_cx_disposition_key(record, field))
            lines.append(
                f"  {record.get('ticker', '?'):<6}  "
                f"{str(record.get('fiscal_year', '?')):<8}  "
                f"v{_cx_checker_version_label(record):<3}  "
                f"{_cx_clip(field.get('canonical_field'), 26):<26}  "
                f"{field.get('status', '?'):<14}  "
                f"{_cx_disposition_text(disposition)}"
            )

    conflict_targets = [
        (record, field)
        for record, field in triage_targets
        if field.get("status") == "CONFLICT"
    ]
    if conflict_targets:
        lines += ["", "  Per-CONFLICT details:"]
        for record, field in conflict_targets:
            disposition = latest_dispositions.get(_cx_disposition_key(record, field))
            lines.append(
                f"    {record.get('ticker', '?')} {record.get('fiscal_year', '?')} "
                f"v{_cx_checker_version_label(record)} "
                f"{field.get('canonical_field', '?')} "
                f"severity={_cx_field_severity(field)} "
                f"triage={_cx_disposition_text(disposition)}"
            )
            lines.append(
                f"      values: FinLens={_cx_fmt_value(field.get('finlens_value'))} "
                f"Gemini={_cx_fmt_value(field.get('gemini_value'))}"
            )
            lines.append(f"      FinLens label: {_cx_clip(field.get('finlens_label'), 96)}")
            lines.append(f"      Gemini label : {_cx_clip(field.get('gemini_label'), 96)}")
    return "\n".join(lines)


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
    all_records = read_log(log_path)
    diagnostics = get_last_read_log_diagnostics()

    # Split by record type.  Existing integrity records have no record_type field;
    # cross-validation and cross-extractor records are tagged explicitly.
    integrity_records = [
        r for r in all_records
        if r.get("record_type", "integrity") == "integrity"
    ]
    cv_records = [
        r for r in all_records
        if r.get("record_type") == "cross_validation"
    ]
    cx_records = [
        r for r in all_records
        if r.get("record_type") == "cross_extractor_agreement"
    ]
    cx_disposition_records = [
        r for r in all_records
        if r.get("record_type") == "cross_extractor_disposition"
    ]

    n = len(integrity_records)

    now_utc    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
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
        f"  Log lines : {diagnostics.physical_lines}",
        f"  Parsed    : {diagnostics.records_parsed} record(s)",
        f"  Unparseable JSON lines: {diagnostics.unparseable_lines}",
        SEP,
    ]

    if not all_records:
        out += [
            "",
            "  Log is empty.  Run some EDGAR analyses to populate it.",
            "",
            SEP,
        ]
        return "\n".join(out)

    if n < LOW_SAMPLE_THRESHOLD and n > 0:
        out += [
            "",
            f"  NOTE: Only {n} integrity filing{'s' if n != 1 else ''} in log "
            f"(fewer than {LOW_SAMPLE_THRESHOLD}).",
            "  Patterns are not yet meaningful -- accumulate more filings",
            "  before drawing conclusions about threshold calibration.",
        ]

    # 1. Summary
    out += ["", THIN, "  1. SUMMARY", THIN, ""]
    out.append(_section_summary(integrity_records, n) if n else "  No integrity records yet.")

    # 2. By sector
    out += ["", THIN, "  2. BY SECTOR", THIN, ""]
    out.append(_section_by_sector(integrity_records) if n else "  No integrity records yet.")

    # 3. By rule
    out += [THIN, "  3. BY RULE", THIN, ""]
    out.append(_section_by_rule(integrity_records, n) if n else "  No integrity records yet.")

    # 4. Distributions
    out += ["", THIN, "  4. OBSERVED-VALUE DISTRIBUTIONS", THIN, ""]
    out.append(_section_distributions(integrity_records) if n else "  No integrity records yet.")

    # 5. Cross-validation divergences
    out += [THIN, "  5. CROSS-VALIDATION DIVERGENCES", THIN, ""]
    out.append(_section_divergence(cv_records))

    # 6. Gemini second-extractor signal
    out += [THIN, "  6. GEMINI SECOND-EXTRACTOR SIGNAL", THIN, ""]
    out.append(
        _section_cross_extractor(
            cx_records,
            cx_disposition_records,
            diagnostics.records_parsed,
            diagnostics.unparseable_lines,
        )
    )

    # Footer
    out += ["", SEP, "  END OF REPORT", SEP]

    return "\n".join(out)


def main() -> None:
    log_path = sys.argv[1] if len(sys.argv) > 1 else None
    print(analyze_log(log_path))


if __name__ == "__main__":
    main()
