from __future__ import annotations

from pathlib import Path

import config
from modules import campaign_pdf


def _point_pdf_root(monkeypatch, pdfs_root: Path) -> None:
    monkeypatch.setattr(config, "LIBRARY_PDFS_DIR", pdfs_root)
    monkeypatch.setattr(campaign_pdf, "LIBRARY_PDFS_DIR", pdfs_root)


def test_resolve_campaign_pdf_returns_canonical_hit(tmp_path, monkeypatch):
    _point_pdf_root(monkeypatch, tmp_path)
    expected = tmp_path / "AEM_FY2025.pdf"
    expected.write_bytes(b"%PDF-1.7\n")

    windows_result = campaign_pdf.resolve_campaign_pdf(
        {"source_pdf_path": r"C:\Users\riley\.finlens\pdfs\AEM_FY2025.pdf"}
    )
    posix_result = campaign_pdf.resolve_campaign_pdf(
        {"source_pdf_path": "/home/other/.finlens/pdfs/AEM_FY2025.pdf"}
    )

    assert windows_result == expected
    assert posix_result == expected


def test_resolve_campaign_pdf_ignores_foreign_recorded_directory(tmp_path, monkeypatch):
    _point_pdf_root(monkeypatch, tmp_path)
    expected = tmp_path / "REI_UN_FY2025.pdf"
    expected.write_bytes(b"%PDF-1.7\n")

    windows_result = campaign_pdf.resolve_campaign_pdf(
        {"source_pdf_path": r"C:\Users\riley\OneDrive\Documents\other\REI_UN_FY2025.pdf"}
    )
    posix_result = campaign_pdf.resolve_campaign_pdf(
        {"source_pdf_path": "/home/other/campaign/REI_UN_FY2025.pdf"}
    )

    assert windows_result == expected
    assert posix_result == expected
    assert windows_result.parent == tmp_path
    assert posix_result.parent == tmp_path


def test_campaign_pdf_candidate_does_not_require_file_to_exist(tmp_path, monkeypatch):
    _point_pdf_root(monkeypatch, tmp_path)

    result = campaign_pdf.campaign_pdf_candidate(
        {"source_pdf_path": r"C:\Users\riley\.finlens\pdfs\CNQ_FY2024.pdf"}
    )

    assert result == tmp_path / "CNQ_FY2024.pdf"
    assert not result.exists()


def test_resolve_campaign_pdf_ignores_stray_file_when_canonical_absent(
    tmp_path, monkeypatch
):
    _point_pdf_root(monkeypatch, tmp_path)
    (tmp_path / "Agnico_2025-Annual-Report.pdf").write_bytes(b"%PDF-1.7\n")

    result = campaign_pdf.resolve_campaign_pdf(
        {"source_pdf_path": "/home/other/AEM_FY2025.pdf"}
    )

    assert result is None


def test_resolve_campaign_pdf_returns_none_when_recorded_file_missing(
    tmp_path, monkeypatch
):
    _point_pdf_root(monkeypatch, tmp_path)

    result = campaign_pdf.resolve_campaign_pdf(
        {"source_pdf_path": "/home/other/CNQ_FY2024.pdf"}
    )

    assert result is None


def test_resolve_campaign_pdf_returns_none_for_missing_empty_or_none_source(
    tmp_path, monkeypatch
):
    _point_pdf_root(monkeypatch, tmp_path)

    assert campaign_pdf.resolve_campaign_pdf({}) is None
    assert campaign_pdf.resolve_campaign_pdf({"source_pdf_path": ""}) is None
    assert campaign_pdf.resolve_campaign_pdf({"source_pdf_path": None}) is None


def test_resolve_campaign_pdf_excludes_cache_subdir(tmp_path, monkeypatch):
    _point_pdf_root(monkeypatch, tmp_path)
    cache_dir = tmp_path / "_cache"
    cache_dir.mkdir()
    (cache_dir / "AEM_FY2025.pdf").write_bytes(b"%PDF-1.7\n")

    result = campaign_pdf.resolve_campaign_pdf(
        {"source_pdf_path": "/home/other/AEM_FY2025.pdf"}
    )

    assert result is None


def test_resolve_campaign_pdf_preserves_sanitized_ticker_filename(
    tmp_path, monkeypatch
):
    _point_pdf_root(monkeypatch, tmp_path)
    expected = tmp_path / "REI_UN_FY2025.pdf"
    expected.write_bytes(b"%PDF-1.7\n")

    result = campaign_pdf.resolve_campaign_pdf(
        {"source_pdf_path": "/home/other/REI_UN_FY2025.pdf"}
    )

    assert result == expected


# --- MD&A second document slot (MDA_FETCHER_SPEC Stage 0) ---


def test_resolve_mda_pdf_returns_canonical_hit(tmp_path, monkeypatch):
    _point_pdf_root(monkeypatch, tmp_path)
    expected = tmp_path / "TOU_FY2025_MDA.pdf"
    expected.write_bytes(b"%PDF-1.7\n")

    result = campaign_pdf.resolve_mda_pdf(
        {"mda_pdf_path": r"C:\Users\riley\.finlens\pdfs\TOU_FY2025_MDA.pdf"}
    )

    assert result == expected


def test_resolve_mda_pdf_none_when_entry_has_no_mda_slot(tmp_path, monkeypatch):
    """In-PDF-first sourcing: most entries carry no mda_pdf_path — the
    combined statements pack IS the MD&A source. Honest None, never a
    fallback to source_pdf_path (the two documents are distinct classes)."""
    _point_pdf_root(monkeypatch, tmp_path)
    (tmp_path / "TOU_FY2025.pdf").write_bytes(b"%PDF-1.7\n")

    entry = {"source_pdf_path": r"C:\Users\riley\.finlens\pdfs\TOU_FY2025.pdf"}
    assert campaign_pdf.resolve_mda_pdf(entry) is None
    assert campaign_pdf.mda_pdf_candidate(entry) is None


def test_resolve_mda_pdf_ignores_foreign_recorded_directory(tmp_path, monkeypatch):
    _point_pdf_root(monkeypatch, tmp_path)
    expected = tmp_path / "PEY_TO_FY2025_MDA.pdf"
    expected.write_bytes(b"%PDF-1.7\n")

    result = campaign_pdf.resolve_mda_pdf(
        {"mda_pdf_path": "/home/other/downloads/PEY_TO_FY2025_MDA.pdf"}
    )

    assert result == expected
    assert result.parent == tmp_path


def test_resolve_mda_pdf_none_when_recorded_file_missing(tmp_path, monkeypatch):
    _point_pdf_root(monkeypatch, tmp_path)

    result = campaign_pdf.resolve_mda_pdf(
        {"mda_pdf_path": r"C:\Users\riley\.finlens\pdfs\ABSENT_MDA.pdf"}
    )

    assert result is None
