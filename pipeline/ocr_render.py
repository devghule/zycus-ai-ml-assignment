"""Stage: document ingestion / page rendering (Phase 2) + OCR fallback (Phase 5).

Renders each page of a source PDF to a cached raster image (for later
visual/LLM analysis) and extracts the embedded text layer per page. The
embedded text layer is kept strictly as supporting evidence, never as
ground truth: many corpus documents are scans with an empty or unreliable
text layer (see STEP1_STEP2_ANALYSIS.md), so downstream stages must be able
to work with `text == ""`.

Per-page rendering failures are isolated (recorded on the RenderedPage, the
rest of the document still processes); a whole-document open failure sets
RenderedDocument.render_error and returns zero pages rather than raising.

Phase 5 adds an OCR fallback boundary: when the embedded text layer is
insufficient (not just empty — also garbled/near-empty), the page is handed
to a pluggable OCRProvider.

There is no Tesseract binary on this machine and no admin rights to install
one (Windows installer requires UAC elevation, unavailable in this
environment — confirmed). Instead, the active provider (when available) is
`rapidocr-onnxruntime`: a fully local, pip-installable, zero-cost OCR engine
(ONNX Runtime + open PaddleOCR-derived models, no system binary, no network
calls at inference time, no API key). It's a genuine engine, not a mock —
verified to produce real recognized text from real scanned corpus pages.
Import is lazy and guarded: if the package isn't installed in the active
Python environment, `get_default_ocr_provider()` falls back to
`NULL_OCR_PROVIDER`, which honestly returns "" rather than fabricating text.
Either way `render_document`'s default provider is resolved lazily (not at
import time) so the module never hard-fails just because the optional
dependency is missing.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pymupdf

from config import CACHE_DIR

logger = logging.getLogger(__name__)

# ~150 DPI equivalent (PDF default is 72 DPI), plenty for visual/LLM review
# without producing huge files.
RENDER_ZOOM = 150 / 72

# --- Text-sufficiency signal -------------------------------------------------
# A page's embedded text is "insufficient" (and should fall back to OCR) not
# only when it's empty, but when it's too short or too low in meaningful
# (alphanumeric) content to be useful — a handful of garbled characters from
# a botched extraction should not be trusted as "we have text".
_MIN_USABLE_CHARS = 15
_MIN_ALNUM_DENSITY = 0.3  # fraction of non-whitespace chars that are alnum


def _is_text_sufficient(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < _MIN_USABLE_CHARS:
        return False
    non_space = [c for c in stripped if not c.isspace()]
    if not non_space:
        return False
    alnum_count = sum(1 for c in non_space if c.isalnum())
    density = alnum_count / len(non_space)
    return density >= _MIN_ALNUM_DENSITY


# --- OCR provider boundary ---------------------------------------------------
# An OCRProvider takes a rendered page image path and returns extracted text
# (or "" if it can't produce any). Kept as a plain callable, not a class
# hierarchy, since there's exactly one behavior to plug in.
OCRProvider = Callable[[Path], str]


def _null_ocr_provider(image_path: Path) -> str:
    """Safe fallback: returns "" honestly rather than fabricating recognized
    text. Active whenever no real OCR engine is importable."""
    return ""


NULL_OCR_PROVIDER: OCRProvider = _null_ocr_provider

# --- RapidOCR-backed provider (real, local, zero-cost) -----------------------
# Lazily constructed: importing/initializing the engine takes a few seconds
# (loading small ONNX models from disk), so it happens at most once per
# process, on first actual use — not at module import time, and not per page.
_rapidocr_engine = None
_rapidocr_import_failed = False


def _get_rapidocr_engine():
    global _rapidocr_engine, _rapidocr_import_failed
    if _rapidocr_engine is not None or _rapidocr_import_failed:
        return _rapidocr_engine
    try:
        from rapidocr_onnxruntime import RapidOCR  # optional dependency
    except ImportError:
        _rapidocr_import_failed = True
        logger.info("rapidocr-onnxruntime not installed; OCR fallback will use NULL_OCR_PROVIDER")
        return None
    try:
        _rapidocr_engine = RapidOCR()
    except Exception as exc:  # noqa: BLE001 - engine init failure must not crash the pipeline
        logger.warning("failed to initialize RapidOCR engine: %s", exc)
        _rapidocr_import_failed = True
        return None
    return _rapidocr_engine


def rapidocr_provider(image_path: Path) -> str:
    """Real local OCR via rapidocr-onnxruntime. Returns "" (not an
    exception) if the engine isn't available or produced nothing — the
    caller (render_document) already treats "" as "OCR found nothing" and
    isolates any exception per-page regardless."""
    engine = _get_rapidocr_engine()
    if engine is None:
        return ""
    result, _elapse = engine(str(image_path))
    if not result:
        return ""
    return "\n".join(entry[1] for entry in result if len(entry) > 1)


def get_default_ocr_provider() -> OCRProvider:
    """Resolve which provider `render_document` should use by default:
    RapidOCR if the optional dependency is installed and initializes
    successfully, otherwise the honest NULL provider. Resolved lazily
    (called from within render_document, not at import time or as a
    mutable default argument) so importing this module never requires the
    optional dependency to be present."""
    engine = _get_rapidocr_engine()
    return rapidocr_provider if engine is not None else NULL_OCR_PROVIDER


@dataclass
class RenderedPage:
    """One page of a source PDF, rendered for downstream (visual/LLM) use."""

    page_number: int  # 1-indexed
    text: str = ""  # the SELECTED text (embedded or OCR) — see text_source
    embedded_text: str = ""  # raw embedded text layer, always preserved as-is
    ocr_text: str = ""  # raw OCR output, if OCR was attempted
    text_source: str = "none"  # "embedded" | "ocr" | "none"
    image_path: Path | None = None  # rendered raster image
    width: int = 0  # rendered image width in pixels
    height: int = 0  # rendered image height in pixels
    page_error: str | None = None  # set if this specific page failed


@dataclass
class RenderedDocument:
    source_path: Path
    pages: list[RenderedPage] = field(default_factory=list)
    render_error: str | None = None  # set if the whole document failed to open


def _cache_dir_for(source_path: Path) -> Path:
    doc_cache = CACHE_DIR / source_path.stem
    doc_cache.mkdir(parents=True, exist_ok=True)
    return doc_cache


def render_document(
    source_path: Path,
    ocr_provider: OCRProvider | None = None,
) -> RenderedDocument:
    """Render every page of source_path to a cached PNG, extract its embedded
    text layer, and fall back to `ocr_provider` when that text is
    insufficient. Public entry point used by run.py.

    `ocr_provider` defaults (when None) to whatever `get_default_ocr_provider()`
    resolves to — RapidOCR if installed and initializable, otherwise the
    honest NULL provider. Resolution is deferred until a page's embedded
    text actually proves insufficient (not done unconditionally up front),
    so documents with a good text layer never pay the OCR-engine-init cost
    at all. Tests substitute an explicit fake provider to prove the
    fallback wiring itself is correct independent of which real engine is
    or isn't installed."""
    try:
        doc = pymupdf.open(source_path)
    except Exception as exc:  # noqa: BLE001 - any open failure is a render_error, not a crash
        logger.warning("%s: failed to open PDF: %s", source_path.name, exc)
        return RenderedDocument(source_path=source_path, render_error=str(exc))

    if doc.page_count == 0:
        doc.close()
        return RenderedDocument(source_path=source_path, render_error="PDF has zero pages")

    doc_cache = _cache_dir_for(source_path)
    pages: list[RenderedPage] = []
    matrix = pymupdf.Matrix(RENDER_ZOOM, RENDER_ZOOM)

    for index in range(doc.page_count):
        page_number = index + 1  # 1-indexed
        image_name = f"page_{page_number:04d}.png"
        image_path = doc_cache / image_name
        rp = RenderedPage(page_number=page_number)
        try:
            page = doc.load_page(index)
            embedded = page.get_text() or ""
            rp.embedded_text = embedded

            pix = page.get_pixmap(matrix=matrix)
            pix.save(image_path)
            rp.image_path = image_path
            rp.width = pix.width
            rp.height = pix.height

            if _is_text_sufficient(embedded):
                rp.text = embedded
                rp.text_source = "embedded"
            else:
                active_provider = ocr_provider if ocr_provider is not None else get_default_ocr_provider()
                try:
                    ocr_text = active_provider(image_path) or ""
                except Exception as exc:  # noqa: BLE001 - OCR failure isolates to this page's text, not a crash
                    logger.warning(
                        "%s: page %d OCR provider failed: %s", source_path.name, page_number, exc
                    )
                    ocr_text = ""
                rp.ocr_text = ocr_text
                if ocr_text:
                    rp.text = ocr_text
                    rp.text_source = "ocr"
                else:
                    # Neither embedded text nor OCR produced anything usable.
                    # Keep whatever (insufficient) embedded text existed
                    # rather than discarding it — downstream sufficiency
                    # checks still apply — but mark the source honestly.
                    rp.text = embedded
                    rp.text_source = "none"
        except Exception as exc:  # noqa: BLE001 - isolate this page, keep going
            logger.warning("%s: page %d failed: %s", source_path.name, page_number, exc)
            rp.page_error = str(exc)
        pages.append(rp)

    doc.close()
    return RenderedDocument(source_path=source_path, pages=pages)
