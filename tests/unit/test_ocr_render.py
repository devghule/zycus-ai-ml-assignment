"""Unit tests for pipeline/ocr_render.py (Phase 2).

Uses synthetically constructed PDFs (built with pymupdf itself) so the
tests never depend on the real corpus.
"""
from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from pipeline.ocr_render import render_document


def _make_pdf(path: Path, page_texts: list[str]) -> None:
    doc = pymupdf.open()
    for text in page_texts:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


def test_page_count_and_ordering(tmp_path):
    pdf_path = tmp_path / "multi.pdf"
    _make_pdf(pdf_path, ["Page One Text", "Page Two Text", "Page Three Text"])

    rendered = render_document(pdf_path)

    assert rendered.render_error is None
    assert len(rendered.pages) == 3
    assert [p.page_number for p in rendered.pages] == [1, 2, 3]


def test_text_extraction_presence(tmp_path):
    pdf_path = tmp_path / "with_text.pdf"
    _make_pdf(pdf_path, ["Invoice No: 123"])

    rendered = render_document(pdf_path)

    assert "Invoice" in rendered.pages[0].text


def test_text_extraction_absence_for_blank_page(tmp_path):
    pdf_path = tmp_path / "blank.pdf"
    _make_pdf(pdf_path, [""])

    rendered = render_document(pdf_path)

    assert rendered.pages[0].text == ""


def test_malformed_pdf_produces_render_error_not_crash(tmp_path):
    bad_path = tmp_path / "garbage.pdf"
    bad_path.write_bytes(b"this is not a pdf file at all")

    rendered = render_document(bad_path)

    assert rendered.render_error is not None
    assert rendered.pages == []


def test_zero_byte_pdf_produces_render_error_not_crash(tmp_path):
    empty_path = tmp_path / "empty.pdf"
    empty_path.write_bytes(b"")

    rendered = render_document(empty_path)

    assert rendered.render_error is not None
    assert rendered.pages == []


def test_deterministic_image_file_naming_and_existence(tmp_path, monkeypatch):
    import config

    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(config, "CACHE_DIR", cache_dir)
    import pipeline.ocr_render as ocr_render
    monkeypatch.setattr(ocr_render, "CACHE_DIR", cache_dir)

    pdf_path = tmp_path / "doc.pdf"
    _make_pdf(pdf_path, ["First", "Second"])

    rendered = ocr_render.render_document(pdf_path)

    expected_dir = cache_dir / "doc"
    assert (expected_dir / "page_0001.png").exists()
    assert (expected_dir / "page_0002.png").exists()
    for page in rendered.pages:
        assert page.image_path is not None
        assert page.image_path.exists()
        assert page.image_path.stat().st_size > 0
        assert page.width > 0 and page.height > 0
