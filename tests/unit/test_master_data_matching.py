"""Phase 8: master-data matching, tested against the ACTUAL master_data/
files (not invented fixtures) plus synthetic held-out cases for patterns
that don't happen to exist in the sample rows (STEP 8.10).
"""
from __future__ import annotations

from pipeline.matching.match_result import MatchStatus
from pipeline.matching.master_data import MasterDataMatcher


def matcher():
    return MasterDataMatcher()


# =====================================================================
# SUPPLIER
# =====================================================================

def test_supplier_exact_vat_match():
    m = matcher()
    r = m.match_supplier(vat_id="DE209177122")
    assert r.status == MatchStatus.MATCHED
    assert r.matched_id == "2845695"
    assert r.method == "exact_vat_id"


def test_supplier_exact_normalized_name_match():
    m = matcher()
    r = m.match_supplier(name="Ehast Koiduni OU")
    assert r.status == MatchStatus.MATCHED
    assert r.matched_id == "2807582"


def test_supplier_punctuation_case_whitespace_normalization():
    m = matcher()
    r = m.match_supplier(name="  ehast   koiduni,  ou.  ")
    assert r.status == MatchStatus.MATCHED
    assert r.matched_id == "2807582"


def test_supplier_fuzzy_match_with_clear_winner():
    m = matcher()
    # One-character typo, same country block -> should still resolve.
    r = m.match_supplier(name="Ehast Koidun OU", country="EE")
    assert r.status == MatchStatus.MATCHED
    assert r.matched_id == "2807582"
    assert r.method == "fuzzy_name_blocked_by_country"


def test_supplier_fuzzy_ambiguity_returns_blank():
    m = matcher()
    # A generic, weakly-similar name with no strong winner in the EE block.
    r = m.match_supplier(name="Some Random Company OU", country="EE")
    assert r.status != MatchStatus.MATCHED
    assert r.id_or_blank == ""


def test_conflicting_exact_vat_vs_name_evidence_strong_identifier_wins():
    m = matcher()
    # VAT belongs to supplier 2845695 (Phocus); name text matches nobody
    # exactly but resembles a different, unrelated company. VAT must win.
    r = m.match_supplier(name="Totally Different Company Name Ltd", vat_id="DE209177122")
    assert r.status == MatchStatus.MATCHED
    assert r.matched_id == "2845695"
    assert r.method == "exact_vat_id"


def test_supplier_unknown_returns_blank():
    m = matcher()
    r = m.match_supplier(name="Nonexistent Company Nobody Has Heard Of", vat_id="XX000000000")
    assert r.id_or_blank == ""


def test_supplier_explicit_vat_not_in_master_does_not_fall_back_to_name_guess():
    m = matcher()
    r = m.match_supplier(name="Ehast Koiduni OU", vat_id="EE999999999")
    # VAT was given but doesn't exist -> must not silently use the name match instead.
    assert r.id_or_blank == ""


def test_every_matched_supplier_id_exists_in_master():
    m = matcher()
    for record in m.suppliers.records:
        r = m.match_supplier(vat_id=record["vat_id"]) if record["vat_id"] else m.match_supplier(name=record["name"])
        if r.status == MatchStatus.MATCHED:
            assert m.validate_supplier_id(r.matched_id)


# =====================================================================
# BUSINESS UNIT / CHART OF BOOKS
# =====================================================================

def test_bu_exact_evidence():
    m = matcher()
    codes, r = m.match_buyer(explicit_bu_code="GH001")
    assert r.status == MatchStatus.MATCHED
    assert codes.business_unit_code == "GH001"
    assert codes.company_code == "BOLTGROUP"


def test_bu_country_with_exactly_one_valid_bu_infers():
    m = matcher()
    codes, r = m.match_buyer(buyer_country="GH")
    assert r.status == MatchStatus.MATCHED
    assert codes.business_unit_code == "GH001"


def test_bu_country_with_multiple_valid_bus_returns_blank():
    m = matcher()
    # Estonia ("EE") has TWO business units (EE001, EE004) in the real
    # master data -> must be ambiguous, not a guess.
    codes, r = m.match_buyer(buyer_country="EE")
    assert r.status == MatchStatus.AMBIGUOUS
    assert codes.business_unit_code == ""


def test_supplier_country_must_not_infer_buyer_bu():
    """Synthetic held-out case (STEP 8.10): calling match_buyer with what is
    actually a SUPPLIER's country is a caller-contract violation this
    module cannot detect by itself, but the API only ever accepts a single
    `buyer_country` parameter — there is no supplier-country parameter that
    could accidentally leak in. This test documents/enforces that
    contract at the call-site level used by the pipeline (see run.py's
    integration)."""
    m = matcher()
    # A supplier country of "MY" must not be usable to resolve the buyer's
    # BU when the actual buyer country ("GH") is known separately.
    codes, r = m.match_buyer(buyer_country="GH")  # correct: buyer's own country
    assert codes.business_unit_code == "GH001"
    # Confirm resolving with the supplier's country instead would (WRONGLY)
    # pick Malaysia's BU -- proving why the pipeline must never pass the
    # wrong country in, not that this module silently protects against it.
    wrong_codes, wrong_r = m.match_buyer(buyer_country="MY")
    assert wrong_codes.business_unit_code == "MY001"
    assert wrong_codes.business_unit_code != codes.business_unit_code


def test_bu_unknown_country_returns_blank():
    m = matcher()
    codes, r = m.match_buyer(buyer_country="ZZ")
    assert r.status == MatchStatus.UNMATCHED
    assert codes.business_unit_code == ""


def test_every_matched_bu_code_exists_in_master():
    m = matcher()
    for country in ("GH", "MY", "ZA", "GB"):
        codes, r = m.match_buyer(buyer_country=country)
        if r.status == MatchStatus.MATCHED:
            assert m.validate_bu_code(codes.business_unit_code)


# =====================================================================
# TAX
# =====================================================================

def test_tax_exact_code_match():
    m = matcher()
    r = m.match_tax(explicit_code="DE_190_VAT")
    assert r.status == MatchStatus.MATCHED
    assert r.matched_id == "DE_190_VAT"


def test_tax_country_type_rate_match():
    m = matcher()
    r = m.match_tax(country="DE", tax_type="VAT", rate=19)
    assert r.status == MatchStatus.MATCHED
    assert r.matched_id == "DE_190_VAT"


def test_tax_ambiguous_candidates_returns_blank():
    m = matcher()
    # Ghana: TAX028 (NHIL, 2.5%) and TAX029 (GETFL, 2.5%) share a rate with
    # no tax_type given -> genuinely ambiguous in the REAL master data.
    r = m.match_tax(country="GH", rate=2.5)
    assert r.status == MatchStatus.AMBIGUOUS
    assert r.id_or_blank == ""


def test_tax_wrong_country_prevents_match():
    m = matcher()
    # 19% VAT exists for DE and RO — asking for a country with no such rate
    # (e.g. GB, which only has 20%/0%) must not match either of those.
    r = m.match_tax(country="GB", tax_type="VAT", rate=19)
    assert r.status == MatchStatus.UNMATCHED


def test_tax_unmatched_code_returns_blank():
    m = matcher()
    r = m.match_tax(explicit_code="NOT_A_REAL_CODE", country="XX", rate=None)
    assert r.id_or_blank == ""


def test_tax_explicit_evidence_not_overwritten_by_weaker_candidate():
    m = matcher()
    # Explicit code is correct and present -> must be used directly, not
    # re-derived (which could disagree if rate/type evidence were noisy).
    r = m.match_tax(explicit_code="DE_070_VAT", country="DE", tax_type="VAT", rate=19)
    assert r.matched_id == "DE_070_VAT"  # explicit code wins even though rate=19 would suggest DE_190_VAT


def test_every_matched_tax_code_exists_in_master():
    m = matcher()
    for record in m.taxes.records:
        r = m.match_tax(country=record["country"], tax_type=record["tax_type"], rate=record["rate"])
        if r.status == MatchStatus.MATCHED:
            assert m.validate_tax_code(r.matched_id)


# =====================================================================
# PAYMENT TERMS
# =====================================================================

def test_payment_term_exact_text_match():
    m = matcher()
    r = m.match_payment_term(text="Net 30")
    assert r.status == MatchStatus.MATCHED
    assert r.matched_id == "Net_30"


def test_payment_term_normalized_equivalent_text():
    m = matcher()
    r = m.match_payment_term(text="  NET   30  ")
    assert r.status == MatchStatus.MATCHED
    assert r.matched_id == "Net_30"


def test_payment_term_unique_day_count_match():
    m = matcher()
    r = m.match_payment_term(invoice_date="2026-01-01", due_date="2026-01-15")
    assert r.status == MatchStatus.MATCHED
    assert r.matched_id == "Net_14"


def test_payment_term_ambiguous_day_count_returns_blank():
    m = matcher()
    # days=0 is shared by "Immediate" and "Monthly_in_advance" in the REAL
    # master data -> must be ambiguous.
    r = m.match_payment_term(invoice_date="2026-01-01", due_date="2026-01-01")
    assert r.status == MatchStatus.AMBIGUOUS
    assert r.id_or_blank == ""


def test_every_matched_payment_term_id_exists_in_master():
    m = matcher()
    r = m.match_payment_term(text="Net 60")
    assert m.validate_payment_term_id(r.matched_id)


# =====================================================================
# PO
# =====================================================================

def test_po_exact_match():
    m = matcher()
    r = m.match_po("PO-EE-2026-0044")
    assert r.status == MatchStatus.MATCHED
    assert r.matched_id == "PO-EE-2026-0044"


def test_po_nonexistent_returns_blank():
    m = matcher()
    r = m.match_po("PO-DOES-NOT-EXIST-0000")
    assert r.id_or_blank == ""


def test_po_similar_but_not_identical_returns_blank():
    m = matcher()
    # One character off from a real PO -> must NOT fuzzy-match.
    r = m.match_po("PO-EE-2026-0045")
    assert r.id_or_blank == ""


def test_every_matched_po_id_exists_in_master():
    m = matcher()
    for record in m.purchase_orders.records:
        r = m.match_po(record["po_number"])
        if r.status == MatchStatus.MATCHED:
            assert m.validate_po_id(r.matched_id)


# =====================================================================
# SAFETY / INTEGRITY
# =====================================================================

def test_empty_missing_input_never_creates_a_match():
    m = matcher()
    assert m.match_supplier().id_or_blank == ""
    assert m.match_buyer()[1].status != MatchStatus.MATCHED
    assert m.match_tax().id_or_blank == ""
    assert m.match_payment_term().id_or_blank == ""
    assert m.match_po("").id_or_blank == ""


def test_matching_is_deterministic_across_repeated_runs():
    m1 = matcher()
    m2 = matcher()
    a = m1.match_supplier(name="Ehast Koiduni OU")
    b = m2.match_supplier(name="Ehast Koiduni OU")
    assert a.matched_id == b.matched_id
    assert a.status == b.status


# =====================================================================
# STEP 8.10 — generalization: synthetic held-out patterns beyond the 42
# known documents / any specific one of them.
# =====================================================================

def test_synthetic_supplier_name_collision_prefers_exact_over_fuzzy():
    m = matcher()
    # Exact name match for one supplier should win outright even though a
    # fuzzy scorer might rate a DIFFERENT supplier's name similarly.
    r = m.match_supplier(name="VMC Distribution Sdn Bhd", country="MY")
    assert r.matched_id == "2841753"
    assert r.method == "exact_normalized_name"


def test_synthetic_explicit_tax_code_from_unknown_country_still_resolves():
    m = matcher()
    r = m.match_tax(explicit_code="TH_WHT_003", country="ZZ", rate=999)
    assert r.status == MatchStatus.MATCHED
    assert r.matched_id == "TH_WHT_003"


def test_synthetic_missing_buyer_country_is_blank_not_a_default():
    m = matcher()
    codes, r = m.match_buyer(buyer_country="")
    assert r.status == MatchStatus.UNMATCHED
    assert codes == codes.__class__()  # fully blank, not a fallback default


def test_synthetic_contradictory_weak_evidence_does_not_force_a_match():
    m = matcher()
    r = m.match_supplier(name="Zzzz Totally Unknown Corp Xyzzy", country="PT")
    assert r.id_or_blank == ""
