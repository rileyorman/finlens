import io
import re
import openpyxl
from openpyxl.cell.cell import MergedCell
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side


# ── Colours ───────────────────────────────────────────────────────────────────
_NAVY       = "1F4E79"
_SECTION_BG = "D9E1F2"   # light periwinkle — section header rows
_TITLE_BG   = "EBF2FF"   # very light blue  — title block
_WHITE      = "FFFFFF"
_GREY       = "595959"
_RED        = "FF0000"

# ── Number formats ─────────────────────────────────────────────────────────────
_FMT_STD       = '#,##0;(#,##0);"-"'                   # whole numbers, parens for negatives
_FMT_PER_SHARE = '#,##0.00;(#,##0.00);"-"'           # two decimals for per-share figures
_FMT_PCT       = '0.0"%";(0.0"%");"-"'               # literal %, value already multiplied by 100
_FMT_MULT      = '0.00"x";(0.00"x");"-"'             # multiples, parens for negatives
_PER_SHARE_KW  = ("per share", "earnings per", " eps")

# ── Border pieces ──────────────────────────────────────────────────────────────
_THIN   = Side(style="thin")
_DOUBLE = Side(style="double")
_MEDIUM = Side(style="medium")

_BORDER_SUBTOTAL    = Border(bottom=_THIN)
_BORDER_TOTAL       = Border(top=_THIN, bottom=_DOUBLE)
_BORDER_TITLE_SPLIT = Border(bottom=_MEDIUM)

# ── Fonts ──────────────────────────────────────────────────────────────────────
_FONT_CO_NAME  = Font(bold=True, size=14)
_FONT_STM_NAME = Font(bold=True, size=12)
_FONT_CURRENCY = Font(italic=True, color=_GREY, size=10)
_FONT_HEADER   = Font(bold=True, color=_WHITE, size=11)
_FONT_SECTION  = Font(bold=True, color=_NAVY, size=10)
_FONT_BOLD     = Font(bold=True)
_FONT_RED      = Font(color=_RED)
_FONT_BOLD_RED = Font(bold=True, color=_RED)
_FONT_NOTE     = Font(italic=True, color=_GREY, size=9)

# ── Summary / RAG colours ──────────────────────────────────────────────────────
_GREEN_RAG = "70AD47"
_AMBER_RAG = "FFC000"
_RED_RAG   = "C00000"
_INPUT_BG  = "FFFDE7"   # light yellow — user-editable cells in Valuation section

_SIGNAL_FILL = {
    "INVESTIGATE": _AMBER_RAG,
    "PASS":        _GREEN_RAG,
    "DECLINE":     _RED_RAG,
}
_SIGNAL_TEXT = {         # font colour on each badge background
    "INVESTIGATE": _NAVY,
    "PASS":        "FFFFFF",
    "DECLINE":     "FFFFFF",
}

_NUM_COLS = 3  # A = label, B = prior year, C = current year


# ═════════════════════════════════════════════════════════════════════════════
# Shared helpers
# ═════════════════════════════════════════════════════════════════════════════

def _fill(hex_color: str) -> PatternFill:
    return PatternFill(start_color=hex_color, end_color=hex_color, fill_type="solid")


def _fill_row(ws, row: int, fill: PatternFill, num_cols: int = _NUM_COLS) -> None:
    for col in range(1, num_cols + 1):
        ws.cell(row=row, column=col).fill = fill


def _write_title_block(ws, line1: str, line2: str, line3: str, line4: str) -> None:
    """Rows 1–4: company name, sheet/tab name, period, subtitle. Medium rule on row 4."""
    title_fill = _fill(_TITLE_BG)
    rows = [(line1, _FONT_CO_NAME), (line2, _FONT_STM_NAME), (line3, None), (line4, _FONT_CURRENCY)]
    for r, (text, font) in enumerate(rows, start=1):
        _fill_row(ws, r, title_fill)
        cell = ws.cell(row=r, column=1, value=text)
        if font:
            cell.font = font
    for col in range(1, _NUM_COLS + 1):
        ws.cell(row=4, column=col).border = _BORDER_TITLE_SPLIT


def _write_column_headers(ws, col_b_label: str, col_c_label: str, row: int = 6) -> None:
    """Dark-navy header row with three columns."""
    header_fill = _fill(_NAVY)
    for col, label, align in [(1, "Line Item", "left"), (2, col_b_label, "right"), (3, col_c_label, "right")]:
        cell = ws.cell(row=row, column=col, value=label)
        cell.font      = _FONT_HEADER
        cell.fill      = header_fill
        cell.alignment = Alignment(horizontal=align)


def _autofit_columns(ws, min_width: int = 12, max_width: int = 60, padding: int = 4) -> None:
    """Set each column width to fit the widest non-merged cell value."""
    col_widths = {}
    for row in ws.iter_rows():
        for cell in row:
            if isinstance(cell, MergedCell) or cell.value is None:
                continue
            col = cell.column_letter
            content_len = len(str(cell.value))
            if content_len > col_widths.get(col, 0):
                col_widths[col] = content_len
    for col_letter, width in col_widths.items():
        ws.column_dimensions[col_letter].width = min(max(width + padding, min_width), max_width)


def _extract_fiscal_year(period: str, offset: int = 0) -> str:
    m = re.search(r"\b(20\d{2})\b", period)
    if m:
        return f"FY{int(m.group(1)) + offset}"
    return "Prior Year" if offset < 0 else "Current Year"


# ═════════════════════════════════════════════════════════════════════════════
# Financial statement sheet
# ═════════════════════════════════════════════════════════════════════════════

def _fmt_for_line(line_item: str) -> str:
    lower = line_item.lower()
    return _FMT_PER_SHARE if any(k in lower for k in _PER_SHARE_KW) else _FMT_STD


def _write_value_cell(ws, row: int, col: int, value, line_item: str, row_type: str) -> None:
    if value is None:
        return
    cell = ws.cell(row=row, column=col, value=value)
    cell.number_format = _fmt_for_line(line_item)
    cell.alignment = Alignment(horizontal="right")
    negative = isinstance(value, (int, float)) and value < 0
    if row_type == "subtotal":
        cell.font   = _FONT_BOLD_RED if negative else _FONT_BOLD
        cell.border = _BORDER_SUBTOTAL
    elif row_type == "total":
        cell.font   = _FONT_BOLD_RED if negative else _FONT_BOLD
        cell.border = _BORDER_TOTAL
    elif negative:
        cell.font = _FONT_RED


def _write_statement_sheet(
    wb, sheet_name: str, rows: list,
    company: str, period: str, currency: str,
    fiscal_year_prior: str, fiscal_year: str,
) -> None:
    ws = wb.create_sheet(title=sheet_name)

    _write_title_block(ws, company, sheet_name, period, f"Currency: {currency}")
    _write_column_headers(ws, fiscal_year_prior, fiscal_year)

    current_row   = 7
    in_section    = False
    first_section = True

    for row in rows:
        line_item   = row.get("line_item", "")
        value       = row.get("value")
        value_prior = row.get("value_prior")
        row_type    = row.get("row_type", "data")

        if row_type == "section_header":
            if not first_section:
                current_row += 1
            first_section = False
            in_section    = True

        cell_a = ws.cell(row=current_row, column=1, value=line_item)

        if row_type == "section_header":
            _fill_row(ws, current_row, _fill(_SECTION_BG))
            cell_a.font = _FONT_SECTION
        elif row_type == "data" and in_section:
            cell_a.alignment = Alignment(indent=1)
        elif row_type in ("subtotal", "total"):
            cell_a.font = _FONT_BOLD

        if row_type != "section_header":
            _write_value_cell(ws, current_row, 2, value_prior, line_item, row_type)
            _write_value_cell(ws, current_row, 3, value,       line_item, row_type)

        current_row += 1

    ws.column_dimensions["A"].width = 50
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 16


# ═════════════════════════════════════════════════════════════════════════════
# Key Ratios — calculation
# ═════════════════════════════════════════════════════════════════════════════

_STEM_STOPWORDS = frozenset({"a", "an", "and", "by", "for", "in", "of", "or", "the", "to"})


def _words_stem(s: str) -> frozenset:
    """5-char stemmed word tokens for fuzzy-match fallback.
    Strips punctuation and stopwords so 'operating' and 'operations' both stem to 'opera'."""
    return frozenset(
        w[:5] for w in re.sub(r"[^a-z\s]", "", s.lower()).split()
        if w not in _STEM_STOPWORDS
    )


def _lookup(rows: list, keywords: list, field: str,
            row_types: list = None, exclude: list = None):
    """Return the value of the first matching row.
    Pass 1 — exact substring match (original behaviour).
    Pass 2 — stemmed-word-set fallback: all 5-char stems of the keyword must appear
              in the line item's stems. Handles suffix variants like
              'operations' vs 'operating', 'revenues' vs 'revenue'.
    """
    def _ok(row):
        li = row.get("line_item", "").lower().strip()
        if row_types and row.get("row_type", "data") not in row_types:
            return False
        if exclude and any(ex.lower() in li for ex in exclude):
            return False
        return True

    # Pass 1: exact substring
    for row in rows:
        if not _ok(row):
            continue
        li = row.get("line_item", "").lower().strip()
        if any(kw.lower() in li for kw in keywords):
            return row.get(field)

    # Pass 2: stemmed word-set fallback
    kw_stem_sets = [_words_stem(kw) for kw in keywords]
    for row in rows:
        if not _ok(row):
            continue
        li_stems = _words_stem(row.get("line_item", ""))
        for kw_stems in kw_stem_sets:
            if kw_stems and kw_stems.issubset(li_stems):
                return row.get(field)

    return None


def _lookup2(rows: list, keywords: list, field: str, exclude: list = None):
    """Prefer subtotal/total rows; fall back to any row type if not found.

    This prevents partial revenue lines (e.g. 'Product revenues') from being
    matched before the total revenue subtotal, while still handling companies
    that label a line like 'Gross margin' as a plain data row.
    """
    v = _lookup(rows, keywords, field, row_types=["subtotal", "total"], exclude=exclude)
    return v if v is not None else _lookup(rows, keywords, field, exclude=exclude)


def _safe_div(num, den):
    if num is None or den is None or den == 0:
        return None
    return num / den


def _pct(v):
    """Convert a decimal fraction (0.2537) to a display percentage (25.37)."""
    return round(v * 100, 4) if v is not None else None


def _calculate_ratios(financial_data: dict) -> list:
    """
    Derive key financial ratios from the already-extracted statement data.
    Returns a list of section dicts, each containing a list of ratio rows:
        {"header": str, "rows": [(name, fmt_type, val_current, val_prior), ...]}
    fmt_type is "pct" (store as decimal fraction, e.g. 0.279) or "mult" (store as multiple, e.g. 3.21).
    """
    is_rows = financial_data.get("income_statement", [])
    bs_rows = financial_data.get("balance_sheet", [])

    # ── Extract raw values for both years ─────────────────────────────────
    vals = {}
    for field in ("value", "value_prior"):

        # Revenue — prefer the total/subtotal row so individual product lines
        # (e.g. "Product revenues") are not matched before "Total revenues".
        rev = _lookup2(is_rows,
                       ["total revenues", "total revenue", "total net revenues",
                        "total net revenue", "net revenues", "net revenue",
                        "net sales", "total sales", "revenues", "revenue", "sales"],
                       field)

        # Gross profit — fall back to data rows so "Gross margin" (Microsoft-style)
        # is found even when Claude doesn't tag it as a subtotal.
        gp  = _lookup2(is_rows,
                       ["gross profit", "gross margin", "gross earnings", "gross income"],
                       field)

        oi  = _lookup(is_rows,
                      ["income (loss) from operations", "income from operations",
                       "operating income", "operating profit", "operating earnings",
                       "earnings from operations", "operating loss", "loss from operations"],
                      field)

        # Net income — prefer total rows; fall back for companies that label it
        # as a data row (e.g. "Net earnings" without a "total" tag).
        ni  = _lookup2(is_rows,
                       ["net income", "net earnings", "net loss",
                        "net income (loss)", "net earnings (loss)",
                        "profit for the period", "profit for the year", "net profit"],
                       field)

        # Interest expense: only treat as expense when the line is truly negative
        int_raw = _lookup(is_rows, ["interest expense"], field)
        if int_raw is None:
            # Some filings combine income and expense on one line (positive = net income)
            combined = _lookup(is_rows,
                               ["interest income (expense)", "interest (income) expense",
                                "interest expense (income)", "interest (expense) income"],
                               field)
            int_exp = abs(combined) if (combined is not None and combined < 0) else None
        else:
            int_exp = abs(int_raw) if int_raw is not None else None

        ca  = _lookup2(bs_rows, ["total current assets"],      field)
        cl  = _lookup2(bs_rows, ["total current liabilities"], field)
        inv = _lookup(bs_rows, ["inventories", "inventory"],   field) or 0
        # Exclude combined "total liabilities and equity" lines
        tl  = _lookup2(bs_rows, ["total liabilities"], field,
                       exclude=["equity", "shareholders", "stockholders"])
        eq  = _lookup2(bs_rows,
                       ["total shareholders' equity", "total stockholders' equity",
                        "total shareowners' equity", "total equity",
                        "shareholders' equity", "stockholders' equity",
                        "total owner", "owners' equity"],
                       field)

        vals[field] = dict(rev=rev, gp=gp, oi=oi, ni=ni, int_exp=int_exp,
                           ca=ca, cl=cl, inv=inv, tl=tl, eq=eq)

    c = vals["value"]        # current year
    p = vals["value_prior"]  # prior year

    def r(nc, dc, np_, dp):
        return _safe_div(nc, dc), _safe_div(np_, dp)

    # Quick ratio removes inventory from current assets
    qr_c = _safe_div((c["ca"] - c["inv"]) if c["ca"] is not None else None, c["cl"])
    qr_p = _safe_div((p["ca"] - p["inv"]) if p["ca"] is not None else None, p["cl"])

    gm_c,  gm_p  = r(c["gp"],  c["rev"], p["gp"],  p["rev"])
    om_c,  om_p  = r(c["oi"],  c["rev"], p["oi"],  p["rev"])
    nm_c,  nm_p  = r(c["ni"],  c["rev"], p["ni"],  p["rev"])
    roe_c, roe_p = r(c["ni"],  c["eq"],  p["ni"],  p["eq"])
    cr_c,  cr_p  = r(c["ca"],  c["cl"],  p["ca"],  p["cl"])
    de_c,  de_p  = r(c["tl"],  c["eq"],  p["tl"],  p["eq"])
    ic_c,  ic_p  = r(c["oi"],  c["int_exp"], p["oi"], p["int_exp"])

    return [
        {
            "header": "PROFITABILITY",
            "rows": [
                ("Gross Margin",     "pct",  _pct(gm_c),  _pct(gm_p)),
                ("Operating Margin", "pct",  _pct(om_c),  _pct(om_p)),
                ("Net Margin",       "pct",  _pct(nm_c),  _pct(nm_p)),
                ("Return on Equity", "pct",  _pct(roe_c), _pct(roe_p)),
            ],
        },
        {
            "header": "LIQUIDITY",
            "rows": [
                ("Current Ratio", "mult", cr_c, cr_p),
                ("Quick Ratio",   "mult", qr_c, qr_p),
            ],
        },
        {
            "header": "LEVERAGE",
            "rows": [
                ("Debt to Equity",    "mult", de_c, de_p),
                ("Interest Coverage", "mult", ic_c, ic_p),
            ],
        },
    ]


# ═════════════════════════════════════════════════════════════════════════════
# Key Ratios sheet
# ═════════════════════════════════════════════════════════════════════════════

def _write_ratio_cell(ws, row: int, col: int, value, fmt_type: str) -> None:
    """Write a single ratio value cell, or an em-dash if the ratio couldn't be computed."""
    if value is None:
        cell = ws.cell(row=row, column=col, value="—")
        cell.font      = Font(color=_GREY)
        cell.alignment = Alignment(horizontal="right")
    else:
        cell = ws.cell(row=row, column=col, value=value)
        cell.number_format = _FMT_PCT if fmt_type == "pct" else _FMT_MULT
        cell.alignment     = Alignment(horizontal="right")
        if isinstance(value, (int, float)) and value < 0:
            cell.font = _FONT_RED


def _write_ratios_sheet(
    wb, ratio_sections: list,
    company: str, period: str,
    fiscal_year_prior: str, fiscal_year: str,
) -> None:
    ws = wb.create_sheet(title="Key Ratios", index=0)   # always first tab

    _write_title_block(
        ws, company, "Key Ratios", period,
        "Calculated from reported financial statements"
    )
    _write_column_headers(ws, fiscal_year_prior, fiscal_year)

    current_row   = 7
    first_section = True

    for section in ratio_sections:
        if not first_section:
            current_row += 1   # blank spacer between sections
        first_section = False

        # Section header row
        _fill_row(ws, current_row, _fill(_SECTION_BG))
        ws.cell(row=current_row, column=1, value=section["header"]).font = _FONT_SECTION
        current_row += 1

        for name, fmt_type, val_c, val_p in section["rows"]:
            ws.cell(row=current_row, column=1, value=name).alignment = Alignment(indent=1)
            _write_ratio_cell(ws, current_row, 2, val_p, fmt_type)   # prior year  → col B
            _write_ratio_cell(ws, current_row, 3, val_c, fmt_type)   # current year → col C
            current_row += 1

    # Note at the bottom
    current_row += 1
    ws.cell(
        row=current_row, column=1,
        value=(
            "Note: All ratios are calculated from figures extracted by AI. "
            "Verify against the source document before use. "
            "A '—' indicates the ratio could not be computed from the available data "
            "(e.g. Interest Coverage where net interest expense is zero or not reported)."
        )
    ).font = _FONT_NOTE

    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 16


# ═════════════════════════════════════════════════════════════════════════════
# Summary sheet helpers
# ═════════════════════════════════════════════════════════════════════════════

def _rag(metric: str, value) -> tuple:
    """Return (PatternFill, label, text_color) for a RAG cell based on defined thresholds."""
    if value is None:
        return _fill(_WHITE), "N/A", _GREY
    G = (_fill(_GREEN_RAG), "GREEN", "FFFFFF")
    A = (_fill(_AMBER_RAG), "AMBER", _NAVY)
    R = (_fill(_RED_RAG),   "RED",   "FFFFFF")
    if metric == "liquidity":
        return G if value >= 2.0 else (A if value >= 1.0 else R)
    if metric == "leverage":
        return G if value <= 1.5 else (A if value <= 3.0 else R)
    if metric == "rev_growth":
        return G if value >= 5.0 else (A if value >= 0.0 else R)
    if metric == "fcf_conv":
        return G if value >= 100.0 else (A if value >= 50.0 else R)
    if metric == "int_cover":
        return G if value >= 3.0 else (A if value >= 1.5 else R)
    return _fill(_WHITE), "N/A", _GREY


# Shared line-item alias lists. _calc_summary_metrics and
# two_year_statement_pairs (the dashboard's two-year charts) must read the
# same statement rows, so the lists live once at module level.
_REV_LABELS = ["total revenues", "total revenue", "total net revenues", "total net revenue",
               "net revenues", "net revenue", "net sales", "total sales", "revenues", "revenue", "sales"]
_GP_LABELS  = ["gross profit", "gross margin", "gross earnings", "gross income"]
_OI_LABELS  = ["income (loss) from operations", "income from operations", "operating income",
               "operating profit", "operating earnings", "earnings from operations"]
_NI_LABELS  = ["net income", "net earnings", "net loss", "net income (loss)",
               "net earnings (loss)", "profit for the period", "profit for the year", "net profit"]
_DA_LABELS  = ["depreciation and amortization", "depreciation & amortization",
               "depreciation, depletion and amortization",
               "depreciation", "amortization"]
_OCF_LABELS = ["net cash provided by operating", "net cash from operating",
               "net cash from operations",
               "net cash used in operating", "cash provided by operating activities",
               "net cash provided by (used in) operating",
               "cash flows from operating", "cash generated from operating"]
_CAPEX_LABELS = ["capital expenditures", "capital expenditure",
                 "purchases of property, plant and equipment",
                 "purchases of property and equipment",
                 "additions to property and equipment",
                 "additions to property",
                 "payments for property and equipment",
                 "acquisition of property", "purchase of property",
                 "purchases of fixed assets", "purchase of fixed assets"]
_BUYBACK_LABELS = ["repurchases of common stock", "repurchase of common stock",
                   "payments for repurchase of common stock", "purchases of treasury stock",
                   "purchase of treasury stock", "share repurchases", "common stock repurchased",
                   "repurchases of shares", "repurchase of shares"]
_DIVIDEND_LABELS = ["dividends paid", "payments of dividends", "payment of dividends",
                    "dividends and dividend equivalents paid", "cash dividends paid",
                    "dividends paid to shareholders", "distributions paid"]
_ICF_LABELS = ["net cash provided by investing", "net cash used in investing",
               "net cash provided by (used in) investing", "net cash from investing",
               "cash flows from investing", "cash used in investing activities"]
_FIN_CF_LABELS = ["net cash provided by financing", "net cash used in financing",
                  "net cash provided by (used in) financing", "net cash from financing",
                  "cash flows from financing", "cash used in financing activities"]


def two_year_statement_pairs(financial_data: dict) -> dict:
    """Current/prior values for the dashboard's two-year charts.

    Returns {item_name: {"current": float|None, "prior": float|None}} using
    the same alias lists as _calc_summary_metrics, so the charts always agree
    with the Summary metrics and the Excel export.
    """
    is_rows = financial_data.get("income_statement", [])
    cf_rows = financial_data.get("cash_flow_statement", [])

    def _pair(rows, labels, lookup_fn):
        return {
            "current": lookup_fn(rows, labels, "value"),
            "prior":   lookup_fn(rows, labels, "value_prior"),
        }

    return {
        "Revenue":              _pair(is_rows, _REV_LABELS, _lookup2),
        "Gross Profit":         _pair(is_rows, _GP_LABELS,  _lookup2),
        "Operating Income":     _pair(is_rows, _OI_LABELS,  _lookup),
        "Net Income":           _pair(is_rows, _NI_LABELS,  _lookup2),
        "Operating Cash Flow":  _pair(cf_rows, _OCF_LABELS, _lookup2),
        "Capital Expenditures": _pair(cf_rows, _CAPEX_LABELS, _lookup),
        "Buybacks":             _pair(cf_rows, _BUYBACK_LABELS, _lookup),
        "Dividends":            _pair(cf_rows, _DIVIDEND_LABELS, _lookup),
        "Investing Cash Flow":  _pair(cf_rows, _ICF_LABELS, _lookup2),
        "Financing Cash Flow":  _pair(cf_rows, _FIN_CF_LABELS, _lookup2),
    }


def _calc_summary_metrics(financial_data: dict) -> dict:
    """Derive metric card and RAG values from Call 1 financial data."""
    is_rows = financial_data.get("income_statement", [])
    bs_rows = financial_data.get("balance_sheet", [])
    cf_rows = financial_data.get("cash_flow_statement", [])

    rev_c = _lookup2(is_rows, _REV_LABELS, "value")
    rev_p = _lookup2(is_rows, _REV_LABELS, "value_prior")
    gp_c  = _lookup2(is_rows, _GP_LABELS,  "value")
    oi_c  = _lookup(is_rows,  _OI_LABELS,  "value")
    ni_c  = _lookup2(is_rows, _NI_LABELS,  "value")

    da_c = _lookup(cf_rows, _DA_LABELS, "value")
    if da_c is not None:
        da_c = abs(da_c)

    ebitda_c = (oi_c + da_c) if (oi_c is not None and da_c is not None) else oi_c

    ocf_c = _lookup2(cf_rows, _OCF_LABELS, "value")

    capex_raw = _lookup(cf_rows, _CAPEX_LABELS, "value")
    capex_c = abs(capex_raw) if capex_raw is not None else None

    fcf_c = (ocf_c - capex_c) if (ocf_c is not None and capex_c is not None) else ocf_c

    ca_c  = _lookup2(bs_rows, ["total current assets"],      "value")
    cl_c  = _lookup2(bs_rows, ["total current liabilities"], "value")
    cash_c = _lookup(bs_rows,
                     ["cash and cash equivalents", "cash and equivalents",
                      "cash, cash equivalents and short-term investments"],
                     "value")
    ltd_c = _lookup(bs_rows,
                    ["long-term debt", "long-term notes payable", "long-term borrowings",
                     "senior notes", "term loan"],
                    "value") or 0
    std_c = _lookup(bs_rows,
                    ["short-term debt", "current portion of long-term debt",
                     "current maturities of long-term debt", "commercial paper"],
                    "value") or 0
    net_debt_c = ((ltd_c + std_c) - (cash_c or 0)) if cash_c is not None else None

    int_raw   = _lookup(is_rows, ["interest expense"], "value")
    int_exp_c = abs(int_raw) if int_raw is not None else None

    yoy_rev       = _pct(_safe_div(rev_c - rev_p, abs(rev_p))) if (rev_c is not None and rev_p) else None
    gp_margin     = _pct(_safe_div(gp_c,     rev_c))
    ebitda_margin = _pct(_safe_div(ebitda_c, rev_c))
    ni_margin     = _pct(_safe_div(ni_c,     rev_c))
    fcf_yield     = _pct(_safe_div(fcf_c,    rev_c))
    current_ratio = _safe_div(ca_c, cl_c)
    nd_ebitda     = _safe_div(net_debt_c, ebitda_c) if ebitda_c else None
    fcf_conv      = _pct(_safe_div(fcf_c, ni_c)) if (ni_c and ni_c != 0) else None
    int_cover     = _safe_div(oi_c, int_exp_c)

    return {
        "rev_c": rev_c,       "yoy_rev": yoy_rev,
        "gp_c": gp_c,         "gp_margin": gp_margin,
        "ebitda_c": ebitda_c, "ebitda_margin": ebitda_margin,
        "ni_c": ni_c,         "ni_margin": ni_margin,
        "fcf_c": fcf_c,       "fcf_yield": fcf_yield,
        "current_ratio": current_ratio,
        "nd_ebitda": nd_ebitda,
        "rev_growth": yoy_rev,
        "fcf_conv": fcf_conv,
        "int_cover": int_cover,
    }


def _write_summary_sheet(
    wb, summary_data: dict, metrics: dict, company: str, period: str,
    market_cap: float = 0.0, bear_bull_data: dict = None,
) -> None:
    """Insert a Summary sheet at index=0 (first tab), populated from Call 2 + derived metrics."""
    ws = wb.create_sheet(title="Summary", index=0)

    signal = (summary_data.get("signal") or "PASS").upper()
    thesis = summary_data.get("thesis") or ""
    cats   = summary_data.get("catalysts") or []
    risks  = summary_data.get("risks") or []
    sector = summary_data.get("sector_inferred") or "—"
    fdate  = summary_data.get("filing_date") or "—"
    ticker = summary_data.get("ticker") or "—"

    sig_bg   = _SIGNAL_FILL.get(signal, _AMBER_RAG)
    sig_text = _SIGNAL_TEXT.get(signal, _NAVY)

    # ── Signal badge + metadata (rows 1–2) ────────────────────────────────────
    ws.merge_cells(start_row=1, start_column=1, end_row=2, end_column=2)
    badge = ws.cell(row=1, column=1, value=f"[ {signal} ]")
    badge.fill      = _fill(sig_bg)
    badge.font      = Font(bold=True, size=15, color=sig_text)
    badge.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 26
    ws.row_dimensions[2].height = 16

    ws.merge_cells(start_row=1, start_column=3, end_row=1, end_column=6)
    co = ws.cell(row=1, column=3, value=company)
    co.font      = Font(bold=True, size=12, color=_NAVY)
    co.alignment = Alignment(horizontal="left", vertical="center")

    ws.merge_cells(start_row=2, start_column=3, end_row=2, end_column=6)
    meta = ws.cell(row=2, column=3,
                   value=f"Ticker: {ticker}   ·   Sector: {sector}   ·   Filing date: {fdate}")
    meta.font      = Font(italic=True, size=9, color=_GREY)
    meta.alignment = Alignment(horizontal="left", vertical="center")

    # ── Thesis (rows 3–4) ─────────────────────────────────────────────────────
    ws.merge_cells(start_row=3, start_column=1, end_row=4, end_column=6)
    th = ws.cell(row=3, column=1, value=thesis)
    th.font      = Font(italic=True, size=10, color=_NAVY)
    th.alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[3].height = 50
    ws.row_dimensions[4].height = 20

    # row 5 = blank spacer
    row = 6

    # ── Financials at a Glance (rows 6–10) ────────────────────────────────────
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
    ws.cell(row=row, column=1, value="FINANCIALS AT A GLANCE").font = _FONT_SECTION
    ws.cell(row=row, column=1).fill = _fill(_SECTION_BG)
    row += 1

    cards = [
        ("Revenue",        metrics.get("rev_c"),     metrics.get("yoy_rev"),       "YoY"),
        ("Gross Profit",   metrics.get("gp_c"),      metrics.get("gp_margin"),     "GP Margin"),
        ("EBITDA",         metrics.get("ebitda_c"),  metrics.get("ebitda_margin"), "EBITDA Margin"),
        ("Net Income",     metrics.get("ni_c"),      metrics.get("ni_margin"),     "NI Margin"),
        ("Free Cash Flow", metrics.get("fcf_c"),     metrics.get("fcf_yield"),     "FCF / Revenue"),
    ]

    for i, (lbl, *_) in enumerate(cards, start=1):
        c = ws.cell(row=row, column=i, value=lbl)
        c.fill = _fill(_TITLE_BG)
        c.font = Font(bold=True, size=9, color=_GREY)
        c.alignment = Alignment(horizontal="center")
    row += 1

    ws.row_dimensions[row].height = 22
    for i, (_, val, __, ___) in enumerate(cards, start=1):
        c = ws.cell(row=row, column=i, value=val)
        c.number_format = _FMT_STD
        c.alignment     = Alignment(horizontal="center")
        is_neg = isinstance(val, (int, float)) and val < 0
        c.font = Font(bold=True, size=13, color=(_RED if is_neg else _NAVY))
    row += 1

    for i, (_, __, sub, sub_lbl) in enumerate(cards, start=1):
        if sub is not None:
            prefix = "+" if (sub > 0 and sub_lbl == "YoY") else ""
            text = f"{prefix}{sub:.1f}%  {sub_lbl}"
        else:
            text = f"—  {sub_lbl}"
        c = ws.cell(row=row, column=i, value=text)
        c.font      = Font(size=8, color=_GREY)
        c.alignment = Alignment(horizontal="center")
    row += 2  # sub-metric row + spacer

    # ── Financial Health RAG (rows ~12–18) ────────────────────────────────────
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
    ws.cell(row=row, column=1, value="FINANCIAL HEALTH").font = _FONT_SECTION
    ws.cell(row=row, column=1).fill = _fill(_SECTION_BG)
    row += 1

    for col, lbl in [(1, "Metric"), (2, "Value"), (3, "Rating")]:
        h = ws.cell(row=row, column=col, value=lbl)
        h.fill      = _fill(_NAVY)
        h.font      = _FONT_HEADER
        h.alignment = Alignment(horizontal=("left" if col == 1 else "center"))
    row += 1

    rag_rows = [
        ("Liquidity  (Current Ratio)",           metrics.get("current_ratio"), "mult", "liquidity"),
        ("Leverage  (Net Debt / EBITDA)",         metrics.get("nd_ebitda"),    "mult", "leverage"),
        ("Revenue Growth  (YoY %)",              metrics.get("rev_growth"),   "pct",  "rev_growth"),
        ("FCF Conversion  (FCF / Net Income %)", metrics.get("fcf_conv"),     "pct",  "fcf_conv"),
        ("Interest Cover  (EBIT / Interest)",    metrics.get("int_cover"),    "mult", "int_cover"),
    ]

    for name, value, fmt, key in rag_rows:
        ws.cell(row=row, column=1, value=name)
        vc = ws.cell(row=row, column=2)
        if value is None:
            vc.value = "—"
            vc.font  = Font(color=_GREY)
        else:
            vc.value         = value
            vc.number_format = _FMT_MULT if fmt == "mult" else _FMT_PCT
        vc.alignment = Alignment(horizontal="center")
        rag_fill_obj, rag_label, rag_text = _rag(key, value)
        rc = ws.cell(row=row, column=3, value=rag_label)
        rc.fill      = rag_fill_obj
        rc.font      = Font(bold=True, size=9, color=rag_text)
        rc.alignment = Alignment(horizontal="center")
        row += 1

    row += 1  # spacer

    # ── Valuation ─────────────────────────────────────────────────────────────
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
    ws.cell(row=row, column=1, value="VALUATION").font = _FONT_SECTION
    ws.cell(row=row, column=1).fill = _fill(_SECTION_BG)
    row += 1

    # Market cap display — value cell is the denominator anchor for all formulas
    mc_label = ws.cell(row=row, column=1, value="Market Cap ($M):")
    mc_label.font = Font(bold=True, size=10, color=_NAVY)
    mc_val = ws.cell(row=row, column=2, value=market_cap if market_cap > 0 else None)
    mc_val.number_format = _FMT_STD
    mc_val.font          = Font(bold=True, size=10, color=_NAVY)
    mc_val.alignment     = Alignment(horizontal="center")
    mc_ref = f"$B${row}"  # absolute reference used in formulas below
    row += 1

    # Column headers
    for col, col_lbl in [(1, "Multiple"), (2, "Value"), (3, "Denominator")]:
        h = ws.cell(row=row, column=col, value=col_lbl)
        h.fill      = _fill(_NAVY)
        h.font      = _FONT_HEADER
        h.alignment = Alignment(horizontal=("left" if col == 1 else "center"))
    row += 1

    # Card values land at row 8 (fixed by the sheet structure above):
    # A8 = Revenue, B8 = Gross Profit, C8 = EBITDA, D8 = Net Income, E8 = FCF
    _CARD_ROW = 8
    multiples = [
        ("EV / EBITDA",  f"$C${_CARD_ROW}", "EBITDA"),
        ("P / E",        f"$D${_CARD_ROW}", "Net Income"),
        ("EV / Revenue", f"$A${_CARD_ROW}", "Revenue"),
        ("P / FCF",      f"$E${_CARD_ROW}", "Free Cash Flow"),
    ]

    for label, denom_ref, denom_name in multiples:
        ws.cell(row=row, column=1, value=label)
        vc = ws.cell(row=row, column=2)
        if market_cap > 0:
            vc.value         = f"=IFERROR({mc_ref}/{denom_ref},\"—\")"
            vc.number_format = _FMT_MULT
        else:
            vc.value = "—"
            vc.font  = Font(color=_GREY)
        vc.alignment = Alignment(horizontal="center")
        nc = ws.cell(row=row, column=3, value=f"/ {denom_name}")
        nc.font      = Font(size=8, italic=True, color=_GREY)
        nc.alignment = Alignment(horizontal="center")
        row += 1

    note = ws.cell(
        row=row, column=1,
        value=(
            "Multiples calculated using market cap entered at time of analysis. "
            "Verify current market cap before use."
        ),
    )
    note.font = _FONT_NOTE
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
    row += 2  # note + spacer

    # ── Catalysts & Risks ─────────────────────────────────────────────────────
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
    ws.cell(row=row, column=1, value="CATALYSTS & RISKS").font = _FONT_SECTION
    ws.cell(row=row, column=1).fill = _fill(_SECTION_BG)
    row += 1

    green_border = Border(left=Side(style="medium", color=_GREEN_RAG))
    red_border   = Border(left=Side(style="medium", color=_RED_RAG))

    for cat in cats[:2]:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
        c = ws.cell(row=row, column=1, value=f"(+)  {cat.get('text', '')}")
        c.font      = Font(size=10, color=_NAVY)
        c.border    = green_border
        c.alignment = Alignment(wrap_text=True, indent=1)
        ws.row_dimensions[row].height = 28
        row += 1

    for risk in risks[:1]:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
        c = ws.cell(row=row, column=1, value=f"(-)  {risk.get('text', '')}")
        c.font      = Font(size=10, color=_NAVY)
        c.border    = red_border
        c.alignment = Alignment(wrap_text=True, indent=1)
        ws.row_dimensions[row].height = 28
        row += 1

    row += 1  # spacer

    # ── Bull / Bear Case ─────────────────────────────────────────────────────
    if bear_bull_data and "error" not in bear_bull_data:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
        ws.cell(row=row, column=1, value="BULL / BEAR CASE").font = _FONT_SECTION
        ws.cell(row=row, column=1).fill = _fill(_SECTION_BG)
        row += 1

        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
        bh = ws.cell(row=row, column=1, value="BULL CASE")
        bh.fill      = _fill("D6E8D4")
        bh.font      = Font(bold=True, size=10, color="375623")
        bh.alignment = Alignment(horizontal="center")

        ws.merge_cells(start_row=row, start_column=4, end_row=row, end_column=6)
        rh = ws.cell(row=row, column=4, value="BEAR CASE")
        rh.fill      = _fill("F2D7D7")
        rh.font      = Font(bold=True, size=10, color="7B0000")
        rh.alignment = Alignment(horizontal="center")
        row += 1

        bull_pts = (bear_bull_data.get("bull_case") or [])[:3]
        bear_pts = (bear_bull_data.get("bear_case") or [])[:3]
        n_rows   = max(len(bull_pts), len(bear_pts), 1)

        green_left = Border(left=Side(style="medium", color=_GREEN_RAG))
        red_left   = Border(left=Side(style="medium", color=_RED_RAG))

        for i in range(n_rows):
            bp = bull_pts[i] if i < len(bull_pts) else None
            rp = bear_pts[i] if i < len(bear_pts) else None

            if bp:
                ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
                bc = ws.cell(row=row, column=1,
                             value=f"{bp.get('title', '')}\n{bp.get('detail', '')}")
                bc.font      = Font(size=9, color=_NAVY)
                bc.border    = green_left
                bc.alignment = Alignment(wrap_text=True, vertical="top", indent=1)

            if rp:
                ws.merge_cells(start_row=row, start_column=4, end_row=row, end_column=6)
                rc = ws.cell(row=row, column=4,
                             value=f"{rp.get('title', '')}\n{rp.get('detail', '')}")
                rc.font      = Font(size=9, color=_NAVY)
                rc.border    = red_left
                rc.alignment = Alignment(wrap_text=True, vertical="top", indent=1)

            ws.row_dimensions[row].height = 42
            row += 1

        row += 1  # spacer after bear/bull

    # ── Auto-fit columns based on actual cell content ─────────────────────────
    _autofit_columns(ws)

    # ── Footer ────────────────────────────────────────────────────────────────
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
    ft = ws.cell(
        row=row, column=1,
        value="FinLens  ·  AI-powered investment analysis  ·  Powered by Claude  ·  Market data: yfinance (15-min delay)  ·  For internal use only",
    )
    ft.font      = Font(italic=True, size=8, color=_GREY)
    ft.alignment = Alignment(horizontal="center")
    ft.border    = Border(top=_THIN)


# ═════════════════════════════════════════════════════════════════════════════
# Public entry point
# ═════════════════════════════════════════════════════════════════════════════

def create_excel_file(financial_data: dict, summary_data: dict = None, market_cap: float = 0.0, bear_bull_data: dict = None) -> bytes:
    """Build a formatted Excel workbook and return it as bytes for Streamlit download."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    company           = financial_data.get("company_name", "Company")
    period            = financial_data.get("period", "")
    currency          = financial_data.get("currency", "")
    fiscal_year       = financial_data.get("fiscal_year")       or _extract_fiscal_year(period,  0)
    fiscal_year_prior = financial_data.get("fiscal_year_prior") or _extract_fiscal_year(period, -1)

    # Key Ratios tab first (index=0 enforces position even if called out of order)
    ratio_sections = _calculate_ratios(financial_data)
    _write_ratios_sheet(wb, ratio_sections, company, period, fiscal_year_prior, fiscal_year)

    # Financial statement tabs
    statements = {
        "Income Statement":    financial_data.get("income_statement", []),
        "Balance Sheet":       financial_data.get("balance_sheet", []),
        "Cash Flow Statement": financial_data.get("cash_flow_statement", []),
    }
    for sheet_name, rows in statements.items():
        _write_statement_sheet(
            wb, sheet_name, rows,
            company, period, currency,
            fiscal_year_prior, fiscal_year,
        )

    # Summary tab — created last with index=0 so it becomes the first tab,
    # pushing Key Ratios and the statement sheets to the right.
    if summary_data and "error" not in summary_data:
        metrics = _calc_summary_metrics(financial_data)
        _write_summary_sheet(wb, summary_data, metrics, company, period, market_cap, bear_bull_data)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()
