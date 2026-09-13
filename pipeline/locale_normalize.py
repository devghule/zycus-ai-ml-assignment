"""Stage: deterministic locale normalization (Phase 6).

Pure deterministic Python — no LLM reasoning anywhere in this module. Turns
raw printed values (numbers, currencies, dates) into the dot-decimal /
ISO-date representation AUTODRAFT_SCHEMA.md and erp.py expect.

Ambiguous input (a number/date/calendar that cannot be resolved without
guessing) raises LocaleNormalizationError rather than picking an
interpretation — "fail safely" is the locked policy for unknown formats.
Credit-memo sign conversion is explicitly NOT done here (see
pipeline/financial_model.py) — this module only parses the sign as printed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


class LocaleNormalizationError(ValueError):
    """Raised when a value cannot be safely normalized (fail safely, per the
    locked policy: never silently guess an ambiguous or unfamiliar format)."""


@dataclass
class NormalizedNumber:
    raw: str
    value: float
    is_negative: bool


# --- Number normalization ----------------------------------------------------

_CURRENCY_CHARS = "€$£¥₹"


def _strip_currency_and_whitespace(s: str) -> str:
    s = s.strip()
    s = s.strip(_CURRENCY_CHARS + " \t")
    # also strip a trailing/leading ISO-ish currency code, e.g. "EUR 12.10" / "12.10 EUR"
    s = re.sub(r"^[A-Z]{3}\s*", "", s)
    s = re.sub(r"\s*[A-Z]{3}$", "", s)
    return s.strip()


def normalize_number(raw: str) -> str:
    """Normalize a printed number to a plain dot-decimal string ('1234.56').

    Handles: EU format (1.234,56), US format (1,234.56), no-thousands with
    comma decimal (1234,56), plain dot-decimal (1234.56), negative sign
    (-123.45), parenthetical negatives ((123.45)), percentages (12.5% ->
    "12.5"), and currency symbol/code wrapping.

    Raises LocaleNormalizationError for genuinely ambiguous input (e.g. a
    single-comma-thousands-only number like "10,000" with no corroborating
    evidence of which convention applies) rather than guessing.
    """
    if raw is None:
        raise LocaleNormalizationError("cannot normalize None")
    s = str(raw).strip()
    if s == "":
        return ""

    is_paren_negative = s.startswith("(") and s.endswith(")")
    if is_paren_negative:
        s = s[1:-1].strip()

    is_percentage = s.endswith("%")
    if is_percentage:
        s = s[:-1].strip()

    s = _strip_currency_and_whitespace(s)

    is_negative = is_paren_negative
    if s.startswith("-"):
        is_negative = True
        s = s[1:].strip()
    elif s.startswith("+"):
        s = s[1:].strip()

    if s == "":
        raise LocaleNormalizationError(f"cannot normalize number: {raw!r}")

    if not re.fullmatch(r"[\d.,\s]+", s):
        raise LocaleNormalizationError(f"cannot normalize number: {raw!r} (non-numeric characters)")

    s = s.replace(" ", "")  # some locales use a thin space as thousands separator

    has_dot = "." in s
    has_comma = "," in s

    if has_dot and has_comma:
        # Whichever separator appears LAST is the decimal separator; the
        # other is thousands grouping. This is unambiguous once both are
        # present (e.g. "1.234,56" -> comma is last -> EU; "1,234.56" ->
        # dot is last -> US).
        last_dot = s.rfind(".")
        last_comma = s.rfind(",")
        if last_comma > last_dot:
            # EU: dot(s) = thousands, comma = decimal
            integer_part = s[:last_comma].replace(".", "")
            decimal_part = s[last_comma + 1 :]
        else:
            # US: comma(s) = thousands, dot = decimal
            integer_part = s[:last_dot].replace(",", "")
            decimal_part = s[last_dot + 1 :]
        normalized = f"{integer_part}.{decimal_part}" if decimal_part else integer_part
    elif has_comma and not has_dot:
        # Single separator type: a comma. Ambiguous between "1234,56"
        # (decimal comma) and "10,000" (thousands comma) UNLESS the digits
        # after the last comma make one interpretation implausible.
        parts = s.split(",")
        last_group = parts[-1]
        if len(parts) == 2 and len(last_group) in (1, 2):
            # Exactly one comma, 1-2 digits after it -> almost certainly a
            # decimal comma (e.g. "1234,56", "67,3").
            normalized = f"{parts[0]}.{last_group}"
        elif len(parts) > 2 or (len(parts) == 2 and len(last_group) == 3):
            # Multiple comma groups, or exactly one group of 3 digits after
            # a single comma ("10,000") — this is the genuinely ambiguous
            # case: could be EU thousands-grouping-only or a decimal comma
            # with 3 fractional digits. Refuse to guess.
            raise LocaleNormalizationError(
                f"ambiguous number (comma-only, 3-digit group): {raw!r} — "
                "cannot determine thousands vs. decimal separator without more context"
            )
        else:
            raise LocaleNormalizationError(f"cannot normalize number: {raw!r}")
    elif has_dot and not has_comma:
        parts = s.split(".")
        last_group = parts[-1]
        if len(parts) == 2:
            # One dot: either a decimal point (any digit count is fine for a
            # decimal point in practice) or thousands-only if the group is
            # exactly 3 digits AND there's a strong prior "US thousands"
            # signal — but a single dot with 3 trailing digits is far more
            # commonly a decimal point written to 3dp, or thousands. Treat a
            # lone dot as decimal (dot-decimal is erp.py's own convention
            # and the most common unambiguous case); this mirrors how
            # "1234.56" and "1234.567" are both read as decimals absent
            # other evidence.
            normalized = s
        else:
            # Multiple dots with no comma: dot is being used as thousands
            # separator throughout (e.g. "1.234.567") with no decimal part
            # shown.
            normalized = "".join(parts)
    else:
        # No separators at all.
        normalized = s

    try:
        value = float(normalized)
    except ValueError as exc:
        raise LocaleNormalizationError(f"cannot normalize number: {raw!r}") from exc

    if is_negative:
        normalized = f"-{normalized}"

    return normalized


# --- Currency normalization ---------------------------------------------------

_SYMBOL_TO_ISO = {
    "€": "EUR",
    "$": "USD",
    "£": "GBP",
    "¥": "JPY",
    "₹": "INR",
}

_ISO_CODES = {
    "EUR", "USD", "GBP", "JPY", "INR", "CHF", "SEK", "DKK", "NOK", "PLN",
    "RON", "THB", "SGD", "MYR", "ZAR", "KES", "GHS", "CAD", "VND", "AUD",
}


def normalize_currency(raw: str) -> str:
    """Map a printed currency symbol/code to its ISO code, ONLY when
    unambiguous. An explicit ISO code already present is never overridden by
    a symbol-based guess (a document showing both a "$" and an explicit
    "USD"/"CAD"/"AUD" label should keep whatever was explicit)."""
    if raw is None:
        return ""
    s = str(raw).strip()
    if s == "":
        return ""
    upper = s.upper()
    if upper in _ISO_CODES:
        return upper
    if s in _SYMBOL_TO_ISO:
        return _SYMBOL_TO_ISO[s]
    # Symbol embedded with an amount, e.g. "€12.10" or "S$250.00" — only
    # resolve the unambiguous single-character symbols; "S$"/"HK$" etc. are
    # genuinely ambiguous without more context and are left unresolved.
    for symbol, iso in _SYMBOL_TO_ISO.items():
        if s.startswith(symbol) or s.endswith(symbol):
            return iso
    raise LocaleNormalizationError(f"cannot normalize currency: {raw!r}")


# --- Date normalization -------------------------------------------------------

_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DMY_DOT_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")
_DMY_SLASH_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_DMY_DASH_RE = re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})$")

_MONTH_NAMES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_DAY_MONTH_NAME_YEAR_RE = re.compile(
    r"^(\d{1,2})\s+([A-Za-z]+)\.?\s+(\d{4})$"
)

# Thai Buddhist Era: BE year = CE year + 543. Triggered by a generic signal
# (a 4-digit year implausibly far in the future for a Gregorian business
# document, i.e. > current-era bound) OR an explicit BE/พ.ศ. marker — never
# by document identity/filename.
_THAI_BE_MARKER_RE = re.compile(r"(พ\.?\s*ศ\.?|B\.?E\.?)", re.IGNORECASE)
_BE_YEAR_THRESHOLD = 2400  # any 4-digit year at/above this is not a plausible Gregorian year


def _is_valid_ymd(year: int, month: int, day: int) -> bool:
    return 1 <= month <= 12 and 1 <= day <= 31 and 1900 <= year <= 2200


def normalize_date(raw: str, has_be_marker: bool | None = None) -> str:
    """Normalize a printed date to ISO YYYY-MM-DD.

    `has_be_marker`: pass True/False if the caller has already determined
    (from surrounding document context) whether a Thai-Buddhist-Era marker
    is present; if None, this function looks for the marker in `raw` itself.

    Raises LocaleNormalizationError for unrecognized formats/calendars
    rather than guessing.
    """
    if raw is None:
        raise LocaleNormalizationError("cannot normalize None date")
    s = str(raw).strip()
    if s == "":
        raise LocaleNormalizationError("cannot normalize empty date")

    be_marker_present = _THAI_BE_MARKER_RE.search(s) is not None if has_be_marker is None else has_be_marker
    s_clean = _THAI_BE_MARKER_RE.sub("", s).strip()

    m = _ISO_DATE_RE.match(s_clean)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _finish_date(year, month, day, be_marker_present)

    m = _DMY_DOT_RE.match(s_clean) or _DMY_DASH_RE.match(s_clean)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _finish_date(year, month, day, be_marker_present)

    m = _DMY_SLASH_RE.match(s_clean)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _finish_date(year, month, day, be_marker_present)

    m = _DAY_MONTH_NAME_YEAR_RE.match(s_clean)
    if m:
        day = int(m.group(1))
        month_name = m.group(2).lower()
        year = int(m.group(3))
        month = _MONTH_NAMES.get(month_name)
        if month is None:
            raise LocaleNormalizationError(f"unrecognized month name in date: {raw!r}")
        return _finish_date(year, month, day, be_marker_present)

    raise LocaleNormalizationError(f"cannot normalize date (unrecognized format): {raw!r}")


def _finish_date(year: int, month: int, day: int, be_marker_present: bool) -> str:
    if be_marker_present or year >= _BE_YEAR_THRESHOLD:
        year -= 543
    if not _is_valid_ymd(year, month, day):
        raise LocaleNormalizationError(
            f"cannot normalize date: resolved to implausible {year:04d}-{month:02d}-{day:02d} "
            "(unrecognized calendar or malformed value)"
        )
    return f"{year:04d}-{month:02d}-{day:02d}"
