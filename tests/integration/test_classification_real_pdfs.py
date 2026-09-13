"""Integration tests: pipeline/classification.py against real corpus PDFs.

Runs the deterministic rule-based classifier (the only path exercised in
this environment — no LLM API key available) over segments produced by
Phase 3 for the full real corpus, and reports the resulting class
distribution. Does not assert a "correct" distribution — the corpus mostly
consists of scanned pages with an empty embedded text layer (confirmed by
Phase 2 integration tests and STEP1_STEP2_ANALYSIS.md), so a majority of
AMBIGUOUS_UNSOLVABLE results here is expected and honestly reported, not a
failure of this test.
"""
from __future__ import annotations

from collections import Counter

from config import DOCUMENTS_DIR
from pipeline.classification import DocumentClass, classify_segment
from pipeline.ocr_render import render_document
from pipeline.segmentation import segment_document


def _all_pdfs():
    return sorted(DOCUMENTS_DIR.glob("*.pdf"))


def test_classification_runs_over_full_corpus_without_crashing_and_reports_distribution(capsys):
    distribution = Counter()
    per_doc = []

    for path in _all_pdfs():
        rendered = render_document(path)
        if rendered.render_error:
            distribution["RENDER_FAILED"] += 1
            continue
        segments = segment_document(rendered)
        for segment in segments:
            classification = classify_segment(rendered, segment)
            distribution[classification.doc_class.value] += 1
            per_doc.append((path.name, segment.page_numbers, classification.doc_class.value, classification.doc_type))

    print("\n--- Classification distribution over real corpus ---")
    for label, count in distribution.most_common():
        print(f"{label}: {count}")

    print("\n--- Per-segment results (first 20) ---")
    for row in per_doc[:20]:
        print(row)

    # Sanity: every discovered document produced at least one accounted-for
    # outcome (either a render failure or >=1 classified segment).
    assert sum(distribution.values()) >= len(_all_pdfs())
    # We never fabricate confidence in classes we have no real basis for:
    # this run must not crash regardless of how the distribution comes out.


def test_documents_with_no_text_layer_are_not_forced_into_a_positive_class():
    """Cross-check against Phase 2's finding that most corpus documents have
    an empty embedded text layer: those segments must land in
    AMBIGUOUS_UNSOLVABLE (insufficient evidence), never a guessed payable
    class, per the conservative-by-design rule."""
    offenders = []
    for path in _all_pdfs():
        rendered = render_document(path)
        if rendered.render_error:
            continue
        total_text = sum(len(p.text.strip()) for p in rendered.pages)
        if total_text > 0:
            continue  # only checking the no-text-at-all case here
        segments = segment_document(rendered)
        for segment in segments:
            classification = classify_segment(rendered, segment)
            if classification.doc_class in (DocumentClass.PAYABLE_INVOICE, DocumentClass.PAYABLE_CREDIT_MEMO):
                offenders.append((path.name, segment.page_numbers, classification.doc_class.value))

    assert offenders == [], f"classified a payable class with zero text evidence: {offenders}"
