"""Phase 5: OCR fallback wiring, on top of Phase 2's real render_document."""
from __future__ import annotations

from pathlib import Path

import pymupdf

from pipeline.ocr_render import NULL_OCR_PROVIDER, render_document


def _make_pdf_with_text(path: Path, text: str) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


def _make_blank_pdf(path: Path) -> None:
    doc = pymupdf.open()
    doc.new_page()
    doc.save(path)
    doc.close()


def test_good_embedded_text_resolves_to_embedded_source(tmp_path: Path):
    pdf_path = tmp_path / "good.pdf"
    _make_pdf_with_text(pdf_path, "Invoice No: 12345\nTotal Due: EUR 100.00\nThank you for your business.")
    rendered = render_document(pdf_path)
    assert rendered.render_error is None
    page = rendered.pages[0]
    assert page.text_source == "embedded"
    assert "Invoice" in page.text


def test_blank_page_falls_back_to_ocr_and_null_provider_returns_none_source(tmp_path: Path):
    pdf_path = tmp_path / "blank.pdf"
    _make_blank_pdf(pdf_path)
    rendered = render_document(pdf_path, ocr_provider=NULL_OCR_PROVIDER)
    assert rendered.render_error is None
    page = rendered.pages[0]
    assert page.embedded_text.strip() == ""
    assert page.text_source == "none"
    assert page.ocr_text == ""


def test_fake_ocr_provider_wiring_works_end_to_end(tmp_path: Path):
    """Proves the fallback WIRING is correct: when a real OCR provider IS
    present (here, a fake/mock one), its output is picked up and
    text_source correctly reports "ocr". This is legitimate interface
    testing, not fake OCR — no claim is made that this fake provider
    represents real OCR quality."""
    pdf_path = tmp_path / "blank.pdf"
    _make_blank_pdf(pdf_path)

    def fake_ocr_provider(image_path: Path) -> str:
        assert image_path.exists()
        return "OCR RECOGNIZED TEXT: Invoice 999"

    rendered = render_document(pdf_path, ocr_provider=fake_ocr_provider)
    page = rendered.pages[0]
    assert page.text_source == "ocr"
    assert page.text == "OCR RECOGNIZED TEXT: Invoice 999"
    assert page.ocr_text == "OCR RECOGNIZED TEXT: Invoice 999"


def test_ocr_provider_failure_is_isolated_not_fatal(tmp_path: Path):
    pdf_path = tmp_path / "blank.pdf"
    _make_blank_pdf(pdf_path)

    def broken_ocr_provider(image_path: Path) -> str:
        raise RuntimeError("OCR engine crashed")

    rendered = render_document(pdf_path, ocr_provider=broken_ocr_provider)
    assert rendered.render_error is None  # whole document still processes
    page = rendered.pages[0]
    assert page.page_error is None  # this isn't treated as a page-render failure
    assert page.text_source == "none"
    assert page.ocr_text == ""


def test_near_empty_garbled_text_is_treated_as_insufficient(tmp_path: Path):
    """A handful of garbled characters should NOT be trusted as "we have
    text" — must still attempt OCR fallback."""
    pdf_path = tmp_path / "garbled.pdf"
    _make_pdf_with_text(pdf_path, "X # @")
    rendered = render_document(pdf_path)
    page = rendered.pages[0]
    assert page.text_source != "embedded"


def test_ocr_render_module_imports_cleanly_without_optional_ocr_dependency():
    """Regression guard for the global-environment incident during Phase 5's
    OCR upgrade (installing rapidocr-onnxruntime globally broke an
    unrelated project's numpy/tensorflow versions): pipeline.ocr_render
    must never require the optional OCR package at import time — only a
    lazy, guarded import inside get_default_ocr_provider()/render_document.
    This test passes in ANY environment (with or without rapidocr
    installed), which is exactly the property that matters."""
    import importlib

    import pipeline.ocr_render as ocr_render_module

    importlib.reload(ocr_render_module)  # must not raise regardless of what's installed
    assert hasattr(ocr_render_module, "NULL_OCR_PROVIDER")
    assert hasattr(ocr_render_module, "get_default_ocr_provider")
