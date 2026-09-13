"""Unit tests for pipeline/segmentation.py (Phase 3)."""
from __future__ import annotations

from pipeline.ocr_render import RenderedDocument, RenderedPage
from pipeline.segmentation import segment_document


def _doc(texts: list[str]) -> RenderedDocument:
    pages = [RenderedPage(page_number=i + 1, text=t) for i, t in enumerate(texts)]
    return RenderedDocument(source_path=__file__, pages=pages)  # source_path unused here


def test_single_document_stays_one_segment():
    rendered = _doc([
        "INVOICE\nInvoice No: 1001\nBill To: Acme Corp",
        "Continued line items...\nSubtotal: 100",
        "Total Due: 120\nThank you",
    ])
    segments = segment_document(rendered)
    assert len(segments) == 1
    assert segments[0].page_numbers == [1, 2, 3]


def test_multi_document_pdf_splits_on_distinct_headers():
    rendered = _doc([
        "INVOICE\nInvoice No: 1001\nBill To: Acme Corp\nTotal Due: 50",
        "DELIVERY NOTE\nDelivery No: DN-9001\nShip To: Acme Warehouse",
        "CUSTOMS DECLARATION\nReference No: CD-5555\nExport declaration details",
    ])
    segments = segment_document(rendered)
    assert len(segments) == 3
    assert segments[0].page_numbers == [1]
    assert segments[1].page_numbers == [2]
    assert segments[2].page_numbers == [3]


def test_page_coverage_invariant_holds():
    rendered = _doc([
        "INVOICE\nInvoice No: 1",
        "WAYBILL\nWaybill No: 2",
        "more waybill continuation text with no header",
        "INVOICE\nInvoice No: 3",
    ])
    segments = segment_document(rendered)

    all_pages = set(p.page_number for p in rendered.pages)
    covered = []
    for seg in segments:
        covered.extend(seg.page_numbers)

    assert set(covered) == all_pages
    assert len(covered) == len(set(covered))  # no duplicates


def test_fallback_to_whole_document_when_signals_weak():
    rendered = _doc([
        "some plain text with no document title patterns at all",
        "more plain continuation text, still nothing distinctive",
    ])
    segments = segment_document(rendered)
    assert len(segments) == 1
    assert segments[0].role_hint == "whole_document"
    assert segments[0].page_numbers == [1, 2]


def test_no_pages_falls_back_to_single_page_segment():
    rendered = RenderedDocument(source_path=__file__, pages=[])
    segments = segment_document(rendered)
    assert len(segments) == 1
    assert segments[0].page_numbers == [1]
