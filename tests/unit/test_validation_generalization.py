"""Phase 10 STEP 10.19: generalization tests over synthetic held-out
fixtures representing the hard-case PATTERNS identified in
STEP1_STEP2_ANALYSIS.md (management-fee tax-base structure, ambiguous
identity, multi-rate tax, "Copy" documents, conflicting totals, explicit
zero-rate tax, withholding, credit memos, duplicates, missing master data,
ambiguous BU). None of these fixtures are any specific real document or
filename — each is a hand-built scenario sharing the STRUCTURAL pattern
only, to prove the pipeline generalizes rather than being fitted to the
visible 42 documents.
"""
from __future__ import annotations

from pathlib import Path

from pipeline.duplicate_detection import DuplicateRegistry, DuplicateVerdict, build_evidence
from pipeline.financial_model import AmbiguousCharge, FinancialFacts, LineItemFact, build_canonical_payable
from pipeline.matching.master_data import MasterDataMatcher
from pipeline.validation import adjudicate


def matcher():
    return MasterDataMatcher()


def test_management_fee_tax_base_pattern_books_correctly():
    """Generalized 'HLD-01 class': base + fee -> taxable base -> VAT ->
    final. Resolved by financial_model's trial-recompute, then confirmed
    valid at the Phase 10 gate."""
    facts = FinancialFacts(
        currency="EUR",
        line_items=[LineItemFact(quantity="1", unit_price="1000.00")],
        header_taxes=[{"tax_type": "VAT", "tax_name": "VAT 7%", "tax_rate": "7"}],
        ambiguous_charges=[AmbiguousCharge(amount="90.00", description="management fee")],
        stated_gross="1166.30",
    )
    canonical = build_canonical_payable(facts)
    assert canonical.reconciled

    payload = _to_full_payload(canonical.payload)
    result = adjudicate(
        payload, {"gross_total_raw": "1166.30", "invoice_number": "REF-1"},
        "PAYABLE_INVOICE", ["invoice identity pattern", "total/subtotal pattern", "tax/VAT pattern"],
        matcher(), raw_text="REF-1 ... 1166.30",
    )
    assert result.ok


def test_ambiguous_supplier_buyer_identity_pattern_stays_blank_not_guessed():
    """Generalized 'HLD-03 class': identity is genuinely illegible/absent.
    Supplier stays blank rather than guessed; the payable can still book on
    its financial merits (identity is not required for ERP reconciliation),
    but no supplier_id is ever fabricated."""
    payload = _to_full_payload({
        "invoice_type": "INVOICE", "currency": "EUR",
        "line_items": [{"description": "x", "item_type": "SERVICE", "uom": "", "quantity": "1",
                         "unit_price": "67.25", "total": "67.25", "discount": "", "discount_percentage": "",
                         "tax_rate": "", "tax_amount": "", "taxes": []}],
        "taxes": [], "discount_amount": "", "freight_charges": "", "insurance_charges": "",
        "extra_charges": "", "excise_duties": "", "gross_total": "67.25",
    })
    # No supplier name/VAT was ever extractable -> supplier_id stays "".
    assert payload["supplier"]["supplier_id"] == ""
    result = adjudicate(
        payload, {"gross_total_raw": "67.25", "invoice_number": "REF-2"},
        "PAYABLE_INVOICE", ["invoice identity pattern", "total/subtotal pattern"],
        matcher(), raw_text="REF-2 ... 67.25",
    )
    assert result.ok  # blank supplier_id is honest, not a validation failure
    assert payload["supplier"]["supplier_id"] == ""  # never fabricated by validation either


def test_multi_rate_tax_pattern_all_rates_preserved_and_valid():
    """Generalized 'HLD-05 class': several distinct tax rates on one
    document, never blended."""
    facts = FinancialFacts(
        currency="EUR",
        line_items=[
            LineItemFact(quantity="1", unit_price="100.00", tax_rate="6"),
            LineItemFact(quantity="1", unit_price="100.00", tax_rate="23"),
        ],
        stated_gross="229.00",
    )
    canonical = build_canonical_payable(facts)
    assert canonical.reconciled
    payload = _to_full_payload(canonical.payload)
    result = adjudicate(
        payload, {"gross_total_raw": "229.00", "invoice_number": "REF-3"},
        "PAYABLE_INVOICE", ["invoice identity pattern", "total/subtotal pattern", "tax/VAT pattern"],
        matcher(), raw_text="REF-3 ... 229.00",
    )
    assert result.ok
    rates = {li["tax_rate"] for li in payload["line_items"]}
    assert rates == {"6", "23"}


def test_copy_tax_invoice_pattern_not_auto_declined_alone():
    """Generalized 'HLD-08 class': a 'Copy Tax Invoice' label alone must
    not trigger an automatic duplicate decline — it may still be a
    legitimate, distinct payable."""
    registry = DuplicateRegistry()
    evidence = build_evidence(
        Path(__file__),  # any real file path works for hashing purposes here
        full_text="COPY TAX INVOICE\nInvoice No: REF-4\nTotal: 500.00",
    )
    result = registry.check("copy_doc.pdf", evidence)
    assert result.verdict != DuplicateVerdict.DUPLICATE_OF_BOOKED_PAYABLE


def test_customs_estimate_conflicting_totals_pattern_declines_as_irreconcilable():
    """Generalized 'INV-23 class': two conflicting totals mean no single
    evidence-supported structure reconciles -> irreconcilable, correctly
    declined rather than forced."""
    facts = FinancialFacts(
        line_items=[LineItemFact(quantity="1", unit_price="13646.04")],
        header_taxes=[{"tax_type": "VAT", "tax_name": "VAT 15%", "tax_rate": "15"}],
        stated_gross="13289.19",  # a DIFFERENT total than what this structure would produce
    )
    canonical = build_canonical_payable(facts)
    assert not canonical.reconciled
    assert canonical.payload is None


def test_explicit_zero_rate_tax_with_amount_pattern_preserved():
    facts = FinancialFacts(
        currency="EUR",
        line_items=[LineItemFact(quantity="1", unit_price="100.00")],
        header_taxes=[{"tax_type": "VAT", "tax_name": "Reverse Charge", "tax_rate": "0", "tax_amount": "5.00"}],
        stated_gross="105.00",
    )
    canonical = build_canonical_payable(facts)
    assert canonical.reconciled
    payload = _to_full_payload(canonical.payload)
    result = adjudicate(
        payload, {"gross_total_raw": "105.00", "invoice_number": "REF-5"},
        "PAYABLE_INVOICE", ["invoice identity pattern", "total/subtotal pattern", "tax/VAT pattern"],
        matcher(), raw_text="REF-5 ... 105.00",
    )
    assert result.ok
    assert payload["taxes"][0]["tax_amount"] == "5.00"
    assert payload["taxes"][0]["tax_rate"] == "0"


def test_withholding_pattern_reduces_gross_and_validates():
    facts = FinancialFacts(
        currency="EUR",
        line_items=[LineItemFact(quantity="1", unit_price="100.00")],
        header_taxes=[
            {"tax_type": "VAT", "tax_name": "VAT 7%", "tax_rate": "7"},
            {"tax_type": "WHT", "tax_name": "Withholding 3%", "tax_rate": "", "tax_amount": "-3.00"},
        ],
        stated_gross="104.00",
    )
    canonical = build_canonical_payable(facts)
    assert canonical.reconciled
    payload = _to_full_payload(canonical.payload)
    result = adjudicate(
        payload, {"gross_total_raw": "104.00", "invoice_number": "REF-6"},
        "PAYABLE_INVOICE", ["invoice identity pattern", "total/subtotal pattern", "tax/VAT pattern"],
        matcher(), raw_text="REF-6 ... 104.00",
    )
    assert result.ok


def test_credit_memo_pattern_books_with_positive_magnitudes():
    facts = FinancialFacts(
        invoice_type="CREDIT_MEMO",
        currency="EUR",
        line_items=[LineItemFact(quantity="1", unit_price="-400.00", total="-400.00")],
        stated_gross="-400.00",
    )
    canonical = build_canonical_payable(facts)
    assert canonical.reconciled
    payload = _to_full_payload(canonical.payload)
    result = adjudicate(
        payload, {"gross_total_raw": "400.00", "invoice_number": "REF-7"},
        "PAYABLE_CREDIT_MEMO", ["credit note/memo vocabulary"],
        matcher(), raw_text="REF-7 credit note ... 400.00",
    )
    assert result.ok
    assert float(payload["gross_total"]) > 0


def test_duplicate_document_pattern_declined_on_second_occurrence():
    registry = DuplicateRegistry()
    ev1 = build_evidence(Path(__file__), supplier_identity="Acme", invoice_number="REF-8",
                          invoice_date="2026-01-01", currency="EUR", gross_total="50.00")
    assert registry.check("doc_a.pdf", ev1).verdict == DuplicateVerdict.NONE
    registry.register("doc_a.pdf", ev1)

    ev2 = build_evidence(Path(__file__), supplier_identity="Acme", invoice_number="REF-8",
                          invoice_date="2026-01-01", currency="EUR", gross_total="50.00")
    result2 = registry.check("doc_b.pdf", ev2)
    assert result2.verdict == DuplicateVerdict.DUPLICATE_OF_BOOKED_PAYABLE


def test_missing_supplier_id_pattern_is_honest_blank_not_a_failure():
    payload = _to_full_payload({
        "invoice_type": "INVOICE", "currency": "EUR",
        "line_items": [{"description": "x", "item_type": "SERVICE", "uom": "", "quantity": "1",
                         "unit_price": "10.00", "total": "10.00", "discount": "", "discount_percentage": "",
                         "tax_rate": "", "tax_amount": "", "taxes": []}],
        "taxes": [], "discount_amount": "", "freight_charges": "", "insurance_charges": "",
        "extra_charges": "", "excise_duties": "", "gross_total": "10.00",
    })
    result = adjudicate(
        payload, {"gross_total_raw": "10.00", "invoice_number": "REF-9"},
        "PAYABLE_INVOICE", ["invoice identity pattern", "total/subtotal pattern"],
        matcher(), raw_text="REF-9 ... 10.00",
    )
    assert result.ok


def test_ambiguous_buyer_bu_pattern_stays_blank():
    m = matcher()
    # Estonia genuinely has 2 BUs in the real master data -> must stay blank.
    codes, match_result = m.match_buyer(buyer_country="EE")
    assert codes.business_unit_code == ""
    payload = _to_full_payload({
        "invoice_type": "INVOICE", "currency": "EUR",
        "line_items": [{"description": "x", "item_type": "SERVICE", "uom": "", "quantity": "1",
                         "unit_price": "10.00", "total": "10.00", "discount": "", "discount_percentage": "",
                         "tax_rate": "", "tax_amount": "", "taxes": []}],
        "taxes": [], "discount_amount": "", "freight_charges": "", "insurance_charges": "",
        "extra_charges": "", "excise_duties": "", "gross_total": "10.00",
    })
    result = adjudicate(
        payload, {"gross_total_raw": "10.00", "invoice_number": "REF-10"},
        "PAYABLE_INVOICE", ["invoice identity pattern", "total/subtotal pattern"],
        m, raw_text="REF-10 ... 10.00",
    )
    assert result.ok  # blank BU is honest, not a failure


def _to_full_payload(canonical_payload: dict) -> dict:
    """Fill in the remaining AUTODRAFT_SCHEMA.md fields a canonical
    financial-model payload doesn't itself carry, mirroring what run.py
    does before calling adjudicate() — kept local to this test file so it
    doesn't depend on run.py internals."""
    payload = dict(canonical_payload)
    payload.setdefault("invoice_number", "REF")
    payload.setdefault("invoice_date", "2026-01-01")
    payload.setdefault("due_date", "")
    payload.setdefault("supplier", {"name": "", "supplier_id": "", "address": "", "vat_id": ""})
    payload.setdefault("buyer", {"company_code": "", "business_unit_code": "", "location_code": ""})
    payload.setdefault("payment_term_id", "")
    payload.setdefault("po_number", "")
    payload.setdefault("po_id", "")
    payload.setdefault("subtotal", "")
    payload.setdefault("total_tax_amount", "")
    return payload
