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
