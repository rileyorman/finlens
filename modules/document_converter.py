import logging
from markitdown import MarkItDown

logger = logging.getLogger(__name__)


def convert_to_markdown(file_path: str) -> str | None:
    """Convert a file (e.g. .docx) to plain Markdown text using MarkItDown.

    Returns the converted text string, or None if conversion fails.
    """
    try:
        md = MarkItDown()
        result = md.convert(file_path)
        return result.text_content
    except Exception as e:
        logger.warning(f"document_converter: failed to convert '{file_path}': {e}")
        return None
