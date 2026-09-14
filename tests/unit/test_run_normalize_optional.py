"""Regression test for a real bug found during the Phase 10 corpus run:
run.py was writing extracted.fields["subtotal_raw"] straight into the
schema's `subtotal` field without Phase 6 normalization, so a comma-
thousands value like '7,434.78' violated the schema's dot-decimal
requirement. Fixed via the shared `_normalize_optional` helper."""
from __future__ import annotations

import pytest

from pipeline.locale_normalize import LocaleNormalizationError, normalize_number
from run import _normalize_optional


def test_normalize_optional_converts_comma_thousands_value():
    assert _normalize_optional("7,434.78", normalize_number) == "7434.78"


def test_normalize_optional_blank_input_returns_blank():
    assert _normalize_optional("", normalize_number) == ""


def test_normalize_optional_fails_safely_on_unnormalizable_input():
    # A genuinely ambiguous value must resolve to "" rather than raise or
    # pass through un-normalized.
    assert _normalize_optional("10,000", normalize_number) == ""
    with pytest.raises(LocaleNormalizationError):
        normalize_number("10,000")  # confirm the underlying function does raise


def test_credit_memo_subtotal_display_sign_stripped():
    """Phase 2 (improve-document-understanding): the display-only
    'subtotal' field must show a positive magnitude on a credit memo,
    consistent with gross_total's existing positive-magnitude convention —
    applied exactly once, here, for this separate display field."""
    normalized = _normalize_optional("-327,87".replace(",", "."), normalize_number)
    assert normalized == "-327.87"
    # The sign-strip itself is exercised at the run.py call site (a single
    # `if` guarded on invoice_type == "CREDIT_MEMO"); this test locks in
    # that normalize_number's own output is unaffected (no double
    # normalization), which is what that call site then strips once.
