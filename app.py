import os
import streamlit as st
from dotenv import load_dotenv

from modules.pdf_extractor import extract_text_from_pdf
from modules.claude_analyzer import analyze_financials, analyze_summary, analyze_bear_bull, analyze_dashboard_insights
from modules.excel_exporter import create_excel_file, _calc_summary_metrics
from modules.memo_exporter import create_memo
from modules.red_flag_detector import detect_flags
from modules.market_data import get_market_data, search_ticker, search_ticker_details
from modules.cache import get_cache_key, load_cache, save_cache, clear_cache, cache_count
from modules.filing_library import add_entry as lib_add, get_entries as lib_get, delete_entry as lib_delete
from modules.portfolio_registry import (
    get_portfolio_names, create_portfolio,
    delete_portfolio as del_portfolio_reg,
    add_ticker as reg_add_ticker, remove_ticker as reg_remove_ticker,
    bulk_add_tickers, get_tickers,
)
from modules.portfolio_manager import get_portfolio_display_data
from config import MAX_FILING_CHARS

load_dotenv()

API_KEY = os.getenv("ANTHROPIC_API_KEY")


def _fmt_market_cap(mc_millions):
    """Format market cap (stored in millions) as $X.XT / $X.XB / $X.XM."""
    if not mc_millions:
        return "—"
    if mc_millions >= 1_000_000:
        return f"${mc_millions / 1_000_000:.1f}T"
    if mc_millions >= 1_000:
        return f"${mc_millions / 1_000:.1f}B"
    return f"${mc_millions:.0f}M"


def _quality_score(m: dict) -> int:
    """0–100 quality score from 5 RAG health metrics. Green=20, Amber=10, Red/None=0."""
    def pts(metric, value):
        if value is None:
            return 0
        if metric == "liquidity":  return 20 if value >= 2.0 else (10 if value >= 1.0 else 0)
        if metric == "leverage":   return 20 if value <= 1.5 else (10 if value <= 3.0 else 0)
        if metric == "rev_growth": return 20 if value >= 5.0 else (10 if value >= 0.0 else 0)
        if metric == "fcf_conv":   return 20 if value >= 100.0 else (10 if value >= 50.0 else 0)
        if metric == "int_cover":  return 20 if value >= 3.0 else (10 if value >= 1.5 else 0)
        return 0
    return sum([
        pts("liquidity",  m.get("current_ratio")),
        pts("leverage",   m.get("nd_ebitda")),
        pts("rev_growth", m.get("rev_growth")),
        pts("fcf_conv",   m.get("fcf_conv")),
        pts("int_cover",  m.get("int_cover")),
    ])


def _dash_rag(metric: str, value) -> tuple:
    """Return (bg_hex, label) for dashboard RAG cells — mirrors excel_exporter thresholds."""
    if value is None:
        return "#D9D9D9", "N/A"
    if metric == "liquidity":  c = "G" if value >= 2.0 else ("A" if value >= 1.0 else "R")
    elif metric == "leverage": c = "G" if value <= 1.5 else ("A" if value <= 3.0 else "R")
    elif metric == "rev_growth": c = "G" if value >= 5.0 else ("A" if value >= 0.0 else "R")
    elif metric == "fcf_conv": c = "G" if value >= 100.0 else ("A" if value >= 50.0 else "R")
    elif metric == "int_cover": c = "G" if value >= 3.0 else ("A" if value >= 1.5 else "R")
    else: return "#D9D9D9", "N/A"
    return {"G": ("#70AD47", "GREEN"), "A": ("#FFC000", "AMBER"), "R": ("#C00000", "RED")}[c]

st.set_page_config(
    page_title="FinLens",
    page_icon="📊",
    layout="wide",
)

st.title("FinLens")
st.caption("AI-powered financial statement analysis. Upload a PDF to extract key financials and download a structured Excel report.")

# --- Sidebar -----------------------------------------------------------
with st.sidebar:
    page = st.radio(
        "Mode",
        ["📊 Single Analysis", "📈 Portfolio Manager"],
        label_visibility="collapsed",
    )
    st.divider()

    # --- Portfolio management (Portfolio Manager mode only) ---------------
    selected_portfolio = None
    if page == "📈 Portfolio Manager":
        pf_names = get_portfolio_names()
        options  = pf_names + ["+ New Portfolio"]
        active   = st.session_state.get("pm_active_portfolio")
        sel_idx  = pf_names.index(active) if active in pf_names else 0

        sel_pf = st.selectbox(
            "Portfolio",
            options,
            index=min(sel_idx, len(options) - 1),
        )

        if sel_pf == "+ New Portfolio":
            new_pf_name = st.text_input("Portfolio name", key="pm_new_name")
            if st.button("Create Portfolio", use_container_width=True, type="primary"):
                n = new_pf_name.strip()
                if n:
                    if create_portfolio(n):
                        st.session_state.pm_active_portfolio = n
                        st.rerun()
                    else:
                        st.warning("A portfolio with that name already exists.")
                else:
                    st.warning("Enter a portfolio name.")
        else:
            st.session_state.pm_active_portfolio = sel_pf
            selected_portfolio = sel_pf
            cur_tickers = get_tickers(sel_pf)

            with st.expander(f"Manage Tickers ({len(cur_tickers)})", expanded=False):
                for t in cur_tickers:
                    tc, rc = st.columns([3, 1])
                    with tc:
                        st.markdown(f"`{t}`")
                    with rc:
                        if st.button("✕", key=f"rm_{sel_pf}_{t}", use_container_width=True):
                            reg_remove_ticker(sel_pf, t)
                            st.rerun()

                if cur_tickers:
                    st.markdown(
                        "<hr style='margin:4px 0;border:none;border-top:0.5px solid #e0e0e0'>",
                        unsafe_allow_html=True,
                    )

                ac, bc = st.columns([3, 1])
                with ac:
                    new_tk = st.text_input(
                        "Ticker", key=f"pm_add_input_{sel_pf}",
                        placeholder="e.g. AAPL", label_visibility="collapsed",
                    )
                with bc:
                    if st.button("Add", key=f"pm_add_btn_{sel_pf}", use_container_width=True):
                        t_up = new_tk.strip().upper()
                        if t_up:
                            with st.spinner(f"Validating {t_up}…"):
                                try:
                                    vmd      = get_market_data(t_up)
                                    is_valid = bool(vmd.get("current_price"))
                                except Exception:
                                    is_valid = False
                            if is_valid:
                                if reg_add_ticker(sel_pf, t_up):
                                    st.session_state[f"pm_add_input_{sel_pf}"] = ""
                                    st.rerun()
                                else:
                                    st.warning(f"{t_up} already in portfolio.")
                            else:
                                st.warning(f"'{t_up}' not found — check the ticker symbol.")
                        else:
                            st.warning("Enter a ticker symbol.")

                csv_up = st.file_uploader(
                    "Bulk add (.csv)", type=["csv"], key=f"pm_csv_{sel_pf}",
                )
                if csv_up is not None:
                    import io, csv as _csv
                    content = csv_up.read().decode("utf-8", errors="ignore")
                    reader  = _csv.reader(io.StringIO(content))
                    raw_tks = []
                    for i, row in enumerate(reader):
                        if not row:
                            continue
                        val = row[0].strip().upper()
                        if i == 0 and val in ("TICKER", "TICKERS", "SYMBOL", "SYMBOLS"):
                            continue
                        if val:
                            raw_tks.append(val)
                    if raw_tks:
                        br = bulk_add_tickers(sel_pf, raw_tks)
                        st.success(f"Added {len(br['added'])}, skipped {len(br['skipped'])}.")
                        st.rerun()
                    else:
                        st.warning("No tickers found in CSV.")

                st.markdown(
                    "<hr style='margin:4px 0;border:none;border-top:0.5px solid #e0e0e0'>",
                    unsafe_allow_html=True,
                )
                if st.session_state.get("pm_confirm_delete") == sel_pf:
                    st.caption(f"Delete **{sel_pf}**? This cannot be undone.")
                    dc1, dc2 = st.columns(2)
                    with dc1:
                        if st.button("Yes, delete", key=f"pm_del_yes_{sel_pf}",
                                     type="primary", use_container_width=True):
                            del_portfolio_reg(sel_pf)
                            st.session_state.pm_confirm_delete   = None
                            st.session_state.pm_active_portfolio = None
                            st.rerun()
                    with dc2:
                        if st.button("Cancel", key=f"pm_del_no_{sel_pf}",
                                     use_container_width=True):
                            st.session_state.pm_confirm_delete = None
                            st.rerun()
                else:
                    if st.button("🗑️ Delete Portfolio", key=f"pm_del_{sel_pf}",
                                 use_container_width=True):
                        st.session_state.pm_confirm_delete = sel_pf
                        st.rerun()

        st.divider()

    st.markdown(
        "**How it works**\n"
        "1. Upload a PDF\n"
        "2. Text is extracted with pdfplumber\n"
        "3. Claude parses the financials\n"
        "4. Download a formatted Excel file"
    )
    st.divider()

    # --- Filing Library ------------------------------------------------
    st.markdown("""
    <style>
    section[data-testid="stSidebar"] .stButton button {
        padding: 1px 8px;
        font-size: 11px;
        line-height: 1.3;
        min-height: 0px;
    }
    </style>
    """, unsafe_allow_html=True)

    lib_entries = lib_get()
    lib_count   = len(lib_entries)
    label       = f"📚 Filing Library ({lib_count} filing{'s' if lib_count != 1 else ''})"
    with st.expander(label, expanded=lib_count > 0):
        if not lib_entries:
            st.caption("No filings saved yet. Analyse a PDF to add it here.")
        for entry in lib_entries:
            eid        = entry["id"]
            ticker     = entry.get("ticker", "—")
            ticker_str = f" · {ticker}" if ticker and ticker != "—" else ""
            fy         = entry.get("fiscal_year") or entry.get("period", "")[:20]
            date_str   = entry.get("analysed_at", "")[:10]
            st.markdown(
                f"<span style='font-size:13px;font-weight:700'>{entry['company_name']}{ticker_str}</span>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<small style='color:#888;font-size:11px'>{fy} · {date_str}</small>",
                unsafe_allow_html=True,
            )
            if st.button("Load", key=f"lib_load_{eid}", use_container_width=True):
                fd = entry["financial_data"]
                sd = entry.get("summary_data")
                bb = entry.get("bear_bull_data")
                st.session_state.financial_data      = fd
                st.session_state.summary_data        = sd
                st.session_state.bear_bull_data      = bb
                st.session_state.dashboard_data      = entry.get("dashboard_data")
                st.session_state.market_data         = {}
                st.session_state.excel_bytes         = create_excel_file(fd, sd, 0.0, bb)
                st.session_state.last_filename       = entry.get("file_name", "")
                st.session_state.resolved_ticker     = ticker if ticker != "—" else None
                st.session_state.cache_hit           = False
                st.session_state.loaded_from_library = True
                st.rerun()
            if st.button("♻️ Re-Analyse", key=f"lib_reanalyse_{eid}", use_container_width=True,
                         help="Re-analyse with fresh Claude calls"):
                st.session_state.confirm_reanalyse = eid
                st.session_state.confirm_delete    = None
                st.rerun()
            if st.button("🗑️ Remove", key=f"lib_del_{eid}", use_container_width=True,
                         help=f"Remove {entry['company_name']} from library"):
                st.session_state.confirm_delete    = eid
                st.session_state.confirm_reanalyse = None
                st.rerun()

            # --- Delete confirmation ---
            if st.session_state.get("confirm_delete") == eid:
                st.caption(f"Delete **{entry['company_name']}**? This cannot be undone.")
                yes_col, no_col = st.columns(2)
                with yes_col:
                    if st.button("Yes, delete", key=f"lib_del_yes_{eid}",
                                 use_container_width=True, type="primary"):
                        lib_delete(eid)
                        st.session_state.confirm_delete = None
                        st.rerun()
                with no_col:
                    if st.button("Cancel", key=f"lib_del_no_{eid}",
                                 use_container_width=True):
                        st.session_state.confirm_delete = None
                        st.rerun()

            # --- Re-analyse confirmation ---
            if st.session_state.get("confirm_reanalyse") == eid:
                st.caption(
                    f"Re-analyse **{entry['company_name']}**? This will run 4 Claude API calls "
                    f"(~$0.10–0.15 cost) and overwrite the existing result."
                )
                yes_col, no_col = st.columns(2)
                with yes_col:
                    if st.button("Yes, re-analyse", key=f"lib_ra_yes_{eid}",
                                 use_container_width=True, type="primary"):
                        st.session_state.confirm_reanalyse = None
                        if entry.get("raw_text"):
                            st.session_state.pending_reanalyse = {
                                "raw_text":     entry["raw_text"],
                                "company_name": entry["company_name"],
                                "entry_id":     eid,
                                "file_name":    entry.get("file_name", ""),
                                "file_size":    entry.get("file_size_bytes", 0),
                            }
                        else:
                            st.session_state.reanalyse_no_text = entry["company_name"]
                            st.session_state.uploader_key += 1
                        st.rerun()
                with no_col:
                    if st.button("Cancel", key=f"lib_ra_no_{eid}",
                                 use_container_width=True):
                        st.session_state.confirm_reanalyse = None
                        st.rerun()

            st.markdown(
                "<hr style='margin: 2px 0; border: none; border-top: 0.5px solid #e0e0e0;'>",
                unsafe_allow_html=True,
            )

    st.divider()
    n = cache_count()
    st.caption(f"Cache: {n} entr{'y' if n == 1 else 'ies'}" if n else "Cache: empty")
    if n:
        if st.button("Clear Cache", use_container_width=True):
            cleared = clear_cache()
            st.session_state.uploader_key += 1  # force file uploader to reset
            st.success(f"Cleared {cleared} cached entr{'y' if cleared == 1 else 'ies'}.")
            st.rerun()

# --- Portfolio Manager page --------------------------------------------
if page == "📈 Portfolio Manager":
    import pandas as pd

    st.subheader("📈 Portfolio Manager")

    pf_names = get_portfolio_names()
    if not pf_names:
        st.info("No portfolios yet. Create one in the sidebar to get started.")
        st.stop()

    if not selected_portfolio:
        st.info("Select or create a portfolio in the sidebar.")
        st.stop()

    tickers = get_tickers(selected_portfolio)
    if not tickers:
        st.info(f"**{selected_portfolio}** has no tickers yet. Add some via the sidebar.")
        st.stop()

    st.caption(
        f"Portfolio: **{selected_portfolio}** · "
        f"{len(tickers)} holding{'s' if len(tickers) != 1 else ''}"
    )

    with st.spinner(f"Fetching live market data for {len(tickers)} holding(s)…"):
        portfolio = get_portfolio_display_data(tickers)

    analysed = [r for r in portfolio if r["has_analysis"]]
    pass_n   = sum(1 for r in analysed if r["signal"] == "PASS")
    inv_n    = sum(1 for r in analysed if r["signal"] == "INVESTIGATE")
    dec_n    = sum(1 for r in analysed if r["signal"] == "DECLINE")
    avg_qs   = (sum(r["quality_score"] for r in analysed) / len(analysed)) if analysed else None

    # --- Section 1: Portfolio Summary ---
    st.markdown("##### Portfolio Summary")
    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("Holdings", len(tickers))
    s2.metric("🟢 PASS", pass_n)
    s3.metric("🟡 INVESTIGATE", inv_n)
    s4.metric("🔴 DECLINE", dec_n)
    qs_color = "#70AD47" if (avg_qs or 0) >= 70 else ("#FFC000" if (avg_qs or 0) >= 40 else "#C00000")
    with s5:
        qs_str = f"{avg_qs:.0f}" if avg_qs is not None else "—"
        st.markdown(
            f'<div style="border:1px solid #ddd;border-radius:6px;padding:8px 12px;text-align:center;margin-top:4px">'
            f'<div style="font-size:11px;color:#888">Avg Quality</div>'
            f'<div style="font-size:22px;font-weight:700;color:{qs_color}">{qs_str}</div>'
            f'<div style="font-size:10px;color:#aaa">/ 100</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.divider()

    # --- Section 2: Holdings Table ---
    st.markdown("##### Holdings")
    _SIG = {"PASS": "🟢 PASS", "INVESTIGATE": "🟡 INVESTIGATE", "DECLINE": "🔴 DECLINE"}

    def _fp(v):
        return f"{v:.1f}%" if v is not None else "—"

    table_rows = []
    for r in sorted(portfolio, key=lambda x: (x["quality_score"] is None, -(x["quality_score"] or 0))):
        table_rows.append({
            "Ticker":    r["ticker"],
            "Company":   r["company_name"],
            "Price":     f"${r['price']:,.2f}" if r["price"] else "—",
            "Mkt Cap":   _fmt_market_cap(r["market_cap"]),
            "P/E":       f"{r['pe_ratio']:.1f}x" if r["pe_ratio"] else "—",
            "Signal":    _SIG.get(r["signal"], "🔍 No analysis") if r["has_analysis"] else "🔍 No analysis",
            "Quality":   r["quality_score"] if r["has_analysis"] else None,
            "Lynch":     r["lynch_category"],
            "Red Flags": f"🔴 {r['red_flag_count']}  🟡 {r['yellow_flag_count']}" if r["has_analysis"] else "—",
        })

    st.dataframe(
        table_rows,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Quality": st.column_config.ProgressColumn(
                "Quality", min_value=0, max_value=100, format="%d",
            ),
        },
    )

    unanalysed = [r for r in portfolio if not r["has_analysis"]]
    if unanalysed:
        st.caption(
            f"💡 {len(unanalysed)} holding(s) have no FinLens analysis — "
            f"switch to 📊 Single Analysis and upload the filing PDF to add them."
        )

    if not analysed:
        st.info("No FinLens analysis available yet. Sections below require at least one analysed filing.")
        st.stop()

    st.divider()

    # --- Section 3: Risk Flags ---
    st.markdown("##### Risk Flags Across Portfolio")
    flag_left, flag_right = st.columns(2)
    flagged = [r for r in analysed if r["red_flag_count"] > 0 or r["yellow_flag_count"] > 0]

    with flag_left:
        if not flagged:
            st.success("No red or yellow flags across analysed holdings.")
        else:
            for r in flagged:
                st.markdown(f"**{r['company_name']} ({r['ticker']})**")
                if r["top_red_flag"]:
                    st.markdown(f"🔴 {r['top_red_flag']}")
                if r["yellow_flag_count"] > 0:
                    st.caption(f"+{r['yellow_flag_count']} yellow flag(s)")

    with flag_right:
        red_counts = {r["ticker"]: r["red_flag_count"] for r in analysed}
        if any(v > 0 for v in red_counts.values()):
            st.caption("Red flag count per holding")
            st.bar_chart(pd.DataFrame.from_dict(red_counts, orient="index", columns=["Red Flags"]))
        else:
            st.success("All analysed holdings: 0 red flags.")

    st.divider()

    # --- Section 4: Lynch Category Breakdown ---
    st.markdown("##### Lynch Category Breakdown")
    lynch_left, lynch_right = st.columns(2)
    lynch_counts = {}
    for r in analysed:
        lynch_counts[r["lynch_category"]] = lynch_counts.get(r["lynch_category"], 0) + 1

    with lynch_left:
        st.caption("Holdings per Lynch category")
        if lynch_counts:
            st.bar_chart(pd.DataFrame.from_dict(lynch_counts, orient="index", columns=["Count"]))

    with lynch_right:
        st.dataframe(
            [
                {
                    "Ticker":   r["ticker"],
                    "Category": r["lynch_category"],
                    "Story":    (r["lynch_story"] or "—")[:120],
                }
                for r in analysed
            ],
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    # --- Section 5: Framework Scores ---
    st.markdown("##### Framework Scores")
    st.dataframe(
        [
            {
                "Ticker":        r["ticker"],
                "Company":       r["company_name"],
                "Quality Score": r["quality_score"],
                "Dalio View":    (r["dalio_view"] or "—")[:100],
                "Marks View":    (r["marks_view"] or "—")[:100],
            }
            for r in analysed
        ],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Quality Score": st.column_config.ProgressColumn(
                "Quality Score", min_value=0, max_value=100, format="%d",
            ),
        },
    )

    st.stop()


# --- Single Analysis page ----------------------------------------------
if not API_KEY:
    st.error("ANTHROPIC_API_KEY not found. Add it to your .env file and restart the app.")
    st.stop()

# --- Ticker Lookup (Dev Tool) ------------------------------------------
with st.expander("🔍 Ticker Lookup (Dev Tool)", expanded=False):
    st.caption("Verify yfinance can find the right company before running a full analysis. No API calls, no cost.")
    with st.form("ticker_lookup_form"):
        tl_col1, tl_col2 = st.columns([3, 1])
        with tl_col1:
            lookup_query = st.text_input("Company name", placeholder="e.g. Mastech Digital")
        with tl_col2:
            st.write("")
            lookup_clicked = st.form_submit_button("Look Up Ticker", use_container_width=True)

    if lookup_clicked and lookup_query.strip():
        with st.spinner("Searching yfinance..."):
            try:
                quotes = search_ticker_details(lookup_query.strip())
            except Exception as e:
                st.error(f"Search failed: {e}")
                quotes = []

        if not quotes:
            st.warning("No results found. Try a different company name.")
        else:
            st.markdown("**Top Results**")
            st.dataframe(
                [
                    {
                        "Symbol":   q.get("symbol", "—"),
                        "Company":  q.get("longname") or q.get("shortname", "—"),
                        "Exchange": q.get("exchange", "—"),
                        "Type":     q.get("quoteType", "—"),
                    }
                    for q in quotes[:5]
                ],
                use_container_width=True,
                hide_index=True,
            )

            top_symbol = quotes[0].get("symbol")
            if top_symbol:
                st.markdown(f"**Market Data — {top_symbol}**")
                with st.spinner(f"Fetching market data for {top_symbol}..."):
                    md = get_market_data(top_symbol)
                if md.get("current_price"):
                    price = md["current_price"]
                    mc    = md.get("market_cap")
                    hi    = md.get("fifty_two_week_high")
                    lo    = md.get("fifty_two_week_low")
                    pe    = md.get("pe_ratio")
                    mc_col, pr_col, rng_col, pe_col = st.columns(4)
                    mc_col.metric("Price",          f"${price:,.2f}")
                    pr_col.metric("Market Cap",     _fmt_market_cap(mc))
                    rng_col.metric("52-week Range", f"${lo:,.2f} – ${hi:,.2f}" if (lo and hi) else "—")
                    pe_col.metric("P/E (trailing)", f"{pe:.1f}x" if pe else "—")
                else:
                    st.warning(f"'{top_symbol}' found but no market data — may be OTC or delisted.")
    elif lookup_clicked:
        st.warning("Enter a company name first.")

st.divider()

# --- Valuation inputs --------------------------------------------------
st.markdown("#### Valuation Inputs")
st.caption("Market cap is fetched automatically from yfinance when the filing contains a ticker. Enter sector and hurdle rate manually.")
vi_col1, vi_col2 = st.columns(2)
with vi_col1:
    sector = st.selectbox("Sector", [
        "Enterprise SaaS", "Specialty Retail", "IT Services",
        "Financial Services", "Upstream Oil & Gas", "Healthcare",
        "Consumer Staples", "Industrials", "Real Estate", "Other",
    ])
with vi_col2:
    hurdle_rate = st.number_input("Hurdle Rate (%)", min_value=0.0, max_value=100.0, value=12.0, step=0.5)
st.components.v1.html("""
<script>
  const inputs = window.parent.document.querySelectorAll('input[type=number]');
  inputs.forEach(input => input.addEventListener('focus', function() { this.select(); }));
</script>
""", height=0)
st.divider()

# --- Session state — persists results across Streamlit reruns ----------
if "financial_data" not in st.session_state:
    st.session_state.financial_data      = None
    st.session_state.summary_data        = None
    st.session_state.bear_bull_data      = None
    st.session_state.dashboard_data      = None
    st.session_state.market_data         = None
    st.session_state.excel_bytes         = None
    st.session_state.last_filename       = None
    st.session_state.resolved_ticker     = None
    st.session_state.cache_hit           = False
    st.session_state.loaded_from_library = False
    st.session_state.uploader_key        = 0

if "summary_data" not in st.session_state:
    st.session_state.summary_data = None

if "market_data" not in st.session_state:
    st.session_state.market_data = None

# --- Main area ---------------------------------------------------------
uploaded_file = st.file_uploader(
    "Upload Financial Statements PDF",
    type=["pdf"],
    help="Annual reports, 10-K filings, or standalone financial statement PDFs work best.",
    key=f"pdf_uploader_{st.session_state.uploader_key}",
)
# Clear stored results when the uploaded file changes.
# When data was loaded from the Filing Library there is no uploaded file,
# so we must NOT reset — library results should persist until the user
# explicitly uploads a different file.
if st.session_state.get("reanalyse_no_text"):
    st.info(f"Re-upload the PDF to re-analyse **{st.session_state.reanalyse_no_text}**.")

if uploaded_file is None:
    if not st.session_state.get("loaded_from_library"):
        st.session_state.financial_data  = None
        st.session_state.summary_data    = None
        st.session_state.bear_bull_data  = None
        st.session_state.dashboard_data  = None
        st.session_state.market_data     = None
        st.session_state.excel_bytes     = None
        st.session_state.resolved_ticker = None
        st.session_state.cache_hit       = False
elif (st.session_state.last_filename and
      uploaded_file.name != st.session_state.last_filename):
    # A different file was dropped in — always reset, including the flag.
    st.session_state.financial_data      = None
    st.session_state.summary_data        = None
    st.session_state.bear_bull_data      = None
    st.session_state.dashboard_data      = None
    st.session_state.market_data         = None
    st.session_state.excel_bytes         = None
    st.session_state.resolved_ticker     = None
    st.session_state.cache_hit           = False
    st.session_state.loaded_from_library = False

# --- Re-analyse from Filing Library (fires when ♻️ button sets pending_reanalyse) ---
if st.session_state.get("pending_reanalyse"):
    ra = st.session_state.pending_reanalyse
    st.info(f"Re-analysing **{ra['company_name']}** — running all 4 Claude calls fresh...")

    _ra_text = ra["raw_text"]

    with st.spinner("Call 1: Extracting financials (Haiku)..."):
        _ra_fd = analyze_financials(_ra_text, API_KEY)

    _ra_sd = None
    with st.spinner("Call 2: Generating investment signal..."):
        _ra_sd = analyze_summary(_ra_text, _ra_fd, API_KEY)

    _ra_bb = None
    with st.spinner("Call 3: Generating bull/bear case..."):
        _ra_bb = analyze_bear_bull(_ra_text, API_KEY)

    _ra_dd = None
    with st.spinner("Call 4: Generating dashboard insights..."):
        _ra_dd = analyze_dashboard_insights(_ra_text, _ra_sd, _ra_fd, API_KEY)

    try:
        lib_add(ra["entry_id"], ra["file_name"], ra["file_size"],
                _ra_fd, _ra_sd, _ra_bb, _ra_dd, raw_text=_ra_text)
    except Exception:
        pass

    st.session_state.financial_data      = _ra_fd
    st.session_state.summary_data        = _ra_sd
    st.session_state.bear_bull_data      = _ra_bb
    st.session_state.dashboard_data      = _ra_dd
    st.session_state.market_data         = {}
    st.session_state.excel_bytes         = create_excel_file(_ra_fd, _ra_sd, 0.0, _ra_bb)
    st.session_state.last_filename       = ra["file_name"]
    st.session_state.resolved_ticker     = None
    st.session_state.loaded_from_library = True
    st.session_state.pending_reanalyse   = None
    st.rerun()

if uploaded_file:
    if st.button("Analyze Financials", type="primary", use_container_width=True):

        st.session_state.reanalyse_no_text = None  # clear prompt once user starts upload

        pdf_bytes = uploaded_file.getvalue()
        cache_key = get_cache_key(pdf_bytes)
        cached    = load_cache(cache_key)
        raw_text  = None  # populated in non-cached path; stored in library for future re-analysis

        if cached:
            financial_data = cached["financial_data"]
            summary_data   = cached.get("summary_data")
            bear_bull_data = cached.get("bear_bull_data")
            dashboard_data = cached.get("dashboard_data")
            st.session_state.cache_hit = True
            st.success(f"Loaded **{uploaded_file.name}** from cache.")
        else:
            st.session_state.cache_hit = False

            # Step 1 — Extract PDF text
            with st.spinner("Extracting text from PDF..."):
                try:
                    raw_text = extract_text_from_pdf(uploaded_file)
                except Exception as e:
                    st.error(f"Could not read the PDF: {e}")
                    st.stop()

            char_count = len(raw_text)
            if char_count < 200:
                st.error("Very little text was extracted — the PDF may be scanned/image-based. Try a text-based PDF.")
                st.stop()

            st.success(f"Extracted {char_count:,} characters from **{uploaded_file.name}**")

            # Step 2 — Call 1: extract structured financials (claude-haiku)
            with st.spinner("Analyzing with Claude (this can take 30–60 seconds for large documents)..."):
                try:
                    financial_data = analyze_financials(raw_text, API_KEY)
                except Exception as e:
                    st.error(f"Claude analysis failed: {e}")
                    st.stop()

            # Step 3 — Call 2: generate investment signal
            summary_data = None
            with st.spinner("Generating investment signal — this may take 20–30 seconds..."):
                try:
                    summary_data = analyze_summary(raw_text, financial_data, API_KEY)
                except Exception as e:
                    st.warning(f"Investment signal could not be generated: {e}. The Excel report will be created without the Summary tab.")

            # Step 4 — Call 3: generate bull / bear case
            bear_bull_data = None
            with st.spinner("Generating bull/bear case — this may take 15–25 seconds..."):
                try:
                    bear_bull_data = analyze_bear_bull(raw_text, API_KEY)
                except Exception as e:
                    st.warning(f"Bull/bear case could not be generated: {e}.")

            # Step 5 — Call 4: generate dashboard insights (Dalio / Lynch / Marks)
            dashboard_data = None
            with st.spinner("Generating dashboard insights — this may take 15–20 seconds..."):
                try:
                    dashboard_data = analyze_dashboard_insights(
                        raw_text, summary_data, financial_data, API_KEY
                    )
                except Exception as e:
                    st.warning(f"Dashboard insights could not be generated: {e}.")

            save_cache(cache_key, uploaded_file.name, financial_data, summary_data,
                       bear_bull_data, dashboard_data)

        # Step 4 — Fetch market data; fall back to company-name search if filing has no ticker
        market_data = {}
        resolved_ticker = (summary_data or {}).get("ticker")

        if not resolved_ticker:
            company_name_search = financial_data.get("company_name", "")
            if company_name_search:
                with st.spinner(f"No ticker in filing — searching for '{company_name_search}'..."):
                    resolved_ticker = search_ticker(company_name_search)
                    if resolved_ticker:
                        st.info(f"Found ticker **{resolved_ticker}** via company name search.")

        if resolved_ticker:
            with st.spinner(f"Fetching market data for {resolved_ticker}..."):
                market_data = get_market_data(resolved_ticker)
                if not market_data.get("current_price"):
                    st.warning(f"Could not fetch market data for '{resolved_ticker}'.")

        market_cap = market_data.get("market_cap") or 0.0

        # Step 5 — Build Excel
        try:
            excel_bytes = create_excel_file(financial_data, summary_data, market_cap, bear_bull_data)
        except Exception as e:
            st.error(f"Could not generate Excel file: {e}")
            st.stop()

        st.session_state.financial_data      = financial_data
        st.session_state.summary_data        = summary_data
        st.session_state.bear_bull_data      = bear_bull_data
        st.session_state.dashboard_data      = dashboard_data
        st.session_state.market_data         = market_data
        st.session_state.excel_bytes         = excel_bytes
        st.session_state.last_filename       = uploaded_file.name
        st.session_state.resolved_ticker     = resolved_ticker
        st.session_state.loaded_from_library = False

        # Persist to Filing Library (permanent — survives cache clears).
        try:
            lib_add(cache_key, uploaded_file.name, len(pdf_bytes),
                    financial_data, summary_data, bear_bull_data, dashboard_data,
                    raw_text=raw_text[:MAX_FILING_CHARS] if raw_text else None)
        except Exception:
            pass  # Library write failure must never block analysis

        # Rerun so sidebar counts (cache + library) reflect the new entry.
        st.rerun()

# --- Display results (runs on every rerun as long as data is in state) -
if st.session_state.financial_data:
    financial_data  = st.session_state.financial_data
    excel_bytes     = st.session_state.excel_bytes
    market_data     = st.session_state.market_data or {}
    summary_data    = st.session_state.summary_data or {}
    bear_bull_data  = st.session_state.bear_bull_data or {}
    dashboard_data  = st.session_state.dashboard_data

    # If dashboard insights are missing (old library entry or failed Call 4 in the
    # upload pipeline), generate them now from the structured data we do have.
    # filing_text is unavailable here, so we pass "" — Claude uses financials + signal.
    if dashboard_data is None:
        with st.spinner("Generating dashboard insights — this may take 15–20 seconds..."):
            dashboard_data = analyze_dashboard_insights(
                "",
                st.session_state.summary_data,
                financial_data,
                API_KEY,
            )
            st.session_state.dashboard_data = dashboard_data

    company  = financial_data.get("company_name", "Results")
    period   = financial_data.get("period", "")
    currency = financial_data.get("currency", "")
    fy       = financial_data.get("fiscal_year", "Current Year")
    fy_prior = financial_data.get("fiscal_year_prior", "Prior Year")
    ticker   = st.session_state.get("resolved_ticker") or summary_data.get("ticker")

    st.subheader(company)
    st.caption(f"{period}  ·  {currency}")

    tab_stmts, tab_dash = st.tabs(["📊 Statements", "📈 Dashboard"])

    # =====================================================================
    with tab_stmts:
    # =====================================================================

        # --- Investment signal badge ---
        _BADGE_STYLE = {
            "PASS":        {"bg": "#70AD47", "color": "#FFFFFF"},
            "INVESTIGATE": {"bg": "#FFC000", "color": "#1F4E79"},
            "DECLINE":     {"bg": "#C00000", "color": "#FFFFFF"},
        }
        signal = (summary_data.get("signal") or "").upper()
        if signal in _BADGE_STYLE:
            s = _BADGE_STYLE[signal]
            st.markdown(
                f'<div style="display:inline-block;background:{s["bg"]};color:{s["color"]};'
                f'padding:8px 28px;border-radius:4px;font-size:18px;font-weight:700;'
                f'letter-spacing:1.5px;margin:6px 0 14px 0">{signal}</div>',
                unsafe_allow_html=True,
            )

        if st.session_state.get("cache_hit"):
            st.info("📦 Using cached response (dev mode) — no API call was made.")

        # --- Market data display or manual fallback ---
        if market_data.get("current_price"):
            price = market_data["current_price"]
            mc    = market_data["market_cap"]
            hi    = market_data.get("fifty_two_week_high")
            lo    = market_data.get("fifty_two_week_low")
            pe    = market_data.get("pe_ratio")

            price_str = f"${price:,.2f}"
            mc_str    = _fmt_market_cap(mc)
            range_str = f"${lo:,.2f} – ${hi:,.2f}" if (lo and hi) else "—"
            pe_str    = f"{pe:.1f}x" if pe else "—"

            st.info(
                f"**{ticker}**  ·  Price: {price_str}  ·  Mkt Cap: {mc_str}"
                f"  ·  52-week: {range_str}  ·  P/E (trailing): {pe_str}"
                f"  ·  *Data: yfinance, ~15-min delay*"
            )
            edgar_url = (
                f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                f"&CIK={ticker}&type=10-K&dateb=&owner=include&count=10"
            )
            st.markdown(
                f'<a href="{edgar_url}" target="_blank" '
                f'style="font-size:12px;color:#595959;text-decoration:none;">'
                f'&#128269; Find filings on SEC EDGAR</a>',
                unsafe_allow_html=True,
            )
        else:
            st.caption("Ticker not found — enter the exchange ticker to fetch live market data and populate valuation multiples.")
            tk_col, btn_col = st.columns([2, 1])
            with tk_col:
                manual_ticker = st.text_input("Ticker Symbol", placeholder="e.g. MHH, AAPL", key="manual_ticker")
            with btn_col:
                st.write("")
                if st.button("Fetch Market Data", use_container_width=True):
                    if manual_ticker.strip():
                        with st.spinner(f"Fetching market data for {manual_ticker.strip().upper()}..."):
                            fetched = get_market_data(manual_ticker.strip())
                            if fetched.get("current_price"):
                                st.session_state.market_data     = fetched
                                st.session_state.resolved_ticker = manual_ticker.strip().upper()
                                mc = fetched.get("market_cap") or 0.0
                                try:
                                    st.session_state.excel_bytes = create_excel_file(
                                        st.session_state.financial_data,
                                        st.session_state.summary_data,
                                        mc,
                                        st.session_state.bear_bull_data,
                                    )
                                except Exception as e:
                                    st.error(f"Could not regenerate Excel: {e}")
                                st.rerun()
                            else:
                                st.warning(f"No market data found for '{manual_ticker.strip()}' — check the ticker and try again.")
                    else:
                        st.warning("Enter a ticker symbol first.")

        # --- Red Flag Analysis ---
        flag_result  = detect_flags(financial_data)
        flags        = flag_result["flags"]
        red_count    = flag_result["red_count"]
        yellow_count = flag_result["yellow_count"]
        override     = flag_result["signal_override"]

        if red_count or yellow_count:
            exp_label = f"🚩 Red Flag Analysis  —  {red_count} red · {yellow_count} yellow"
        else:
            exp_label = "🟢 Red Flag Analysis  —  Clean"

        with st.expander(exp_label, expanded=(red_count > 0)):
            if not flags:
                st.success("No major red flags detected across all monitored thresholds.")
            else:
                if override:
                    claude_signal = (summary_data.get("signal") or "—").upper()
                    if override == claude_signal:
                        st.info(
                            f"Ratio analysis **confirms** Claude's **{claude_signal}** signal — "
                            f"{red_count} red flag(s), {yellow_count} yellow flag(s)."
                        )
                    else:
                        st.info(
                            f"**Signal override:** Ratio thresholds suggest **{override}** "
                            f"(Claude's signal: {claude_signal}) — "
                            f"{red_count} red flag(s), {yellow_count} yellow flag(s)."
                        )
                for flag in [f for f in flags if f["severity"] == "red"]:
                    st.error(f"🔴 **{flag['label']}** — {flag['detail']}")
                for flag in [f for f in flags if f["severity"] == "yellow"]:
                    st.warning(f"🟡 **{flag['label']}** — {flag['detail']}")

        # --- Financial statement tables ---
        col_cfg = {
            "line_item":   st.column_config.TextColumn("Line Item"),
            "value_prior": st.column_config.NumberColumn(fy_prior, format="%.0f"),
            "value":       st.column_config.NumberColumn(fy,       format="%.0f"),
        }

        def _display_rows(rows):
            return [
                {"line_item": r.get("line_item"), "value_prior": r.get("value_prior"), "value": r.get("value")}
                for r in rows
            ]

        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("**Income Statement**")
            rows = financial_data.get("income_statement", [])
            if rows:
                st.dataframe(_display_rows(rows), column_config=col_cfg, use_container_width=True, hide_index=True)
            else:
                st.info("Not found in document.")

        with col2:
            st.markdown("**Balance Sheet**")
            rows = financial_data.get("balance_sheet", [])
            if rows:
                st.dataframe(_display_rows(rows), column_config=col_cfg, use_container_width=True, hide_index=True)
            else:
                st.info("Not found in document.")

        with col3:
            st.markdown("**Cash Flow Statement**")
            rows = financial_data.get("cash_flow_statement", [])
            if rows:
                st.dataframe(_display_rows(rows), column_config=col_cfg, use_container_width=True, hide_index=True)
            else:
                st.info("Not found in document.")

        # --- Bull / Bear Case ---
        if bear_bull_data and "error" not in bear_bull_data:
            with st.expander("Bull / Bear Case", expanded=False):
                bull_col, bear_col = st.columns(2)
                with bull_col:
                    st.markdown("**Bull Case**")
                    for pt in (bear_bull_data.get("bull_case") or [])[:3]:
                        st.markdown(f"**{pt.get('title', '')}**")
                        st.caption(pt.get("detail", ""))
                with bear_col:
                    st.markdown("**Bear Case**")
                    for pt in (bear_bull_data.get("bear_case") or [])[:3]:
                        st.markdown(f"**{pt.get('title', '')}**")
                        st.caption(pt.get("detail", ""))

        # --- Download buttons ---
        st.divider()
        filename      = f"FinLens_{company.replace(' ', '_')}_{fy}.xlsx"
        memo_filename = f"FinLens_Memo_{company.replace(' ', '_')}_{fy}.docx"

        try:
            memo_bytes = create_memo(financial_data, summary_data, bear_bull_data, market_data, flag_result)
        except Exception as e:
            memo_bytes = None
            st.warning(f"Memo generation failed: {e}")

        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            st.download_button(
                label="Download FinLens Report",
                data=excel_bytes,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                type="primary",
            )
        with dl_col2:
            if memo_bytes:
                st.download_button(
                    label="Download Investment Memo",
                    data=memo_bytes,
                    file_name=memo_filename,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                    type="secondary",
                )

    # =====================================================================
    with tab_dash:
    # =====================================================================

        metrics = _calc_summary_metrics(financial_data)
        dd = dashboard_data if dashboard_data and "error" not in dashboard_data else {}

        if dashboard_data and "error" in dashboard_data:
            st.error(
                f"Dashboard insights could not be generated: "
                f"{dashboard_data['error']}  \n"
                f"Re-analyse the filing to try again. "
                f"Ratio metrics and stress scenarios below are still available."
            )
        elif not dashboard_data:
            st.warning(
                "Dashboard insights were not generated for this filing. "
                "Re-analyse to run Call 4 (Dalio / Lynch / Marks frameworks)."
            )

        # --- Section 1: Header — Signal badge, thesis, Quality Score, Beta, MoS ---
        sig_col, qs_col, beta_col, mos_col = st.columns([3, 2, 2, 2])

        with sig_col:
            _BADGE_STYLE_D = {
                "PASS":        {"bg": "#70AD47", "color": "#FFFFFF"},
                "INVESTIGATE": {"bg": "#FFC000", "color": "#1F4E79"},
                "DECLINE":     {"bg": "#C00000", "color": "#FFFFFF"},
            }
            signal_d = (summary_data.get("signal") or "").upper()
            if signal_d in _BADGE_STYLE_D:
                s = _BADGE_STYLE_D[signal_d]
                st.markdown(
                    f'<div style="display:inline-block;background:{s["bg"]};color:{s["color"]};'
                    f'padding:6px 22px;border-radius:4px;font-size:16px;font-weight:700;'
                    f'letter-spacing:1.5px;margin:4px 0 6px 0">{signal_d}</div>',
                    unsafe_allow_html=True,
                )
            thesis = summary_data.get("thesis") or ""
            if thesis:
                st.caption(thesis[:300])

        qs = _quality_score(metrics)
        qs_color = "#70AD47" if qs >= 70 else ("#FFC000" if qs >= 40 else "#C00000")

        with qs_col:
            st.markdown(
                f'<div style="border:1px solid #ddd;border-radius:6px;padding:12px 16px;text-align:center">'
                f'<div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px">Quality Score</div>'
                f'<div style="font-size:28px;font-weight:700;color:{qs_color}">{qs}</div>'
                f'<div style="font-size:10px;color:#aaa">/ 100</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        with beta_col:
            beta_val = market_data.get("beta")
            beta_str = f"{beta_val:.2f}" if beta_val else "—"
            st.markdown(
                f'<div style="border:1px solid #ddd;border-radius:6px;padding:12px 16px;text-align:center">'
                f'<div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px">Beta</div>'
                f'<div style="font-size:28px;font-weight:700">{beta_str}</div>'
                f'<div style="font-size:10px;color:#aaa">market sensitivity</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        with mos_col:
            st.markdown(
                f'<div style="border:1px solid #ddd;border-radius:6px;padding:12px 16px;text-align:center">'
                f'<div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px">Margin of Safety</div>'
                f'<div style="font-size:28px;font-weight:700">—</div>'
                f'<div style="font-size:10px;color:#aaa">DCF required</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.divider()

        # --- Section 2: Manager Framework Banners ---
        st.markdown("##### Framework Perspectives")
        fw_dalio, fw_lynch, fw_marks = st.columns(3)

        with fw_dalio:
            dalio_text = dd.get("dalio_view") or "Re-analyse to generate Dalio view."
            st.markdown(
                f'<div style="background:#EEEDFE;border-radius:8px;padding:16px 18px">'
                f'<div style="font-size:12px;font-weight:700;color:#5B4FCF;margin-bottom:8px;'
                f'text-transform:uppercase;letter-spacing:0.5px">Dalio — All Weather</div>'
                f'<div style="font-size:14px;color:#333;line-height:1.5">{dalio_text}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        with fw_lynch:
            lynch_cat  = dd.get("lynch_category") or ""
            lynch_text = dd.get("lynch_story") or "Re-analyse to generate Lynch view."
            cat_suffix = f" ({lynch_cat})" if lynch_cat else ""
            st.markdown(
                f'<div style="background:#E1F5EE;border-radius:8px;padding:16px 18px">'
                f'<div style="font-size:12px;font-weight:700;color:#217A4B;margin-bottom:8px;'
                f'text-transform:uppercase;letter-spacing:0.5px">Lynch — One Up{cat_suffix}</div>'
                f'<div style="font-size:14px;color:#333;line-height:1.5">{lynch_text}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        with fw_marks:
            marks_text = dd.get("marks_view") or "Re-analyse to generate Marks view."
            st.markdown(
                f'<div style="background:#FAEEDA;border-radius:8px;padding:16px 18px">'
                f'<div style="font-size:12px;font-weight:700;color:#B06000;margin-bottom:8px;'
                f'text-transform:uppercase;letter-spacing:0.5px">Marks — Second Level</div>'
                f'<div style="font-size:14px;color:#333;line-height:1.5">{marks_text}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.divider()

        # --- Section 3: Key Metrics Row ---
        st.markdown("##### Key Metrics")
        m1, m2, m3, m4, m5 = st.columns(5)

        rev_c    = metrics.get("rev_c")
        yoy_rev  = metrics.get("yoy_rev")
        gp_m     = metrics.get("gp_margin")
        ebitda_m = metrics.get("ebitda_margin")
        ni_c     = metrics.get("ni_c")
        ni_m     = metrics.get("ni_margin")
        fcf_c    = metrics.get("fcf_c")

        def _fmt_num(v):
            if v is None:
                return "—"
            if abs(v) >= 1_000_000:
                return f"{v / 1_000_000:,.1f}M"
            if abs(v) >= 1_000:
                return f"{v / 1_000:,.0f}K"
            return f"{v:,.0f}"

        def _fmt_pct(v):
            return f"{v:.1f}%" if v is not None else None

        with m1:
            st.metric("Revenue", _fmt_num(rev_c), _fmt_pct(yoy_rev))
        with m2:
            st.metric("Gross Margin", _fmt_pct(gp_m) or "—")
        with m3:
            st.metric("EBITDA Margin", _fmt_pct(ebitda_m) or "—")
        with m4:
            st.metric("Net Income", _fmt_num(ni_c), _fmt_pct(ni_m))
        with m5:
            st.metric("Free Cash Flow", _fmt_num(fcf_c))

        st.divider()

        # --- Section 4: Financial Health (RAG) | Capital Allocation ---
        rag_col, cap_col = st.columns(2)

        with rag_col:
            with st.container(border=True):
                st.markdown("##### Financial Health")
                rag_items = [
                    ("Liquidity",      "liquidity",  metrics.get("current_ratio")),
                    ("Leverage",       "leverage",   metrics.get("nd_ebitda")),
                    ("Revenue Growth", "rev_growth", metrics.get("rev_growth")),
                    ("FCF Conversion", "fcf_conv",   metrics.get("fcf_conv")),
                    ("Interest Cover", "int_cover",  metrics.get("int_cover")),
                ]
                for lbl, key, val in rag_items:
                    bg, rag_lbl = _dash_rag(key, val)
                    if val is None:
                        val_str = "—"
                    elif key in ("rev_growth", "fcf_conv"):
                        val_str = f"{val:.1f}%"
                    else:
                        val_str = f"{val:.2f}"
                    lbl_color = "#fff" if rag_lbl == "RED" else "#333"
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;align-items:center;'
                        f'padding:7px 4px;border-bottom:1px solid #f0f0f0">'
                        f'<span style="font-size:14px">{lbl}</span>'
                        f'<span>'
                        f'<span style="font-size:13px;margin-right:10px;color:#555">{val_str}</span>'
                        f'<span style="background:{bg};color:{lbl_color};padding:2px 10px;'
                        f'border-radius:3px;font-size:11px;font-weight:700">{rag_lbl}</span>'
                        f'</span></div>',
                        unsafe_allow_html=True,
                    )

        with cap_col:
            with st.container(border=True):
                st.markdown("##### Capital Allocation")
                cap_items = dd.get("capital_allocation") or []
                if cap_items:
                    for item in cap_items[:5]:
                        if isinstance(item, dict):
                            # prompt returns "label"/"value"; fall back to "title"/"detail" for safety
                            title  = item.get("label") or item.get("title", "")
                            detail = item.get("value") or item.get("detail", "")
                        else:
                            title, detail = str(item), ""
                        st.markdown(f"**{title}**")
                        if detail:
                            st.caption(detail)
                else:
                    st.caption("Re-analyse to generate capital allocation insights.")

        st.divider()

        # --- Section 5: Lynch Category | Lynch Story ---
        lc_col, ls_col = st.columns(2)

        with lc_col:
            with st.container(border=True):
                st.markdown("##### Lynch Category")
                cat = dd.get("lynch_category") or "—"
                st.markdown(f"**{cat}**")
                _LYNCH_DESCS = {
                    "Slow Grower":   "Low growth, often pays dividends. Watch for declining market share.",
                    "Stalwart":      "10–12% growers. Buy below P/E-to-growth rate; low institutional ownership.",
                    "Fast Grower":   "20–25% growers. Verify the niche, check balance sheet and P/E-to-growth.",
                    "Cyclical":      "Revenue tied to economic cycle. Buy at high P/E (trough), sell at low P/E (peak).",
                    "Turnaround":    "Depressed company with restructuring potential. Catalyst required.",
                    "Asset Play":    "Hidden balance sheet value overlooked by the market.",
                }
                desc = _LYNCH_DESCS.get(cat, "")
                if desc:
                    st.caption(desc)

        with ls_col:
            with st.container(border=True):
                st.markdown("##### Lynch Story")
                story = dd.get("lynch_story") or "Re-analyse to generate Lynch story."
                st.write(story)

        st.divider()

        # --- Section 6: Market Sentiment | Second-Level Question ---
        crowd_col, marks_col = st.columns(2)

        with crowd_col:
            with st.container(border=True):
                st.markdown("##### Market Sentiment (Marks)")
                crowd = dd.get("crowd_thinks") or "Re-analyse to generate sentiment view."
                st.write(crowd)

        with marks_col:
            with st.container(border=True):
                st.markdown("##### Second-Level Question")
                mq = dd.get("marks_question") or "Re-analyse to generate Marks question."
                st.write(mq)
                st.caption("Margin of Safety: — (DCF required)")

        st.divider()

        # --- Section 7: Dalio Stress Scenarios | Market Sensitivity ---
        stress_col, beta_col2 = st.columns(2)
        ic = metrics.get("int_cover")

        with stress_col:
            with st.container(border=True):
                st.markdown("##### Dalio Stress Scenarios")
                st.caption("Interest coverage (OI / Interest Expense) under stress")
                scenarios = [
                    ("EBIT –30%",             None if ic is None else ic * 0.70),
                    ("EBIT –60%",             None if ic is None else ic * 0.40),
                    ("Revenue –20% + Margin", None if ic is None else ic * 0.56),
                    ("Credit Seizure",        None if ic is None else ic * 0.50),
                ]
                for scen_name, stressed_ic in scenarios:
                    if stressed_ic is None:
                        status, bg, lbl_c = "N/A", "#D9D9D9", "#333"
                    elif stressed_ic >= 3.0:
                        status, bg, lbl_c = "SAFE", "#70AD47", "#fff"
                    elif stressed_ic >= 1.5:
                        status, bg, lbl_c = "WATCH", "#FFC000", "#333"
                    elif stressed_ic >= 1.0:
                        status, bg, lbl_c = "STRESS", "#FF8C00", "#fff"
                    else:
                        status, bg, lbl_c = "DISTRESS", "#C00000", "#fff"
                    ic_str = f"{stressed_ic:.1f}x" if stressed_ic is not None else "—"
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;align-items:center;'
                        f'padding:7px 4px;border-bottom:1px solid #f0f0f0">'
                        f'<span style="font-size:14px">{scen_name}</span>'
                        f'<span>'
                        f'<span style="font-size:13px;margin-right:10px;color:#555">{ic_str}</span>'
                        f'<span style="background:{bg};color:{lbl_c};padding:2px 10px;'
                        f'border-radius:3px;font-size:11px;font-weight:700">{status}</span>'
                        f'</span></div>',
                        unsafe_allow_html=True,
                    )

        with beta_col2:
            with st.container(border=True):
                st.markdown("##### Market Sensitivity (Beta)")
                b = market_data.get("beta")
                if b:
                    if b < 0.8:
                        interp = "Defensive — moves less than the market. Suitable for All-Weather positioning."
                    elif b < 1.2:
                        interp = "Market-neutral — tracks the index closely."
                    elif b < 1.8:
                        interp = "Cyclical — amplifies market moves. Higher upside, higher drawdown risk."
                    else:
                        interp = "High-beta — significantly more volatile than the market. Position size carefully."
                    st.metric("Beta (5Y Monthly)", f"{b:.2f}")
                    st.caption(interp)
                else:
                    st.caption("Beta not available — market data not loaded.")
                    st.caption("Fetch market data via the ticker lookup to populate this section.")

        st.divider()

        # --- Section 8: Variant Perception | Valuation Snapshot ---
        vp_col, val_col = st.columns([2, 1])

        with vp_col:
            with st.container(border=True):
                st.markdown("##### Variant Perception")
                st.caption("What does the market believe vs. what the data suggests?")
                crowd_txt = dd.get("crowd_thinks") or ""
                marks_q   = dd.get("marks_question") or ""
                if crowd_txt:
                    st.markdown(f"**Consensus view:** {crowd_txt}")
                if marks_q:
                    st.markdown(f"**What the market isn't asking:** {marks_q}")
                if not crowd_txt and not marks_q:
                    st.caption("Re-analyse to generate variant perception insights.")

        with val_col:
            with st.container(border=True):
                st.markdown("##### Valuation Snapshot")
                mc_val       = market_data.get("market_cap")
                pe_val       = market_data.get("pe_ratio")
                ebitda_c_val = metrics.get("ebitda_c")
                rev_c_val    = metrics.get("rev_c")

                ev_ebitda = None
                ev_rev    = None
                if mc_val and ebitda_c_val and ebitda_c_val > 0:
                    ev_ebitda = (mc_val * 1_000_000) / ebitda_c_val
                if mc_val and rev_c_val and rev_c_val > 0:
                    ev_rev = (mc_val * 1_000_000) / rev_c_val

                for vname, vval in [
                    ("P/E",        f"{pe_val:.1f}x"    if pe_val    else "—"),
                    ("EV/EBITDA",  f"{ev_ebitda:.1f}x" if ev_ebitda else "—"),
                    ("EV/Revenue", f"{ev_rev:.2f}x"    if ev_rev    else "—"),
                    ("MoS",        "—"),
                ]:
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;padding:5px 4px;'
                        f'border-bottom:1px solid #f0f0f0">'
                        f'<span style="font-size:14px;color:#555">{vname}</span>'
                        f'<span style="font-size:14px;font-weight:700">{vval}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

        st.divider()

        # --- Section 9: Bull / Bear with Framework Attribution ---
        st.markdown("##### Framework-Attributed Cases")
        bull_fw_col, bear_fw_col = st.columns(2)

        bull_cases = (bear_bull_data or {}).get("bull_case") or []
        bear_cases = (bear_bull_data or {}).get("bear_case") or []
        _BULL_FW = ["Lynch", "Marks", "Dalio"]
        _BEAR_FW = ["Marks", "Dalio", "Lynch"]

        with bull_fw_col:
            st.markdown("**Bull Case**")
            for i, pt in enumerate(bull_cases[:3]):
                fw     = _BULL_FW[i] if i < len(_BULL_FW) else ""
                title  = pt.get("title", "")
                detail = pt.get("detail", "")
                st.markdown(
                    f'<div style="background:#F0F7EC;border-left:4px solid #70AD47;'
                    f'padding:10px 14px;margin-bottom:8px;border-radius:0 6px 6px 0">'
                    f'<div style="font-size:11px;color:#4A7C35;font-weight:700;text-transform:uppercase;'
                    f'letter-spacing:0.5px;margin-bottom:4px">{fw}</div>'
                    f'<div style="font-size:14px;font-weight:600;margin-bottom:4px">{title}</div>'
                    f'<div style="font-size:13px;color:#555">{detail}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            if not bull_cases:
                st.caption("Re-analyse to generate bull case.")

        with bear_fw_col:
            st.markdown("**Bear Case**")
            for i, pt in enumerate(bear_cases[:3]):
                fw     = _BEAR_FW[i] if i < len(_BEAR_FW) else ""
                title  = pt.get("title", "")
                detail = pt.get("detail", "")
                st.markdown(
                    f'<div style="background:#FDF2F2;border-left:4px solid #C00000;'
                    f'padding:10px 14px;margin-bottom:8px;border-radius:0 6px 6px 0">'
                    f'<div style="font-size:11px;color:#8B0000;font-weight:700;text-transform:uppercase;'
                    f'letter-spacing:0.5px;margin-bottom:4px">{fw}</div>'
                    f'<div style="font-size:14px;font-weight:600;margin-bottom:4px">{title}</div>'
                    f'<div style="font-size:13px;color:#555">{detail}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            if not bear_cases:
                st.caption("Re-analyse to generate bear case.")

        st.caption("Powered by Dalio · Lynch · Marks frameworks")

else:
    if not uploaded_file:
        st.info("Upload a PDF above to get started.")
