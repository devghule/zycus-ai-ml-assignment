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

_KNOWN_ISO_CURRENCY_CODES = (
    "EUR|USD|GBP|CHF|THB|SGD|MYR|ZAR|KES|GHS|DKK|PLN|AUD|CAD|SEK|NOK|RON|VND|INR|JPY"
)

_CURRENCY_AMOUNT_RE = re.compile(
    r"(?:[$€£]|\bEUR\b|\bUSD\b|\bGBP\b)\s*([\d.,]+)|([\d.,]+)\s*(?:[$€£]|\bEUR\b|\bUSD\b|\bGBP\b)"
)
_TOTAL_LABEL_RE = re.compile(
    # "gesamtsumme" and "endbetrag" added alongside the existing
    # "gesamtbetrag": all three are distinct, commonly-printed German total
    # labels (found via corpus audit on INV-01 — Combined Improvement Pass,
    # improve-document-understanding) and none is a substring of another,
    # so adding them carries no new false-positive risk.
    r"\b(?:grand\s*total|total\s*due|amount\s*due|total|gesamtbetrag|gesamtsumme|endbetrag|"
    r"kokku|summa|total\s*a\s*pagar)\b"
    rf"[:\s]*(?:[$€£]|\b(?:{_KNOWN_ISO_CURRENCY_CODES})\b)?\s*([\d.,]+)",
    re.IGNORECASE,
)
_SUBTOTAL_LABEL_RE = re.compile(
    r"\b(?:sub\s*total|subtotal|net\s*total|vahesumma)\b"
    rf"[:\s]*(?:[$€£]|\b(?:{_KNOWN_ISO_CURRENCY_CODES})\b)?\s*([\d.,]+)",
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
    # Two conditions, both required, fix a real false-positive class found
    # via corpus audit (Phase 2, improve-document-understanding):
    # "PORTUGAL" -> "RTUGAL", "P.OBox14108" -> "Box14108",
    # "SHPR:POIVexDISTRIBUTIONGMBH" -> "IVexDISTRIBUTIONGMBH".
    #   1. (?![A-Za-z]) immediately after the label token: the character
    #      right after "PO"/"P.O"/"purchase order"/"tellimus" must NOT be a
    #      letter, so the 2-letter "PO" label can never blend into the next
    #      word of running OCR text (a plain \b here is insufficient, since
    #      an optional trailing "." on "P.O." leaves a non-word/non-word
    #      boundary that \b would also reject on the legitimate case).
    #   2. The number-indicator suffix (No./Number/#) is now REQUIRED, not
    #      optional — the same proven fix already applied to
    #      _INVOICE_NUMBER_RE in Phase 11, for the same reason: without a
    #      real suffix there is no positive signal that a value actually
    #      follows, only a bare label.
    r"\b(?:p\.?\s*o\.?|purchase\s*order|tellimus)(?![A-Za-z])\s*(?:no\.?|number|#)\s*[:\-]?\s*"
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

_CURRENCY_CODE_RE = re.compile(rf"\b({_KNOWN_ISO_CURRENCY_CODES})\b")
# Only currency SYMBOLS that are unambiguous in practice (a single currency
# uses them) are extracted directly — "$" is deliberately excluded (it's
# shared by USD/SGD/AUD/CAD/... and guessing would violate the "do not
# guess ambiguous symbols" rule); an ISO code elsewhere on the page (caught
# above) is the correct, unambiguous signal for $-using currencies. "GHC" is
# the old (pre-2007 redenomination) Ghana Cedi symbol, still printed as-is
# on real invoices in this corpus (confirmed: INV-19) even though the ISO
# code / master-data code is "GHS" — this is a literal, unambiguous symbol
# the document itself prints, not an inference from country/supplier.
_UNAMBIGUOUS_CURRENCY_SYMBOL_RE = re.compile(r"[€£]|\bGHC\b")
_SYMBOL_TO_ISO = {"€": "EUR", "£": "GBP", "GHC": "GHS"}

# --- OCR "glue" normalization ------------------------------------------------
# OCR frequently concatenates a currency ISO code directly against an
# adjacent digit or label word with no intervening space (confirmed via
# corpus audit — Combined Improvement Pass, recall investigation:
# "EUR153,58" on DU-06, "AmountZAR"/"TOTALZAR" on INV-04). A plain \b-based
# regex can never match across that boundary, because both the code and the
# digit/letter on either side are \w characters with no transition between
# them. This is purely a whitespace-repair step — it never invents or
# changes any digit, only inserts a space at a boundary the OCR engine
# itself failed to preserve. Restricted to the fixed, known ISO code list
# above, so it cannot fire on unrelated text.
_KNOWN_CURRENCY_MARKERS = f"{_KNOWN_ISO_CURRENCY_CODES}|GHC"
_GLUE_CODE_THEN_DIGIT_RE = re.compile(rf"\b({_KNOWN_CURRENCY_MARKERS})(\d)")
_GLUE_DIGIT_THEN_CODE_RE = re.compile(rf"(\d)({_KNOWN_CURRENCY_MARKERS})\b")
_GLUE_LABEL_THEN_CODE_RE = re.compile(
    rf"\b(total|subtotal|amount|sum)({_KNOWN_CURRENCY_MARKERS})\b", re.IGNORECASE
)


def _repair_ocr_glue(text: str) -> str:
    text = _GLUE_CODE_THEN_DIGIT_RE.sub(r"\1 \2", text)
    text = _GLUE_DIGIT_THEN_CODE_RE.sub(r"\1 \2", text)
    text = _GLUE_LABEL_THEN_CODE_RE.sub(r"\1 \2", text)
    return text

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
# A supplier/buyer LABEL is sometimes immediately followed by ANOTHER
# label line rather than the actual company name (confirmed — corpus
# audit, DU-02: "SELLER" is directly followed by the line "SHIP TO", with
# the real company name two lines further down) — the regex above has no
# way to know that "SHIP TO" isn't a name, since it's syntactically
# identical to one (capitalized words). This is a small, fixed blocklist
# of common shipping/logistics section headers that are never themselves a
# company name; a candidate matching one is rejected (field stays blank)
# rather than kept as a wrong value — consistent with "blank over
# fabrication," just applied to a captured-but-wrong label rather than a
# missing one.
_GENERIC_NON_COMPANY_LABELS = frozenset({
    "ship to", "ship from", "bill to", "bill from", "sold to", "deliver to",
    "delivery to", "delivery address", "importer of record", "consignee",
    "invoice notes", "shipment information", "invoice information",
})


def _looks_like_generic_label(candidate: str) -> bool:
    return candidate.strip().lower() in _GENERIC_NON_COMPANY_LABELS
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

# --- Narrow Estonian tax-summary support (DU-11 class) -----------------------
# "Summa km-ta" = the tax-EXCLUSIVE (net) amount; the VAT line beneath it is
# often abbreviated bare "KM<rate>%" rather than spelled "Käibemaks". Bare
# "KM" is deliberately NOT added to the general _HEADER_TAX_RE alternation
# above: "km" is also the ordinary abbreviation for kilometers, so accepting
# it generically would risk false positives on unrelated documents. It is
# only safe to interpret "KM<digits>%" as a VAT line when it appears
# alongside the much more specific "summa km-ta" net-base anchor phrase,
# which is not a generic multilingual tax-parser redesign — it is a single,
# narrowly-gated fallback that only ever fires when BOTH signals are found
# together (see the caller below).
_ESTONIAN_NET_BASE_RE = re.compile(
    # No trailing \b after "ta": OCR frequently concatenates the label
    # directly against a following rate/percent with no separating space
    # (e.g. "Summakm-ta22%"), and digits count as word characters, so a \b
    # there would (incorrectly) require a non-word character immediately
    # after "ta" — rejecting exactly the real-world case this exists to
    # match. There is no false-positive risk from omitting it here (unlike
    # the PO-label fix above): this phrase is specific enough on its own.
    r"\bsumma\s*km[\s\-]*ta\s*(?:\d{1,2}(?:[.,]\d+)?\s*%)?\D{0,10}?([\-\d.,]+)",
    re.IGNORECASE,
)
_ESTONIAN_VAT_LINE_RE = re.compile(
    r"\bkm\s*(\d{1,2}(?:[.,]\d+)?)\s*%\D{0,10}?([\-\d.,]+)",
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
    stripped = _repair_ocr_glue(stripped)

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
    if m and not _looks_like_generic_label(m.group(1)):
        result.fields["supplier_name"] = m.group(1).strip().rstrip(",.")
    m = _BUYER_LABEL_RE.search(stripped)
    if m and not _looks_like_generic_label(m.group(1)):
        result.fields["buyer_name"] = m.group(1).strip().rstrip(",.")

    # Real VAT/tax registration identifiers universally contain at least one
    # digit after the country-code prefix (confirmed against every VAT
    # format in master_data/suppliers.json). A candidate with NO digit at
    # all is not a VAT id — it's virtually always a table/document header
    # caught by the regex's re.IGNORECASE flag treating any two letters as
    # a plausible "country code" (e.g. "AmountGBP", a "Amount, GBP" column
    # header, found via corpus audit — Phase 2, improve-document-understanding).
    # This is a narrow structural rejection, not an attempt at general VAT
    # validation — it only rejects candidates that could not possibly be a
    # real identifier, never second-guesses a candidate that has a digit.
    def _looks_like_real_vat_id(candidate: str) -> bool:
        return any(ch.isdigit() for ch in candidate)

    vat_matches = [m for m in _VAT_ID_RE.finditer(stripped) if _looks_like_real_vat_id(m.group(1))]
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

    if "subtotal_raw" not in result.fields and "header_taxes_raw" not in result.fields:
        # Narrow Estonian tax-summary fallback — only fires when BOTH the
        # net-base anchor AND a matching VAT-rate line are found; either
        # alone leaves the fields untouched (fail safe, per Phase 6/7
        # policy: no partial/guessed structure).
        net_m = _ESTONIAN_NET_BASE_RE.search(stripped)
        vat_m = _ESTONIAN_VAT_LINE_RE.search(stripped)
        if net_m and vat_m:
            result.fields["subtotal_raw"] = net_m.group(1)
            result.fields["header_taxes_raw"] = [
                {
                    "tax_type": "VAT",
                    "tax_rate_raw": vat_m.group(1).replace(",", "."),
                    "tax_amount_raw": vat_m.group(2),
                }
            ]

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
