"""Phase 8 orchestrator: wires the five master-data matchers together and
exposes one entry point the pipeline calls after the financial model has
produced a canonical payable.

Every emitted code is validated to actually exist in its master (STEP 8.7)
immediately before being placed in the payload — if a matcher's own logic
ever had a bug that produced a phantom ID, this is the final backstop that
prevents it reaching output. This module never invents evidence: if the
caller has no supplier name/VAT/buyer country/tax info/payment terms/PO
number to offer, the corresponding matcher is simply not called and the
field stays blank — that is correct, expected behavior, not a defect.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from config import MASTER_DATA_DIR
from pipeline.matching.chart_of_books import BuyerCodes, ChartOfBooksIndex
from pipeline.matching.match_result import MatchResult, MatchStatus
from pipeline.matching.payment_terms import PaymentTermIndex
from pipeline.matching.po_master import PurchaseOrderIndex
from pipeline.matching.suppliers import SupplierIndex
from pipeline.matching.tax_master import TaxIndex


@dataclass
class MasterDataMatches:
    """Everything Phase 8 resolved for one payable — the plain IDs are what
    go into the schema payload; `diagnostics` is internal-only."""

    supplier_id: str = ""
    buyer: BuyerCodes = field(default_factory=BuyerCodes)
    tax_type_codes: list[str] = field(default_factory=list)  # parallel to input tax list, "" for no-match
    payment_term_id: str = ""
    po_id: str = ""
    diagnostics: dict[str, MatchResult] = field(default_factory=dict)


class MasterDataMatcher:
    def __init__(self, master_data_dir: Path = MASTER_DATA_DIR) -> None:
        self.suppliers = SupplierIndex(master_data_dir)
        self.chart_of_books = ChartOfBooksIndex(master_data_dir)
        self.taxes = TaxIndex(master_data_dir)
        self.payment_terms = PaymentTermIndex(master_data_dir)
        self.purchase_orders = PurchaseOrderIndex(master_data_dir)

    def match_supplier(self, name: str = "", vat_id: str = "", country: str = "") -> MatchResult:
        return self.suppliers.match(name=name, vat_id=vat_id, country=country)

    def match_buyer(self, buyer_country: str = "", explicit_bu_code: str = "") -> tuple[BuyerCodes, MatchResult]:
        """`buyer_country` must be the BUYER's (tenant's) country — never the
        supplier's. `explicit_bu_code` takes priority when known."""
        if explicit_bu_code:
            result = self.chart_of_books.match_by_explicit_bu_code(explicit_bu_code)
        else:
            result = self.chart_of_books.match_by_buyer_country(buyer_country)
        if result.status != MatchStatus.MATCHED:
            return BuyerCodes(), result
        return self.chart_of_books.to_buyer_codes(result.matched_id), result

    def match_tax(self, country: str = "", tax_type: str = "", rate: float | None = None,
                  explicit_code: str = "") -> MatchResult:
        if explicit_code:
            result = self.taxes.match_by_explicit_code(explicit_code)
            if result.status == MatchStatus.MATCHED:
                return result
            # An explicit code that ISN'T in the master doesn't automatically
            # mean "no tax code exists" — fall through to composite matching
            # in case the explicit code was just a printed label mismatch,
            # but a country+type+rate winner still wins over nothing.
        return self.taxes.match(country=country, tax_type=tax_type, rate=rate)

    def match_payment_term(self, text: str = "", invoice_date: str = "", due_date: str = "") -> MatchResult:
        if text:
            result = self.payment_terms.match_by_text(text)
            if result.status == MatchStatus.MATCHED:
                return result
        return self.payment_terms.match_by_dates(invoice_date, due_date)

    def match_po(self, po_number: str = "", supplier_id: str = "", currency: str = "") -> MatchResult:
        return self.purchase_orders.match(po_number, supplier_id=supplier_id, currency=currency)

    # --- validation backstop --------------------------------------------

    def validate_supplier_id(self, supplier_id: str) -> bool:
        return bool(supplier_id) and self.suppliers.exists(supplier_id)

    def validate_bu_code(self, business_unit_code: str) -> bool:
        return bool(business_unit_code) and self.chart_of_books.exists(business_unit_code)

    def validate_tax_code(self, tax_code: str) -> bool:
        return bool(tax_code) and self.taxes.exists(tax_code)

    def validate_payment_term_id(self, payment_term_id: str) -> bool:
        return bool(payment_term_id) and self.payment_terms.exists(payment_term_id)

    def validate_po_id(self, po_id: str) -> bool:
        return bool(po_id) and self.purchase_orders.exists(po_id)
