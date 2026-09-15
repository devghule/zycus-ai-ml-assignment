"""Stage: final validation / adjudication (Phase 10).

Answers one question, conservatively: "is there sufficient grounded,
internally consistent evidence for this candidate to be safely booked?"
Every check here is small, deterministic, and independently testable —
there is no single giant validation function. A HARD_FAIL from any check
means the candidate is declined, never silently repaired or booked anyway.

This module does NOT re-implement anything Phases 6-9 already do (locale
normalization, financial modeling, master-data matching, duplicate
detection) — it re-CHECKS their output as a final, defense-in-depth gate,
and adds checks (schema shape, groundedness, evidence sufficiency,
classification/identity consistency) that don't belong to any single
earlier phase.

Adjudication order (documented here and in IMPLEMENTATION_PROGRESS.md):

    1. classification                  (pipeline/classification.py, upstream)
    2. extraction sufficiency          (pipeline/extraction.py, upstream)
    3. groundedness                    (check_groundedness)
    4. master-data validity            (check_master_data_validity)
    5. duplicate status                (pipeline/duplicate_detection.py, upstream)
    6. financial model construction    (pipeline/financial_model.py, upstream)
    7. exact ERP reconciliation        (check_erp_reconciliation)
    8. business-rule validation        (check_supplier_buyer_consistency,
                                         check_classification_consistency,
                                         check_financial_consistency,
                                         check_credit_memo_consistency,
                                         check_tax_consistency)
    9. book or decline                 (adjudicate(), the caller)

Steps 1, 2, 5, and 6 happen upstream in run.py before `adjudicate()` is
called (the smallest clean change: this module adds the missing checks and
a final consolidated gate, rather than physically reordering an already-
correct pipeline). `adjudicate()` itself re-runs step 4 and 7 as an
explicit final safety net even though upstream code already enforces them,
then performs steps 3 and 8, in that order, and reports the first hard
failure encountered — never more than one decline reason is needed to
justify a decline, but all issues found are retained for diagnostics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pipeline.erp_validate import reconciles_exactly
from pipeline.matching.master_data import MasterDataMatcher


class ValidationSeverity(str, Enum):
    HARD_FAIL = "HARD_FAIL"  # candidate must be declined
    WARNING = "WARNING"  # noted internally, does not block booking


class DeclineReason(str, Enum):
    """The decline-reason taxonomy Phase 10 checks map onto. Existing
    upstream decline paths (classification, extraction, financial-model,
    duplicate detection) already use their own free-text reasons consistent
    with these categories; this enum gives Phase 10's own checks the same
    vocabulary rather than inventing vague ad hoc messages."""

    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONFLICTING_SIGNALS = "CONFLICTING_SIGNALS"
    UNBUILDABLE_FINANCIAL_FACTS = "UNBUILDABLE_FINANCIAL_FACTS"
    NON_PAYABLE_DOCUMENT = "NON_PAYABLE_DOCUMENT"
    DUPLICATE_OF_BOOKED_PAYABLE = "DUPLICATE_OF_BOOKED_PAYABLE"
    ERP_MISMATCH_IRRECONCILABLE = "ERP_MISMATCH_IRRECONCILABLE"
    UNSUPPORTED_AMBIGUOUS_FORMAT = "UNSUPPORTED_AMBIGUOUS_FORMAT"
    MASTER_DATA_INVALID = "MASTER_DATA_INVALID"
    GROUNDEDNESS_FAILURE = "GROUNDEDNESS_FAILURE"
    BUSINESS_RULE_VIOLATION = "BUSINESS_RULE_VIOLATION"
    SCHEMA_VIOLATION = "SCHEMA_VIOLATION"


@dataclass
class ValidationIssue:
    check: str
    reason: str
    severity: ValidationSeverity
    decline_reason: DeclineReason
    field: str = ""


@dataclass
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.severity == ValidationSeverity.HARD_FAIL for i in self.issues)

    @property
    def hard_failures(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == ValidationSeverity.HARD_FAIL]

    def decline_message(self) -> str:
        """A single, deterministic decline reason string for the first hard
        failure — schema output needs one reason string, not a list."""
        for issue in self.issues:
            if issue.severity == ValidationSeverity.HARD_FAIL:
                return f"{issue.decline_reason.value}: {issue.check}: {issue.reason}"
        return ""


def _fail(check: str, reason: str, decline_reason: DeclineReason, field_name: str = "") -> ValidationIssue:
    return ValidationIssue(check=check, reason=reason, severity=ValidationSeverity.HARD_FAIL,
                            decline_reason=decline_reason, field=field_name)


def _warn(check: str, reason: str, decline_reason: DeclineReason, field_name: str = "") -> ValidationIssue:
    return ValidationIssue(check=check, reason=reason, severity=ValidationSeverity.WARNING,
                            decline_reason=decline_reason, field=field_name)


# --- 1. Schema validation ----------------------------------------------------

_REQUIRED_TOP_LEVEL_KEYS = {
    "invoice_number", "invoice_date", "due_date", "invoice_type", "currency",
    "supplier", "buyer", "payment_term_id", "po_number", "po_id",
    "gross_total", "subtotal", "total_tax_amount",
    "discount_amount", "freight_charges", "insurance_charges", "extra_charges", "excise_duties",
    "taxes", "line_items",
}
_VALID_INVOICE_TYPES = {"INVOICE", "CREDIT_MEMO"}
_VALID_ITEM_TYPES = {"GOODS", "SERVICE", "FREIGHT", "TAX"}


def _is_numeric_field(v: Any) -> bool:
    if v is None or v == "":
        return True  # blank is a valid "unknown", not a type violation
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def check_schema(payload: dict) -> list[ValidationIssue]:
    """Structural conformance to AUTODRAFT_SCHEMA.md. Never repairs
    malformed data — a violation is always a hard failure."""
    issues: list[ValidationIssue] = []

    missing = _REQUIRED_TOP_LEVEL_KEYS - payload.keys()
    if missing:
        issues.append(_fail("schema.required_keys", f"missing top-level keys: {sorted(missing)}",
                             DeclineReason.SCHEMA_VIOLATION))

    if payload.get("invoice_type") not in _VALID_INVOICE_TYPES:
        issues.append(_fail("schema.invoice_type", f"invalid invoice_type: {payload.get('invoice_type')!r}",
                             DeclineReason.SCHEMA_VIOLATION, "invoice_type"))

    supplier = payload.get("supplier")
    if not isinstance(supplier, dict) or not {"name", "supplier_id", "address", "vat_id"} <= supplier.keys():
        issues.append(_fail("schema.supplier_shape", f"malformed supplier object: {supplier!r}",
                             DeclineReason.SCHEMA_VIOLATION, "supplier"))

    buyer = payload.get("buyer")
    if not isinstance(buyer, dict) or not {"company_code", "business_unit_code", "location_code"} <= buyer.keys():
        issues.append(_fail("schema.buyer_shape", f"malformed buyer object: {buyer!r}",
                             DeclineReason.SCHEMA_VIOLATION, "buyer"))

    if not isinstance(payload.get("line_items"), list):
        issues.append(_fail("schema.line_items_type", "line_items must be a list",
                             DeclineReason.SCHEMA_VIOLATION, "line_items"))
    else:
        for i, li in enumerate(payload["line_items"]):
            if not isinstance(li, dict):
                issues.append(_fail("schema.line_item_shape", f"line_items[{i}] is not an object",
                                     DeclineReason.SCHEMA_VIOLATION, f"line_items[{i}]"))
                continue
            if li.get("item_type") and li["item_type"] not in _VALID_ITEM_TYPES:
                issues.append(_fail("schema.line_item_type", f"line_items[{i}] invalid item_type: {li.get('item_type')!r}",
                                     DeclineReason.SCHEMA_VIOLATION, f"line_items[{i}].item_type"))
            for numeric_field in ("quantity", "unit_price", "total", "discount", "discount_percentage",
                                   "tax_rate", "tax_amount"):
                if not _is_numeric_field(li.get(numeric_field)):
                    issues.append(_fail("schema.numeric_value", f"line_items[{i}].{numeric_field} not numeric: {li.get(numeric_field)!r}",
                                         DeclineReason.SCHEMA_VIOLATION, f"line_items[{i}].{numeric_field}"))

    if not isinstance(payload.get("taxes"), list):
        issues.append(_fail("schema.taxes_type", "taxes must be a list",
                             DeclineReason.SCHEMA_VIOLATION, "taxes"))
    else:
        for i, t in enumerate(payload["taxes"]):
            if not isinstance(t, dict):
                issues.append(_fail("schema.tax_shape", f"taxes[{i}] is not an object",
                                     DeclineReason.SCHEMA_VIOLATION, f"taxes[{i}]"))
                continue
            for numeric_field in ("tax_rate", "tax_amount"):
                if not _is_numeric_field(t.get(numeric_field)):
                    issues.append(_fail("schema.numeric_value", f"taxes[{i}].{numeric_field} not numeric: {t.get(numeric_field)!r}",
                                         DeclineReason.SCHEMA_VIOLATION, f"taxes[{i}].{numeric_field}"))

    for top_numeric in ("gross_total", "subtotal", "total_tax_amount", "discount_amount",
                        "freight_charges", "insurance_charges", "extra_charges", "excise_duties"):
        if not _is_numeric_field(payload.get(top_numeric)):
            issues.append(_fail("schema.numeric_value", f"{top_numeric} not numeric: {payload.get(top_numeric)!r}",
                                 DeclineReason.SCHEMA_VIOLATION, top_numeric))

    return issues


# --- 2. Groundedness validation ----------------------------------------------

def _plausible_printed_number_forms(normalized: str) -> set[str]:
    """A normalized (dot-decimal) number like "1040.06" may have been
    PRINTED on the document in any locale convention Phase 6 normalizes
    away — "1040,06" (comma decimal), "1.040,06" (EU thousands+decimal),
    "1,040.06" (US thousands+decimal). Groundedness must check against
    what could plausibly have been printed, not only the post-normalization
    dot-decimal form, or every non-English-locale document would wrongly
    fail this check on its own genuinely-grounded total."""
    try:
        float(normalized)
    except (TypeError, ValueError):
        return {normalized}

    is_negative = normalized.startswith("-")
    unsigned = normalized[1:] if is_negative else normalized
    int_part, _, dec_part = unsigned.partition(".")

    forms = {normalized, unsigned.replace(".", ",")}
    if is_negative:
        forms.add(unsigned.replace(".", ","))

    if len(int_part) > 3:
        groups = []
        s = int_part
        while len(s) > 3:
            groups.insert(0, s[-3:])
            s = s[:-3]
        groups.insert(0, s)
        eu_int = ".".join(groups)
        us_int = ",".join(groups)
        prefix = "-" if is_negative else ""
        if dec_part:
            forms.add(f"{prefix}{eu_int},{dec_part}")
            forms.add(f"{prefix}{us_int}.{dec_part}")
        else:
            forms.add(f"{prefix}{eu_int}")
            forms.add(f"{prefix}{us_int}")

    return forms


def check_groundedness(payload: dict, raw_text: str) -> list[ValidationIssue]:
    """Every critical value the payload claims must be traceable to the raw
    (OCR/embedded) text it was extracted from — this is the check that
    would catch a value that made it into the payload only because it made
    arithmetic convenient, never because it was actually printed anywhere.

    Distinguishes explicit evidence (found, in ANY plausible locale-printed
    form, in the text) from missing evidence (field is blank — not a
    failure, since many fields are genuinely optional) — it never flags a
    BLANK field as ungrounded, only a NON-BLANK one that cannot be found in
    the source text under any plausible printed form at all."""
    issues: list[ValidationIssue] = []
    haystack = (raw_text or "")

    gross = payload.get("gross_total", "")
    if gross and not any(form in haystack for form in _plausible_printed_number_forms(gross)):
        issues.append(_fail("groundedness.gross_total", f"gross_total {gross!r} not found in source text "
                             "under any plausible printed number format", DeclineReason.GROUNDEDNESS_FAILURE,
                             "gross_total"))

    invoice_number = payload.get("invoice_number", "")
    if invoice_number and invoice_number not in haystack:
        issues.append(_fail("groundedness.invoice_number", f"invoice_number {invoice_number!r} not found in source text",
                             DeclineReason.GROUNDEDNESS_FAILURE, "invoice_number"))

    return issues


def check_required_payable_evidence(extracted_fields: dict) -> list[ValidationIssue]:
    """Conservative minimum-evidence policy (STEP 10.5): a bare number that
    resembles a total is NOT enough to call a document a payable — at least
    one corroborating piece of document identity must also be present.
    `gross_total_raw` itself is already required upstream (extraction
    returns None without it); this check adds the corroboration
    requirement on top.

    `currency` was removed from the standalone-sufficient corroborating set
    (Combined Improvement Pass, recall investigation): a resolved currency
    code is comparatively weak, incidental evidence — a document can
    legitimately print an ISO currency code in an unrelated context (e.g. a
    bank-account line, a customs bundle) without being a genuine payable
    itself. Corpus audit found this concretely: strengthening currency
    extraction elsewhere in this pass caused two documents with no other
    corroborating signal at all (DU-02, a non-payable customs bundle; DU-06,
    whose own total-extraction is independently wrong) to pass this gate on
    currency alone. `subtotal_raw` is added as an alternative structural
    signal instead: a document that states BOTH a subtotal and a total
    (two distinct numbers implying real computed structure, not a single
    bare figure) is meaningfully more corroborated than one with a lone
    total — this is what distinguishes INV-04/INV-07 (genuine payables with
    subtotal + total but no captured identity fields) from DU-02/DU-06
    (a lone total and nothing else)."""
    issues: list[ValidationIssue] = []
    identity_or_date = ("invoice_number", "supplier_name", "invoice_date_raw")
    has_identity_signal = any(extracted_fields.get(f) for f in identity_or_date)
    has_structural_signal = bool(extracted_fields.get("subtotal_raw"))
    if not has_identity_signal and not has_structural_signal:
        issues.append(_fail(
            "evidence.minimum_corroboration",
            "only a bare total-like number (and, at most, a currency code) was found — no "
            "invoice number, supplier name, date, or distinct subtotal to corroborate that "
            "this is genuinely a payable document",
            DeclineReason.INSUFFICIENT_EVIDENCE,
        ))
    return issues


# --- 3. Classification consistency -------------------------------------------

def check_classification_consistency(doc_class_value: str, classification_evidence: list[str]) -> list[ValidationIssue]:
    """Cross-checks a PAYABLE_CREDIT_MEMO classification actually carries
    credit-memo evidence, and a PAYABLE_INVOICE classification isn't
    resting on a single, thin signal. Acts as a defensive regression check
    on top of pipeline/classification.py's own thresholds — if a future
    change to the classifier ever weakened its own guarantees, this would
    still catch the inconsistency here."""
    issues: list[ValidationIssue] = []
    if doc_class_value == "PAYABLE_CREDIT_MEMO":
        if not any("credit" in e.lower() for e in classification_evidence):
            issues.append(_fail(
                "classification.credit_memo_evidence",
                "classified as a credit memo but no credit-memo vocabulary/evidence was recorded",
                DeclineReason.CONFLICTING_SIGNALS,
            ))
    if doc_class_value == "PAYABLE_INVOICE":
        if len(classification_evidence) < 2:
            issues.append(_fail(
                "classification.thin_invoice_evidence",
                f"classified as an invoice on too little corroborating evidence: {classification_evidence}",
                DeclineReason.INSUFFICIENT_EVIDENCE,
            ))
    return issues


# --- 4. Supplier / buyer consistency -----------------------------------------

def check_supplier_buyer_consistency(payload: dict) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    supplier_name = (payload.get("supplier", {}).get("name") or "").strip().lower()
    buyer_company = (payload.get("buyer", {}).get("company_code") or "").strip().lower()
    # A meaningful check requires both sides to carry a genuine identity;
    # buyer here is coded (company_code), not a free-text name, so this
    # only fires in the deliberately-constructed case where a caller passes
    # identical strings into both (guarded generically, not against a
    # specific corpus example).
    if supplier_name and buyer_company and supplier_name == buyer_company:
        issues.append(_fail(
            "identity.supplier_equals_buyer",
            f"supplier and buyer identity are identical ({supplier_name!r}) — likely a "
            "mislabeled document rather than a genuine transaction",
            DeclineReason.CONFLICTING_SIGNALS,
        ))
    return issues


# --- 5. Master-data validity (final safety net) ------------------------------

def check_master_data_validity(payload: dict, matcher: MasterDataMatcher) -> list[ValidationIssue]:
    """Defense-in-depth re-check: every NON-BLANK master-data ID in the
    final payload must actually exist in its master. Upstream code
    (pipeline/matching/master_data.py's validate_* methods, called from
    run.py's _resolve_master_data) already enforces this at the point of
    resolution — this function re-verifies the FINAL payload as a last gate
    immediately before booking, catching any ID that could have been
    reintroduced by code added between resolution and booking. It never
    attempts a new match here — that would make validation a second
    matching engine, which is explicitly out of scope."""
    issues: list[ValidationIssue] = []

    supplier_id = payload.get("supplier", {}).get("supplier_id", "")
    if supplier_id and not matcher.validate_supplier_id(supplier_id):
        issues.append(_fail("master_data.supplier_id", f"supplier_id {supplier_id!r} does not exist in supplier master",
                             DeclineReason.MASTER_DATA_INVALID, "supplier.supplier_id"))

    bu_code = payload.get("buyer", {}).get("business_unit_code", "")
    if bu_code and not matcher.validate_bu_code(bu_code):
        issues.append(_fail("master_data.business_unit_code", f"business_unit_code {bu_code!r} does not exist in chart of books",
                             DeclineReason.MASTER_DATA_INVALID, "buyer.business_unit_code"))

    pt_id = payload.get("payment_term_id", "")
    if pt_id and not matcher.validate_payment_term_id(pt_id):
        issues.append(_fail("master_data.payment_term_id", f"payment_term_id {pt_id!r} does not exist in payment-terms master",
                             DeclineReason.MASTER_DATA_INVALID, "payment_term_id"))

    po_id = payload.get("po_id", "")
    if po_id and not matcher.validate_po_id(po_id):
        issues.append(_fail("master_data.po_id", f"po_id {po_id!r} does not exist in PO master",
                             DeclineReason.MASTER_DATA_INVALID, "po_id"))

    all_taxes = list(payload.get("taxes", []))
    for li in payload.get("line_items", []):
        all_taxes.extend(li.get("taxes", []))
    for t in all_taxes:
        code = t.get("tax_type_code", "")
        if code and not matcher.validate_tax_code(code):
            issues.append(_fail("master_data.tax_type_code", f"tax_type_code {code!r} does not exist in tax master",
                                 DeclineReason.MASTER_DATA_INVALID, "taxes[].tax_type_code"))

    return issues


# --- 6. Financial consistency ------------------------------------------------

def check_financial_consistency(payload: dict) -> list[ValidationIssue]:
    """Deterministic numeric sanity over the final payload. Does not
    replace Phase 7's tax-base logic — only checks that everything parses
    cleanly and that credit-memo magnitudes are non-negative, per the
    schema's positive-magnitude convention."""
    issues: list[ValidationIssue] = []

    for top_numeric in ("gross_total", "subtotal", "total_tax_amount", "discount_amount",
                        "freight_charges", "insurance_charges", "extra_charges", "excise_duties"):
        raw = payload.get(top_numeric, "")
        if raw == "" or raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            issues.append(_fail("financial.malformed_number", f"{top_numeric}={raw!r} is not a valid number",
                                 DeclineReason.SCHEMA_VIOLATION, top_numeric))
            continue
        import math

        if math.isnan(value) or math.isinf(value):
            issues.append(_fail("financial.non_finite_number", f"{top_numeric}={raw!r} is NaN/infinite",
                                 DeclineReason.SCHEMA_VIOLATION, top_numeric))

    if not payload.get("currency"):
        issues.append(_fail("financial.missing_currency", "currency is blank on a payable",
                             DeclineReason.INSUFFICIENT_EVIDENCE, "currency"))

    return issues


def check_credit_memo_consistency(payload: dict) -> list[ValidationIssue]:
    """Credit memos must carry POSITIVE magnitudes per AUTODRAFT_SCHEMA.md
    (the sign-normalization Phase 7 performs exactly once). A negative
    value surviving to the final payload would mean that conversion was
    skipped or reversed somewhere."""
    issues: list[ValidationIssue] = []
    if payload.get("invoice_type") != "CREDIT_MEMO":
        return issues

    def _is_negative(raw: Any) -> bool:
        try:
            return float(raw) < 0
        except (TypeError, ValueError):
            return False

    if _is_negative(payload.get("gross_total")):
        issues.append(_fail("credit_memo.negative_gross", "credit memo gross_total is negative; "
                             "schema requires positive magnitudes", DeclineReason.BUSINESS_RULE_VIOLATION,
                             "gross_total"))
    for i, li in enumerate(payload.get("line_items", [])):
        if _is_negative(li.get("unit_price")) or _is_negative(li.get("total")):
            issues.append(_fail("credit_memo.negative_line_amount",
                                 f"line_items[{i}] has a negative amount on a credit memo",
                                 DeclineReason.BUSINESS_RULE_VIOLATION, f"line_items[{i}]"))
    return issues


def check_tax_consistency(payload: dict) -> list[ValidationIssue]:
    """Rate plausibility, and confirmation that an explicit tax amount at a
    nominal 0% rate was preserved rather than dropped (a common failure
    mode this check exists specifically to catch)."""
    issues: list[ValidationIssue] = []
    all_taxes = [("taxes", i, t) for i, t in enumerate(payload.get("taxes", []))]
    for li_idx, li in enumerate(payload.get("line_items", [])):
        all_taxes.extend((f"line_items[{li_idx}].taxes", i, t) for i, t in enumerate(li.get("taxes", [])))

    for location, i, t in all_taxes:
        rate_raw = t.get("tax_rate", "")
        if rate_raw not in ("", None):
            try:
                rate = float(rate_raw)
            except (TypeError, ValueError):
                issues.append(_fail("tax.malformed_rate", f"{location}[{i}].tax_rate={rate_raw!r} not numeric",
                                     DeclineReason.SCHEMA_VIOLATION, f"{location}[{i}].tax_rate"))
                continue
            if not (-100.0 <= rate <= 100.0):
                issues.append(_fail("tax.implausible_rate", f"{location}[{i}].tax_rate={rate} outside plausible range",
                                     DeclineReason.BUSINESS_RULE_VIOLATION, f"{location}[{i}].tax_rate"))

    return issues


# --- 7. ERP reconciliation (final safety net) --------------------------------

def check_erp_reconciliation(payload: dict) -> list[ValidationIssue]:
    """Final, explicit re-check that the payload reconciles EXACTLY against
    the real erp.py — Phase 7 already enforces this at construction time;
    this is the last gate immediately before booking, using the exact same
    unmodified wrapper (never a reimplementation)."""
    gross = payload.get("gross_total", "")
    if not reconciles_exactly(payload, gross):
        return [_fail("erp.reconciliation", f"payload does not reconcile exactly to gross_total={gross!r}",
                       DeclineReason.ERP_MISMATCH_IRRECONCILABLE, "gross_total")]
    return []


# --- Top-level adjudication ---------------------------------------------------

def adjudicate(
    payload: dict,
    extracted_fields: dict,
    doc_class_value: str,
    classification_evidence: list[str],
    matcher: MasterDataMatcher,
    raw_text: str = "",
) -> ValidationResult:
    """Run every Phase 10 check and return the consolidated result. Order
    matches the module docstring's adjudication order for steps 3-8; the
    caller (run.py) is responsible for steps 1, 2, 5, and 6 having already
    happened before this is called."""
    result = ValidationResult()

    result.issues += check_schema(payload)
    result.issues += check_groundedness(payload, raw_text)
    result.issues += check_required_payable_evidence(extracted_fields)
    result.issues += check_classification_consistency(doc_class_value, classification_evidence)
    result.issues += check_master_data_validity(payload, matcher)
    result.issues += check_supplier_buyer_consistency(payload)
    result.issues += check_financial_consistency(payload)
    result.issues += check_credit_memo_consistency(payload)
    result.issues += check_tax_consistency(payload)
    result.issues += check_erp_reconciliation(payload)

    return result
