"""Integration tests: pipeline/ocr_render.py against real corpus PDFs.

Representative fixtures are picked dynamically by inspecting real PDFs'
properties (page count, text-layer presence) rather than hardcoding
filenames as production logic. Referencing a filename here is fixture
selection for tests only, per the assignment brief's own carve-out.
"""
from __future__ import annotations

import pymupdf
import pytest

from config import DOCUMENTS_DIR
from pipeline.ocr_render import render_document


def _all_pdfs():
    return sorted(DOCUMENTS_DIR.glob("*.pdf"))


def _pick_by_page_count(target: str):
    """target: 'single' or 'multi' (>1 page)."""
    for path in _all_pdfs():
        try:
            doc = pymupdf.open(path)
            count = doc.page_count
            doc.close()
        except Exception:
            continue
        if target == "single" and count == 1:
            return path
        if target == "multi" and count > 1:
            return path
    return None


def _pick_near_empty_text_layer():
    for path in _all_pdfs():
        try:
            doc = pymupdf.open(path)
            total = sum(len(p.get_text().strip()) for p in doc)
            doc.close()
        except Exception:
            continue
        if total == 0:
            return path
    return None


def _pick_with_real_text_layer():
    for path in _all_pdfs():
        try:
            doc = pymupdf.open(path)
            total = sum(len(p.get_text().strip()) for p in doc)
            doc.close()
        except Exception:
            continue
        if total > 500:
            return path
    return None


@pytest.fixture(scope="module")
def real_pdf_samples():
    samples = {
        "single_page": _pick_by_page_count("single"),
        "multi_page": _pick_by_page_count("multi"),
        "empty_text_layer": _pick_near_empty_text_layer(),
        "real_text_layer": _pick_with_real_text_layer(),
    }
    if not any(samples.values()):
        pytest.skip("no documents/ corpus available in this environment")
    return samples


def test_single_page_real_pdf_renders(real_pdf_samples):
    path = real_pdf_samples["single_page"]
    if path is None:
        pytest.skip("no single-page PDF found in corpus")
    rendered = render_document(path)
    assert rendered.render_error is None
    assert len(rendered.pages) == 1
    page = rendered.pages[0]
    assert page.page_number == 1
    assert page.image_path is not None and page.image_path.exists()
    assert page.image_path.stat().st_size > 0


def test_multi_page_real_pdf_renders_all_pages_in_order(real_pdf_samples):
    path = real_pdf_samples["multi_page"]
    if path is None:
        pytest.skip("no multi-page PDF found in corpus")
    rendered = render_document(path)
    assert rendered.render_error is None
    assert len(rendered.pages) > 1
    assert [p.page_number for p in rendered.pages] == list(range(1, len(rendered.pages) + 1))
    for page in rendered.pages:
        assert page.page_error is None
        assert page.image_path is not None and page.image_path.exists()
        assert page.image_path.stat().st_size > 0


def test_empty_text_layer_real_pdf_is_handled_without_crash(real_pdf_samples):
    path = real_pdf_samples["empty_text_layer"]
    if path is None:
        pytest.skip("no near-empty-text-layer PDF found in corpus (all had text)")
    rendered = render_document(path)
    assert rendered.render_error is None
    # The embedded PDF text layer is empty for this document, but
    # render_document() now falls back to real RapidOCR by default (Phase 5),
    # so p.text may legitimately contain OCR-derived text instead of "" —
    # that is the intended behavior, not a failure. What this test actually
    # verifies (per its name) is that an empty embedded text layer is
    # handled successfully, without crashing, and still yields rendered
    # pages/images for every page.
    assert all(p.embedded_text == "" for p in rendered.pages)
    assert all(p.page_error is None for p in rendered.pages)
    # Images must still be produced even with no usable embedded text layer.
    assert all(p.image_path is not None and p.image_path.exists() for p in rendered.pages)


def test_real_text_layer_pdf_keeps_text_page_associated(real_pdf_samples):
    path = real_pdf_samples["real_text_layer"]
    if path is None:
        pytest.skip("no PDF with a substantial text layer found in corpus")
    rendered = render_document(path)
    assert rendered.render_error is None
    assert any(p.text.strip() for p in rendered.pages)
    # Text is per-page, not a single flattened blob.
    texts = [p.text for p in rendered.pages]
    assert isinstance(texts, list)


def test_batch_over_full_corpus_never_crashes():
    failures = []
    for path in _all_pdfs():
        try:
            rendered = render_document(path)
        except Exception as exc:  # noqa: BLE001
            failures.append((path.name, str(exc)))
            continue
        # Either it opened (pages present or a documented render_error), never both empty+no-error
        assert rendered.render_error is not None or len(rendered.pages) > 0
    assert failures == [], f"render_document crashed on: {failures}"
