import pytest

from pipeline.locale_normalize import (
    LocaleNormalizationError,
    normalize_currency,
    normalize_date,
    normalize_number,
)


# --- Numbers ------------------------------------------------------------

def test_eu_number_format():
    assert normalize_number("1.234,56") == "1234.56"


def test_us_number_format():
    assert normalize_number("1,234.56") == "1234.56"


def test_no_thousands_comma_decimal():
    assert normalize_number("1234,56") == "1234.56"


def test_no_thousands_dot_decimal():
    assert normalize_number("1234.56") == "1234.56"


def test_negative_number():
    assert normalize_number("-123.45") == "-123.45"


def test_parenthetical_negative():
    assert normalize_number("(123.45)") == "-123.45"


def test_percentage_strips_percent_sign():
    assert normalize_number("12.5%") == "12.5"


def test_currency_symbol_prefixed():
    assert normalize_number("€1.234,56") == "1234.56"


def test_currency_code_wrapped():
    assert normalize_number("EUR 12.10") == "12.10"


def test_ambiguous_comma_thousands_only_refuses_to_guess():
    with pytest.raises(LocaleNormalizationError):
        normalize_number("10,000")


def test_malformed_number_raises():
    with pytest.raises(LocaleNormalizationError):
        normalize_number("not a number")


def test_empty_number_is_empty_string():
    assert normalize_number("") == ""


# --- Currency -------------------------------------------------------------

def test_currency_symbol_to_iso():
    assert normalize_currency("€") == "EUR"
    assert normalize_currency("$") == "USD"
    assert normalize_currency("£") == "GBP"


def test_explicit_iso_code_passthrough_never_overridden():
    assert normalize_currency("USD") == "USD"
    assert normalize_currency("eur") == "EUR"


def test_unresolvable_currency_raises():
    with pytest.raises(LocaleNormalizationError):
        normalize_currency("XYZ123")


# --- Dates ------------------------------------------------------------

def test_iso_date_passthrough():
    assert normalize_date("2026-02-02") == "2026-02-02"


def test_dot_date_format():
    assert normalize_date("02.02.2026") == "2026-02-02"


def test_slash_date_format():
    assert normalize_date("02/03/2026") == "2026-03-02"  # DD/MM/YYYY


def test_dash_date_format():
    assert normalize_date("02-03-2026") == "2026-03-02"


def test_day_month_name_year_format():
    assert normalize_date("20 June 2026") == "2026-06-20"


def test_thai_buddhist_era_explicit_marker():
    # BE 2569 -> CE 2026
    assert normalize_date("02.02.2569 B.E.") == "2026-02-02"


def test_thai_buddhist_era_inferred_from_implausible_year():
    # No explicit marker, but 2569 is not a plausible Gregorian year for a
    # business document -> general BE inference triggers.
    assert normalize_date("02.02.2569") == "2026-02-02"


def test_unrecognized_date_format_fails_safely():
    with pytest.raises(LocaleNormalizationError):
        normalize_date("the second of February")


def test_unrecognized_calendar_with_implausible_result_fails_safely():
    with pytest.raises(LocaleNormalizationError):
        normalize_date("02.02.9999")
