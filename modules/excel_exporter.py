import io
import re
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side


# ── Colours ──────────────────────────────────────────────────────────────────
_NAVY        = "1F4E79"
_SECTION_BG  = "D9E1F2"   # light periwinkle for section header rows
_TITLE_BG    = "EBF2FF"   # very light blue for the title block
_WHITE       = "FFFFFF"
_GREY        = "595959"

# ── Number formats ────────────────────────────────────────────────────────────
# Accounting style: commas, parentheses for negatives, dash for zero
_FMT_STD       = '#,##0;(#,##0);"-"'
_FMT_PER_SHARE = '#,##0.00;(#,##0.00);"-"'
_PER_SHARE_KW  = ("per share", "earnings per", " eps")

# ── Border pieces ─────────────────────────────────────────────────────────────
_THIN   = Side(style="thin")
_DOUBLE = Side(style="double")
_MEDIUM = Side(style="medium")

_BORDER_SUBTOTAL    = Border(bottom=_THIN)
_BORDER_TOTAL       = Border(top=_THIN, bottom=_DOUBLE)
_BORDER_TITLE_SPLIT = Border(bottom=_MEDIUM)   # separates title block from data

# ── Fill helpers ──────────────────────────────────────────────────────────────
def _fill(hex_color: str) -> PatternFill:
    return PatternFill(start_color=hex_color, end_color=hex_color, fill_type="solid")


# ── Font constants ────────────────────────────────────────────────────────────
_FONT_CO_NAME   = Font(bold=True, size=14)
_FONT_STM_NAME  = Font(bold=True, size=12)
_FONT_CURRENCY  = Font(italic=True, color=_GREY, size=10)
_FONT_HEADER    = Font(bold=True, color=_WHITE, size=11)
_FONT_SECTION   = Font(bold=True, color=_NAVY, size=10)
_FONT_BOLD      = Font(bold=True)


def _num_fmt(line_item: str) -> str:
    lower = line_item.lower()
    return _FMT_PER_SHARE if any(k in lower for k in _PER_SHARE_KW) else _FMT_STD


def _extract_fiscal_year(period: str) -> str:
    """Derive a short column label from the period string if Claude didn't supply one."""
    m = re.search(r"\b(20\d{2})\b", period)
    return f"FY{m.group(1)}" if m else "Value"


def _write_statement_sheet(
    wb, sheet_name: str, rows: list,
    company: str, period: str, currency: str, fiscal_year: str
):
    ws = wb.create_sheet(title=sheet_name)
    title_fill = _fill(_TITLE_BG)

    # ── Title block (rows 1–4) ────────────────────────────────────────────────
    title_rows = [
        (company,              _FONT_CO_NAME),
        (sheet_name,           _FONT_STM_NAME),
        (period,               None),
        (f"Currency: {currency}", _FONT_CURRENCY),
    ]
    for r, (text, font) in enumerate(title_rows, start=1):
        for col in (1, 2):
            ws.cell(row=r, column=col).fill = title_fill
        cell = ws.cell(row=r, column=1, value=text)
        if font:
            cell.font = font

    # Medium border under title block to visually separate it from data
    for col in (1, 2):
        ws.cell(row=4, column=col).border = _BORDER_TITLE_SPLIT

    # ── Column header (row 6) ─────────────────────────────────────────────────
    HEADER_ROW = 6
    header_fill = _fill(_NAVY)
    for col, label in ((1, "Line Item"), (2, fiscal_year)):
        cell = ws.cell(row=HEADER_ROW, column=col, value=label)
        cell.font   = _FONT_HEADER
        cell.fill   = header_fill
        cell.alignment = Alignment(horizontal="right" if col == 2 else "left")

    # ── Data rows ─────────────────────────────────────────────────────────────
    current_row  = HEADER_ROW + 1
    in_section   = False   # tracks whether we're inside a section_header block
    first_section = True

    for row in rows:
        line_item = row.get("line_item", "")
        value     = row.get("value")
        row_type  = row.get("row_type", "data")  # default to "data" if missing

        # Insert a blank spacer row before every section header except the first
        if row_type == "section_header":
            if not first_section:
                current_row += 1
            first_section = False
            in_section = True

        cell_a = ws.cell(row=current_row, column=1, value=line_item)

        if row_type == "section_header":
            sect_fill = _fill(_SECTION_BG)
            cell_a.font = _FONT_SECTION
            cell_a.fill = sect_fill
            ws.cell(row=current_row, column=2).fill = sect_fill

        elif row_type == "data":
            # Indent data rows that sit inside a named section
            if in_section:
                cell_a.alignment = Alignment(indent=1)

        elif row_type in ("subtotal", "total"):
            cell_a.font = _FONT_BOLD

        # ── Value cell (column B) ─────────────────────────────────────────────
        if row_type != "section_header" and value is not None:
            cell_b = ws.cell(row=current_row, column=2, value=value)
            cell_b.number_format = _num_fmt(line_item)
            cell_b.alignment = Alignment(horizontal="right")

            if row_type == "subtotal":
                cell_b.font   = _FONT_BOLD
                cell_b.border = _BORDER_SUBTOTAL

            elif row_type == "total":
                cell_b.font   = _FONT_BOLD
                cell_b.border = _BORDER_TOTAL

        current_row += 1

    # ── Column widths ─────────────────────────────────────────────────────────
    ws.column_dimensions["A"].width = 50
    ws.column_dimensions["B"].width = 18


def create_excel_file(financial_data: dict) -> bytes:
    """Build a formatted Excel workbook and return it as bytes for Streamlit download."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    company     = financial_data.get("company_name", "Company")
    period      = financial_data.get("period", "")
    currency    = financial_data.get("currency", "")
    fiscal_year = financial_data.get("fiscal_year") or _extract_fiscal_year(period)

    statements = {
        "Income Statement":    financial_data.get("income_statement", []),
        "Balance Sheet":       financial_data.get("balance_sheet", []),
        "Cash Flow Statement": financial_data.get("cash_flow_statement", []),
    }

    for sheet_name, rows in statements.items():
        _write_statement_sheet(wb, sheet_name, rows, company, period, currency, fiscal_year)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()
