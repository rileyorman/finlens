"""Campaign PDF path resolution."""
from __future__ import annotations

from pathlib import Path, PureWindowsPath
from typing import Any

from config import LIBRARY_PDFS_DIR


def campaign_pdf_candidate(registry_entry: dict[str, Any] | None) -> Path | None:
    """Build the single canonical campaign PDF candidate path."""
    source_pdf_path = (registry_entry or {}).get("source_pdf_path")
    if not source_pdf_path:
        return None

    filename = PureWindowsPath(source_pdf_path).name
    return LIBRARY_PDFS_DIR / filename


def resolve_campaign_pdf(registry_entry: dict[str, Any] | None) -> Path | None:
    """Resolve the recorded campaign PDF filename in the canonical PDF root."""
    candidate = campaign_pdf_candidate(registry_entry)
    if candidate is None:
        return None
    if candidate.is_file():
        return candidate
    return None
