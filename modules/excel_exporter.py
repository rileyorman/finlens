import io
import re
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side


# ── Colours ───────────────────────────────────────────────────────────────────
_NAVY       = "1F4E79"
_SECTION_BG = "D9E1F2"   # light periwinkle — section header rows
_TITLE_BG   = "EBF2FF"   # very light blue  — title block
_WHITE      = "FFFFFF"
_GREY       = "595959"

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
_FONT_NOTE     = Font(italic=True, color=_GREY, size=9)

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
    if row_type == "subtotal":
        cell.font   = _FONT_BOLD
        cell.border = _BORDER_SUBTOTAL
    elif row_type == "total":
        cell.font   = _FONT_BOLD
        cell.border = _BORDER_TOTAL


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

def _lookup(rows: list, keywords: list, field: str,
            row_types: list = None, exclude: list = None):
    """Return the value of the first row whose line_item contains any keyword."""
    for row in rows:
        li = row.get("line_item", "").lower().strip()
        rt = row.get("row_type", "data")
        if row_types and rt not in row_types:
            continue
        if exclude and any(ex.lower() in li for ex in exclude):
            continue
        for kw in keywords:
            if kw.lower() in li:
                return row.get(field)
    return None


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

        rev = _lookup(is_rows,
                      ["revenues", "revenue", "net revenue", "net sales", "total revenues"],
                      field)
        gp  = _lookup(is_rows,
                      ["gross profit", "gross margin"],
                      field, row_types=["subtotal", "total"])
        oi  = _lookup(is_rows,
                      ["income (loss) from operations", "operating income",
                       "income from operations", "operating profit", "loss from operations"],
                      field)
        ni  = _lookup(is_rows,
                      ["net income", "net loss", "net earnings"],
                      field, row_types=["total"])

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

        ca  = _lookup(bs_rows, ["total current assets"],      field)
        cl  = _lookup(bs_rows, ["total current liabilities"], field)
        inv = _lookup(bs_rows, ["inventory", "inventories"],  field) or 0
        # Exclude "total liabilities and shareholders'/stockholders' equity"
        tl  = _lookup(bs_rows, ["total liabilities"], field,
                      exclude=["equity", "shareholders", "stockholders"])
        eq  = _lookup(bs_rows,
                      ["total shareholders' equity", "total stockholders' equity", "total equity"],
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
# Public entry point
# ═════════════════════════════════════════════════════════════════════════════

def create_excel_file(financial_data: dict) -> bytes:
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

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()
