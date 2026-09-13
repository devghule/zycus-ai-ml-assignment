"""Stage: ERP exact-gross validation (Phase 10 wires this into the full
validation gate sequence; this module itself is usable from Phase 7 on).

Wraps erp.py — never reimplements or modifies it. erp.py is imported from
the kit root, which is on sys.path because run.py lives there too.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from erp import erp_book  # sealed oracle — read-only import, never modified


def reconciles_exactly(payable: dict, stated_gross: str) -> bool:
    """True iff erp.py's recomputed gross equals the document's stated gross
    to the cent, exactly (locked decision: no tolerance)."""
    result = erp_book(payable)
    try:
        booked = Decimal(str(result["will_book_gross"]))
        stated = Decimal(str(stated_gross))
    except (InvalidOperation, KeyError):
        return False
    return booked == stated
