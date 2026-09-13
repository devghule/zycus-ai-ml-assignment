"""Deprecated Phase 1 stub — superseded by pipeline/validation.py (Phase 10),
which implements the real business-rule checks (`check_supplier_buyer_
consistency`, `check_financial_consistency`, `check_credit_memo_consistency`,
`check_tax_consistency`) as part of its `adjudicate()` gate. Kept only so any
historical import of this module path doesn't break.
"""
from __future__ import annotations

from pipeline.validation import ValidationResult  # noqa: F401
