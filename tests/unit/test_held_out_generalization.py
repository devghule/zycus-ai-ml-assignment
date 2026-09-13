"""Phase 11 Part L: held-out generalization test set.

A small, self-contained set of synthetic cases NOT used by the core
implementation tests, covering the pattern checklist from the Phase 11
brief. Each case is a hand-built scenario, never a real document/filename —
the goal is confirming the architecture generalizes, not re-testing what
individual phase test files already cover in depth (this file references
those, rather than duplicating them, where a pattern is already covered).
"""
from __future__ import annotations

from pathlib import Path

import pymupdf

from pipeline.duplicate_detection import DuplicateRegistry, DuplicateVerdict, build_evidence
from pipeline.financial_model import AmbiguousCharge, FinancialFacts, LineItemFact, build_canonical_payable
from pipeline.locale_normalize import LocaleNormalizationError, normalize_date, normalize_number
from pipeline.matching.master_data import MasterDataMatcher
from pipeline.validation import DeclineReason, check_financial_consistency


def matcher():
    return MasterDataMatcher()


# 1. simple invoice
def test_simple_invoice_reconciles():
    facts = FinancialFacts(currency="EUR", line_items=[LineItemFact(quantity="1", unit_price="50.00")],
                            stated_gross="50.00")
    assert build_canonical_payable(facts).reconciled


# 2. credit memo (already deeply covered in test_financial_model.py;
# reconfirmed here as a held-out pattern)
def test_credit_memo_pattern():
    facts = FinancialFacts(invoice_type="CREDIT_MEMO", currency="EUR",
                            line_items=[LineItemFact(quantity="1", unit_price="-50.00", total="-50.00")],
                            stated_gross="-50.00")
    result = build_canonical_payable(facts)
    assert result.reconciled
    assert float(result.payload["gross_total"]) > 0


# 3. multi-tax invoice
def test_multi_tax_invoice_pattern():
    facts = FinancialFacts(
        currency="EUR",
        line_items=[LineItemFact(quantity="1", unit_price="100.00", tax_rate="5"),
                    LineItemFact(quantity="1", unit_price="100.00", tax_rate="20")],
        stated_gross="225.00",
    )
    assert build_canonical_payable(facts).reconciled


# 4. withholding
def test_withholding_pattern():
    facts = FinancialFacts(
        currency="EUR", line_items=[LineItemFact(quantity="1", unit_price="100.00")],
        header_taxes=[{"tax_type": "WHT", "tax_name": "WHT", "tax_rate": "", "tax_amount": "-5.00"}],
        stated_gross="95.00",
    )
    assert build_canonical_payable(facts).reconciled


# 5. header discount (a genuine gap — no prior test exercised discount_amount)
def test_header_discount_pattern():
    facts = FinancialFacts(
        currency="EUR", line_items=[LineItemFact(quantity="1", unit_price="100.00")],
        discount_amount="10.00", stated_gross="90.00",
    )
    result = build_canonical_payable(facts)
    assert result.reconciled
    assert result.payload["discount_amount"] == "10.00"


# 6. post-tax charge
def test_post_tax_charge_pattern():
    facts = FinancialFacts(
        currency="EUR", line_items=[LineItemFact(quantity="1", unit_price="100.00")],
        header_taxes=[{"tax_type": "VAT", "tax_name": "VAT", "tax_rate": "10"}],
        ambiguous_charges=[AmbiguousCharge(amount="20.00")],
        stated_gross="130.00",  # 100*1.10 + 20, only if the charge is NOT taxed
    )
    result = build_canonical_payable(facts)
    assert result.reconciled
    assert result.hypothesis_used == "charge_post_tax"


# 7. ambiguous charge (neither hypothesis reconciles -> irreconcilable)
def test_ambiguous_charge_neither_hypothesis_reconciles():
    facts = FinancialFacts(
        currency="EUR", line_items=[LineItemFact(quantity="1", unit_price="100.00")],
        header_taxes=[{"tax_type": "VAT", "tax_name": "VAT", "tax_rate": "10"}],
        ambiguous_charges=[AmbiguousCharge(amount="20.00")],
        stated_gross="500.00",  # matches neither hypothesis
    )
    result = build_canonical_payable(facts)
    assert not result.reconciled


# 8. customs estimate (non-payable document identity pattern — covered at
# classification.py level; here confirm the identity type doesn't leak into
# a false payable via financial-consistency alone, i.e. financial validity
# is necessary but not sufficient — classification gates first upstream)
def test_customs_estimate_identity_is_a_classification_concern_not_financial():
    # A document that LOOKS financially valid must still have been
    # classified as payable upstream — this test documents that
    # check_financial_consistency alone says nothing about document type,
    # which is intentional (single-responsibility checks).
    payload = {"gross_total": "100.00", "subtotal": "", "total_tax_amount": "", "discount_amount": "",
               "freight_charges": "", "insurance_charges": "", "extra_charges": "", "excise_duties": "",
               "currency": "EUR"}
    assert check_financial_consistency(payload) == []  # financially fine
    # (whether this SHOULD be a payable at all is decided by classification,
    # not by this check — see test_classification.py's customs-document case)


# 9. delivery note -- non-payable classification, covered exhaustively in
# tests/unit/test_classification.py::test_delivery_note_classifies_as_non_payable


# 10. duplicate invoice
def test_duplicate_invoice_pattern():
    registry = DuplicateRegistry()
    ev1 = build_evidence(Path(__file__), supplier_identity="Acme", invoice_number="D-1",
                          invoice_date="2026-01-01", currency="EUR", gross_total="10.00")
    registry.register("a.pdf", ev1)
    ev2 = build_evidence(Path(__file__), supplier_identity="Acme", invoice_number="D-1",
                          invoice_date="2026-01-01", currency="EUR", gross_total="10.00")
    assert registry.check("b.pdf", ev2).verdict == DuplicateVerdict.DUPLICATE_OF_BOOKED_PAYABLE


# 11. copy invoice -- covered in test_duplicate_detection.py and
# test_validation_generalization.py's copy_tax_invoice test; not duplicated here.


# 12. ambiguous supplier -- covered in test_validation_generalization.py's
# ambiguous_supplier_buyer_identity test; not duplicated here.


# 13. multiple BUs in one country
def test_multiple_bus_in_one_country_pattern():
    m = matcher()
    codes, result = m.match_buyer(buyer_country="EE")  # real master data: 2 BUs for EE
    assert codes.business_unit_code == ""


# 14. ambiguous tax codes
def test_ambiguous_tax_codes_pattern():
    m = matcher()
    result = m.match_tax(country="GH", rate=2.5)  # real master data: TAX028 and TAX029 both 2.5%
    assert result.id_or_blank == ""


# 15. missing currency
def test_missing_currency_pattern_fails_financial_consistency():
    payload = {"gross_total": "100.00", "subtotal": "", "total_tax_amount": "", "discount_amount": "",
               "freight_charges": "", "insurance_charges": "", "extra_charges": "", "excise_duties": "",
               "currency": ""}
    issues = check_financial_consistency(payload)
    assert issues and issues[0].decline_reason == DeclineReason.INSUFFICIENT_EVIDENCE


# 16. malformed number
def test_malformed_number_pattern_fails_safely():
    import pytest

    with pytest.raises(LocaleNormalizationError):
        normalize_number("not-a-number-at-all")


# 17. unsupported date/calendar
def test_unsupported_calendar_pattern_fails_safely():
    import pytest

    with pytest.raises(LocaleNormalizationError):
        normalize_date("the fourth Tuesday of next month")


# 18. bundled multi-document PDF (full end-to-end coverage lives in
# tests/integration/test_bundled_document_end_to_end.py; here a lighter
# unit-level check that segmentation's page-coverage invariant generalizes
# to an arbitrary N-page synthetic bundle)
def test_bundled_pdf_page_coverage_generalizes(tmp_path: Path):
    from pipeline.ocr_render import render_document
    from pipeline.segmentation import segment_document

    doc = pymupdf.open()
    for i in range(4):
        page = doc.new_page()
        page.insert_text((72, 72), f"INVOICE\nInvoice No: GEN-{i}\nTotal: {i}00.00")
    pdf_path = tmp_path / "generalization_bundle.pdf"
    doc.save(pdf_path)
    doc.close()

    rendered = render_document(pdf_path)
    segments = segment_document(rendered)
    all_pages = {p.page_number for p in rendered.pages}
    covered_pages = set()
    for seg in segments:
        covered_pages.update(seg.page_numbers)
    assert covered_pages == all_pages  # no page silently lost, for ANY N
