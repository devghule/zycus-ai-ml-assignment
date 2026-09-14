"""Entry point: process every document under documents/ and write output/*.json.

Usage:
    python run.py

This is the one documented command the brief asks for. It discovers PDFs
dynamically (never assumes a fixed corpus size), processes each one with
full error isolation (one bad file must not crash the batch), and writes a
schema-shaped output/<stem>.json for every input file.

Phase 1 status: the pipeline stages are stubs (see pipeline/*.py). This
runner proves the skeleton end-to-end — discovery, per-document error
isolation, and schema-shaped output — without pretending Phase 4+
classification/extraction/financial-modeling logic already exists. Every
document currently yields an honest empty result (no payables claimed, no
declines claimed) rather than a fabricated one.
"""
from __future__ import annotations

import logging
import sys

from config import DOCUMENTS_DIR, OUTPUT_DIR
from pipeline.assemble_output import DocumentResult, declined_entry, write_result
from pipeline.discovery import discover_documents
from pipeline.duplicate_detection import DuplicateRegistry, DuplicateVerdict, build_evidence
from pipeline.extraction import extract_payable_from_segment
from pipeline.financial_model import FinancialFacts, LineItemFact, build_canonical_payable
from pipeline.locale_normalize import LocaleNormalizationError, normalize_date, normalize_number
from pipeline.logging_setup import configure_logging
from pipeline.matching.master_data import MasterDataMatcher
from pipeline.matching.match_result import MatchStatus
from pipeline.ocr_render import render_document
from pipeline.segmentation import segment_document
from pipeline.classification import DocumentClass, classify_segment
from pipeline.validation import adjudicate

logger = logging.getLogger(__name__)


def _normalize_optional(raw: str, normalize_fn) -> str:
    """Normalize `raw` with `normalize_fn`, returning "" for blank input or
    on any normalization failure — never lets an un-normalized raw string
    (e.g. a comma-thousands number) leak into a schema field that requires
    dot-decimal form. Shared by every optional date/number field below so
    this fail-safe behavior is defined exactly once."""
    if not raw:
        return ""
    try:
        return normalize_fn(raw)
    except LocaleNormalizationError:
        return ""


def _facts_from_extraction(extracted, classification) -> FinancialFacts | None:
    """Bridge Phase 5's pattern-extraction output into Phase 7's
    FinancialFacts shape. Only proceeds if a stated gross total was found —
    without one there is nothing for erp.py to reconcile against, and
    fabricating one is prohibited.

    Two structures are attempted, in order of evidence strength:
      1. If a subtotal AND at least one header tax rate/amount were found,
         build a line item at the subtotal (the net, tax-exclusive base)
         plus the extracted header tax(es) — this can reconcile documents
         with a real subtotal->tax->total structure, not just a trivial
         single-total case.
      2. Otherwise, the minimal defensible fallback: a single line item
         carrying the stated gross as its own unit_price (no tax) — the
         honest limit when only a bare total was found.

    Line-item-level (per-SKU) extraction remains a documented limitation —
    this bridge only reconstructs HEADER-level structure from what the
    text-pattern extractor can support without real vision/table
    understanding."""
    gross_raw = extracted.fields.get("gross_total_raw")
    if not gross_raw:
        return None

    try:
        gross = normalize_number(gross_raw)
    except LocaleNormalizationError:
        return None
    if not gross:
        return None

    currency = extracted.fields.get("currency", "")
    invoice_type = (
        "CREDIT_MEMO" if classification.doc_class == DocumentClass.PAYABLE_CREDIT_MEMO else "INVOICE"
    )

    header_taxes: list[dict] = []
    for raw_tax in extracted.fields.get("header_taxes_raw", []):
        rate_raw = raw_tax.get("tax_rate_raw", "")
        amount_raw = raw_tax.get("tax_amount_raw", "")
        try:
            rate = normalize_number(rate_raw) if rate_raw else ""
        except LocaleNormalizationError:
            rate = ""
        try:
            amount = normalize_number(amount_raw) if amount_raw else ""
        except LocaleNormalizationError:
            amount = ""
        if not rate and not amount:
            continue
        header_taxes.append(
            {
                "tax_type": raw_tax.get("tax_type", ""),
                "tax_name": raw_tax.get("tax_type", ""),
                "tax_rate": rate,
                "tax_amount": amount,
                "tax_type_code": "",
            }
        )

    subtotal_raw = extracted.fields.get("subtotal_raw")
    if subtotal_raw and header_taxes:
        try:
            subtotal = normalize_number(subtotal_raw)
        except LocaleNormalizationError:
            subtotal = ""
        if subtotal:
            line_items = [LineItemFact(quantity="1", unit_price=subtotal, total=subtotal)]
            return FinancialFacts(
                invoice_type=invoice_type,
                currency=currency,
                line_items=line_items,
                header_taxes=header_taxes,
                stated_gross=gross,
            )

    line_items = [LineItemFact(quantity="1", unit_price=gross, total=gross)]
    return FinancialFacts(
        invoice_type=invoice_type,
        currency=currency,
        line_items=line_items,
        stated_gross=gross,
    )


def _resolve_master_data(payload: dict, extracted, matcher: MasterDataMatcher) -> None:
    """Phase 8: resolve master-data codes onto `payload` in place, using
    ONLY evidence `extracted` actually produced. If Phase 5's sparse
    extractor found no supplier name/VAT, no buyer country, no PO number,
    etc., the corresponding matcher calls correctly return blank — this is
    NOT a Phase 8 defect, it's the honest consequence of what extraction
    could see (see Phase 5 notes). No evidence is invented here to make
    matching "demonstrate" something it has nothing to work with."""
    supplier_name = extracted.fields.get("supplier_name", "")
    supplier_vat = extracted.fields.get("supplier_vat_id", "")
    supplier_country = extracted.fields.get("supplier_country", "")
    supplier_result = matcher.match_supplier(name=supplier_name, vat_id=supplier_vat, country=supplier_country)
    supplier_id = supplier_result.matched_id if supplier_result.status == MatchStatus.MATCHED else ""
    if supplier_id and matcher.validate_supplier_id(supplier_id):
        payload["supplier"]["supplier_id"] = supplier_id

    buyer_country = extracted.fields.get("buyer_country", "")
    buyer_explicit_bu = extracted.fields.get("buyer_business_unit_code", "")
    buyer_codes, buyer_result = matcher.match_buyer(buyer_country=buyer_country, explicit_bu_code=buyer_explicit_bu)
    if buyer_result.status == MatchStatus.MATCHED and matcher.validate_bu_code(buyer_codes.business_unit_code):
        payload["buyer"]["company_code"] = buyer_codes.company_code
        payload["buyer"]["business_unit_code"] = buyer_codes.business_unit_code
        payload["buyer"]["location_code"] = buyer_codes.location_code

    payment_term_text = extracted.fields.get("payment_term_text", "")
    pt_result = matcher.match_payment_term(
        text=payment_term_text,
        invoice_date=payload.get("invoice_date", ""),
        due_date=payload.get("due_date", ""),
    )
    if pt_result.status == MatchStatus.MATCHED and matcher.validate_payment_term_id(pt_result.matched_id):
        payload["payment_term_id"] = pt_result.matched_id

    po_number = extracted.fields.get("po_number", "")
    if po_number:
        payload["po_number"] = po_number
        po_result = matcher.match_po(po_number, supplier_id=supplier_id, currency=payload.get("currency", ""))
        if po_result.status == MatchStatus.MATCHED and matcher.validate_po_id(po_result.matched_id):
            payload["po_id"] = po_result.matched_id

    resolved_country = supplier_country or buyer_country
    for tax in payload.get("taxes", []):
        _resolve_one_tax(tax, resolved_country, matcher)
    for li in payload.get("line_items", []):
        for tax in li.get("taxes", []):
            _resolve_one_tax(tax, resolved_country, matcher)


def _resolve_one_tax(tax: dict, country: str, matcher: MasterDataMatcher) -> None:
    explicit_code = tax.get("tax_type_code", "")
    rate_str = str(tax.get("tax_rate") or "").strip()
    rate = None
    if rate_str:
        try:
            rate = float(rate_str)
        except ValueError:
            rate = None
    result = matcher.match_tax(country=country, tax_type=tax.get("tax_type", ""), rate=rate, explicit_code=explicit_code)
    if result.status == MatchStatus.MATCHED and matcher.validate_tax_code(result.matched_id):
        tax["tax_type_code"] = result.matched_id


def process_one(doc_path, matcher: MasterDataMatcher, duplicate_registry: DuplicateRegistry) -> DocumentResult:
    """Run the full stage sequence for one document, isolating any failure
    to this document alone.

    Phases 2-9 status: render (real local OCR fallback when the optional
    rapidocr-onnxruntime dependency is installed, else the honest NULL
    provider), segment, classify are real and corpus-run. Extraction is a
    deterministic, label/pattern-based extractor (no LLM/vision API
    available here) — it only produces a payable when it found an explicit
    stated gross total; everything else stays blank rather than fabricated.
    The resulting facts are run through the canonical financial model,
    which is validated against the REAL erp.py: only a payable whose
    recomputed gross reconciles EXACTLY with the extracted stated gross
    becomes a candidate. Master-data codes are then resolved (Phase 8)
    using only whatever evidence extraction actually produced. Finally,
    Phase 9 duplicate detection checks the candidate against every payable
    already booked earlier in this run — a strong match (exact file, exact
    content, or complete business-key) declines it as
    DUPLICATE_OF_BOOKED_PAYABLE instead of double-booking; a weaker
    (advisory) match does not block booking."""
    result = DocumentResult(file_name=doc_path.name)

    rendered = render_document(doc_path)
    if rendered.render_error:
        logger.warning("%s: render failed: %s", doc_path.name, rendered.render_error)
        return result

    segments = segment_document(rendered)
    for segment in segments:
        classification = classify_segment(rendered, segment)
        logger.debug(
            "%s: segment pages=%s -> %s (%s)",
            doc_path.name,
            segment.page_numbers,
            classification.doc_class,
            classification.doc_type,
        )

        if classification.doc_class in (DocumentClass.NON_PAYABLE, DocumentClass.AMBIGUOUS_UNSOLVABLE):
            result.declined.append(declined_entry(classification.doc_type, classification.reason))
            continue

        # PAYABLE_INVOICE / PAYABLE_CREDIT_MEMO from here on.
        extracted = extract_payable_from_segment(rendered, segment, classification)
        if extracted is None:
            result.declined.append(
                declined_entry(
                    classification.doc_type,
                    "Classified as payable but no extractable fields (no stated gross total "
                    "found in the available text) — no OCR/LLM vision available in this "
                    "environment to interpret the scanned page. Declining rather than guessing.",
                )
            )
            continue

        facts = _facts_from_extraction(extracted, classification)
        if facts is None:
            result.declined.append(
                declined_entry(
                    classification.doc_type,
                    "Classified as payable but could not build financial facts (missing or "
                    "unnormalizable stated gross total).",
                )
            )
            continue

        canonical = build_canonical_payable(facts)
        if not canonical.reconciled:
            result.declined.append(
                declined_entry(
                    classification.doc_type,
                    f"Could not reconcile a candidate payable against erp.py: {canonical.reason}",
                )
            )
            continue

        payload = canonical.payload
        payload.setdefault("invoice_number", extracted.fields.get("invoice_number", ""))

        payload.setdefault("invoice_date", _normalize_optional(extracted.fields.get("invoice_date_raw", ""), normalize_date))
        payload.setdefault("due_date", _normalize_optional(extracted.fields.get("due_date_raw", ""), normalize_date))

        payload.setdefault(
            "supplier",
            {
                "name": extracted.fields.get("supplier_name", ""),
                "supplier_id": "",
                "address": "",
                "vat_id": extracted.fields.get("supplier_vat_id", ""),
            },
        )
        payload.setdefault(
            "buyer", {"company_code": "", "business_unit_code": "", "location_code": ""}
        )
        payload.setdefault("payment_term_id", "")
        payload.setdefault("po_number", "")
        payload.setdefault("po_id", "")
        subtotal_display = _normalize_optional(extracted.fields.get("subtotal_raw", ""), normalize_number)
        if payload.get("invoice_type") == "CREDIT_MEMO" and subtotal_display.startswith("-"):
            # Mirror financial_model.py's positive-magnitude convention for
            # credit memos on this display-only field (subtotal itself is
            # never fed back through the financial model, so it needs its
            # own single, narrow sign normalization here — applied exactly
            # once, consistent with how gross_total is already positive).
            subtotal_display = subtotal_display[1:]
        payload.setdefault("subtotal", subtotal_display)
        payload.setdefault("total_tax_amount", "")

        _resolve_master_data(payload, extracted, matcher)

        segment_text = "\n".join(
            p.text for p in rendered.pages if p.page_number in segment.page_numbers and p.text
        )
        supplier_identity = payload["supplier"].get("supplier_id") or payload["supplier"].get("name", "")
        evidence = build_evidence(
            doc_path,
            full_text=segment_text,
            supplier_identity=supplier_identity,
            invoice_number=payload.get("invoice_number", ""),
            invoice_date=payload.get("invoice_date", ""),
            currency=payload.get("currency", ""),
            gross_total=payload.get("gross_total", ""),
        )
        dup_check = duplicate_registry.check(doc_path.name, evidence)
        if dup_check.verdict == DuplicateVerdict.DUPLICATE_OF_BOOKED_PAYABLE:
            result.declined.append(
                declined_entry("duplicate_payable", f"DUPLICATE_OF_BOOKED_PAYABLE: {dup_check.reason}")
            )
            continue

        # Phase 10: final adjudication gate — schema/groundedness/evidence-
        # sufficiency/classification-consistency/master-data-validity/
        # financial-consistency/credit-memo/tax-consistency/exact-ERP
        # checks, all as a last safety net immediately before booking. A
        # hard failure here declines the document; it is never silently
        # repaired or booked anyway.
        validation = adjudicate(
            payload,
            extracted.fields,
            classification.doc_class.value,
            classification.evidence,
            matcher,
            raw_text=segment_text,
        )
        if not validation.ok:
            result.declined.append(declined_entry(classification.doc_type, validation.decline_message()))
            continue

        duplicate_registry.register(doc_path.name, evidence)
        result.payables.append(payload)

    return result


def main() -> int:
    configure_logging()
    documents = discover_documents(DOCUMENTS_DIR)
    logger.info("processing %d document(s) -> %s", len(documents), OUTPUT_DIR)

    matcher = MasterDataMatcher()  # loaded once, reused across all documents
    duplicate_registry = DuplicateRegistry()  # one registry per run, shared across all documents

    failures = 0
    for doc in documents:
        try:
            result = process_one(doc.path, matcher, duplicate_registry)
        except Exception:  # noqa: BLE001 - error isolation: one bad PDF must not crash the batch
            logger.exception("unhandled failure processing %s", doc.path.name)
            failures += 1
            result = DocumentResult(file_name=doc.path.name)
        write_result(result, OUTPUT_DIR)

    logger.info("done: %d processed, %d failed", len(documents), failures)
    return 0


if __name__ == "__main__":
    sys.exit(main())
