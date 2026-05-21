import os
import streamlit as st
from dotenv import load_dotenv

from modules.pdf_extractor import extract_text_from_pdf
from modules.claude_analyzer import analyze_financials
from modules.excel_exporter import create_excel_file

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

# --- Session state — persists results across Streamlit reruns ----------
# Without this, results (including the download button) disappear the
# moment the user interacts with anything on the page after analysis.
if "financial_data" not in st.session_state:
    st.session_state.financial_data = None
    st.session_state.excel_bytes    = None
    st.session_state.last_filename  = None

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

        # Step 2 — Send to Claude
        with st.spinner("Analyzing with Claude (this can take 30–60 seconds for large documents)..."):
            try:
                financial_data = analyze_financials(raw_text, API_KEY)
            except Exception as e:
                st.error(f"Claude analysis failed: {e}")
                st.stop()

        # Step 3 — Build Excel and store everything in session state
        try:
            excel_bytes = create_excel_file(financial_data)
        except Exception as e:
            st.error(f"Could not generate Excel file: {e}")
            st.stop()

        st.session_state.financial_data = financial_data
        st.session_state.excel_bytes    = excel_bytes
        st.session_state.last_filename  = uploaded_file.name

# --- Display results (runs on every rerun as long as data is in state) -
if st.session_state.financial_data:
    financial_data = st.session_state.financial_data
    excel_bytes    = st.session_state.excel_bytes

    company  = financial_data.get("company_name", "Results")
    period   = financial_data.get("period", "")
    currency = financial_data.get("currency", "")
    fy       = financial_data.get("fiscal_year", "Current Year")
    fy_prior = financial_data.get("fiscal_year_prior", "Prior Year")

    st.subheader(company)
    st.caption(f"{period}  ·  {currency}")

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

    # --- Download button -----------------------------------------------
    st.divider()
    filename = f"FinLens_{company.replace(' ', '_')}_{fy}.xlsx"
    st.download_button(
        label="⬇ Download FinLens Report",
        data=excel_bytes,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        type="primary",
    )

else:
    if not uploaded_file:
        st.info("Upload a PDF above to get started.")
