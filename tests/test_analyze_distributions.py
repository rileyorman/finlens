"""
Tests for _section_distributions in modules/integrity/analyze.py.

Covers the three required cases from the Sunday 2026-07-05 audit fix:
  1. Breach from a FAILED check  -> "all flagged (rule working)", no false alarm.
  2. Breach from a PASSED check  -> rule-bug alarm line.
  3. No breach                   -> headroom lines unchanged.

Tests call _section_distributions directly with small in-memory record dicts
that match the shape _rule_stats reads:
  records -> list of dicts, each with a "checks" list whose items have:
    rule_id, passed, observed_value, threshold (optional skipped key absent here).
"""
from modules.integrity.analyze import _section_distributions

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_records(rule_id, observations, threshold=None):
    """
    Build a minimal list of integrity records for testing _section_distributions.

    Parameters
    ----------
    rule_id      : str   -- must be one of DISTRIBUTION_RULES.
    observations : list of (value: float, passed: bool) tuples.
    threshold    : dict  -- e.g. {"min": -1.0, "max": 1.0}; omit for no threshold.
    """
    checks = []
    for value, check_passed in observations:
        check = {
            "rule_id": rule_id,
            "passed": check_passed,
            "observed_value": value,
        }
        if threshold is not None:
            check["threshold"] = threshold
        checks.append(check)
    return [{"checks": checks}]


# ---------------------------------------------------------------------------
# Case 1: breach from a FAILED check (rule working correctly)
# ---------------------------------------------------------------------------

def test_ceiling_breach_that_flagged():
    """Ceiling exceeded but the check FAILED -- rule caught it; say 'all flagged'."""
    records = _make_records(
        "revenue_growth_sanity",
        [(3.5, False)],  # +350% YoY growth; check failed (correctly flagged)
        threshold={"min": -1.0, "max": 1.0},
    )
    report = _section_distributions(records)
    assert "all flagged" in report
    assert "should have flagged" not in report
    assert "rule bug" not in report


def test_floor_breach_that_flagged():
    """Floor breached but the check FAILED -- rule caught it; say 'all flagged'."""
    records = _make_records(
        "gross_margin_range",
        [(-0.5, False)],  # -50% gross margin; check failed (correctly flagged)
        threshold={"min": 0.0, "max": 0.9},
    )
    report = _section_distributions(records)
    assert "all flagged" in report
    assert "should have flagged" not in report
    assert "rule bug" not in report


def test_multiple_ceiling_breaches_all_flagged():
    """Multiple ceiling breaches, all from failed checks -- still 'all flagged'."""
    records = _make_records(
        "revenue_growth_sanity",
        [
            (-0.735, False),  # -73.5%, below floor -- irrelevant to ceiling test
            (2.902, False),   # +290.2%, above ceiling, flagged
            (1.142, False),   # +114.2%, above ceiling, flagged
        ],
        threshold={"min": -1.0, "max": 1.0},
    )
    report = _section_distributions(records)
    assert "all flagged" in report
    assert "should have flagged" not in report
    assert "rule bug" not in report


# ---------------------------------------------------------------------------
# Case 2: breach from a PASSED check (engine bug -- missed detection)
# ---------------------------------------------------------------------------

def test_ceiling_breach_that_passed():
    """Ceiling exceeded and the check PASSED -- engine missed it; fire the alarm."""
    records = _make_records(
        "revenue_growth_sanity",
        [(3.5, True)],  # +350% YoY growth; check PASSED (bug -- should have failed)
        threshold={"min": -1.0, "max": 1.0},
    )
    report = _section_distributions(records)
    assert "rule bug" in report


def test_floor_breach_that_passed():
    """Floor breached and the check PASSED -- engine missed it; fire the alarm."""
    records = _make_records(
        "gross_margin_range",
        [(-0.5, True)],  # -50% gross margin; check PASSED (bug)
        threshold={"min": 0.0, "max": 0.9},
    )
    report = _section_distributions(records)
    assert "rule bug" in report


# ---------------------------------------------------------------------------
# Case 3: no breach -- headroom lines unchanged
# ---------------------------------------------------------------------------

def test_no_breach_headroom_lines():
    """Observation within bounds: both headroom lines appear."""
    records = _make_records(
        "gross_margin_range",
        [(0.5, True)],  # 50% margin; well within [0.0, 0.9]
        threshold={"min": 0.0, "max": 0.9},
    )
    report = _section_distributions(records)
    assert "Headroom to ceiling" in report
    assert "Headroom above floor" in report
    assert "rule bug" not in report
    assert "all flagged" not in report


def test_no_breach_ceiling_only():
    """No ceiling breach when threshold has only a max."""
    records = _make_records(
        "net_margin_ceiling",
        [(0.2, True)],  # 20% net margin; below ceiling
        threshold={"max": 0.5},
    )
    report = _section_distributions(records)
    assert "Headroom to ceiling" in report
    assert "rule bug" not in report
    assert "all flagged" not in report
