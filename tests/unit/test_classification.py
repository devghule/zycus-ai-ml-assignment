"""Unit tests for pipeline/classification.py (Phase 4).

Uses synthetic page-text fixtures (not full PDFs) to exercise the
deterministic rule-based classifier directly, plus mocked LLM responses to
prove the (unverified against a live API) validation/retry/fallback path.
"""
from __future__ import annotations

from pipeline.classification import (
    Classification,
    DocumentClass,
    classify_segment_from_text,
    classify_via_llm_response,
)


def test_normal_invoice_classifies_as_payable_invoice():
    text = (
        "INVOICE\nInvoice No: INV-1001\nBill To: Acme Corp\n"
        "Qty  Description        Unit Price\n2    Widget              10.00\n"
        "Subtotal: $20.00\nVAT: $2.00\nTotal Due: $22.00\nDue Date: 2026-01-15"
    )
    result = classify_segment_from_text(text)
    assert result.doc_class == DocumentClass.PAYABLE_INVOICE


def test_multi_page_invoice_classifies_as_payable_invoice():
    text = (
        "INVOICE\nInvoice Nr: 55\nSupplier: Foo GmbH\n"
        "Qty  Description  Unit Price\n1  Item A  5.00\n2  Item B  10.00\n"
        "Page 2 of 2\nSubtotal: 25.00\nTotal Due: 27.00\nPayment Terms: Net 30"
    )
    result = classify_segment_from_text(text)
    assert result.doc_class == DocumentClass.PAYABLE_INVOICE


def test_explicit_credit_note_classifies_as_credit_memo():
    text = (
        "CREDIT NOTE\nCredit Note No: CN-77\nReferring to Invoice INV-1001\n"
        "Bill To: Acme Corp\nAmount: -$50.00\nTotal Due: -$50.00"
    )
    result = classify_segment_from_text(text)
    assert result.doc_class == DocumentClass.PAYABLE_CREDIT_MEMO


def test_delivery_note_classifies_as_non_payable():
    text = (
        "DELIVERY NOTE\nDelivery No: DN-2001\nShip To: Warehouse 4\n"
        "Qty  Description\n5  Boxes of widgets\nDelivered by driver: J. Smith"
    )
    result = classify_segment_from_text(text)
    assert result.doc_class == DocumentClass.NON_PAYABLE


def test_waybill_classifies_as_non_payable():
    text = "WAYBILL\nCMR Waybill No: 88123\nCarrier: Speedy Logistics\nConsignee: Acme Corp\nGoods description: pallets"
    result = classify_segment_from_text(text)
    assert result.doc_class == DocumentClass.NON_PAYABLE


def test_customs_document_classifies_as_non_payable():
    text = "CUSTOMS DECLARATION\nExport Declaration No: ED-4400\nCountry of origin: DE\nHS Code: 8471.30"
    result = classify_segment_from_text(text)
    assert result.doc_class == DocumentClass.NON_PAYABLE


def test_dunning_letter_classifies_as_non_payable():
    text = "PAYMENT REMINDER\nOverdue Notice\nDear customer, your invoice is overdue. Please pay immediately."
    result = classify_segment_from_text(text)
    assert result.doc_class == DocumentClass.NON_PAYABLE


def test_internal_approval_classifies_as_non_payable():
    text = "PURCHASE REQUISITION\nApproval Request\nInternal Memo: please approve this quotation for review."
    result = classify_segment_from_text(text)
    assert result.doc_class == DocumentClass.NON_PAYABLE


def test_quotation_classifies_as_non_payable():
    text = "QUOTATION\nEstimate No: EST-99\nThis is a non-binding quotation, not an invoice."
    result = classify_segment_from_text(text)
    assert result.doc_class == DocumentClass.NON_PAYABLE


def test_conflicting_signals_classify_as_ambiguous():
    text = (
        "INVOICE\nInvoice No: 123\nBill To: Acme Corp\nSubtotal: $10\nVAT: $1\n"
        "DELIVERY NOTE\nDelivery No: 456\nWaybill\nExport Declaration\nCustoms clearance required"
    )
    result = classify_segment_from_text(text)
    assert result.doc_class == DocumentClass.AMBIGUOUS_UNSOLVABLE


def test_empty_or_unreadable_text_classifies_as_ambiguous():
    result = classify_segment_from_text("   \n\n  ")
    assert result.doc_class == DocumentClass.AMBIGUOUS_UNSOLVABLE
    assert "insufficient" in result.reason.lower()


# --- LLM validation/retry/fallback path (mocked only, no live API) ---------

def test_llm_well_formed_response_is_accepted():
    def fake_call():
        return {
            "label": "PAYABLE_INVOICE",
            "confidence": 0.9,
            "evidence": ["invoice number present", "total due present"],
            "doc_type": "invoice",
            "reason": "clear invoice structure",
        }

    result = classify_via_llm_response(fake_call)
    assert result.doc_class == DocumentClass.PAYABLE_INVOICE
    assert result.confidence == 0.9


def test_llm_malformed_response_falls_back_to_ambiguous_after_retries():
    calls = {"count": 0}

    def fake_call():
        calls["count"] += 1
        return {"label": "NOT_A_REAL_LABEL", "confidence": 2.0}  # invalid on every count

    result = classify_via_llm_response(fake_call, max_retries=2)
    assert result.doc_class == DocumentClass.AMBIGUOUS_UNSOLVABLE
    assert calls["count"] == 3  # initial attempt + 2 retries


def test_llm_response_missing_fields_falls_back():
    result = classify_via_llm_response(lambda: {"label": "PAYABLE_INVOICE"}, max_retries=0)
    assert result.doc_class == DocumentClass.AMBIGUOUS_UNSOLVABLE


def test_llm_response_recovers_on_a_later_successful_attempt():
    calls = {"count": 0}

    def fake_call():
        calls["count"] += 1
        if calls["count"] < 2:
            return {"label": "garbage"}
        return {"label": "NON_PAYABLE", "confidence": 0.7, "evidence": ["delivery note vocabulary"]}

    result = classify_via_llm_response(fake_call, max_retries=2)
    assert result.doc_class == DocumentClass.NON_PAYABLE
