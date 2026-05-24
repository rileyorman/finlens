import pdfplumber


def extract_text_from_pdf(uploaded_file) -> str:
    """Extract all text from an uploaded Streamlit PDF file object."""
    pages = []
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n\n".join(pages)
