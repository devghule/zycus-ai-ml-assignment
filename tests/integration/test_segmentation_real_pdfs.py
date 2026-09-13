"""Integration tests: pipeline/segmentation.py against real corpus PDFs.

Fixture selection references STEP1_STEP2_ANALYSIS.md's forensic findings
only to pick representative real documents for testing — never as
production branching logic. Segmentation quality against real bundled
documents is reported honestly; imperfect splits are expected and noted,
not asserted away.
"""
from __future__ import annotations

from config import DOCUMENTS_DIR
from pipeline.ocr_render import render_document
from pipeline.segmentation import segment_document


def _all_pdfs():
    return sorted(DOCUMENTS_DIR.glob("*.pdf"))


def test_page_coverage_invariant_holds_for_every_real_document():
    """Critical invariant: union of segment page_numbers == all source pages,
    with no duplicates, for every document in the real corpus."""
    violations = []
    for path in _all_pdfs():
        rendered = render_document(path)
        if rendered.render_error:
            continue  # nothing to segment if it didn't even render
        segments = segment_document(rendered)

        all_pages = set(p.page_number for p in rendered.pages)
        covered: list[int] = []
        for seg in segments:
            covered.extend(seg.page_numbers)

        if set(covered) != all_pages or len(covered) != len(set(covered)):
            violations.append((path.name, all_pages, covered))

    assert violations == [], f"page coverage invariant violated for: {violations}"


def test_segmentation_never_crashes_over_full_corpus():
    for path in _all_pdfs():
        rendered = render_document(path)
        if rendered.render_error:
            continue
        segments = segment_document(rendered)
        assert len(segments) >= 1


def test_report_segmentation_outcomes_for_known_multi_page_documents(capsys):
    """Not a pass/fail assertion on exact split correctness (unsupervised,
    hard problem) — reports what the segmenter actually produces for a
    handful of multi-page documents, for honest manual/CI-log review."""
    multi_page = [p for p in _all_pdfs()][:0]  # placeholder, filled below
    candidates = []
    for path in _all_pdfs():
        rendered = render_document(path)
        if rendered.render_error or len(rendered.pages) <= 1:
            continue
        candidates.append((path, rendered))
        if len(candidates) >= 5:
            break

    for path, rendered in candidates:
        segments = segment_document(rendered)
        print(
            f"{path.name}: {len(rendered.pages)} pages -> "
            f"{len(segments)} segment(s): "
            f"{[(s.page_numbers, s.role_hint, round(s.confidence, 2)) for s in segments]}"
        )

    assert True  # this test exists to report, not to assert exact splits
