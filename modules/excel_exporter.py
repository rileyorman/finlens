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
_FMT_STD       = '#,##0;(#,##0);"-"'        # whole numbers, parens for negatives
_FMT_PER_SHARE = '#,##0.00;(#,##0.00);"-"'  # two decimals for per-share figures
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

_NUM_COLS = 3  # A = line item, B = prior year, C = current year


def _fill(hex_color: str) -> PatternFill:
    return PatternFill(start_color=hex_color, end_color=hex_color, fill_type="solid")


def _num_fmt(line_item: str) -> str:
    lower = line_item.lower()
    return _FMT_PER_SHARE if any(k in lower for k in _PER_SHARE_KW) else _FMT_STD


def _fill_row(ws, row: int, fill: PatternFill, num_cols: int = _NUM_COLS) -> None:
    for col in range(1, num_cols + 1):
        ws.cell(row=row, column=col).fill = fill


def _write_value_cell(ws, row: int, col: int, value, line_item: str, row_type: str) -> None:
    """Write, format, and optionally border a single numeric cell."""
    if value is None:
        return
    cell = ws.cell(row=row, column=col, value=value)
    cell.number_format = _num_fmt(line_item)
    cell.alignment = Alignment(horizontal="right")
    if row_type == "subtotal":
        cell.font   = _FONT_BOLD
        cell.border = _BORDER_SUBTOTAL
    elif row_type == "total":
        cell.font   = _FONT_BOLD
        cell.border = _BORDER_TOTAL


def _extract_fiscal_year(period: str, offset: int = 0) -> str:
    """Pull the year from a period string and apply an optional offset (e.g. -1 for prior year)."""
    m = re.search(r"\b(20\d{2})\b", period)
    if m:
        return f"FY{int(m.group(1)) + offset}"
    return "Prior Year" if offset < 0 else "Current Year"


def _write_statement_sheet(
    wb,
    sheet_name: str,
    rows: list,
    company: str,
    period: str,
    currency: str,
    fiscal_year_prior: str,
    fiscal_year: str,
) -> None:
    ws = wb.create_sheet(title=sheet_name)
    title_fill = _fill(_TITLE_BG)

    # ── Title block (rows 1–4) ─────────────────────────────────────────────
    title_rows = [
        (company,                 _FONT_CO_NAME),
        (sheet_name,              _FONT_STM_NAME),
        (period,                  None),
        (f"Currency: {currency}", _FONT_CURRENCY),
    ]
    for r, (text, font) in enumerate(title_rows, start=1):
        _fill_row(ws, r, title_fill)
        cell = ws.cell(row=r, column=1, value=text)
        if font:
            cell.font = font

    # Medium rule separates title block from data
    for col in range(1, _NUM_COLS + 1):
        ws.cell(row=4, column=col).border = _BORDER_TITLE_SPLIT

    # ── Column headers (row 6) ─────────────────────────────────────────────
    HEADER_ROW = 6
    header_fill = _fill(_NAVY)
    headers = [
        (1, "Line Item",       "left"),
        (2, fiscal_year_prior, "right"),
        (3, fiscal_year,       "right"),
    ]
    for col, label, align in headers:
        cell = ws.cell(row=HEADER_ROW, column=col, value=label)
        cell.font      = _FONT_HEADER
        cell.fill      = header_fill
        cell.alignment = Alignment(horizontal=align)

    # ── Data rows ──────────────────────────────────────────────────────────
    current_row   = HEADER_ROW + 1
    in_section    = False
    first_section = True

    for row in rows:
        line_item   = row.get("line_item", "")
        value       = row.get("value")        # current year (col C)
        value_prior = row.get("value_prior")  # prior year   (col B)
        row_type    = row.get("row_type", "data")

        # Blank spacer row before every section header except the first
        if row_type == "section_header":
            if not first_section:
                current_row += 1
            first_section = False
            in_section    = True

        # ── Column A — line item label ─────────────────────────────────────
        cell_a = ws.cell(row=current_row, column=1, value=line_item)

        if row_type == "section_header":
            _fill_row(ws, current_row, _fill(_SECTION_BG))
            cell_a.font = _FONT_SECTION

        elif row_type == "data" and in_section:
            cell_a.alignment = Alignment(indent=1)

        elif row_type in ("subtotal", "total"):
            cell_a.font = _FONT_BOLD

        # ── Columns B & C — prior and current year values ──────────────────
        if row_type != "section_header":
            _write_value_cell(ws, current_row, 2, value_prior, line_item, row_type)
            _write_value_cell(ws, current_row, 3, value,       line_item, row_type)

        current_row += 1

    # ── Column widths ──────────────────────────────────────────────────────
    ws.column_dimensions["A"].width = 50
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 16


def create_excel_file(financial_data: dict) -> bytes:
    """Build a formatted Excel workbook and return it as bytes for Streamlit download."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    company     = financial_data.get("company_name", "Company")
    period      = financial_data.get("period", "")
    currency    = financial_data.get("currency", "")
    fiscal_year       = financial_data.get("fiscal_year")       or _extract_fiscal_year(period,  0)
    fiscal_year_prior = financial_data.get("fiscal_year_prior") or _extract_fiscal_year(period, -1)

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
