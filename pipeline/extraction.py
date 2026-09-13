"""Stage: structured field extraction (Phase 5).

Two extraction paths, mirroring classification's structure:

1. A deterministic, pattern-based "best-effort" extractor
   (`extract_from_text`) that works only on segments with usable text. It
   is intentionally NOT a full parser — it exists to prove the pipeline's
   plumbing and data shapes end-to-end on the handful of real text-bearing
   corpus documents in this environment. It NEVER fabricates a field it
   can't find; a blank/missing field is the correct, honest result.

2. A clean `VisionExtractorProvider` boundary + strict response validator +
   bounded retry, matching DESIGN.md's LLM-usage design. NOT live-tested in
   this environment (no LLM SDK/API key available) — only exercised via
   injected mock provider callables in unit tests.

`extract_payable_from_segment` is the production entry point; it always
takes the deterministic path here (no LLM client is configured).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from pipeline.classification import Classification
from pipeline.ocr_render import RenderedDocument
from pipeline.segmentation import Segment


@dataclass
class ExtractedPayable:
    """Raw, ungrounded-checked field extraction for one segment classified as
    a payable. Shape loosely mirrors AUTODRAFT_SCHEMA.md; financial_model.py
    turns this into a canonical payable and validates it against erp.py."""

    fields: dict[str, Any] = field(default_factory=dict)
    line_items: list[dict[str, Any]] = field(default_factory=list)
    confidence_notes: list[str] = field(default_factory=list)
    flagged_lines: list[int] = field(default_factory=list)  # indexes failing qty*price≈total


# --- Deterministic pattern-based extraction (the only production path here) -
#
# All patterns here are STRUCTURAL/LABEL-based (invoice-number labels,
# supplier/buyer role labels, tax labels, etc.) across several languages
# already confirmed present in the corpus (STEP1_STEP2_ANALYSIS.md) — never
# a specific document's own text. A field is populated only when a
# recognizable label/pattern is actually found; everything else stays
# absent from `fields` rather than guessed.

_CURRENCY_AMOUNT_RE = re.compile(
    r"(?:[$€£]|\bEUR\b|\bUSD\b|\bGBP\b)\s*([\d.,]+)|([\d.,]+)\s*(?:[$€£]|\bEUR\b|\bUSD\b|\bGBP\b)"
)
_TOTAL_LABEL_RE = re.compile(
    r"\b(?:grand\s*total|total\s*due|amount\s*due|total|gesamtbetrag|kokku|summa|total\s*a\s*pagar)\b"
    r"[:\s]*(?:[$€£]|\bEUR\b|\bUSD\b|\bGBP\b)?\s*([\d.,]+)",
    re.IGNORECASE,
)
_SUBTOTAL_LABEL_RE = re.compile(
    r"\b(?:sub\s*total|subtotal|net\s*total|vahesumma)\b"
    r"[:\s]*(?:[$€£]|\bEUR\b|\bUSD\b|\bGBP\b)?\s*([\d.,]+)",
    re.IGNORECASE,
)
_INVOICE_NUMBER_RE = re.compile(
    # The number-indicator suffix (No./Nr./Number/#/Número) is REQUIRED, not
    # optional — without it, "Invoice" alone (as a document title, followed
    # by an unrelated field like "Date:") would wrongly capture that next
    # field's value as the invoice number. This was a real bug found via
    # the Phase 11 corpus audit (false positives: "Date", "INVOICE",
    # Estonian "kokku"/"Kuupäev" were being captured as invoice numbers).
    r"\b(?:invoice|rechnung(?:s)?|arve|fatura|factura)\s*(?:no\.?|nr\.?|number|#|n[uú]mero)"
    r"\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9\-/]{1,30})",
    re.IGNORECASE,
)
# Explicitly excluded from ever being read as an invoice number: PO
# references, phone numbers, and pure dates — these are checked separately
# so a matched "invoice number" candidate that is actually one of these gets
# discarded rather than kept.
_PHONE_LIKE_RE = re.compile(r"^[+]?\d[\d\s\-]{6,}$")
_DATE_LIKE_RE = re.compile(r"^\d{1,4}[./\-]\d{1,2}[./\-]\d{1,4}$")

_PO_NUMBER_RE = re.compile(
    r"\b(?:p\.?\s*o\.?|purchase\s*order|tellimus)\s*(?:no\.?|number|#)?\s*[:\-]?\s*"
    r"([A-Za-z0-9][A-Za-z0-9\-/]{2,30})",
    re.IGNORECASE,
)

_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_DOT_DATE_RE = re.compile(r"\b(\d{1,2}\.\d{1,2}\.\d{4})\b")
_SLASH_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")
_ANY_DATE_RE = re.compile("|".join(p.pattern for p in (_ISO_DATE_RE, _DOT_DATE_RE, _SLASH_DATE_RE)))

_INVOICE_DATE_LABEL_RE = re.compile(
    r"\b(?:invoice\s*date|date\s*of\s*issue|rechnungsdatum|kuupäev|kuup(?:ä|a)ev|arve\s*kuup(?:ä|a)ev)\b"
    r"\s*[:\-]?\s*(\d{1,4}[./\-]\d{1,2}[./\-]\d{1,4})",
    re.IGNORECASE,
)
_DUE_DATE_LABEL_RE = re.compile(
    r"\b(?:due\s*date|payment\s*due|maksetähtaeg|maksetahtaeg|f[äa]lligkeitsdatum|vencimento)\b"
    r"\s*[:\-]?\s*(\d{1,4}[./\-]\d{1,2}[./\-]\d{1,4})",
    re.IGNORECASE,
)

_CURRENCY_CODE_RE = re.compile(
    r"\b(EUR|USD|GBP|CHF|THB|SGD|MYR|ZAR|KES|GHS|DKK|PLN|AUD|CAD|SEK|NOK|RON|VND|INR|JPY)\b"
)
# Only currency SYMBOLS that are unambiguous in practice (a single currency
# uses them) are extracted directly — "$" is deliberately excluded (it's
# shared by USD/SGD/AUD/CAD/... and guessing would violate the "do not
# guess ambiguous symbols" rule); an ISO code elsewhere on the page (caught
# above) is the correct, unambiguous signal for $-using currencies.
_UNAMBIGUOUS_CURRENCY_SYMBOL_RE = re.compile(r"[€£]")
_SYMBOL_TO_ISO = {"€": "EUR", "£": "GBP"}

# Supplier / buyer role labels, multilingual (STEP 8.5-equivalent for
# extraction: label-first, then fall back to nothing rather than guessing).
_SUPPLIER_LABEL_RE = re.compile(
    r"\b(?:supplier|vendor|seller|from|bill\s*from|m[uü][uü]ja|lieferant)\s*[:\-]?\s*\n?\s*"
    r"([A-Z][A-Za-z0-9&.,\-\s]{2,60}?)(?:\n|$)",
    re.IGNORECASE,
)
_BUYER_LABEL_RE = re.compile(
    r"\b(?:buyer|customer|bill\s*to|sold\s*to|ostja|rechnungsempf[äa]nger)\s*[:\-]?\s*\n?\s*"
    r"([A-Z][A-Za-z0-9&.,\-\s]{2,60}?)(?:\n|$)",
    re.IGNORECASE,
)
_VAT_ID_RE = re.compile(
    r"\b(?:VAT|TAX\s*ID|USt-?ID|KMKR(?:\s*nr\.?)?|Tax\s*Registration)\s*(?:No\.?|Nr\.?|ID)?\s*[:\-]?\s*"
    r"([A-Z]{2}[A-Z0-9\-]{5,15})",
    re.IGNORECASE,
)
_ISO2_PREFIX_RE = re.compile(r"^([A-Z]{2})")

_PAYMENT_TERMS_LABEL_RE = re.compile(
    r"\b(?:payment\s*terms?|terms\s*of\s*payment|tasumistingimus)\s*[:\-]?\s*([A-Za-z0-9 ]{2,30})",
    re.IGNORECASE,
)

# Header-level tax: a label (VAT/IVA/MwSt/GST/SST/Käibemaks) with a percent
# rate, optionally followed by an explicit amount on the same line.
_HEADER_TAX_RE = re.compile(
    r"\b(VAT|IVA|MwSt|GST|SST|K[äa]ibemaks|Tax)\b\D{0,10}?(\d{1,2}(?:[.,]\d+)?)\s*%"
    r"(?:[^\d\n]{0,15}([\d.,]+))?",
    re.IGNORECASE,
)


def _segment_text(rendered: RenderedDocument, segment: Segment) -> str:
    by_number = {p.page_number: p for p in rendered.pages}
    parts = []
    for n in segment.page_numbers:
        page = by_number.get(n)
        if page is not None and page.text:
            parts.append(page.text)
    return "\n".join(parts)


def extract_from_text(text: str) -> ExtractedPayable:
    """Best-effort deterministic extraction of header-level fields from raw
    segment text. Never invents a value: every field is either found via
    pattern match or left absent from `fields`. Line-item table extraction
    remains a known, documented limitation of this text-pattern approach
    (see module docstring / IMPLEMENTATION_PROGRESS.md) — real table
    structure recognition needs vision/LLM understanding this environment
    doesn't have live access to; this function focuses on what a label-based
    regex pass over (OCR or embedded) text can honestly support."""
    result = ExtractedPayable()
    stripped = text.strip()
    if not stripped:
        result.confidence_notes.append("no text available to extract from")
        return result

    m = _INVOICE_NUMBER_RE.search(stripped)
    if m:
        candidate = m.group(1).strip()
        if not _PHONE_LIKE_RE.match(candidate) and not _DATE_LIKE_RE.match(candidate):
            result.fields["invoice_number"] = candidate

    m = _PO_NUMBER_RE.search(stripped)
    if m:
        result.fields["po_number"] = m.group(1).strip()

    m = _CURRENCY_CODE_RE.search(stripped)
    if m:
        result.fields["currency"] = m.group(1)
    else:
        # Fall back to an unambiguous symbol ONLY when no ISO code was
        # found anywhere on the page — never overrides an explicit code
        # (Phase 6's normalize_currency has the same rule; this mirrors it
        # at the extraction stage so the field is populated at all).
        sm = _UNAMBIGUOUS_CURRENCY_SYMBOL_RE.search(stripped)
        if sm:
            result.fields["currency"] = _SYMBOL_TO_ISO[sm.group(0)]

    m = _INVOICE_DATE_LABEL_RE.search(stripped)
    if m:
        result.fields["invoice_date_raw"] = m.group(1)
    m = _DUE_DATE_LABEL_RE.search(stripped)
    if m:
        result.fields["due_date_raw"] = m.group(1)
    if "invoice_date_raw" not in result.fields:
        # Fall back to the first date found ANYWHERE only if there is
        # exactly one distinct date on the page — with two+ unlabeled
        # candidates we cannot safely say which is the invoice date, so we
        # leave it blank rather than guess (per Phase 6/7's fail-safe policy).
        all_dates = set(_ANY_DATE_RE.findall(stripped)) if not m else set()
        flat_dates = {d for group in all_dates for d in (group if isinstance(group, tuple) else (group,)) if d}
        if len(flat_dates) == 1:
            result.fields["invoice_date_raw"] = next(iter(flat_dates))

    m = _SUPPLIER_LABEL_RE.search(stripped)
    if m:
        result.fields["supplier_name"] = m.group(1).strip().rstrip(",.")
    m = _BUYER_LABEL_RE.search(stripped)
    if m:
        result.fields["buyer_name"] = m.group(1).strip().rstrip(",.")

    vat_matches = list(_VAT_ID_RE.finditer(stripped))
    if vat_matches:
        # First VAT-labeled id found is treated as the supplier's (the
        # supplier block conventionally appears before the buyer's tax id
        # in most corpus layouts) — genuinely ambiguous multi-VAT documents
        # are a known limitation, not silently resolved by guessing which is
        # which beyond this convention.
        vat = vat_matches[0].group(1).strip()
        result.fields["supplier_vat_id"] = vat
        country_match = _ISO2_PREFIX_RE.match(vat)
        if country_match:
            result.fields["supplier_country"] = country_match.group(1)

    m = _PAYMENT_TERMS_LABEL_RE.search(stripped)
    if m:
        result.fields["payment_term_text"] = m.group(1).strip()

    m = _TOTAL_LABEL_RE.search(stripped)
    if m:
        result.fields["gross_total_raw"] = m.group(1)
    else:
        amounts = _CURRENCY_AMOUNT_RE.findall(stripped)
        flat = [g1 or g2 for g1, g2 in amounts]
        if flat:
            # Best-effort only: the LAST currency-amount on the page is a
            # weak heuristic for "the total" (totals are usually printed
            # last) — explicitly flagged as low-confidence, never presented
            # as equivalent to a labeled total.
            result.fields["gross_total_raw"] = flat[-1]
            result.confidence_notes.append(
                "gross_total_raw inferred from last currency amount on page, no explicit "
                "total label found — low confidence"
            )

    m = _SUBTOTAL_LABEL_RE.search(stripped)
    if m:
        result.fields["subtotal_raw"] = m.group(1)

    tax_matches = _HEADER_TAX_RE.findall(stripped)
    header_taxes: list[dict[str, str]] = []
    for tax_type, rate, amount in tax_matches:
        header_taxes.append(
            {
                "tax_type": tax_type.upper() if tax_type.upper() != "TAX" else "VAT",
                "tax_rate_raw": rate.replace(",", "."),
                "tax_amount_raw": amount if amount else "",
            }
        )
    if header_taxes:
        result.fields["header_taxes_raw"] = header_taxes

    if not result.fields:
        result.confidence_notes.append("no extractable fields found in available text")

    return result


def check_unit_price_sanity(
    quantity: float, unit_price: float, total: float, tolerance_abs: float = 0.02, tolerance_rel: float = 0.01
) -> bool:
    """Generic numeric sanity check: does quantity x unit_price ≈ total?

    Used to flag (never silently "fix") a line whose printed columns don't
    agree — the general form of the "is this column actually a line
    extension, not a unit price" class of problem. Tolerance is absolute
    (rounding) OR relative (percentage), whichever is looser, since
    documents round at different points."""
    expected = quantity * unit_price
    if total == 0 and expected == 0:
        return True
    abs_diff = abs(expected - total)
    rel_diff = abs_diff / abs(total) if total else float("inf")
    return abs_diff <= tolerance_abs or rel_diff <= tolerance_rel


def extract_payable_from_segment(
    rendered: RenderedDocument, segment: Segment, classification: Classification
) -> ExtractedPayable | None:
    """Production entry point: deterministic pattern extraction over a
    segment's selected page text. Returns None if there's nothing usable to
    extract (never returns a fabricated/empty-but-pretend-successful
    result)."""
    text = _segment_text(rendered, segment)
    extracted = extract_from_text(text)
    if not extracted.fields:
        return None
    return extracted


# --- LLM/vision extraction interface (unverified, no live API key) ---------

_REQUIRED_LLM_FIELDS = {"line_items", "confidence"}


class LLMExtractionError(Exception):
    """Raised when an LLM extraction response fails schema validation."""


def _validate_llm_extraction_response(payload: Any) -> ExtractedPayable:
    """Validate a raw (already-JSON-decoded) LLM extraction response.

    Expected shape: {"fields": {...}, "line_items": [...], "confidence": 0.0}
    Never trusts the LLM to have calculated anything — this only validates
    shape, it never runs or checks arithmetic (that's financial_model.py's
    and erp.py's job)."""
    if not isinstance(payload, dict):
        raise LLMExtractionError("response is not a JSON object")
    if not _REQUIRED_LLM_FIELDS.issubset(payload.keys()):
        missing = _REQUIRED_LLM_FIELDS - payload.keys()
        raise LLMExtractionError(f"missing required fields: {sorted(missing)}")

    line_items = payload.get("line_items")
    if not isinstance(line_items, list):
        raise LLMExtractionError("line_items must be a list")

    confidence = payload.get("confidence")
    if not isinstance(confidence, (int, float)) or not (0.0 <= float(confidence) <= 1.0):
        raise LLMExtractionError(f"invalid confidence: {confidence!r}")

    fields = payload.get("fields", {})
    if not isinstance(fields, dict):
        raise LLMExtractionError("fields must be an object")

    return ExtractedPayable(
        fields=dict(fields),
        line_items=list(line_items),
        confidence_notes=[f"LLM extraction confidence: {confidence}"],
    )


def extract_via_llm_response(
    call_llm: Callable[[], Any],
    max_retries: int = 2,
) -> ExtractedPayable | None:
    """Bounded-retry wrapper around an LLM extraction call. `call_llm` is
    injected so tests can supply a fake/mocked response without any real
    network/API access. Returns None (not a fabricated extraction) if every
    attempt fails validation.

    NOT exercised against a real LLM in this environment: no API key/SDK is
    available here. Only unit-tested via mocked `call_llm` callables.
    """
    for _attempt in range(max_retries + 1):
        try:
            raw = call_llm()
            return _validate_llm_extraction_response(raw)
        except LLMExtractionError:
            continue
        except Exception:  # noqa: BLE001 - any unexpected failure also falls through to retry/None
            continue
    return None
