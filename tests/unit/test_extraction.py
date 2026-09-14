from pipeline.extraction import (
    check_unit_price_sanity,
    extract_from_text,
    extract_via_llm_response,
)


# --- Deterministic extraction -----------------------------------------------

def test_extracts_invoice_number():
    text = "Invoice No: INV-1234\nSome other content here."
    result = extract_from_text(text)
    assert result.fields.get("invoice_number") == "INV-1234"


def test_extracts_currency_code():
    text = "Total amount: 150.00 EUR due on receipt."
    result = extract_from_text(text)
    assert result.fields.get("currency") == "EUR"


def test_extracts_iso_date():
    text = "Invoice date: 2026-02-02, thank you."
    result = extract_from_text(text)
    assert result.fields.get("invoice_date_raw") == "2026-02-02"


def test_extracts_labeled_total():
    text = "Subtotal: 100.00\nTotal Due: EUR 120.00"
    result = extract_from_text(text)
    assert result.fields.get("gross_total_raw") == "120.00"


def test_repairs_currency_code_glued_to_digit():
    # OCR-observed pattern (DU-06): "EUR153,58" with no space.
    text = "TOTAL\nEUR153,58"
    result = extract_from_text(text)
    assert result.fields.get("currency") == "EUR"
    assert result.fields.get("gross_total_raw") == "153,58"


def test_repairs_total_label_glued_to_currency_code():
    # OCR-observed pattern (INV-04): "TOTALZAR" with no space.
    text = "Subtotal 17,157.00\nTOTALZAR 19,730.55"
    result = extract_from_text(text)
    assert result.fields.get("gross_total_raw") == "19,730.55"


def test_repairs_amount_label_glued_to_currency_code():
    # OCR-observed pattern (INV-04): "AmountZAR" with no space.
    text = "AmountZAR 19,730.55"
    result = extract_from_text(text)
    assert result.fields.get("currency") == "ZAR"


def test_total_label_recognizes_non_major_iso_currency_marker():
    # _TOTAL_LABEL_RE previously only recognized EUR/USD/GBP as the optional
    # currency marker between the label and the digits; SGD/ZAR/etc. left the
    # amount unmatched even with a space present.
    text = "Total SGD 771.66"
    result = extract_from_text(text)
    assert result.fields.get("gross_total_raw") == "771.66"


def test_ghc_symbol_recognized_as_ghs():
    text = "Total Tax Inclusive Value GHC8,045.40"
    result = extract_from_text(text)
    assert result.fields.get("currency") == "GHS"


def test_extracts_total_labeled_gesamtsumme():
    text = "Gesamtsumme\n438,00\nzzgl. 0% MwSt\n0,00"
    result = extract_from_text(text)
    assert result.fields.get("gross_total_raw") == "438,00"


def test_extracts_total_labeled_endbetrag():
    text = "Endbetrag\n438,00"
    result = extract_from_text(text)
    assert result.fields.get("gross_total_raw") == "438,00"


def test_empty_text_returns_no_fields():
    result = extract_from_text("")
    assert result.fields == {}
    assert "no text available" in result.confidence_notes[0]


def test_unrecognizable_text_returns_no_fields_honestly():
    result = extract_from_text("lorem ipsum dolor sit amet consectetur")
    assert result.fields == {}


# --- Unit-price sanity check -------------------------------------------------

def test_unit_price_sanity_matching_case():
    assert check_unit_price_sanity(quantity=4, unit_price=73.0, total=292.0)


def test_unit_price_sanity_mismatched_case():
    assert not check_unit_price_sanity(quantity=4, unit_price=73.0, total=1000.0)


def test_unit_price_sanity_zero_case():
    assert check_unit_price_sanity(quantity=0, unit_price=0, total=0)


def test_unit_price_sanity_within_rounding_tolerance():
    # 3 x 33.33 = 99.99, printed total rounded to 100.00 — should pass.
    assert check_unit_price_sanity(quantity=3, unit_price=33.33, total=100.00)


# --- LLM extraction interface (mocked only — no live API) -------------------

def test_llm_extraction_well_formed_response():
    def good_call():
        return {"fields": {"invoice_number": "123"}, "line_items": [], "confidence": 0.9}

    result = extract_via_llm_response(good_call)
    assert result is not None
    assert result.fields["invoice_number"] == "123"


def test_llm_extraction_malformed_response_returns_none_after_retries():
    def bad_call():
        return {"not_the_right_shape": True}

    result = extract_via_llm_response(bad_call, max_retries=2)
    assert result is None


def test_llm_extraction_missing_required_field():
    def bad_call():
        return {"fields": {}, "confidence": 0.5}  # missing line_items

    result = extract_via_llm_response(bad_call, max_retries=0)
    assert result is None


def test_llm_extraction_invalid_confidence_range():
    def bad_call():
        return {"fields": {}, "line_items": [], "confidence": 5.0}

    result = extract_via_llm_response(bad_call, max_retries=0)
    assert result is None


def test_llm_extraction_recovers_after_transient_bad_response():
    calls = {"count": 0}

    def flaky_call():
        calls["count"] += 1
        if calls["count"] == 1:
            return {"bad": "shape"}
        return {"fields": {"currency": "EUR"}, "line_items": [], "confidence": 0.7}

    result = extract_via_llm_response(flaky_call, max_retries=2)
    assert result is not None
    assert result.fields["currency"] == "EUR"


def test_evidence_never_required_in_fields_shape():
    # confidence_notes is internal audit only — never something a caller
    # needs to strip before building schema output, since it's a separate
    # attribute from `fields`/`line_items`.
    result = extract_from_text("Invoice No: 999")
    assert "confidence_notes" not in result.fields


# --- Phase 5 extraction upgrade: richer header-level fields -----------------

def test_extracts_po_number():
    text = "P.O. Number: PO-EE-2026-0044\nInvoice No: 555"
    result = extract_from_text(text)
    assert result.fields.get("po_number") == "PO-EE-2026-0044"


def test_extracts_labeled_invoice_date_and_due_date_separately():
    text = "Invoice Date: 02.02.2026\nDue Date: 12.02.2026"
    result = extract_from_text(text)
    assert result.fields.get("invoice_date_raw") == "02.02.2026"
    assert result.fields.get("due_date_raw") == "12.02.2026"


def test_single_unlabeled_date_is_used_as_invoice_date():
    text = "Some invoice content mentioning 2026-02-02 only once, no other dates."
    result = extract_from_text(text)
    assert result.fields.get("invoice_date_raw") == "2026-02-02"


def test_multiple_unlabeled_dates_are_not_guessed():
    text = "Reference 2026-01-01 and also 2026-03-03 appear with no labels."
    result = extract_from_text(text)
    assert "invoice_date_raw" not in result.fields


def test_extracts_supplier_name_from_label():
    text = "Supplier: Ehast Koiduni OU\nSome other line"
    result = extract_from_text(text)
    assert result.fields.get("supplier_name") == "Ehast Koiduni OU"


def test_extracts_buyer_name_from_label():
    text = "Bill To: Northwind Operations OU\nAddress line"
    result = extract_from_text(text)
    assert result.fields.get("buyer_name") == "Northwind Operations OU"


def test_seller_label_immediately_followed_by_another_label_is_rejected():
    # OCR-observed pattern (DU-02): "SELLER" is directly followed by the
    # line "SHIP TO", with the real company name two lines further down —
    # the naive regex would otherwise capture "SHIP TO" itself as the name.
    text = "SELLER\nSHIP TO\nNovatek U.S.LLC"
    result = extract_from_text(text)
    assert "supplier_name" not in result.fields


def test_buyer_label_immediately_followed_by_another_label_is_rejected():
    text = "Bill To:\nDeliver To\nSome Real Company Ltd"
    result = extract_from_text(text)
    assert "buyer_name" not in result.fields


def test_extracts_vat_id_and_derives_country():
    text = "VAT No: DE209177122\nSome invoice text"
    result = extract_from_text(text)
    assert result.fields.get("supplier_vat_id") == "DE209177122"
    assert result.fields.get("supplier_country") == "DE"


def test_extracts_payment_terms_text():
    text = "Payment Terms: Net 30\nOther content"
    result = extract_from_text(text)
    assert result.fields.get("payment_term_text") == "Net 30"


def test_extracts_header_tax_rate_and_amount():
    text = "Subtotal: 100.00\nVAT 20% 20.00\nTotal: 120.00"
    result = extract_from_text(text)
    taxes = result.fields.get("header_taxes_raw")
    assert taxes and taxes[0]["tax_type"] == "VAT"
    assert taxes[0]["tax_rate_raw"] == "20"


def test_extracts_subtotal_separately_from_total():
    text = "Subtotal: 100.00\nTotal Due: EUR 120.00"
    result = extract_from_text(text)
    assert result.fields.get("subtotal_raw") == "100.00"
    assert result.fields.get("gross_total_raw") == "120.00"


def test_invoice_number_excludes_phone_like_candidate():
    text = "Invoice Number: +1 555 123 4567 8901"
    result = extract_from_text(text)
    # A phone-like sequence must not be accepted as an invoice number.
    if "invoice_number" in result.fields:
        assert not result.fields["invoice_number"].startswith("+")


# --- Phase 11: currency extraction improvements -----------------------------

def test_extracts_additional_iso_currency_codes():
    assert extract_from_text("Total: AUD 250.00").fields.get("currency") == "AUD"


def test_extracts_unambiguous_euro_symbol_when_no_iso_code_present():
    result = extract_from_text("Total: €120.00")
    assert result.fields.get("currency") == "EUR"


def test_does_not_guess_ambiguous_dollar_symbol():
    result = extract_from_text("Total: $120.00")
    assert "currency" not in result.fields


def test_explicit_iso_code_wins_over_symbol_if_both_present():
    result = extract_from_text("Total: SGD $120.00")
    assert result.fields.get("currency") == "SGD"


# --- Phase 11: invoice-number false-positive regression tests --------------

def test_invoice_number_not_captured_from_bare_title_followed_by_date_label():
    """Regression: 'INVOICE\nDate: ...' must not capture 'Date' as the
    invoice number — a real false positive found in the Phase 11 corpus
    audit (also occurred with Estonian 'Kuupaev'/'kokku')."""
    text = "INVOICE\nDate: 2026-01-01\nTotal: 100.00"
    result = extract_from_text(text)
    assert "invoice_number" not in result.fields


def test_invoice_number_still_captured_with_proper_label():
    text = "Invoice No: INV-999\nDate: 2026-01-01"
    result = extract_from_text(text)
    assert result.fields.get("invoice_number") == "INV-999"


def test_invoice_number_estonian_label_still_works():
    text = "Arve nr. 18533\nKuupaev: 2026-01-01"
    result = extract_from_text(text)
    assert result.fields.get("invoice_number") == "18533"


def test_invoice_number_bare_title_with_no_label_anywhere_stays_blank():
    text = "ARVE\nkokku: 400.00 EUR"
    result = extract_from_text(text)
    assert "invoice_number" not in result.fields


# --- Phase 2 (improve-document-understanding): PO false-positive regressions

def test_po_not_captured_from_country_name_portugal():
    """Regression: 'PORTUGAL' must not yield 'RTUGAL' as a PO number."""
    text = "Consignee address: Lisbon, PORTUGAL\nTotal: 100.00"
    result = extract_from_text(text)
    assert "po_number" not in result.fields


def test_po_not_captured_from_po_box_address():
    """Regression: 'P.O Box 14108' (a postal address) must not yield
    'Box14108' as a PO reference."""
    text = "Supplier address: P.OBox14108, Nairobi, Kenya\nTotal: 100.00"
    result = extract_from_text(text)
    assert "po_number" not in result.fields


def test_po_not_captured_from_shipper_field_running_into_company_name():
    """Regression: 'SHPR:POIVexDISTRIBUTIONGMBH&CO.KG' must not yield
    'IVexDISTRIBUTIONGMBH' as a PO number."""
    text = "SHPR:POIVexDISTRIBUTIONGMBH&CO.KG\nTotal: 100.00"
    result = extract_from_text(text)
    assert "po_number" not in result.fields


def test_po_still_captured_with_genuine_estonian_label():
    text = "Tellimus #2287\nTotal: 100.00"
    result = extract_from_text(text)
    assert result.fields.get("po_number") == "2287"


def test_po_still_captured_with_dotted_label_and_number_suffix():
    text = "P.O. Number: PO-EE-2026-0044\nInvoice No: 555"
    result = extract_from_text(text)
    assert result.fields.get("po_number") == "PO-EE-2026-0044"


# --- Phase 2 (improve-document-understanding): VAT-ID false-positive regressions

def test_vat_id_not_captured_from_table_column_header():
    """Regression: 'Amount, GBP' (a table column header, OCR-concatenated
    to 'AmountGBP') must not become a VAT ID — real VAT IDs always contain
    at least one digit; this candidate has none."""
    text = "VAT\nAmountGBP\nSome line item here."
    result = extract_from_text(text)
    assert "supplier_vat_id" not in result.fields


def test_vat_id_still_captured_when_genuinely_present():
    text = "VAT No: DE209177122\nSome invoice text"
    result = extract_from_text(text)
    assert result.fields.get("supplier_vat_id") == "DE209177122"
    assert result.fields.get("supplier_country") == "DE"


# --- Phase 2 (improve-document-understanding): DU-11 Estonian tax-summary --

def test_estonian_net_base_and_vat_line_extracted_together():
    """DU-11 class: 'Summa km-ta' (net base) + 'KM<rate>%' (VAT line),
    exactly as OCR concatenates them in the real document."""
    text = "Kreeditarve nr 6265-K\nSummakm-ta22%\n-327,87\nKM22%\n-72,13\nArve kokku (EUR)\n-400,00"
    result = extract_from_text(text)
    assert result.fields.get("subtotal_raw") == "-327,87"
    taxes = result.fields.get("header_taxes_raw")
    assert taxes and taxes[0]["tax_type"] == "VAT"
    assert taxes[0]["tax_rate_raw"] == "22"
    assert taxes[0]["tax_amount_raw"] == "-72,13"


def test_estonian_net_base_alone_does_not_fire_without_vat_line():
    """Fail-safe: the net-base anchor alone (no matching VAT line) must not
    produce a partial/guessed structure."""
    text = "Summakm-ta\n-327,87\nArve kokku (EUR)\n-400,00"
    result = extract_from_text(text)
    assert "subtotal_raw" not in result.fields
    assert "header_taxes_raw" not in result.fields


def test_bare_km_without_net_base_anchor_does_not_misfire_as_kilometers():
    """A document mentioning distance in km (with an incidental percent
    sign nearby, e.g. '50% of the 22km route') must not trigger the
    Estonian VAT fallback, since the net-base anchor phrase is absent."""
    text = "Distance: 22km\nFuel usage: 50%\nTotal: 100.00"
    result = extract_from_text(text)
    assert "header_taxes_raw" not in result.fields
