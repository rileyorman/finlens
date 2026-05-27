"""One-page Investment Memo — Word document export (.docx).

Generates a CFO-ready memo from FinLens analysis output using python-docx.
Colour palette and metric calculations mirror the Excel Summary tab.
"""

import io
from datetime import datetime

from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from modules.excel_exporter import _calc_summary_metrics


# ── Colours ───────────────────────────────────────────────────────────────────
_NAVY_HEX  = "1F4E79"
_NAVY      = RGBColor(0x1F, 0x4E, 0x79)
_WHITE     = RGBColor(0xFF, 0xFF, 0xFF)
_GREY      = RGBColor(0x59, 0x59, 0x59)
_RED_FONT  = RGBColor(0xC0, 0x00, 0x00)
_BULL_BG   = "D6E8D4"
_BEAR_BG   = "F2D7D7"
_BULL_TEXT = RGBColor(0x37, 0x56, 0x23)
_BEAR_TEXT = RGBColor(0x7B, 0x00, 0x00)

_GREEN_RAG  = "70AD47"
_AMBER_RAG  = "FFC000"
_RED_RAG    = "C00000"
_GREEN_FONT = RGBColor(0x70, 0xAD, 0x47)
_DARK_AMBER = RGBColor(0xB8, 0x86, 0x0B)

_SIGNAL_BG = {
    "INVESTIGATE": _AMBER_RAG,
    "PASS":        _GREEN_RAG,
    "DECLINE":     _RED_RAG,
}
_SIGNAL_FG = {
    "INVESTIGATE": _NAVY,
    "PASS":        _WHITE,
    "DECLINE":     _WHITE,
}

# Usable page width (8.5" − 0.6" × 2 margins)
_W = 7.3


# ── XML / cell helpers ────────────────────────────────────────────────────────

def _bg(cell, hex_color: str) -> None:
    """Set cell background to a solid hex colour."""
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd  = OxmlElement("w:shd")
    shd.set(qn("w:val"),   "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"),  hex_color)
    existing = tcPr.find(qn("w:shd"))
    if existing is not None:
        tcPr.remove(existing)
    tcPr.append(shd)


def _borders(cell, color: str = "BFBFBF", sz: int = 4) -> None:
    """Apply thin borders to all four cell sides."""
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    bdr  = OxmlElement("w:tcBorders")
    for side in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"),   "single")
        el.set(qn("w:sz"),    str(sz))
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), color)
        bdr.append(el)
    existing = tcPr.find(qn("w:tcBorders"))
    if existing is not None:
        tcPr.remove(existing)
    tcPr.append(bdr)


def _no_borders(cell) -> None:
    """Remove all cell borders."""
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    bdr  = OxmlElement("w:tcBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"),   "none")
        el.set(qn("w:sz"),    "0")
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), "auto")
        bdr.append(el)
    existing = tcPr.find(qn("w:tcBorders"))
    if existing is not None:
        tcPr.remove(existing)
    tcPr.append(bdr)


def _cell_width(cell, inches: float) -> None:
    """Set a cell's preferred width."""
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcW  = OxmlElement("w:tcW")
    tcW.set(qn("w:w"),    str(int(inches * 1440)))
    tcW.set(qn("w:type"), "dxa")
    existing = tcPr.find(qn("w:tcW"))
    if existing is not None:
        tcPr.remove(existing)
    tcPr.append(tcW)


def _tight(para, before: int = 0, after: int = 2) -> None:
    para.paragraph_format.space_before = Pt(before)
    para.paragraph_format.space_after  = Pt(after)


def _run(para, text: str, bold=False, italic=False,
         size: int = 10, color: RGBColor = None) -> None:
    r = para.add_run(text)
    r.font.bold   = bold
    r.font.italic = italic
    r.font.size   = Pt(size)
    if color:
        r.font.color.rgb = color


# ── Number formatters ─────────────────────────────────────────────────────────

def _n(v) -> str:
    """Plain number with commas, or em-dash."""
    if v is None:
        return "—"
    return f"{float(v):,.0f}"


def _pct(v, show_sign=False) -> str:
    if v is None:
        return "—"
    sign = ("+" if v > 0 else "") if show_sign else ""
    return f"{sign}{float(v):.1f}%"


def _mult(v) -> str:
    if v is None:
        return "—"
    return f"{float(v):.2f}x"


# ── RAG helper ────────────────────────────────────────────────────────────────

def _rag(metric: str, value) -> tuple:
    """Return (hex_bg, label) for a RAG metric."""
    if value is None:
        return None, "N/A"
    if metric == "liquidity":
        c = _GREEN_RAG if value >= 2.0 else (_AMBER_RAG if value >= 1.0 else _RED_RAG)
    elif metric == "leverage":
        c = _GREEN_RAG if value <= 1.5 else (_AMBER_RAG if value <= 3.0 else _RED_RAG)
    elif metric == "rev_growth":
        c = _GREEN_RAG if value >= 5.0 else (_AMBER_RAG if value >= 0.0 else _RED_RAG)
    elif metric == "fcf_conv":
        c = _GREEN_RAG if value >= 100.0 else (_AMBER_RAG if value >= 50.0 else _RED_RAG)
    elif metric == "int_cover":
        c = _GREEN_RAG if value >= 3.0 else (_AMBER_RAG if value >= 1.5 else _RED_RAG)
    else:
        return None, "N/A"
    label = "GREEN" if c == _GREEN_RAG else ("AMBER" if c == _AMBER_RAG else "RED")
    return c, label


# ── Section header ────────────────────────────────────────────────────────────

def _section_header(doc, text: str) -> None:
    """Navy full-width section header using a single-cell table."""
    tbl = doc.add_table(rows=1, cols=1)
    tbl.style = "Table Grid"
    cell = tbl.cell(0, 0)
    _bg(cell, _NAVY_HEX)
    _no_borders(cell)
    _cell_width(cell, _W)
    p = cell.paragraphs[0]
    _tight(p, before=2, after=2)
    _run(p, text.upper(), bold=True, size=10, color=_WHITE)
    # Micro-spacer after the header
    sp = doc.add_paragraph()
    _tight(sp, before=0, after=0)


# ── Table builders ────────────────────────────────────────────────────────────

def _add_table(doc, rows: int, col_widths: list) -> object:
    """Create a borderless table with specified column widths (inches)."""
    tbl = doc.add_table(rows=rows, cols=len(col_widths))
    tbl.style = "Table Grid"
    for r in tbl.rows:
        for i, cell in enumerate(r.cells):
            _cell_width(cell, col_widths[i])
    return tbl


def _tbl_header_row(tbl, labels: list, col_widths: list) -> None:
    """Write a navy header row into row 0 of a table."""
    row = tbl.rows[0]
    for i, (cell, lbl) in enumerate(zip(row.cells, labels)):
        _bg(cell, _NAVY_HEX)
        _no_borders(cell)
        _cell_width(cell, col_widths[i])
        p = cell.paragraphs[0]
        _tight(p, before=2, after=2)
        align = WD_ALIGN_PARAGRAPH.LEFT if i == 0 else WD_ALIGN_PARAGRAPH.CENTER
        p.alignment = align
        _run(p, lbl, bold=True, size=9, color=_WHITE)


def _data_row(tbl, row_idx: int, values: list, col_widths: list,
              alt: bool = False, value_color: RGBColor = None) -> None:
    """Write a data row; optional alternating shade."""
    row = tbl.rows[row_idx]
    bg  = "F2F5FA" if alt else "FFFFFF"
    for i, (cell, val) in enumerate(zip(row.cells, values)):
        _bg(cell, bg)
        _borders(cell, color="D9D9D9", sz=4)
        _cell_width(cell, col_widths[i])
        p = cell.paragraphs[0]
        _tight(p, before=2, after=2)
        align = WD_ALIGN_PARAGRAPH.LEFT if i == 0 else WD_ALIGN_PARAGRAPH.CENTER
        p.alignment = align
        bold  = (i == 0)
        color = value_color if (value_color and i != 0) else (None if i != 0 else None)
        _run(p, str(val) if val is not None else "—",
             bold=bold, size=9,
             color=(value_color if (value_color and i > 0) else None))


# ── Main entry point ──────────────────────────────────────────────────────────

def create_memo(
    financial_data: dict,
    summary_data: dict | None,
    bear_bull_data: dict | None,
    market_data: dict | None,
    red_flags_data: dict = None,
) -> bytes:
    """Build a one-page Investment Memo and return .docx bytes."""

    doc = Document()

    # Page setup — tight margins for one-page target
    sec = doc.sections[0]
    sec.top_margin    = Inches(0.5)
    sec.bottom_margin = Inches(0.5)
    sec.left_margin   = Inches(0.6)
    sec.right_margin  = Inches(0.6)

    # Remove the default empty paragraph Word adds
    for para in list(doc.paragraphs):
        para._element.getparent().remove(para._element)

    # ── Unpack data ───────────────────────────────────────────────────────────
    company  = financial_data.get("company_name", "Company")
    period   = financial_data.get("period", "")
    currency = financial_data.get("currency", "")
    fy       = financial_data.get("fiscal_year", "Current Year")
    fy_prior = financial_data.get("fiscal_year_prior", "Prior Year")

    sd       = summary_data or {}
    signal   = (sd.get("signal") or "PASS").upper()
    thesis   = sd.get("thesis") or ""
    ticker   = sd.get("ticker") or "—"
    sector   = sd.get("sector_inferred") or "—"
    fdate    = sd.get("filing_date") or "—"
    cats     = sd.get("catalysts") or []
    risks    = sd.get("risks") or []

    bb       = bear_bull_data or {}
    bull_pts = (bb.get("bull_case") or [])[:3]
    bear_pts = (bb.get("bear_case") or [])[:3]

    md       = market_data or {}
    mc       = md.get("market_cap") or 0.0   # millions

    metrics  = _calc_summary_metrics(financial_data)
    today    = datetime.utcnow().strftime("%B %d, %Y")

    sig_bg = _SIGNAL_BG.get(signal, _AMBER_RAG)
    sig_fg = _SIGNAL_FG.get(signal, _NAVY)

    # ── 1. HEADER ─────────────────────────────────────────────────────────────
    # Two-column table: company name + meta | signal badge
    W_L, W_R = _W * 0.73, _W * 0.27
    hdr = doc.add_table(rows=1, cols=2)
    hdr.style = "Table Grid"

    lc = hdr.cell(0, 0)
    rc = hdr.cell(0, 1)

    # Left: company name + meta
    _bg(lc, "FFFFFF")
    _no_borders(lc)
    _cell_width(lc, W_L)
    lc.paragraphs[0]  # use default paragraph
    _tight(lc.paragraphs[0], before=4, after=1)
    _run(lc.paragraphs[0], company, bold=True, size=14, color=_NAVY)
    p_meta = lc.add_paragraph()
    _tight(p_meta, before=0, after=4)
    ticker_str = f"{ticker}   ·   " if ticker != "—" else ""
    _run(p_meta, f"{ticker_str}{period}   ·   {today}", italic=True, size=9, color=_GREY)

    # Right: signal badge
    _bg(rc, sig_bg)
    _no_borders(rc)
    _cell_width(rc, W_R)
    p_sig = rc.paragraphs[0]
    p_sig.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _tight(p_sig, before=9, after=5)
    _run(p_sig, f"  {signal}  ", bold=True, size=12, color=sig_fg)

    # Dividing rule beneath header
    hr = doc.add_paragraph()
    _tight(hr, before=0, after=4)
    pPr = hr._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bot = OxmlElement("w:bottom")
    bot.set(qn("w:val"),   "single")
    bot.set(qn("w:sz"),    "8")
    bot.set(qn("w:space"), "1")
    bot.set(qn("w:color"), _NAVY_HEX)
    pBdr.append(bot)
    pPr.append(pBdr)

    # ── 2. INVESTMENT THESIS ──────────────────────────────────────────────────
    _section_header(doc, "Investment Thesis")

    p_thesis = doc.add_paragraph()
    _tight(p_thesis, before=3, after=2)
    _run(p_thesis, thesis, italic=True, size=10)

    meta_line = doc.add_paragraph()
    _tight(meta_line, before=0, after=4)
    _run(meta_line, f"Sector: {sector}   ·   Filing date: {fdate}   ·   {currency}",
         size=8, color=_GREY, italic=True)

    # ── 3. FINANCIALS AT A GLANCE ─────────────────────────────────────────────
    _section_header(doc, "Financials at a Glance")

    fin_cols = [_W * 0.34, _W * 0.22, _W * 0.22, _W * 0.22]
    fin_data = [
        ("Revenue",        metrics.get("rev_c"),    metrics.get("yoy_rev"),       "YoY %"),
        ("Gross Profit",   metrics.get("gp_c"),     metrics.get("gp_margin"),     "GP Margin"),
        ("EBITDA",         metrics.get("ebitda_c"), metrics.get("ebitda_margin"), "EBITDA Margin"),
        ("Net Income",     metrics.get("ni_c"),     metrics.get("ni_margin"),     "NI Margin"),
        ("Free Cash Flow", metrics.get("fcf_c"),    metrics.get("fcf_yield"),     "FCF / Revenue"),
    ]

    fin_tbl = _add_table(doc, rows=1 + len(fin_data), col_widths=fin_cols)
    _tbl_header_row(fin_tbl, ["Metric", fy, "vs Prior / Margin", ""], fin_cols)
    for i, (label, val_c, sub_val, sub_lbl) in enumerate(fin_data):
        is_neg = isinstance(val_c, (int, float)) and val_c < 0
        pct_str = _pct(sub_val, show_sign=(sub_lbl == "YoY %")) if sub_val is not None else "—"
        _data_row(fin_tbl, i + 1,
                  [label, _n(val_c), pct_str, sub_lbl],
                  fin_cols, alt=(i % 2 == 0),
                  value_color=(_RED_FONT if is_neg else _NAVY))

    doc.add_paragraph()._p.getparent().remove(doc.paragraphs[-1]._p)
    sp = doc.add_paragraph()
    _tight(sp, before=0, after=4)

    # ── 4. FINANCIAL HEALTH ───────────────────────────────────────────────────
    _section_header(doc, "Financial Health")

    hlth_cols = [_W * 0.52, _W * 0.24, _W * 0.24]
    hlth_data = [
        ("Liquidity  (Current Ratio)",           metrics.get("current_ratio"), _mult,  "liquidity"),
        ("Leverage  (Net Debt / EBITDA)",         metrics.get("nd_ebitda"),    _mult,  "leverage"),
        ("Revenue Growth  (YoY %)",              metrics.get("rev_growth"),   _pct,   "rev_growth"),
        ("FCF Conversion  (FCF / Net Income %)", metrics.get("fcf_conv"),     _pct,   "fcf_conv"),
        ("Interest Cover  (EBIT / Interest)",    metrics.get("int_cover"),    _mult,  "int_cover"),
    ]

    hlth_tbl = _add_table(doc, rows=1 + len(hlth_data), col_widths=hlth_cols)
    _tbl_header_row(hlth_tbl, ["Metric", "Value", "Rating"], hlth_cols)

    for i, (label, value, fmt_fn, key) in enumerate(hlth_data):
        rag_hex, rag_label = _rag(key, value)
        row_obj = hlth_tbl.rows[i + 1]
        bg = "F2F5FA" if i % 2 == 0 else "FFFFFF"

        for j, cell in enumerate(row_obj.cells):
            _borders(cell, color="D9D9D9", sz=4)
            _cell_width(cell, hlth_cols[j])

        # Metric name
        _bg(row_obj.cells[0], bg)
        p = row_obj.cells[0].paragraphs[0]
        _tight(p, 2, 2)
        _run(p, label, bold=True, size=9)

        # Value
        _bg(row_obj.cells[1], bg)
        p = row_obj.cells[1].paragraphs[0]
        _tight(p, 2, 2)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _run(p, fmt_fn(value), size=9)

        # RAG badge
        if rag_hex:
            _bg(row_obj.cells[2], rag_hex)
        else:
            _bg(row_obj.cells[2], "D9D9D9")
        p = row_obj.cells[2].paragraphs[0]
        _tight(p, 2, 2)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        text_color = _WHITE if rag_hex in (_GREEN_RAG, _RED_RAG) else _NAVY
        _run(p, rag_label, bold=True, size=9, color=text_color)

    sp2 = doc.add_paragraph()
    _tight(sp2, before=0, after=4)

    # ── 4b. RISK FLAGS ────────────────────────────────────────────────────────
    _section_header(doc, "Risk Flags")

    rfd          = red_flags_data or {}
    rf_flags     = rfd.get("flags", [])
    rf_override  = rfd.get("signal_override")

    if not rf_flags:
        p_clean = doc.add_paragraph()
        _tight(p_clean, before=3, after=2)
        _run(p_clean, "No material flags identified.", size=9, color=_GREEN_FONT)
    else:
        for flag in [f for f in rf_flags if f["severity"] == "red"]:
            p = doc.add_paragraph()
            _tight(p, before=2, after=1)
            _run(p, f"\U0001f534 {flag['label']}", bold=True, size=9, color=_RED_FONT)
            _run(p, f" — {flag['detail']}", size=9, color=_RED_FONT)

        for flag in [f for f in rf_flags if f["severity"] == "yellow"]:
            p = doc.add_paragraph()
            _tight(p, before=2, after=1)
            _run(p, f"\U0001f7e1 {flag['label']}", bold=True, size=9, color=_DARK_AMBER)
            _run(p, f" — {flag['detail']}", size=9, color=_DARK_AMBER)

        if rf_override and rf_override != signal:
            p_note = doc.add_paragraph()
            _tight(p_note, before=4, after=2)
            _run(p_note,
                 f"Note: Quantitative flags suggest {rf_override} — "
                 "review alongside qualitative signal.",
                 italic=True, size=8, color=_GREY)

    sp_flags = doc.add_paragraph()
    _tight(sp_flags, before=0, after=4)

    # ── 5. VALUATION ─────────────────────────────────────────────────────────
    if mc > 0:
        _section_header(doc, "Valuation")

        val_cols = [_W * 0.34, _W * 0.33, _W * 0.33]
        val_rows = [
            ("EV / EBITDA",  metrics.get("ebitda_c"), "EBITDA"),
            ("P / E",        metrics.get("ni_c"),      "Net Income"),
            ("EV / Revenue", metrics.get("rev_c"),     "Revenue"),
            ("P / FCF",      metrics.get("fcf_c"),     "Free Cash Flow"),
        ]

        val_tbl = _add_table(doc, rows=1 + len(val_rows), col_widths=val_cols)
        _tbl_header_row(val_tbl, ["Multiple", "Value", "Denominator"], val_cols)

        for i, (label, denom, denom_name) in enumerate(val_rows):
            if denom and denom != 0:
                multiple = mc / denom
                mult_str = _mult(multiple)
                is_neg   = multiple < 0
            else:
                mult_str = "—"
                is_neg   = False
            _data_row(val_tbl, i + 1,
                      [label, mult_str, denom_name],
                      val_cols, alt=(i % 2 == 0),
                      value_color=(_RED_FONT if is_neg else _NAVY))

        note = doc.add_paragraph()
        _tight(note, before=2, after=4)
        _run(note,
             f"Market cap: ${mc:,.0f}M   ·   Multiples use reporting-unit denominator from filing.",
             size=8, color=_GREY, italic=True)

    # ── 6. BULL / BEAR CASE ───────────────────────────────────────────────────
    if bull_pts or bear_pts:
        _section_header(doc, "Bull / Bear Case")

        bb_cols = [_W * 0.06, _W * 0.44, _W * 0.06, _W * 0.44]
        bb_tbl  = _add_table(doc, rows=1 + max(len(bull_pts), len(bear_pts), 1),
                             col_widths=bb_cols)

        # Sub-header row (row 0)
        row0 = bb_tbl.rows[0]
        for j, cell in enumerate(row0.cells):
            _no_borders(cell)
        _bg(row0.cells[0], _BULL_BG); _bg(row0.cells[1], _BULL_BG)
        _bg(row0.cells[2], _BEAR_BG); _bg(row0.cells[3], _BEAR_BG)
        _cell_width(row0.cells[0], bb_cols[0]); _cell_width(row0.cells[1], bb_cols[1])
        _cell_width(row0.cells[2], bb_cols[2]); _cell_width(row0.cells[3], bb_cols[3])
        p = row0.cells[1].paragraphs[0]
        _tight(p, 2, 2); _run(p, "BULL CASE", bold=True, size=9, color=_BULL_TEXT)
        p = row0.cells[3].paragraphs[0]
        _tight(p, 2, 2); _run(p, "BEAR CASE", bold=True, size=9, color=_BEAR_TEXT)

        n_pts = max(len(bull_pts), len(bear_pts), 1)
        for i in range(n_pts):
            row_obj = bb_tbl.rows[i + 1]
            bp = bull_pts[i] if i < len(bull_pts) else None
            rp = bear_pts[i] if i < len(bear_pts) else None

            # Bull marker + text
            _bg(row_obj.cells[0], "EAFAEA"); _borders(row_obj.cells[0], _GREEN_RAG, sz=6)
            _cell_width(row_obj.cells[0], bb_cols[0])
            pm = row_obj.cells[0].paragraphs[0]
            _tight(pm, 3, 3); pm.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _run(pm, "▲", size=8, color=RGBColor(0x37, 0x56, 0x23))

            _bg(row_obj.cells[1], "F5FBF5"); _borders(row_obj.cells[1], "D9D9D9")
            _cell_width(row_obj.cells[1], bb_cols[1])
            if bp:
                p = row_obj.cells[1].paragraphs[0]
                _tight(p, 3, 1)
                _run(p, bp.get("title", ""), bold=True, size=9)
                p2 = row_obj.cells[1].add_paragraph()
                _tight(p2, 0, 3)
                _run(p2, bp.get("detail", ""), size=8, color=_GREY)

            # Bear marker + text
            _bg(row_obj.cells[2], "FDECEA"); _borders(row_obj.cells[2], _RED_RAG, sz=6)
            _cell_width(row_obj.cells[2], bb_cols[2])
            pm2 = row_obj.cells[2].paragraphs[0]
            _tight(pm2, 3, 3); pm2.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _run(pm2, "▼", size=8, color=RGBColor(0x7B, 0x00, 0x00))

            _bg(row_obj.cells[3], "FDF5F5"); _borders(row_obj.cells[3], "D9D9D9")
            _cell_width(row_obj.cells[3], bb_cols[3])
            if rp:
                p = row_obj.cells[3].paragraphs[0]
                _tight(p, 3, 1)
                _run(p, rp.get("title", ""), bold=True, size=9)
                p2 = row_obj.cells[3].add_paragraph()
                _tight(p2, 0, 3)
                _run(p2, rp.get("detail", ""), size=8, color=_GREY)

        sp3 = doc.add_paragraph()
        _tight(sp3, before=0, after=4)

    # ── 7. FOOTER ─────────────────────────────────────────────────────────────
    footer_para = doc.add_paragraph()
    _tight(footer_para, before=6, after=0)
    footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pPr = footer_para._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    top = OxmlElement("w:top")
    top.set(qn("w:val"),   "single")
    top.set(qn("w:sz"),    "4")
    top.set(qn("w:space"), "1")
    top.set(qn("w:color"), "D9D9D9")
    pBdr.append(top)
    pPr.append(pBdr)
    _run(footer_para,
         f"Generated by FinLens  ·  AI-powered financial analysis  ·  {today}  ·  For internal use only",
         size=8, color=_GREY, italic=True)

    # ── Serialise ─────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()
