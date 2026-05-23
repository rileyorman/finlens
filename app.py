import os
import streamlit as st
from dotenv import load_dotenv

from modules.pdf_extractor import extract_text_from_pdf
from modules.claude_analyzer import analyze_financials, analyze_summary
from modules.excel_exporter import create_excel_file
from modules.market_data import get_market_data

load_dotenv()

API_KEY = os.getenv("ANTHROPIC_API_KEY")

st.set_page_config(
    page_title="FinLens",
    page_icon="📊",
    layout="wide",
)

st.title("FinLens")
st.caption("AI-powered financial statement analysis. Upload a PDF to extract key financials and download a structured Excel report.")

# --- Sidebar -----------------------------------------------------------
with st.sidebar:
    st.markdown(
        "**How it works**\n"
        "1. Upload a PDF\n"
        "2. Text is extracted with pdfplumber\n"
        "3. Claude parses the financials\n"
        "4. Download a formatted Excel file"
    )

if not API_KEY:
    st.error("ANTHROPIC_API_KEY not found. Add it to your .env file and restart the app.")
    st.stop()

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
    st.session_state.financial_data = None
    st.session_state.summary_data   = None
    st.session_state.market_data    = None
    st.session_state.excel_bytes    = None
    st.session_state.last_filename  = None

if "summary_data" not in st.session_state:
    st.session_state.summary_data = None

if "market_data" not in st.session_state:
    st.session_state.market_data = None

# --- Main area ---------------------------------------------------------
uploaded_file = st.file_uploader(
    "Upload Financial Statements PDF",
    type=["pdf"],
    help="Annual reports, 10-K filings, or standalone financial statement PDFs work best.",
)
# Clear stored results when a new file is uploaded
if uploaded_file is None or (
    st.session_state.last_filename and
    uploaded_file.name != st.session_state.last_filename
):
    st.session_state.financial_data = None
    st.session_state.summary_data   = None
    st.session_state.market_data    = None
    st.session_state.excel_bytes    = None

if uploaded_file:
    if st.button("Analyze Financials", type="primary", use_container_width=True):

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

        # Step 3 — Call 2: generate investment signal (claude-opus-4-7)
        summary_data = None
        with st.spinner("Generating investment signal — this may take 20–30 seconds..."):
            try:
                summary_data = analyze_summary(raw_text, financial_data, API_KEY)
            except Exception as e:
                st.warning(f"Investment signal could not be generated: {e}. The Excel report will be created without the Summary tab.")

        # Step 4 — Fetch market data from yfinance using ticker from Call 2
        market_data = {}
        ticker = (summary_data or {}).get("ticker")
        if ticker:
            with st.spinner(f"Fetching market data for {ticker}..."):
                market_data = get_market_data(ticker)
                if not market_data.get("current_price"):
                    st.warning(f"Could not fetch market data for '{ticker}' — enter market cap manually below if needed.")

        market_cap = market_data.get("market_cap") or 0.0

        # Step 5 — Build Excel
        try:
            excel_bytes = create_excel_file(financial_data, summary_data, market_cap)
        except Exception as e:
            st.error(f"Could not generate Excel file: {e}")
            st.stop()

        st.session_state.financial_data = financial_data
        st.session_state.summary_data   = summary_data
        st.session_state.market_data    = market_data
        st.session_state.excel_bytes    = excel_bytes
        st.session_state.last_filename  = uploaded_file.name

# --- Display results (runs on every rerun as long as data is in state) -
if st.session_state.financial_data:
    financial_data = st.session_state.financial_data
    excel_bytes    = st.session_state.excel_bytes
    market_data    = st.session_state.market_data or {}
    summary_data   = st.session_state.summary_data or {}

    company  = financial_data.get("company_name", "Results")
    period   = financial_data.get("period", "")
    currency = financial_data.get("currency", "")
    fy       = financial_data.get("fiscal_year", "Current Year")
    fy_prior = financial_data.get("fiscal_year_prior", "Prior Year")
    ticker   = summary_data.get("ticker")

    st.subheader(company)
    st.caption(f"{period}  ·  {currency}")

    # --- Market data display or manual fallback ----------------------------
    if market_data.get("current_price"):
        price = market_data["current_price"]
        mc    = market_data["market_cap"]
        hi    = market_data.get("fifty_two_week_high")
        lo    = market_data.get("fifty_two_week_low")
        pe    = market_data.get("pe_ratio")

        price_str = f"${price:,.2f}"
        mc_str    = f"${mc:,.0f}M" if mc else "—"
        range_str = f"${lo:,.2f} – ${hi:,.2f}" if (lo and hi) else "—"
        pe_str    = f"{pe:.1f}x" if pe else "—"

        st.info(
            f"**{ticker}**  ·  Price: {price_str}  ·  Mkt Cap: {mc_str}"
            f"  ·  52-week: {range_str}  ·  P/E (trailing): {pe_str}"
            f"  ·  *Data: yfinance, ~15-min delay*"
        )
    else:
        st.caption("Ticker not found in filing — enter market cap manually to populate valuation multiples in Excel.")
        mc_col, btn_col = st.columns([2, 1])
        with mc_col:
            manual_mc = st.number_input("Market Cap ($M)", min_value=0.0, value=0.0, step=100.0, key="manual_mc")
        with btn_col:
            st.write("")  # vertical alignment spacer
            if st.button("Update Excel", use_container_width=True):
                try:
                    st.session_state.excel_bytes = create_excel_file(
                        st.session_state.financial_data,
                        st.session_state.summary_data,
                        manual_mc,
                    )
                    excel_bytes = st.session_state.excel_bytes
                except Exception as e:
                    st.error(f"Could not regenerate Excel: {e}")

    # --- Financial statement tables ----------------------------------------
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

    # --- Download button ---------------------------------------------------
    st.divider()
    filename = f"FinLens_{company.replace(' ', '_')}_{fy}.xlsx"
    st.download_button(
        label="Download FinLens Report",
        data=excel_bytes,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        type="primary",
    )

else:
    if not uploaded_file:
        st.info("Upload a PDF above to get started.")
