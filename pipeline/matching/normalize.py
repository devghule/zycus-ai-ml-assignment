"""Shared, explainable normalization helpers for master-data matching.

Every rule here is deliberately simple and named for what it does — no
"clever" fuzzy cleanup that could turn two genuinely different identifiers
into a false exact match. Reused by every matcher in pipeline/matching/ so
normalization logic isn't duplicated per master file.
"""
from __future__ import annotations

import re
import unicodedata


def normalize_whitespace(s: str) -> str:
    """Collapse runs of whitespace to a single space and strip ends."""
    return re.sub(r"\s+", " ", s or "").strip()


def normalize_unicode(s: str) -> str:
    """NFKC-normalize so visually-identical characters compare equal
    (e.g. full-width vs half-width digits), without deleting anything."""
    return unicodedata.normalize("NFKC", s or "")


def normalize_case(s: str) -> str:
    return (s or "").casefold()


def normalize_name(s: str) -> str:
    """Normalize a company/supplier name for exact comparison: unicode
    form, case, whitespace, and safe punctuation (commas/periods only —
    never deletes letters, digits, or distinguishing marks like hyphens
    inside a name)."""
    s = normalize_unicode(s or "")
    s = s.replace(",", " ").replace(".", " ")
    s = normalize_whitespace(s)
    return normalize_case(s)


def normalize_vat_id(s: str) -> str:
    """Normalize a VAT/tax-registration number: unicode form, uppercase,
    and removal of spaces/dashes (VAT numbers are commonly printed with
    inconsistent spacing, e.g. "DE 209 177 122" vs "DE209177122", but the
    underlying identifier is the same digit/letter sequence)."""
    s = normalize_unicode(s or "")
    s = re.sub(r"[\s\-]", "", s)
    return s.upper()


def normalize_po_number(s: str) -> str:
    """Normalize a PO number for EXACT comparison only: unicode form,
    whitespace, and case. No character deletion beyond whitespace collapse
    — PO numbers are identifiers, not free text, so punctuation inside them
    (dashes, slashes) is meaningful and preserved."""
    s = normalize_unicode(s or "")
    s = normalize_whitespace(s)
    return s.upper()


def normalize_payment_term_text(s: str) -> str:
    """Normalize free-text payment-term wording for exact-alias comparison
    (e.g. "Net 30" / "30 days" / "30 days net" are handled by having each
    as a distinct alias in the master data — this function only normalizes
    case/whitespace/punctuation so trivial variants of the SAME alias match,
    it does not itself decide that two different wordings are equivalent)."""
    s = normalize_unicode(s or "")
    s = s.replace(".", "")
    s = normalize_whitespace(s)
    return normalize_case(s)


def normalize_country(s: str) -> str:
    """Normalize a country to its upper-case form for comparison. Expects
    an ISO-2-ish code or a code-like token; does not attempt free-text
    country-name resolution (e.g. "Germany" -> "DE") since that would be a
    fuzzy inference this module deliberately does not perform."""
    return normalize_unicode(s or "").strip().upper()


def name_similarity(a: str, b: str) -> float:
    """A simple, explainable similarity score in [0, 1] between two
    already-normalized names, using stdlib difflib (no extra dependency)."""
    import difflib

    return difflib.SequenceMatcher(None, a, b).ratio()
