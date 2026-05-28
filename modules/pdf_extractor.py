import gc

import pdfplumber

# Limit page extraction to avoid memory exhaustion on Streamlit Cloud free tier.
# Annual reports always contain financials in the first half; 150 pages is sufficient.
MAX_PAGES = 150
BATCH_SIZE = 20  # pages per chunk; release memory between batches


def extract_text_from_pdf(uploaded_file) -> str:
    """Extract text from a PDF, capped at MAX_PAGES pages.

    Processes pages in batches of BATCH_SIZE to keep peak memory low — important
    for Streamlit Cloud's free tier which has a ~1 GB RAM limit.
    """
    all_text: list[str] = []

    with pdfplumber.open(uploaded_file) as pdf:
        page_limit = min(len(pdf.pages), MAX_PAGES)

        for batch_start in range(0, page_limit, BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, page_limit)
            batch_text: list[str] = []

            for i in range(batch_start, batch_end):
                page = pdf.pages[i]
                text = page.extract_text()
                if text:
                    batch_text.append(text)
                del page  # drop reference so GC can reclaim the page object

            all_text.extend(batch_text)
            del batch_text
            gc.collect()  # explicitly free batch memory before loading next chunk

    return "\n\n".join(all_text)
