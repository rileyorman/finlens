"""CB-020 — loss-form net-income sign convention (ratified 2026-07-07).

A label that unambiguously declares a loss — contains "loss" and none of the
profit words {income, profit, earnings} — carries a loss and must be stored
NEGATIVE, regardless of the filer's presented sign. NGEx prints a
positive-magnitude "Net loss" (+123,335,862) that the old scrape returned
positive, so the Net Income card showed a profit on a loss year and CB-019's
explorer suppression had nothing to suppress. AP.UN/SIG/NFG print the loss
parenthetically (already negative) — the rule must NOT double-negate those,
and must never flip a genuine profit or the "Net income (loss)" template.

Full ruling + spec: docs/design_sessions/2026-07-07-explorer-loss-sign-convention__cc.md
"""

from modules.excel_exporter import (
    _calc_summary_metrics,
    _signed_bottom_line,
    two_year_statement_pairs,
)
from modules.integrity.sedar_mapper import _is_loss_declaring_label, map_line_items
from modules.red_flag_detector import detect_flags


def _row(label, value, row_type=None):
    row = {"line_item": label, "value": value}
    if row_type is not None:
        row["row_type"] = row_type
    return row


def _fd(is_rows=(), cf_rows=(), bs_rows=(), **top):
    fd = {
        "income_statement": list(is_rows),
        "cash_flow_statement": list(cf_rows),
        "balance_sheet": list(bs_rows),
    }
    fd.update(top)
    return fd


# ── T1: the loss-declaring predicate ────────────────────────────────────────

def test_t1_loss_declaring_predicate():
    for label in (
        "Net loss",
        "Net loss and comprehensive loss",
        "loss and comprehensive loss for the year",
        "LOSS FOR THE PERIOD",
    ):
        assert _is_loss_declaring_label(label) is True, label
    for label in (
        "net income",
        "profit for the year",
        "net earnings",
        "net income (loss)",       # profit-or-loss TEMPLATE — value sign wins
        "net earnings (loss)",
        "operating income",
        "",
        None,
    ):
        assert _is_loss_declaring_label(label) is False, label


# ── T2–T5, T8: sign helper and the summary scrape ───────────────────────────

def test_t2_scrape_positive_magnitude_net_loss_is_negated():
    # NGEx shape: bare "Net loss" printed positive, no canonical field mapped.
    fd = _fd(is_rows=[_row("Net loss", 123_335_862)])
    m = _calc_summary_metrics(fd)
    assert m["ni_c"] == -123_335_862


def test_t3_scrape_parenthetical_loss_not_double_negated():
    # SIG/AP.UN shape: loss already presented negative — must stay put.
    fd = _fd(is_rows=[_row("Net loss and comprehensive loss", -3_417_435)])
    m = _calc_summary_metrics(fd)
    assert m["ni_c"] == -3_417_435


def test_t4_scrape_profit_template_positive_unchanged():
    fd = _fd(is_rows=[_row("Net income (loss)", 5_000)])
    m = _calc_summary_metrics(fd)
    assert m["ni_c"] == 5_000


def test_t5_scrape_loss_template_negative_unchanged():
    fd = _fd(is_rows=[_row("Net income (loss)", -3_000)])
    m = _calc_summary_metrics(fd)
    assert m["ni_c"] == -3_000


def test_t8_scrape_profit_regression_unchanged():
    fd = _fd(is_rows=[_row("Net income", 20_369)])
    m = _calc_summary_metrics(fd)
    assert m["ni_c"] == 20_369


def test_signed_bottom_line_helper_direct():
    assert _signed_bottom_line("Net loss", 123_335_862) == -123_335_862
    assert _signed_bottom_line("Net loss and comprehensive loss", -3_417_435) == -3_417_435
    assert _signed_bottom_line("net income", 20_369) == 20_369
    assert _signed_bottom_line("Net income (loss)", 5_000) == 5_000
    assert _signed_bottom_line("Net loss", None) is None
    # Non-numeric passes through unchanged (no new failure mode vs. old scrape).
    assert _signed_bottom_line("Net loss", "n/a") == "n/a"


# ── T6/T7: canonical-first ordering (net_income → net_loss → scrape) ─────────

def test_t6_explorer_net_loss_canonical_used_before_scrape():
    # The mapper signs net_loss; the summary layer reads it before scraping.
    fd = _fd(
        is_rows=[_row("Net loss", 999)],   # a decoy scrape row, must be ignored
        net_loss=-50_268_354,
    )
    m = _calc_summary_metrics(fd)
    assert m["ni_c"] == -50_268_354


def test_t7_canonical_net_income_wins_over_everything():
    fd = _fd(is_rows=[_row("Net loss", 999)], net_income=-123_335_862)
    m = _calc_summary_metrics(fd)
    assert m["ni_c"] == -123_335_862


# ── T9/T10: mapper-boundary defense-in-depth ────────────────────────────────

def test_t9_mapper_negates_positive_magnitude_long_form_loss():
    # A future filer printing "net loss and comprehensive loss" as a POSITIVE
    # magnitude: the mapper boundary signs it negative (net_income field).
    items = [{"label": "Net loss and comprehensive loss", "value": 7_000, "confidence": 0.99}]
    result = map_line_items(items, "IFRS", sector="Real Estate (REIT)")
    assert result["mapped"]["net_income"]["value"] == -7_000


def test_t9b_mapper_negates_positive_explorer_net_loss():
    items = [{"label": "net loss and comprehensive loss", "value": 3_417_435, "confidence": 0.99}]
    result = map_line_items(items, "IFRS", sector="Mining Exploration")
    assert result["meta"]["sector_profile"] == "mining_exploration_sector"
    assert result["mapped"]["net_loss"]["value"] == -3_417_435


def test_t10_mapper_noop_on_parenthetical_loss_no_drift():
    # The corpus case (SIG/NFG present the loss negative): the rule fires only
    # on positive values, so the stored value is byte-identical (int, same
    # magnitude) — no fixture/registry drift.
    items = [{"label": "net loss and comprehensive loss", "value": -3_417_435, "confidence": 0.99}]
    result = map_line_items(items, "IFRS", sector="Mining Exploration")
    stored = result["mapped"]["net_loss"]["value"]
    assert stored == -3_417_435
    assert isinstance(stored, int)


# ── T11: CB-019 interaction (the point of the fix) ──────────────────────────

def _explorer_scrape_fd():
    """NGEx shape driven entirely by the scrape: positive-magnitude 'Net loss',
    negative FCF, healthy current ratio, no top-level canonical net field."""
    return {
        "mapping": {"meta": {"sector_profile": "mining_exploration_sector"}},
        "income_statement": [_row("Net loss", 123_335_862)],
        "cash_flow_statement": [
            _row("net cash provided by operating activities", -50_000_000),
            _row("capital expenditures", -10_000_000),
        ],
        "balance_sheet": [
            _row("total current assets", 3_200_000),
            _row("total current liabilities", 1_000_000),
        ],
    }


def test_t11_explorer_negative_net_income_now_suppressed_by_cb019():
    res = detect_flags(_explorer_scrape_fd())
    supp = {s["check"]: s for s in res["suppressed"]}
    # The sign fix makes net_income and FCF negative, so CB-019 can suppress:
    assert "net_income" in supp
    assert "free_cash_flow" in supp
    # And the suppressed record carries the CORRECT negative value:
    assert supp["net_income"]["metric_value"] == -123_335_862
    # No surviving flags → honest None override (was a false INVESTIGATE).
    assert res["flags"] == []
    assert res["signal_override"] is None


def test_charts_net_income_signed_and_agrees_with_card():
    # Sibling-path guard (Change Propagation Rule): the two-year charts must
    # carry the SAME signed value as the Net Income card — else NGEx's chart
    # shows +123.3M while the card shows −123.3M.
    fd = _fd(is_rows=[_row("Net loss", 123_335_862)])
    pairs = two_year_statement_pairs(fd)
    card = _calc_summary_metrics(fd)
    assert pairs["Net Income"]["current"] == -123_335_862
    assert pairs["Net Income"]["current"] == card["ni_c"]


def test_charts_net_income_prior_column_also_signed():
    # Both columns of a loss row are signed: prior loss must not stay positive.
    fd = _fd(is_rows=[{"line_item": "Net loss", "value": 123_335_862,
                       "value_prior": 100_000_000}])
    pairs = two_year_statement_pairs(fd)
    assert pairs["Net Income"]["current"] == -123_335_862
    assert pairs["Net Income"]["prior"] == -100_000_000


def test_charts_net_income_canonical_net_loss_used():
    fd = _fd(is_rows=[_row("Net loss", 999)], net_loss=-50_268_354)
    pairs = two_year_statement_pairs(fd)
    assert pairs["Net Income"]["current"] == -50_268_354


def test_t11b_reit_net_loss_still_fires_not_suppressed():
    # Regression guard: CB-020 must not over-suppress. A REIT net loss keeps
    # firing (CB-019 suppresses only mining_exploration_sector).
    fd = {
        "mapping": {"meta": {"sector_profile": "reit_sector"}},
        "income_statement": [_row("Net loss and comprehensive loss", -1_327_532_000)],
        "balance_sheet": [],
        "cash_flow_statement": [],
    }
    res = detect_flags(fd)
    assert all(s["check"] != "net_income" for s in res["suppressed"])
    assert any("net income" in f["label"].lower() for f in res["flags"])
