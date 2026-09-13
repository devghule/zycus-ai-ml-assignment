"""Stage: canonical financial model + erp.py reconciliation (Phase 7).

Builds an AUTODRAFT_SCHEMA.md-shaped payable from extracted "facts" and
validates it against the REAL, unmodified erp.py via
`pipeline.erp_validate.reconciles_exactly`. This module never reimplements
erp.py's arithmetic — it only assembles candidate payables and asks the
sealed oracle whether one of them reproduces the document's stated gross,
to the cent, with no tolerance.

Central mechanism — generalized trial-recompute for ambiguous charges:
some documents contain a charge/fee whose placement relative to tax is not
explicit (is it added to the taxable base before tax, or added to the gross
after tax?). Rather than trusting a column label or guessing, this module
builds BOTH candidate structures and keeps whichever one the real erp.py
confirms reproduces the printed total:

  Hypothesis A ("taxed together"): the charge becomes an additional line
  item, folding it into item_discounted_total / net_base so any existing
  header tax (computed on net_base) applies to it too.

  Hypothesis B ("post-tax addition"): the charge goes into extra_charges,
  which erp.py adds directly to gross without taxing it.

This is the general form of the "management-fee inside the tax base" class
of problem (base -> +fee -> taxable base -> VAT -> withholding -> final) —
there is no per-document special case here, only two structural hypotheses
adjudicated by the real ERP oracle against document evidence.

If neither hypothesis (nor the no-ambiguous-charge baseline) reconciles
exactly, the result is explicitly IRRECONCILABLE — never a fabricated match.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from pipeline.erp_validate import reconciles_exactly


@dataclass
class LineItemFact:
    """One extracted line item, in the raw (pre-canonical) shape."""

    description: str = ""
    item_type: str = "SERVICE"  # GOODS | SERVICE | FREIGHT | TAX
    uom: str = ""
    quantity: str = "1"
    unit_price: str = "0"
    total: str = ""  # as printed — cross-check only, never trusted blindly
    discount: str = ""
    discount_percentage: str = ""
    tax_rate: str = ""
    tax_amount: str = ""
    taxes: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AmbiguousCharge:
    """A charge/fee whose tax-base placement is not certain from extraction
    alone — resolved by trial-recompute against the real erp.py, not by
    trusting a label or an LLM's guess."""

    amount: str
    description: str = "fee"


@dataclass
class FinancialFacts:
    """Everything extraction (Phase 5) + locale normalization (Phase 6)
    could establish about one payable, before financial modeling."""

    invoice_type: str = "INVOICE"  # INVOICE | CREDIT_MEMO
    currency: str = ""
    line_items: list[LineItemFact] = field(default_factory=list)
    header_taxes: list[dict[str, Any]] = field(default_factory=list)
    discount_amount: str = ""
    freight_charges: str = ""
    insurance_charges: str = ""
    extra_charges: str = ""
    excise_duties: str = ""
    ambiguous_charges: list[AmbiguousCharge] = field(default_factory=list)
    stated_gross: str = ""  # the document's printed "amount owed" — the reconciliation target


@dataclass
class CanonicalPayable:
    """Result of financial modeling: either a reconciled, schema-shaped
    payable, or an explicit irreconcilable outcome (never a fabricated
    match)."""

    payload: dict[str, Any] | None
    reconciled: bool
    hypothesis_used: str = ""  # "" | "baseline" | "charge_taxed_together" | "charge_post_tax"
    reason: str = ""  # populated when reconciled is False


def _magnitude(raw: str) -> str:
    """Strip a leading '-' — used exactly once, at the credit-memo boundary,
    to convert a natively-negative printed amount to the positive magnitude
    the schema requires for CREDIT_MEMO records."""
    s = (raw or "").strip()
    return s[1:] if s.startswith("-") else s


def normalize_credit_memo_signs(facts: FinancialFacts) -> FinancialFacts:
    """If `facts.invoice_type == "CREDIT_MEMO"`, convert every magnitude
    field to a positive value. This is the ONE place sign conversion for
    credit memos happens — callers must not flip signs a second time
    upstream or downstream of this function."""
    if facts.invoice_type != "CREDIT_MEMO":
        return facts

    converted = copy.deepcopy(facts)
    for li in converted.line_items:
        li.unit_price = _magnitude(li.unit_price)
        li.total = _magnitude(li.total)
        li.discount = _magnitude(li.discount)
        li.tax_amount = _magnitude(li.tax_amount)
        for t in li.taxes:
            if "tax_amount" in t:
                t["tax_amount"] = _magnitude(str(t["tax_amount"]))
    for t in converted.header_taxes:
        if "tax_amount" in t:
            t["tax_amount"] = _magnitude(str(t["tax_amount"]))
    converted.discount_amount = _magnitude(converted.discount_amount)
    converted.freight_charges = _magnitude(converted.freight_charges)
    converted.insurance_charges = _magnitude(converted.insurance_charges)
    converted.extra_charges = _magnitude(converted.extra_charges)
    converted.excise_duties = _magnitude(converted.excise_duties)
    for c in converted.ambiguous_charges:
        c.amount = _magnitude(c.amount)
    converted.stated_gross = _magnitude(converted.stated_gross)
    return converted


def _line_item_payload(li: LineItemFact) -> dict[str, Any]:
    return {
        "description": li.description,
        "item_type": li.item_type,
        "uom": li.uom,
        "quantity": li.quantity,
        "unit_price": li.unit_price,
        "total": li.total,
        "discount": li.discount,
        "discount_percentage": li.discount_percentage,
        "tax_rate": li.tax_rate,
        "tax_amount": li.tax_amount,
        "taxes": li.taxes,
    }


def _base_payload(facts: FinancialFacts) -> dict[str, Any]:
    return {
        "invoice_type": facts.invoice_type,
        "currency": facts.currency,
        "line_items": [_line_item_payload(li) for li in facts.line_items],
        "taxes": [dict(t) for t in facts.header_taxes],
        "discount_amount": facts.discount_amount,
        "freight_charges": facts.freight_charges,
        "insurance_charges": facts.insurance_charges,
        "extra_charges": facts.extra_charges,
        "excise_duties": facts.excise_duties,
        "gross_total": facts.stated_gross,
    }


def _apply_charge_taxed_together(payload: dict[str, Any], charge: AmbiguousCharge) -> dict[str, Any]:
    """Hypothesis A: the charge becomes an additional line item, so it folds
    into item_discounted_total / net_base and is subject to whatever header
    tax already applies to that base — the general form of "fee inside the
    taxable base"."""
    candidate = copy.deepcopy(payload)
    candidate["line_items"].append(
        {
            "description": charge.description,
            "item_type": "SERVICE",
            "uom": "",
            "quantity": "1",
            "unit_price": charge.amount,
            "total": charge.amount,
            "discount": "",
            "discount_percentage": "",
            "tax_rate": "",
            "tax_amount": "",
            "taxes": [],
        }
    )
    return candidate


def _apply_charge_post_tax(payload: dict[str, Any], charge: AmbiguousCharge) -> dict[str, Any]:
    """Hypothesis B: the charge is a post-tax addition — erp.py adds
    extra_charges directly to gross without taxing it."""
    candidate = copy.deepcopy(payload)
    existing = candidate.get("extra_charges") or "0"
    try:
        combined = float(existing or 0) + float(charge.amount or 0)
    except ValueError:
        combined = float(charge.amount or 0)
    candidate["extra_charges"] = str(combined)
    return candidate


def _try_reconcile(payload: dict[str, Any], stated_gross: str) -> bool:
    if not stated_gross:
        return False
    return reconciles_exactly(payload, stated_gross)


def build_canonical_payable(facts: FinancialFacts) -> CanonicalPayable:
    """Build a schema-shaped payable from `facts` and validate it against
    the real erp.py. Applies credit-memo sign normalization exactly once,
    then — if there are ambiguous charges — trials each structural
    hypothesis and keeps only the one the oracle confirms.

    Returns an IRRECONCILABLE result (payload=None, reconciled=False) rather
    than ever returning a candidate that doesn't reproduce the document's
    stated gross exactly.
    """
    facts = normalize_credit_memo_signs(facts)
    base_payload = _base_payload(facts)

    if not facts.ambiguous_charges:
        if _try_reconcile(base_payload, facts.stated_gross):
            return CanonicalPayable(payload=base_payload, reconciled=True, hypothesis_used="baseline")
        return CanonicalPayable(
            payload=None,
            reconciled=False,
            reason="No ambiguous charges to resolve, and the baseline structure does not "
            "reproduce the document's stated gross exactly.",
        )

    # Exactly one ambiguous charge is the common case (e.g. HLD-01's
    # management fee); if there are several, each is trialed with the same
    # hypothesis together (fewer degrees of freedom than testing every
    # combination — a defensible simplification for a 4-day build, noted
    # here rather than silently assumed elsewhere).
    candidate_together = base_payload
    candidate_post_tax = base_payload
    for charge in facts.ambiguous_charges:
        candidate_together = _apply_charge_taxed_together(candidate_together, charge)
        candidate_post_tax = _apply_charge_post_tax(candidate_post_tax, charge)

    if _try_reconcile(candidate_together, facts.stated_gross):
        return CanonicalPayable(
            payload=candidate_together, reconciled=True, hypothesis_used="charge_taxed_together"
        )
    if _try_reconcile(candidate_post_tax, facts.stated_gross):
        return CanonicalPayable(
            payload=candidate_post_tax, reconciled=True, hypothesis_used="charge_post_tax"
        )
    if _try_reconcile(base_payload, facts.stated_gross):
        # The charge shouldn't have been added at all under either
        # hypothesis (e.g. it was already included in a line total) — the
        # baseline (charge omitted) is itself evidence-supported here only
        # if it independently reconciles.
        return CanonicalPayable(payload=base_payload, reconciled=True, hypothesis_used="baseline")

    return CanonicalPayable(
        payload=None,
        reconciled=False,
        reason="Neither the 'charge taxed together', 'charge post-tax', nor the baseline "
        "structure reproduces the document's stated gross exactly. This document is "
        "irreconcilable from the available evidence — it must not be forced.",
    )
