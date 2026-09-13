"""Phase 10: final validation / adjudication gate."""
from __future__ import annotations

from pipeline.matching.master_data import MasterDataMatcher
from pipeline.validation import (
    DeclineReason,
    ValidationSeverity,
    adjudicate,
    check_classification_consistency,
    check_credit_memo_consistency,
    check_erp_reconciliation,
    check_financial_consistency,
    check_groundedness,
    check_master_data_validity,
    check_required_payable_evidence,
    check_schema,
    check_supplier_buyer_consistency,
    check_tax_consistency,
)


def matcher():
    return MasterDataMatcher()


def _base_payload(**overrides):
    payload = {
        "invoice_number": "INV-1",
        "invoice_date": "2026-01-01",
        "due_date": "2026-01-31",
        "invoice_type": "INVOICE",
        "currency": "EUR",
        "supplier": {"name": "Acme Ltd", "supplier_id": "", "address": "", "vat_id": ""},
        "buyer": {"company_code": "", "business_unit_code": "", "location_code": ""},
        "payment_term_id": "",
        "po_number": "",
        "po_id": "",
        "gross_total": "100.00",
        "subtotal": "100.00",
        "total_tax_amount": "0.00",
        "discount_amount": "",
        "freight_charges": "",
        "insurance_charges": "",
        "extra_charges": "",
        "excise_duties": "",
        "taxes": [],
        "line_items": [
            {"description": "x", "item_type": "SERVICE", "uom": "", "quantity": "1",
             "unit_price": "100.00", "total": "100.00", "discount": "", "discount_percentage": "",
             "tax_rate": "", "tax_amount": "", "taxes": []}
        ],
    }
    payload.update(overrides)
    return payload


# --- Groundedness ------------------------------------------------------------

# 1. extracted value supported by evidence -> valid
def test_groundedness_value_supported_by_text_is_valid():
    payload = _base_payload()
    issues = check_groundedness(payload, "Invoice INV-1 ... Total: 100.00")
    assert issues == []


# 2. missing optional field -> valid
def test_groundedness_missing_optional_field_is_valid():
    payload = _base_payload(invoice_number="")
    issues = check_groundedness(payload, "Total: 100.00")
    assert issues == []


# 3. required evidence absent -> decline
def test_required_evidence_absent_declines():
    issues = check_required_payable_evidence({"gross_total_raw": "100.00"})
    assert issues and issues[0].decline_reason == DeclineReason.INSUFFICIENT_EVIDENCE


def test_required_evidence_present_is_valid():
    issues = check_required_payable_evidence({"gross_total_raw": "100.00", "invoice_number": "INV-1"})
    assert issues == []


# 4. fabricated/non-evidenced critical value -> decline
def test_fabricated_gross_total_not_in_text_declines():
    payload = _base_payload(gross_total="999.99")
    issues = check_groundedness(payload, "This text never mentions that number at all.")
    assert issues and issues[0].decline_reason == DeclineReason.GROUNDEDNESS_FAILURE


# 5. ambiguous date candidates -> decline/blank per extraction contract
# (already covered by tests/unit/test_extraction.py's
# test_multiple_unlabeled_dates_are_not_guessed — re-affirmed at the
# validation layer via required-evidence: a document with no invoice_number,
# no supplier, and no currency, only an ambiguous-and-therefore-blank date,
# cannot satisfy the corroboration requirement.)
def test_only_ambiguous_blank_date_evidence_is_insufficient():
    issues = check_required_payable_evidence({"gross_total_raw": "100.00"})  # date resolved to blank upstream
    assert issues


# --- Classification consistency ----------------------------------------------

# 6-9: non-payable classes are declined upstream by classification.py itself
# (see tests/unit/test_classification.py); this module's job is the
# CONSISTENCY check for classes that reached this layer at all.

# 10. credit memo with explicit evidence -> valid classification
def test_credit_memo_with_evidence_is_consistent():
    issues = check_classification_consistency("PAYABLE_CREDIT_MEMO", ["credit note/memo vocabulary"])
    assert issues == []


# 11. contradictory classification evidence -> decline
def test_credit_memo_without_evidence_is_inconsistent():
    issues = check_classification_consistency("PAYABLE_CREDIT_MEMO", ["invoice identity pattern"])
    assert issues and issues[0].decline_reason == DeclineReason.CONFLICTING_SIGNALS


def test_invoice_with_thin_evidence_is_flagged():
    issues = check_classification_consistency("PAYABLE_INVOICE", ["invoice identity pattern"])
    assert issues and issues[0].decline_reason == DeclineReason.INSUFFICIENT_EVIDENCE


def test_invoice_with_adequate_evidence_is_consistent():
    issues = check_classification_consistency(
        "PAYABLE_INVOICE", ["invoice identity pattern", "total/subtotal pattern", "tax/VAT pattern"]
    )
    assert issues == []


# --- Master data --------------------------------------------------------------

# 12. valid supplier ID -> accepted
def test_valid_supplier_id_accepted():
    payload = _base_payload()
    payload["supplier"]["supplier_id"] = "2845695"  # real id from master_data/suppliers.json
    issues = check_master_data_validity(payload, matcher())
    assert issues == []


# 13. nonexistent supplier ID -> rejected
def test_nonexistent_supplier_id_rejected():
    payload = _base_payload()
    payload["supplier"]["supplier_id"] = "9999999"
    issues = check_master_data_validity(payload, matcher())
    assert issues and issues[0].decline_reason == DeclineReason.MASTER_DATA_INVALID


# 14. valid tax code -> accepted
def test_valid_tax_code_accepted():
    payload = _base_payload(taxes=[{"tax_type": "VAT", "tax_name": "x", "tax_rate": "19",
                                     "tax_amount": "", "tax_type_code": "DE_190_VAT"}])
    issues = check_master_data_validity(payload, matcher())
    assert issues == []


# 15. nonexistent tax code -> rejected
def test_nonexistent_tax_code_rejected():
    payload = _base_payload(taxes=[{"tax_type": "VAT", "tax_name": "x", "tax_rate": "19",
                                     "tax_amount": "", "tax_type_code": "NOT_A_REAL_CODE"}])
    issues = check_master_data_validity(payload, matcher())
    assert issues and issues[0].decline_reason == DeclineReason.MASTER_DATA_INVALID


# 16. ambiguous BU -> remains blank (tested at matcher level in
# test_master_data_matching.py); here we confirm a BLANK bu code passes
# validation cleanly (never treated as an error).
def test_blank_bu_code_is_not_a_validation_failure():
    payload = _base_payload()
    issues = check_master_data_validity(payload, matcher())
    assert issues == []


# 17. invalid PO -> rejected
def test_invalid_po_id_rejected():
    payload = _base_payload(po_id="PO-DOES-NOT-EXIST")
    issues = check_master_data_validity(payload, matcher())
    assert issues and issues[0].decline_reason == DeclineReason.MASTER_DATA_INVALID


# --- Financial -----------------------------------------------------------------

# 18. exact ERP match -> valid
def test_exact_erp_match_is_valid():
    payload = _base_payload()
    issues = check_erp_reconciliation(payload)
    assert issues == []


# 19. one-cent mismatch -> decline
def test_one_cent_mismatch_declines():
    payload = _base_payload(gross_total="100.01")
    issues = check_erp_reconciliation(payload)
    assert issues and issues[0].decline_reason == DeclineReason.ERP_MISMATCH_IRRECONCILABLE


# 20. discount consistency (covered thoroughly in test_financial_model.py;
# here confirm the validation layer's numeric-sanity check passes a
# well-formed discounted payload)
def test_discount_consistency_numeric_sanity():
    payload = _base_payload(
        line_items=[{"description": "x", "item_type": "GOODS", "uom": "", "quantity": "10",
                     "unit_price": "10.00", "total": "90.00", "discount": "", "discount_percentage": "10",
                     "tax_rate": "", "tax_amount": "", "taxes": []}],
        gross_total="90.00", subtotal="90.00",
    )
    issues = check_financial_consistency(payload)
    assert issues == []


# 21. tax consistency
def test_tax_consistency_valid_rate():
    payload = _base_payload(taxes=[{"tax_type": "VAT", "tax_name": "x", "tax_rate": "20", "tax_amount": "", "tax_type_code": ""}])
    issues = check_tax_consistency(payload)
    assert issues == []


def test_tax_consistency_implausible_rate_flagged():
    payload = _base_payload(taxes=[{"tax_type": "VAT", "tax_name": "x", "tax_rate": "500", "tax_amount": "", "tax_type_code": ""}])
    issues = check_tax_consistency(payload)
    assert issues and issues[0].decline_reason == DeclineReason.BUSINESS_RULE_VIOLATION


# 22. withholding reduces gross correctly -- covered in test_financial_model.py
# (test_negative_withholding_reduces_gross); Phase 10 doesn't duplicate that
# arithmetic check, only re-verifies the final payload still reconciles.
def test_withholding_payload_still_reconciles_at_validation_layer():
    payload = _base_payload(
        taxes=[
            {"tax_type": "VAT", "tax_name": "VAT 7%", "tax_rate": "7", "tax_amount": "", "tax_type_code": ""},
            {"tax_type": "WHT", "tax_name": "Withholding 3%", "tax_rate": "", "tax_amount": "-3.00", "tax_type_code": ""},
        ],
        gross_total="104.00",
    )
    issues = check_erp_reconciliation(payload)
    assert issues == []


# 23. explicit zero-rate tax amount preserved
def test_explicit_zero_rate_tax_amount_preserved_and_valid():
    payload = _base_payload(
        taxes=[{"tax_type": "VAT", "tax_name": "Reverse Charge", "tax_rate": "0", "tax_amount": "5.00", "tax_type_code": ""}],
        gross_total="105.00",
    )
    assert check_erp_reconciliation(payload) == []
    assert check_tax_consistency(payload) == []


# 24. multiple tax rates preserved
def test_multiple_tax_rates_each_individually_valid():
    payload = _base_payload(
        taxes=[
            {"tax_type": "VAT", "tax_name": "a", "tax_rate": "5", "tax_amount": "", "tax_type_code": ""},
            {"tax_type": "VAT", "tax_name": "b", "tax_rate": "12", "tax_amount": "", "tax_type_code": ""},
        ]
    )
    issues = check_tax_consistency(payload)
    assert issues == []


# 25. irreconcilable charge hypothesis -> decline (financial_model.py already
# returns reconciled=False for this — Phase 10's ERP re-check would also
# catch it if it somehow reached this layer anyway)
def test_irreconcilable_payload_declines_at_erp_gate():
    payload = _base_payload(gross_total="123456.78")
    issues = check_erp_reconciliation(payload)
    assert issues and issues[0].decline_reason == DeclineReason.ERP_MISMATCH_IRRECONCILABLE


# --- Credit memo ---------------------------------------------------------------

# 26. credit memo sign normalization once (tested in test_financial_model.py);
# here: a correctly-normalized (positive) credit memo passes validation.
def test_credit_memo_positive_magnitudes_pass():
    payload = _base_payload(invoice_type="CREDIT_MEMO", gross_total="400.00",
                             line_items=[{"description": "x", "item_type": "SERVICE", "uom": "",
                                          "quantity": "1", "unit_price": "400.00", "total": "400.00",
                                          "discount": "", "discount_percentage": "", "tax_rate": "",
                                          "tax_amount": "", "taxes": []}],
                             subtotal="400.00")
    issues = check_credit_memo_consistency(payload)
    assert issues == []


# 27. repeated normalization remains unchanged (idempotence — tested
# directly in test_financial_model.py's
# test_credit_memo_converts_to_positive_magnitudes_exactly_once; here we
# confirm validation doesn't itself perform any conversion — it's read-only)
def test_credit_memo_validation_does_not_mutate_payload():
    payload = _base_payload(invoice_type="CREDIT_MEMO", gross_total="400.00")
    before = dict(payload)
    check_credit_memo_consistency(payload)
    assert payload == before


# 28. credit memo ERP reconciliation
def test_credit_memo_negative_amount_flagged():
    payload = _base_payload(invoice_type="CREDIT_MEMO", gross_total="-400.00")
    issues = check_credit_memo_consistency(payload)
    assert issues and issues[0].decline_reason == DeclineReason.BUSINESS_RULE_VIOLATION


# --- Safety --------------------------------------------------------------------

# 29. missing data never produces invented values
def test_missing_data_never_invents_values_in_schema_check():
    payload = _base_payload(po_number="", po_id="", payment_term_id="")
    issues = check_schema(payload)
    assert issues == []  # blanks are valid, not schema violations


# 30. validation is deterministic
def test_validation_is_deterministic():
    payload = _base_payload()
    m = matcher()
    r1 = adjudicate(payload, {"gross_total_raw": "100.00", "invoice_number": "INV-1"},
                     "PAYABLE_INVOICE", ["invoice identity pattern", "total/subtotal pattern"], m,
                     raw_text="Invoice INV-1 Total: 100.00")
    r2 = adjudicate(payload, {"gross_total_raw": "100.00", "invoice_number": "INV-1"},
                     "PAYABLE_INVOICE", ["invoice identity pattern", "total/subtotal pattern"], m,
                     raw_text="Invoice INV-1 Total: 100.00")
    assert r1.ok == r2.ok
    assert [i.check for i in r1.issues] == [i.check for i in r2.issues]


# 31. validation does not mutate financial facts
def test_validation_does_not_mutate_payload_financials():
    payload = _base_payload()
    before = dict(payload)
    check_financial_consistency(payload)
    check_erp_reconciliation(payload)
    assert payload == before


# 32. validation does not modify master-data IDs
def test_validation_does_not_modify_master_data_ids():
    payload = _base_payload()
    payload["supplier"]["supplier_id"] = "2845695"
    before_id = payload["supplier"]["supplier_id"]
    check_master_data_validity(payload, matcher())
    assert payload["supplier"]["supplier_id"] == before_id


# --- Full adjudicate() integration -------------------------------------------

def test_adjudicate_accepts_a_well_formed_payable():
    payload = _base_payload()
    result = adjudicate(
        payload, {"gross_total_raw": "100.00", "invoice_number": "INV-1"},
        "PAYABLE_INVOICE", ["invoice identity pattern", "total/subtotal pattern", "tax/VAT pattern"],
        matcher(), raw_text="Invoice INV-1 Total: 100.00",
    )
    assert result.ok


def test_adjudicate_declines_a_payload_with_erp_mismatch():
    payload = _base_payload(gross_total="999.99")
    result = adjudicate(
        payload, {"gross_total_raw": "999.99", "invoice_number": "INV-1"},
        "PAYABLE_INVOICE", ["invoice identity pattern", "total/subtotal pattern"],
        matcher(), raw_text="Invoice INV-1 Total: 999.99",
    )
    assert not result.ok
    assert "ERP_MISMATCH" in result.decline_message()


def test_adjudicate_declines_insufficient_corroboration():
    payload = _base_payload(invoice_number="")
    result = adjudicate(
        payload, {"gross_total_raw": "100.00"},  # no invoice_number/supplier/currency/date evidence
        "PAYABLE_INVOICE", ["invoice identity pattern", "total/subtotal pattern"],
        matcher(), raw_text="Total: 100.00",
    )
    assert not result.ok
    assert "INSUFFICIENT_EVIDENCE" in result.decline_message()


# --- Regression tests for real bugs found during the Phase 10 corpus run ----

def test_groundedness_accepts_comma_decimal_printed_form():
    """Regression: a document printed with a comma-decimal total (e.g. EU
    locale '400,00') must not be flagged ungrounded just because the
    normalized payload value is dot-decimal ('400.00')."""
    payload = _base_payload(gross_total="400.00", invoice_number="")
    issues = check_groundedness(payload, "Kokku: 400,00 EUR")
    assert issues == []


def test_groundedness_accepts_eu_thousands_separator_printed_form():
    """Regression: '1.040,06' (EU thousands+decimal) must ground a
    normalized '1040.06'."""
    payload = _base_payload(gross_total="1040.06", invoice_number="")
    issues = check_groundedness(payload, "Total a pagar: 1.040,06")
    assert issues == []


def test_groundedness_accepts_us_thousands_separator_printed_form():
    payload = _base_payload(gross_total="1040.06", invoice_number="")
    issues = check_groundedness(payload, "Total Due: 1,040.06")
    assert issues == []


def test_groundedness_still_rejects_a_genuinely_fabricated_total():
    payload = _base_payload(gross_total="1040.06")
    issues = check_groundedness(payload, "This total never appears anywhere: 999.99")
    assert issues and issues[0].decline_reason == DeclineReason.GROUNDEDNESS_FAILURE
