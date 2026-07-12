"""Campaign PDF path resolution."""
from __future__ import annotations

from pathlib import Path, PureWindowsPath
from typing import Any

from config import LIBRARY_PDFS_DIR


def _pdf_candidate(registry_entry: dict[str, Any] | None, path_key: str) -> Path | None:
    """Build a canonical PDF candidate path from a registry-entry path field.

    Only the bare filename of the recorded path is trusted; it is always
    resolved under the canonical PDF root (foreign directories in stale
    registry entries must not escape the root).
    """
    recorded_path = (registry_entry or {}).get(path_key)
    if not recorded_path:
        return None

    filename = PureWindowsPath(recorded_path).name
    return LIBRARY_PDFS_DIR / filename


def _resolve_pdf(registry_entry: dict[str, Any] | None, path_key: str) -> Path | None:
    candidate = _pdf_candidate(registry_entry, path_key)
    if candidate is None:
        return None
    if candidate.is_file():
        return candidate
    return None


def campaign_pdf_candidate(registry_entry: dict[str, Any] | None) -> Path | None:
    """Build the single canonical campaign PDF candidate path."""
    return _pdf_candidate(registry_entry, "source_pdf_path")


def resolve_campaign_pdf(registry_entry: dict[str, Any] | None) -> Path | None:
    """Resolve the recorded campaign PDF filename in the canonical PDF root."""
    return _resolve_pdf(registry_entry, "source_pdf_path")


def mda_pdf_candidate(registry_entry: dict[str, Any] | None) -> Path | None:
    """Build the canonical standalone-MD&A PDF candidate path (the registry's
    optional second document slot, docs/MDA_FETCHER_SPEC.md Stage 0). Entries
    without an MD&A document simply lack the key and resolve to None."""
    return _pdf_candidate(registry_entry, "mda_pdf_path")


def resolve_mda_pdf(registry_entry: dict[str, Any] | None) -> Path | None:
    """Resolve the recorded standalone-MD&A PDF filename in the canonical
    PDF root. None when the entry has no MD&A document or the file is absent
    (in-PDF-first sourcing: a combined statements+MD&A pack needs no entry
    here — the locator reads the statement PDF directly)."""
    return _resolve_pdf(registry_entry, "mda_pdf_path")
