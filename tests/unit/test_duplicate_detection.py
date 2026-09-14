"""Phase 9: duplicate detection — five layers, booking-aware, deterministic."""
from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.duplicate_detection import (
    HIGH_CONFIDENCE_NEAR_DUPLICATE_SIMILARITY_THRESHOLD,
    DuplicateRegistry,
    DuplicateVerdict,
    build_evidence,
    compute_business_key,
    compute_content_hash,
    compute_file_hash,
    detect_copy_indicator,
)


@pytest.fixture()
def make_pdf(tmp_path: Path):
    def _make(name: str, content: bytes) -> Path:
        p = tmp_path / name
        p.write_bytes(content)
        return p

    return _make


# 1. byte-identical files -> duplicate
def test_byte_identical_files_are_duplicate(make_pdf):
    a = make_pdf("a.pdf", b"%PDF-1.4 identical bytes here")
    b = make_pdf("b.pdf", b"%PDF-1.4 identical bytes here")
    registry = DuplicateRegistry()

    ev_a = build_evidence(a, full_text="Invoice 123")
    assert registry.check("a.pdf", ev_a).verdict == DuplicateVerdict.NONE
    registry.register("a.pdf", ev_a)

    ev_b = build_evidence(b, full_text="Invoice 123")
    result = registry.check("b.pdf", ev_b)
    assert result.verdict == DuplicateVerdict.DUPLICATE_OF_BOOKED_PAYABLE
    assert result.method == "file_hash"


# 2. identical content, different file metadata -> duplicate
def test_identical_content_different_bytes_is_duplicate(make_pdf):
    a = make_pdf("a.pdf", b"%PDF-1.4 version A bytes, metadata differs")
    b = make_pdf("b.pdf", b"%PDF-1.5 version B bytes, totally different wrapper")
    registry = DuplicateRegistry()

    same_text = "Invoice No: 999\nTotal: 100.00"
    ev_a = build_evidence(a, full_text=same_text)
    registry.register("a.pdf", ev_a)

    ev_b = build_evidence(b, full_text=same_text)
    result = registry.check("b.pdf", ev_b)
    assert result.verdict == DuplicateVerdict.DUPLICATE_OF_BOOKED_PAYABLE
    assert result.method == "content_hash"


# 3. same supplier + invoice number + date + total -> strong business-key duplicate
def test_full_business_key_match_is_duplicate(make_pdf):
    a = make_pdf("a.pdf", b"content A")
    b = make_pdf("b.pdf", b"totally different content B")
    registry = DuplicateRegistry()

    ev_a = build_evidence(
        a, supplier_identity="Acme Ltd", invoice_number="INV-1", invoice_date="2026-01-01",
        currency="EUR", gross_total="100.00",
    )
    registry.register("a.pdf", ev_a)

    ev_b = build_evidence(
        b, supplier_identity="Acme Ltd", invoice_number="INV-1", invoice_date="2026-01-01",
        currency="EUR", gross_total="100.00",
    )
    result = registry.check("b.pdf", ev_b)
    assert result.verdict == DuplicateVerdict.DUPLICATE_OF_BOOKED_PAYABLE
    assert result.method == "business_key"


# 4. same invoice number but different supplier -> NOT automatically duplicate
def test_same_invoice_number_different_supplier_not_duplicate(make_pdf):
    a = make_pdf("a.pdf", b"content A unique")
    b = make_pdf("b.pdf", b"content B unique different")
    registry = DuplicateRegistry()

    ev_a = build_evidence(
        a, supplier_identity="Acme Ltd", invoice_number="INV-1", invoice_date="2026-01-01",
        currency="EUR", gross_total="100.00",
    )
    registry.register("a.pdf", ev_a)

    ev_b = build_evidence(
        b, supplier_identity="Different Supplier Inc", invoice_number="INV-1", invoice_date="2026-01-01",
        currency="EUR", gross_total="100.00",
    )
    result = registry.check("b.pdf", ev_b)
    assert result.verdict != DuplicateVerdict.DUPLICATE_OF_BOOKED_PAYABLE


# 5. same supplier but different invoice number -> NOT automatically duplicate
def test_same_supplier_different_invoice_number_not_duplicate(make_pdf):
    a = make_pdf("a.pdf", b"content A unique 2")
    b = make_pdf("b.pdf", b"content B unique different 2")
    registry = DuplicateRegistry()

    ev_a = build_evidence(
        a, supplier_identity="Acme Ltd", invoice_number="INV-1", invoice_date="2026-01-01",
        currency="EUR", gross_total="100.00",
    )
    registry.register("a.pdf", ev_a)

    ev_b = build_evidence(
        b, supplier_identity="Acme Ltd", invoice_number="INV-2", invoice_date="2026-01-01",
        currency="EUR", gross_total="100.00",
    )
    result = registry.check("b.pdf", ev_b)
    assert result.verdict != DuplicateVerdict.DUPLICATE_OF_BOOKED_PAYABLE


# 6. near duplicate -> advisory/not automatic decline
def test_near_duplicate_text_is_advisory_not_auto_declined(make_pdf):
    a = make_pdf("a.pdf", b"content A near dup")
    b = make_pdf("b.pdf", b"content B near dup slightly different")
    registry = DuplicateRegistry()

    text_a = "Invoice No: 42\nSupplier: Acme Ltd\nTotal Due: EUR 500.00\nThank you for your business."
    text_b = "Invoice No: 42\nSupplier: Acme Ltd\nTotal Due: EUR 500.00\nThank you for your business!"

    ev_a = build_evidence(a, full_text=text_a)
    registry.register("a.pdf", ev_a)

    ev_b = build_evidence(b, full_text=text_b)
    result = registry.check("b.pdf", ev_b)
    assert result.verdict == DuplicateVerdict.ADVISORY
    assert result.method == "near_duplicate"


# 7. "Copy" alone -> NOT automatic decline
def test_copy_label_alone_is_not_auto_declined(make_pdf):
    a = make_pdf("a.pdf", b"unique content copy label")
    registry = DuplicateRegistry()
    ev = build_evidence(a, full_text="COPY TAX INVOICE\nInvoice No: 77\nTotal: 250.00")
    assert detect_copy_indicator("COPY TAX INVOICE") is True
    result = registry.check("a.pdf", ev)
    assert result.verdict != DuplicateVerdict.DUPLICATE_OF_BOOKED_PAYABLE
    assert result.verdict == DuplicateVerdict.ADVISORY


# 8. "Copy" + strong identical business evidence -> duplicate
def test_copy_label_plus_strong_business_evidence_is_duplicate(make_pdf):
    a = make_pdf("a.pdf", b"original invoice bytes")
    b = make_pdf("b.pdf", b"copy invoice bytes completely different file")
    registry = DuplicateRegistry()

    ev_a = build_evidence(
        a, full_text="TAX INVOICE\nInvoice No: 88",
        supplier_identity="Acme Ltd", invoice_number="88", invoice_date="2026-02-02",
        currency="ZAR", gross_total="8550.00",
    )
    registry.register("a.pdf", ev_a)

    ev_b = build_evidence(
        b, full_text="COPY TAX INVOICE\nInvoice No: 88",
        supplier_identity="Acme Ltd", invoice_number="88", invoice_date="2026-02-02",
        currency="ZAR", gross_total="8550.00",
    )
    result = registry.check("b.pdf", ev_b)
    assert result.verdict == DuplicateVerdict.DUPLICATE_OF_BOOKED_PAYABLE
    assert result.method == "business_key"


# 9 & 10. first valid payable remains bookable; second strong duplicate becomes DUPLICATE_OF_BOOKED_PAYABLE
def test_first_payable_bookable_second_strong_duplicate_declined(make_pdf):
    a = make_pdf("a.pdf", b"same bytes exactly")
    b = make_pdf("b.pdf", b"same bytes exactly")
    registry = DuplicateRegistry()

    ev_a = build_evidence(a, full_text="Invoice 1")
    first = registry.check("a.pdf", ev_a)
    assert first.verdict == DuplicateVerdict.NONE  # first document is bookable
    registry.register("a.pdf", ev_a)

    ev_b = build_evidence(b, full_text="Invoice 1")
    second = registry.check("b.pdf", ev_b)
    assert second.verdict == DuplicateVerdict.DUPLICATE_OF_BOOKED_PAYABLE
    assert second.matched_against == "a.pdf"


# 11. missing evidence does not create a fake duplicate key
def test_missing_evidence_does_not_create_fake_business_key():
    key = compute_business_key("Acme Ltd", "INV-1", "", "EUR", "100.00")  # missing invoice_date
    assert key == ""

    key_all_present = compute_business_key("Acme Ltd", "INV-1", "2026-01-01", "EUR", "100.00")
    assert key_all_present != ""


def test_empty_text_produces_no_content_hash():
    assert compute_content_hash("") == ""
    assert compute_content_hash("   ") == ""


# 12. deterministic repeated results
def test_duplicate_detection_is_deterministic(make_pdf):
    a = make_pdf("a.pdf", b"deterministic content")
    h1 = compute_file_hash(a)
    h2 = compute_file_hash(a)
    assert h1 == h2

    c1 = compute_content_hash("Invoice 123 Total 45.00")
    c2 = compute_content_hash("Invoice 123 Total 45.00")
    assert c1 == c2

    k1 = compute_business_key("Acme", "1", "2026-01-01", "EUR", "1.00")
    k2 = compute_business_key("Acme", "1", "2026-01-01", "EUR", "1.00")
    assert k1 == k2


# 13 & 14. duplicate detection does not modify financial amounts or master-data IDs
def test_duplicate_detection_never_touches_payload_fields(make_pdf):
    """DuplicateRegistry only ever returns a verdict/reason — it has no
    method that accepts or mutates a payable dict at all, so there is
    structurally no way for it to alter gross_total or any master-data ID."""
    import inspect

    from pipeline.duplicate_detection import DuplicateRegistry as Registry

    for name, method in inspect.getmembers(Registry, predicate=inspect.isfunction):
        sig = inspect.signature(method)
        assert "payload" not in sig.parameters
        assert "payable" not in sig.parameters


# 15. existing non-payable documents are not incorrectly converted into duplicate payables
def test_unregistered_declined_document_cannot_cause_false_duplicate(make_pdf):
    """A document that was declined (never registered) must not poison
    later duplicate checks — only `register`ed (i.e. actually booked)
    documents participate in future duplicate detection."""
    a = make_pdf("a.pdf", b"a non-payable delivery note")
    b = make_pdf("b.pdf", b"a genuine invoice with similar wording")
    registry = DuplicateRegistry()

    ev_a = build_evidence(a, full_text="DELIVERY NOTE\nNo prices, not a payable.")
    # a is classified NON_PAYABLE and declined -> never registered.
    result_a = registry.check("a.pdf", ev_a)
    assert result_a.verdict == DuplicateVerdict.NONE
    # Deliberately do NOT call registry.register("a.pdf", ev_a)

    ev_b = build_evidence(b, full_text="DELIVERY NOTE\nNo prices, not a payable.")  # same text, hypothetically
    result_b = registry.check("b.pdf", ev_b)
    # Since "a" was never registered (it was declined, not booked), "b" must
    # not be flagged as a duplicate of it.
    assert result_b.verdict != DuplicateVerdict.DUPLICATE_OF_BOOKED_PAYABLE


def test_multiple_segments_from_same_bundled_file_are_not_flagged_as_duplicates(make_pdf):
    """Regression test: a single PDF bundling several distinct logical
    payables (e.g. a consolidated customs invoice with 10+ sub-invoices —
    a real corpus pattern) must not have its own later segments flagged as
    'duplicate of itself' merely because they share the same source file
    bytes/content. Only a genuinely DIFFERENT file/document should ever
    trigger file_hash or content_hash duplicate evidence."""
    bundle = make_pdf("bundle.pdf", b"one PDF containing many sub-invoices")
    registry = DuplicateRegistry()

    # Segment 1 of the bundle: booked.
    ev1 = build_evidence(
        bundle, full_text="Sub-invoice 1 content",
        supplier_identity="Acme", invoice_number="SUB-1", invoice_date="2026-01-01",
        currency="EUR", gross_total="10.00",
    )
    result1 = registry.check("bundle.pdf", ev1)
    assert result1.verdict == DuplicateVerdict.NONE
    registry.register("bundle.pdf", ev1)

    # Segment 2 of the SAME bundle (same file_hash, since it's the same
    # physical PDF) but a genuinely different sub-invoice.
    ev2 = build_evidence(
        bundle, full_text="Sub-invoice 2 content, different amount",
        supplier_identity="Acme", invoice_number="SUB-2", invoice_date="2026-01-01",
        currency="EUR", gross_total="20.00",
    )
    result2 = registry.check("bundle.pdf", ev2)
    assert result2.verdict != DuplicateVerdict.DUPLICATE_OF_BOOKED_PAYABLE


# --- High-confidence near-duplicate promotion (Combined Improvement Pass,
# duplicate-resolution investigation: INV-04/INV-07) --------------------------
#
# These two documents are two independently-scanned copies of the same
# underlying invoice: OCR noise means content_hash differs, and neither
# extraction produced an invoice_number/date/supplier, so no business_key
# can be built either. The only remaining honest signals are near-total
# text similarity plus exact-matching currency and gross_total — this is
# what the new tier promotes to an auto-decline, and ONLY when all three
# hold together.

# Modeled directly on the real INV-04/INV-07 OCR text (same proportions:
# a small address-line difference against a much larger shared body), so
# the similarity score this produces is representative of the real pair
# (~0.987) rather than an artificially short fixture that exaggerates the
# one differing line's weight.
_INV04_TEXT = (
    "InvoiceDate\nTAXINVOICE\nLarkspurDistributionMeridianPrint\n30Apr2025\n"
    "LarkspurDistributionMeridianPrint\nGartenweg173\n"
    "NorthwindServicesZA(Pty)MeridianPrintLtd\nINV7097292303\nF04,KiepersolHouse\n"
    "RuadoOuro5\nBahnhofstrasse300\nUnit7,BlockB\nINV7097292303\nDarrenwood\n"
    "Gartenweg60\nGauteng\nMaitland\n2195\n8690782647\n"
    "WESTERNCAPECAPETOWN7405\nSouthAfrica\nSOUTHAFRICA\n"
    "VATNumber:9446639440\nDescription\nQuantity\nUnitPrice\nVAT\nAmountZAR\n"
    "StandardCriminalVerification\n133.00\n129.00\n15%\n17,157.00\n"
    "Subtotal\n17,157.00\nTOTALVAT\n2,573.55\nTOTALZAR\n19,730.55\n"
    "LessAmountCredited\n13,110.00\nAMOUNTDUEZAR\n6,620.55\nDueDate:31May2025\n"
    "OakhavenDistributionMeridianPrintLtd\nRedwaterBank\nBranch:Sand\n"
    "BranchNumber-\nAccount\n897530172\nSWIFT:SYEWTNPV\n"
    "Pleaseuseyourinvoicenumberasreferencewhenmakingpayment.\n"
    "CompanyRegistrationNo:3268/558090/90.RegisteredOffice:Gartenweg173"
)
_INV07_TEXT = _INV04_TEXT.replace("RuadoOuro5", "M5OfficePark")


def test_high_confidence_near_duplicate_pair_is_auto_declined(make_pdf):
    a = make_pdf("INV-04.pdf", b"scan one of the invoice")
    b = make_pdf("INV-07.pdf", b"scan two of the same invoice, different bytes")
    registry = DuplicateRegistry()

    ev_a = build_evidence(a, full_text=_INV04_TEXT, currency="ZAR", gross_total="19730.55")
    assert ev_a.business_key == ""  # no invoice_number/date/supplier — confirms the real scenario
    registry.register("INV-04.pdf", ev_a)

    ev_b = build_evidence(b, full_text=_INV07_TEXT, currency="ZAR", gross_total="19730.55")
    result = registry.check("INV-07.pdf", ev_b)
    assert result.verdict == DuplicateVerdict.DUPLICATE_OF_BOOKED_PAYABLE
    assert result.method == "high_confidence_near_duplicate"


def test_high_confidence_survivor_is_the_first_booked_deterministically(make_pdf):
    # Discovery order is filename-sorted (pipeline/discovery.py), so
    # "INV-04.pdf" is always processed/booked before "INV-07.pdf" — the
    # survivor is whichever was registered first, with no extra scoring
    # logic needed. Confirm the matched_against/surviving identifier.
    a = make_pdf("INV-04.pdf", b"scan one")
    b = make_pdf("INV-07.pdf", b"scan two")
    registry = DuplicateRegistry()
    ev_a = build_evidence(a, full_text=_INV04_TEXT, currency="ZAR", gross_total="19730.55")
    registry.register("INV-04.pdf", ev_a)
    ev_b = build_evidence(b, full_text=_INV07_TEXT, currency="ZAR", gross_total="19730.55")
    result = registry.check("INV-07.pdf", ev_b)
    assert result.matched_against == "INV-04.pdf"


def test_same_amount_but_different_invoice_evidence_not_duplicate(make_pdf):
    # Same currency and gross_total, but genuinely different underlying
    # text (different supplier, different line items) — similarity stays
    # well below even the advisory bar, so this must not merge.
    a = make_pdf("a.pdf", b"invoice one")
    b = make_pdf("b.pdf", b"invoice two")
    registry = DuplicateRegistry()
    ev_a = build_evidence(
        a, full_text="Acme Consulting Ltd\nProfessional services rendered in March\nHourly rate 150.00",
        currency="EUR", gross_total="500.00",
    )
    registry.register("a.pdf", ev_a)
    ev_b = build_evidence(
        b, full_text="Zenith Office Supplies\nStationery order #4471\nBulk paper and toner delivery",
        currency="EUR", gross_total="500.00",
    )
    result = registry.check("b.pdf", ev_b)
    assert result.verdict != DuplicateVerdict.DUPLICATE_OF_BOOKED_PAYABLE


def test_similar_template_different_transaction_not_duplicate(make_pdf):
    # Same supplier/template/wording, but a DIFFERENT invoice number and
    # DIFFERENT amount — a real recurring-invoice scenario. gross_total
    # differs, so the high-confidence tier's exact-match requirement can
    # never fire, regardless of how similar the surrounding template text is.
    a = make_pdf("a.pdf", b"march invoice")
    b = make_pdf("b.pdf", b"april invoice")
    registry = DuplicateRegistry()
    ev_a = build_evidence(
        a, full_text="Northwind Services\nMonthly retainer\nInvoice No: 100\nTotal Due: EUR 500.00",
        currency="EUR", gross_total="500.00",
    )
    registry.register("a.pdf", ev_a)
    ev_b = build_evidence(
        b, full_text="Northwind Services\nMonthly retainer\nInvoice No: 101\nTotal Due: EUR 525.00",
        currency="EUR", gross_total="525.00",
    )
    result = registry.check("b.pdf", ev_b)
    assert result.verdict != DuplicateVerdict.DUPLICATE_OF_BOOKED_PAYABLE


def test_near_duplicate_missing_financial_corroboration_stays_advisory(make_pdf):
    # High text similarity (above the advisory bar) but currency/gross_total
    # not both available — must NOT be promoted, stays advisory only.
    a = make_pdf("a.pdf", b"scan one, no financials extracted")
    b = make_pdf("b.pdf", b"scan two, no financials extracted")
    registry = DuplicateRegistry()
    text = "Invoice No: 42\nSupplier: Acme Ltd\nTotal Due: EUR 500.00\nThank you for your business."
    ev_a = build_evidence(a, full_text=text)  # currency/gross_total default to ""
    registry.register("a.pdf", ev_a)
    ev_b = build_evidence(b, full_text=text + "!")  # trivial variation, same missing financials
    result = registry.check("b.pdf", ev_b)
    assert result.verdict == DuplicateVerdict.ADVISORY
    assert result.method == "near_duplicate"


def test_existing_exact_and_business_key_duplicate_behavior_unchanged(make_pdf):
    # Regression guard: file_hash/content_hash/business_key tiers must
    # still fire exactly as before — the new tier is additive, checked
    # only after those three tiers have already been tried and missed.
    a = make_pdf("a.pdf", b"identical bytes")
    b = make_pdf("b.pdf", b"identical bytes")
    registry = DuplicateRegistry()
    ev_a = build_evidence(a, full_text="Invoice 555")
    registry.register("a.pdf", ev_a)
    ev_b = build_evidence(b, full_text="Invoice 555")
    result = registry.check("b.pdf", ev_b)
    assert result.verdict == DuplicateVerdict.DUPLICATE_OF_BOOKED_PAYABLE
    assert result.method == "file_hash"


def test_high_confidence_promotion_is_deterministic_across_repeated_runs(make_pdf):
    a = make_pdf("INV-04.pdf", b"scan one")
    b = make_pdf("INV-07.pdf", b"scan two")

    verdicts = []
    for _ in range(3):
        registry = DuplicateRegistry()
        ev_a = build_evidence(a, full_text=_INV04_TEXT, currency="ZAR", gross_total="19730.55")
        registry.register("INV-04.pdf", ev_a)
        ev_b = build_evidence(b, full_text=_INV07_TEXT, currency="ZAR", gross_total="19730.55")
        verdicts.append(registry.check("INV-07.pdf", ev_b).verdict)

    assert verdicts == [DuplicateVerdict.DUPLICATE_OF_BOOKED_PAYABLE] * 3


def test_high_confidence_threshold_is_stricter_than_advisory_threshold():
    assert HIGH_CONFIDENCE_NEAR_DUPLICATE_SIMILARITY_THRESHOLD > 0.92
