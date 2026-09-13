"""Phase 7: canonical financial model + exact erp.py reconciliation.

All fixtures here are hand-built payable-construction scenarios (not real
PDFs) — this tests the financial-model <-> erp.py contract directly.
"""
from __future__ import annotations

from erp import erp_book
from pipeline.financial_model import (
    AmbiguousCharge,
    FinancialFacts,
    LineItemFact,
    build_canonical_payable,
    normalize_credit_memo_signs,
)


def test_single_line_no_tax_reconciles():
    facts = FinancialFacts(
        line_items=[LineItemFact(quantity="2", unit_price="50.00", total="100.00")],
        stated_gross="100.00",
    )
    result = build_canonical_payable(facts)
    assert result.reconciled
    assert result.hypothesis_used == "baseline"


def test_multiple_lines_reconcile():
    facts = FinancialFacts(
        line_items=[
            LineItemFact(quantity="4", unit_price="73.00", total="292.00"),
            LineItemFact(quantity="2", unit_price="73.00", total="146.00"),
        ],
        stated_gross="438.00",
    )
    result = build_canonical_payable(facts)
    assert result.reconciled
    assert result.payload["gross_total"] == "438.00"


def test_percentage_discount_reconciles():
    # 10 x 10.00 = 100.00, less 10% discount = 90.00
    facts = FinancialFacts(
        line_items=[
            LineItemFact(quantity="10", unit_price="10.00", discount_percentage="10", total="90.00")
        ],
        stated_gross="90.00",
    )
    result = build_canonical_payable(facts)
    assert result.reconciled


def test_absolute_discount_reconciles():
    # erp.py's _line_base: item_price = price - (disc_amt / qty); then * qty
    # 10 x 10.00, absolute discount 20.00 total -> (10 - 2) * 10 = 80.00
    facts = FinancialFacts(
        line_items=[LineItemFact(quantity="10", unit_price="10.00", discount="20.00")],
        stated_gross="80.00",
    )
    result = build_canonical_payable(facts)
    assert result.reconciled


def test_single_header_tax_reconciles():
    facts = FinancialFacts(
        line_items=[LineItemFact(quantity="1", unit_price="100.00")],
        header_taxes=[{"tax_type": "VAT", "tax_name": "VAT 20%", "tax_rate": "20"}],
        stated_gross="120.00",
    )
    result = build_canonical_payable(facts)
    assert result.reconciled


def test_single_line_tax_reconciles():
    facts = FinancialFacts(
        line_items=[
            LineItemFact(quantity="1", unit_price="100.00", tax_rate="15", tax_amount="")
        ],
        stated_gross="115.00",
    )
    result = build_canonical_payable(facts)
    assert result.reconciled


def test_multiple_line_taxes_stay_distinct_not_blended():
    facts = FinancialFacts(
        line_items=[
            LineItemFact(quantity="1", unit_price="100.00", tax_rate="5"),
            LineItemFact(quantity="1", unit_price="100.00", tax_rate="12"),
        ],
        stated_gross="217.00",  # 100+5 + 100+12
    )
    result = build_canonical_payable(facts)
    assert result.reconciled
    rates = [li["tax_rate"] for li in result.payload["line_items"]]
    assert rates == ["5", "12"]  # never blended into one rate


def test_freight_charge_added_to_gross():
    facts = FinancialFacts(
        line_items=[LineItemFact(quantity="1", unit_price="100.00")],
        freight_charges="10.00",
        stated_gross="110.00",
    )
    result = build_canonical_payable(facts)
    assert result.reconciled


def test_insurance_charge_added_to_gross():
    facts = FinancialFacts(
        line_items=[LineItemFact(quantity="1", unit_price="100.00")],
        insurance_charges="5.00",
        stated_gross="105.00",
    )
    result = build_canonical_payable(facts)
    assert result.reconciled


def test_extra_charges_added_to_gross():
    facts = FinancialFacts(
        line_items=[LineItemFact(quantity="1", unit_price="100.00")],
        extra_charges="7.50",
        stated_gross="107.50",
    )
    result = build_canonical_payable(facts)
    assert result.reconciled


def test_excise_duties_added_to_gross():
    facts = FinancialFacts(
        line_items=[LineItemFact(quantity="1", unit_price="100.00")],
        excise_duties="3.00",
        stated_gross="103.00",
    )
    result = build_canonical_payable(facts)
    assert result.reconciled


def test_explicit_tax_amount_preserved_even_at_nominal_zero_rate():
    # A "reverse charge 0%" tax with an explicit amount printed anyway must
    # keep that explicit amount, not be discarded because the rate is 0.
    facts = FinancialFacts(
        line_items=[LineItemFact(quantity="1", unit_price="100.00")],
        header_taxes=[
            {"tax_type": "VAT", "tax_name": "Reverse Charge", "tax_rate": "0", "tax_amount": "5.00"}
        ],
        stated_gross="105.00",
    )
    result = build_canonical_payable(facts)
    assert result.reconciled
    assert result.payload["taxes"][0]["tax_amount"] == "5.00"
    assert result.payload["taxes"][0]["tax_rate"] == "0"  # not reverse-engineered into some other rate


def test_negative_withholding_reduces_gross():
    with_withholding = FinancialFacts(
        line_items=[LineItemFact(quantity="1", unit_price="100.00")],
        header_taxes=[
            {"tax_type": "VAT", "tax_name": "VAT 7%", "tax_rate": "7"},
            {"tax_type": "WHT", "tax_name": "Withholding 3%", "tax_rate": "", "tax_amount": "-3.00"},
        ],
        stated_gross="104.00",  # 100 + 7 - 3
    )
    result = build_canonical_payable(with_withholding)
    assert result.reconciled

    without_withholding = FinancialFacts(
        line_items=[LineItemFact(quantity="1", unit_price="100.00")],
        header_taxes=[{"tax_type": "VAT", "tax_name": "VAT 7%", "tax_rate": "7"}],
        stated_gross="107.00",
    )
    result2 = build_canonical_payable(without_withholding)
    assert result2.reconciled

    booked_with = erp_book(result.payload)["will_book_gross"]
    booked_without = erp_book(result2.payload)["will_book_gross"]
    assert booked_with < booked_without


def test_fee_inside_tax_base_class_reconciles_via_taxed_together_hypothesis():
    """Generalized 'management fee inside the tax base' class: base -> +fee
    -> taxable base -> VAT -> final. No document-specific logic — this is a
    hand-built scenario, not HLD-01 itself."""
    facts = FinancialFacts(
        line_items=[LineItemFact(quantity="1", unit_price="1000.00")],
        header_taxes=[{"tax_type": "VAT", "tax_name": "VAT 7%", "tax_rate": "7"}],
        ambiguous_charges=[AmbiguousCharge(amount="90.00", description="management fee")],
        # (1000 + 90) * 1.07 = 1166.30 -> only reconciles if the fee is
        # folded into the taxable base before VAT is applied.
        stated_gross="1166.30",
    )
    result = build_canonical_payable(facts)
    assert result.reconciled
    assert result.hypothesis_used == "charge_taxed_together"
    assert len(result.payload["line_items"]) == 2  # fee became its own line item


def test_fee_post_tax_class_reconciles_via_post_tax_hypothesis():
    """The opposite structural hypothesis: the fee is added AFTER tax, not
    part of the taxable base."""
    facts = FinancialFacts(
        line_items=[LineItemFact(quantity="1", unit_price="1000.00")],
        header_taxes=[{"tax_type": "VAT", "tax_name": "VAT 7%", "tax_rate": "7"}],
        ambiguous_charges=[AmbiguousCharge(amount="90.00", description="handling fee")],
        # 1000 * 1.07 + 90 = 1160.00 -> only reconciles if the fee is NOT taxed.
        stated_gross="1160.00",
    )
    result = build_canonical_payable(facts)
    assert result.reconciled
    assert result.hypothesis_used == "charge_post_tax"
    assert len(result.payload["line_items"]) == 1  # fee did NOT become a line item


def test_credit_memo_converts_to_positive_magnitudes_exactly_once():
    facts = FinancialFacts(
        invoice_type="CREDIT_MEMO",
        line_items=[LineItemFact(quantity="1", unit_price="-400.00", total="-400.00")],
        stated_gross="-400.00",
    )
    normalized = normalize_credit_memo_signs(facts)
    assert normalized.line_items[0].unit_price == "400.00"
    assert normalized.stated_gross == "400.00"

    # Running it through normalize_credit_memo_signs a second time must NOT
    # flip the sign again (it's already positive).
    twice = normalize_credit_memo_signs(normalized)
    assert twice.line_items[0].unit_price == "400.00"

    result = build_canonical_payable(facts)
    assert result.reconciled
    assert result.payload["invoice_type"] == "CREDIT_MEMO"
    assert result.payload["gross_total"] == "400.00"
    assert float(result.payload["line_items"][0]["unit_price"]) > 0


def test_irreconcilable_case_returns_no_payload():
    facts = FinancialFacts(
        line_items=[LineItemFact(quantity="1", unit_price="100.00")],
        stated_gross="999.99",  # nothing about this structure produces 999.99
    )
    result = build_canonical_payable(facts)
    assert not result.reconciled
    assert result.payload is None
    assert result.reason  # must explain why, not just silently fail


def test_irreconcilable_with_ambiguous_charge_tries_both_hypotheses_and_fails_honestly():
    facts = FinancialFacts(
        line_items=[LineItemFact(quantity="1", unit_price="100.00")],
        header_taxes=[{"tax_type": "VAT", "tax_name": "VAT 10%", "tax_rate": "10"}],
        ambiguous_charges=[AmbiguousCharge(amount="20.00")],
        stated_gross="500.00",  # matches neither (100+20)*1.1=132 nor 100*1.1+20=130
    )
    result = build_canonical_payable(facts)
    assert not result.reconciled
    assert result.payload is None
