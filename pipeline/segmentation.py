"""Stage: segmentation (Phase 3).

A single source PDF can bundle several logical documents (e.g. an invoice
followed by a customs declaration, or a delivery note followed by a
waybill — confirmed patterns in STEP1_STEP2_ANALYSIS.md). This module
detects likely boundaries between such logical documents using general,
structural/textual heuristics over the page text produced by Phase 2 — no
filename- or document-identity-specific logic.

No LLM is available in this environment (no API key configured), so the
only implemented signal path is deterministic. `_llm_seam` documents where
a semantic LLM-based boundary pass would plug in later without needing to
restructure this module.

Conservative fallback: if the heuristics are not confident a document
contains more than one logical document, the whole PDF is treated as a
single segment (the Phase 1 stub behavior, kept as the honest default).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from pipeline.ocr_render import RenderedDocument, RenderedPage

# --- General "new document is starting" signals -----------------------------
# Patterns that tend to appear near the top of a fresh logical document's
# first page, across languages. These are structural label patterns, not
# corpus-specific literals.
_DOCUMENT_TITLE_PATTERNS = [
    r"\bINVOICE\b", r"\bRECHNUNG\b", r"\bFAKTURA\b", r"\bARVE\b", r"\bFATURA\b",
    r"\bCREDIT\s+NOTE\b", r"\bCREDIT\s+MEMO\b", r"\bGUTSCHRIFT\b", r"\bKREEDITARVE\b",
    r"\bNOTA\s+DE\s+CR[ÉE]DITO\b",
    r"\bDELIVERY\s+NOTE\b", r"\bLIEFERSCHEIN\b", r"\bPACKING\s+LIST\b",
    r"\bWAYBILL\b", r"\bBILL\s+OF\s+LADING\b", r"\bCMR\b",
    r"\bCUSTOMS\s+DECLARATION\b", r"\bEXPORT\s+DECLARATION\b",
    r"\bPURCHASE\s+ORDER\b", r"\bQUOTATION\b", r"\bESTIMATE\b",
]
_TITLE_RE = re.compile("|".join(_DOCUMENT_TITLE_PATTERNS), re.IGNORECASE)

# An "identity block" pattern: a labelled reference number near the top of a
# page (invoice no / document no / reference no, in several languages).
_IDENTITY_RE = re.compile(
    r"\b(invoice|document|reference|ref|order|delivery|waybill)\s*(no\.?|nr\.?|number|#)\s*[:\-]?\s*\S+",
    re.IGNORECASE,
)


@dataclass
class Segment:
    """A contiguous page range believed to be one logical document."""

    page_numbers: list[int]
    role_hint: str = "unknown"
    confidence: float = 1.0  # 1.0 = conservative whole-document fallback
    evidence: list[str] = field(default_factory=list)


def _top_region(text: str, max_lines: int = 8) -> str:
    """Return the first few non-blank lines of a page's text (where a fresh
    document's title/identity block typically lives)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines[:max_lines])


def _looks_like_new_document_start(prev: RenderedPage, curr: RenderedPage) -> tuple[bool, list[str]]:
    """General structural signal: does curr's top region look like the start
    of a fresh logical document, distinct from prev? Returns (is_boundary,
    evidence)."""
    evidence: list[str] = []

    curr_top = _top_region(curr.text)
    prev_top = _top_region(prev.text)

    if not curr_top.strip():
        # No text at all on this page -> no positive evidence of a new start.
        return False, evidence

    curr_titles = set(m.group(0).upper() for m in _TITLE_RE.finditer(curr_top))
    prev_titles = set(m.group(0).upper() for m in _TITLE_RE.finditer(prev_top))

    # Signal A: a document-title pattern appears at the top of curr but did
    # NOT appear at the top of prev -> looks like a fresh document heading.
    new_titles = curr_titles - prev_titles
    if new_titles:
        evidence.append(f"new title pattern(s) at page top: {sorted(new_titles)}")

    # Signal B: curr has its own identity/reference block near the top, and
    # it differs from prev's (a distinct invoice/reference number implies a
    # distinct logical document rather than a continuation page).
    curr_ids = set(m.group(0).lower() for m in _IDENTITY_RE.finditer(curr_top))
    prev_ids = set(m.group(0).lower() for m in _IDENTITY_RE.finditer(prev_top))
    new_ids = curr_ids - prev_ids
    if new_ids and curr_ids != prev_ids:
        evidence.append(f"distinct identity block at page top: {sorted(new_ids)}")

    # Require at least one strong signal (a title pattern change), or both a
    # new identity block AND some title pattern present, to call a boundary.
    # This keeps continuation pages (e.g. an invoice's page 2 of 3, which
    # often repeats no header at all) from being mis-split.
    is_boundary = bool(new_titles) or (bool(new_ids) and bool(curr_titles))
    return is_boundary, evidence


def _llm_seam(pages: list[RenderedPage]) -> list[int] | None:
    """Seam for a future LLM-based semantic segmentation pass.

    Not implemented: no LLM client/API key is available in this environment.
    If/when one is configured, this function would send page images/text to
    the LLM and return a list of page numbers that start new segments (or
    None to defer to the deterministic heuristics below). Always returns
    None today so the deterministic path is the only one actually exercised.
    """
    return None


def segment_document(rendered: RenderedDocument) -> list[Segment]:
    """Split a rendered document into logical segments.

    Every source page belongs to exactly one segment. If no boundary is
    detected with confidence, the whole document is returned as one segment
    (conservative fallback).
    """
    pages = rendered.pages
    if not pages:
        return [Segment(page_numbers=[1], role_hint="whole_document", confidence=1.0,
                         evidence=["no rendered pages available"])]

    llm_boundaries = _llm_seam(pages)
    boundary_pages: set[int] = set()
    boundary_evidence: dict[int, list[str]] = {}

    if llm_boundaries is not None:
        boundary_pages = set(llm_boundaries)
    else:
        for prev, curr in zip(pages, pages[1:]):
            is_boundary, evidence = _looks_like_new_document_start(prev, curr)
            if is_boundary:
                boundary_pages.add(curr.page_number)
                boundary_evidence[curr.page_number] = evidence

    if not boundary_pages:
        page_numbers = [p.page_number for p in pages]
        return [Segment(page_numbers=page_numbers, role_hint="whole_document", confidence=1.0,
                         evidence=["no segmentation boundary signals found"])]

    segments: list[Segment] = []
    current: list[int] = []
    current_evidence: list[str] = []
    for p in pages:
        if p.page_number in boundary_pages and current:
            segments.append(Segment(page_numbers=current, role_hint="detected_segment",
                                     confidence=0.6, evidence=current_evidence or ["structural fallback"]))
            current = []
            current_evidence = []
        current.append(p.page_number)
        if p.page_number in boundary_evidence:
            current_evidence.extend(boundary_evidence[p.page_number])
    if current:
        segments.append(Segment(page_numbers=current, role_hint="detected_segment",
                                 confidence=0.6, evidence=current_evidence or ["structural fallback"]))

    return segments
