"""Stage: duplicate detection (Phase 9).

Five evidence layers, strongest first:
  1. exact file hash (byte-identical PDFs)
  2. content hash (normalized-text-identical, survives re-scans/re-saves)
  3. business-key (supplier + invoice_number + invoice_date + currency +
     gross_total, only when EVERY field is actually present — never built
     from missing/fabricated values)
  4. near-duplicate similarity (advisory only)
  5. "copy" indicator (metadata only — never decisive alone)

Locked policy: automatic decline fires ONLY for strong evidence (exact
file, exact content, or a complete business-key match) against an
ALREADY-BOOKED payable from earlier in the same run. A "Copy" label alone,
or near-duplicate similarity alone, is advisory — surfaced internally, never
an automatic decline. The first valid payable in a run always remains
bookable; only a SUBSEQUENT strong duplicate of it is declined, as
DUPLICATE_OF_BOOKED_PAYABLE (an addition to the existing decline taxonomy).

This module never modifies financial amounts or master-data IDs — it only
decides whether a candidate payable should be declined as a duplicate of one
already accepted in this run.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class DuplicateVerdict(str, Enum):
    NONE = "NONE"  # no duplicate evidence at all
    ADVISORY = "ADVISORY"  # near-duplicate and/or bare "copy" label — not auto-declined
    DUPLICATE_OF_BOOKED_PAYABLE = "DUPLICATE_OF_BOOKED_PAYABLE"  # strong evidence -> auto-decline


@dataclass
class DuplicateEvidence:
    file_hash: str = ""
    content_hash: str = ""
    business_key: str = ""  # "" unless every required field was present
    has_copy_indicator: bool = False
    normalized_text: str = ""  # kept for near-duplicate similarity scoring only
    # Kept alongside normalized_text specifically to support the
    # high-confidence near-duplicate promotion below — NOT used to build
    # business_key (which requires the full identity set) or any other
    # existing check. "" means "not extracted", and never matches another
    # "" (see _high_confidence_financial_match below).
    currency: str = ""
    gross_total: str = ""


@dataclass
class DuplicateCheck:
    verdict: DuplicateVerdict = DuplicateVerdict.NONE
    method: str = ""  # "file_hash" | "content_hash" | "business_key" | "near_duplicate" | "copy_indicator"
    matched_against: str = ""  # identifier of the earlier booked document, if any
    reason: str = ""


_COPY_INDICATOR_RE = re.compile(r"\b(copy|duplicate|reprint|copy\s+tax\s+invoice)\b", re.IGNORECASE)

# Near-duplicate similarity threshold — explicit, named constant, not a
# magic number. Deliberately conservative: near-duplicate is ADVISORY ONLY
# regardless of score, so this threshold only controls whether the advisory
# fires, never an auto-decline.
NEAR_DUPLICATE_SIMILARITY_THRESHOLD = 0.92

# High-confidence near-duplicate promotion (Combined Improvement Pass,
# duplicate-resolution investigation): the ordinary near-duplicate check
# above is deliberately advisory-only, because text similarity alone can't
# distinguish "two scans of the same invoice" from "two different invoices
# from the same supplier using the same template." Auto-decline requires
# BOTH near-total textual identity (well above the advisory bar — corpus
# evidence: INV-04 vs INV-07, two independently OCR'd scans of the same
# underlying document, score 0.987; a genuinely different invoice from the
# same template differs in invoice number, date, and amounts, which in
# practice pushes similarity well below this bar) AND an EXACT match on
# both currency and gross_total (both non-empty — matching "" against ""
# proves nothing and is explicitly excluded). This is a conservative
# conjunction of two independent signal families (textual + financial), not
# a lowered similarity threshold and not "same amount alone."
HIGH_CONFIDENCE_NEAR_DUPLICATE_SIMILARITY_THRESHOLD = 0.97


def _exact_nonempty_match(a: str, b: str) -> bool:
    return bool(a) and bool(b) and a.strip() == b.strip()


def _normalize_text_for_hash(text: str) -> str:
    """Collapse whitespace/case so trivial re-scans/re-saves of the same
    document hash identically even if line breaks or spacing differ."""
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def compute_file_hash(file_path: Path) -> str:
    """Deterministic cryptographic hash of the raw file bytes."""
    h = hashlib.sha256()
    with file_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_content_hash(full_text: str) -> str:
    """Hash of normalized text content — catches PDFs that are not
    byte-identical (different metadata, re-saved, re-scanned at a different
    resolution) but carry the same recognized text. Empty text produces an
    empty hash (never a false "duplicate" between two blank/unreadable
    documents that happen to both have no text)."""
    normalized = _normalize_text_for_hash(full_text)
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_business_key(
    supplier_identity: str, invoice_number: str, invoice_date: str, currency: str, gross_total: str
) -> str:
    """A business key is only ever built when EVERY field is genuinely
    present — a partial key (e.g. missing invoice_date) returns "" rather
    than a key built from missing/fabricated values, per the locked
    'no fake duplicate key from missing evidence' rule."""
    fields = [supplier_identity, invoice_number, invoice_date, currency, gross_total]
    if not all(f.strip() for f in fields if f is not None) or any(f is None for f in fields):
        return ""
    normalized = "|".join(f.strip().lower() for f in fields)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def detect_copy_indicator(text: str) -> bool:
    return bool(_COPY_INDICATOR_RE.search(text or ""))


def text_similarity(a: str, b: str) -> float:
    import difflib

    return difflib.SequenceMatcher(None, a, b).ratio()


def build_evidence(
    file_path: Path,
    full_text: str = "",
    supplier_identity: str = "",
    invoice_number: str = "",
    invoice_date: str = "",
    currency: str = "",
    gross_total: str = "",
) -> DuplicateEvidence:
    """Build the full evidence bundle for one document/payable. Any field
    the caller doesn't have (extraction didn't find it) is simply omitted —
    the business_key naturally becomes "" if incomplete, which is correct."""
    return DuplicateEvidence(
        file_hash=compute_file_hash(file_path),
        content_hash=compute_content_hash(full_text),
        business_key=compute_business_key(supplier_identity, invoice_number, invoice_date, currency, gross_total),
        has_copy_indicator=detect_copy_indicator(full_text),
        normalized_text=_normalize_text_for_hash(full_text),
        currency=currency,
        gross_total=gross_total,
    )


@dataclass
class _BookedRecord:
    identifier: str  # e.g. the file name, for diagnostic reference
    evidence: DuplicateEvidence


class DuplicateRegistry:
    """Booking-aware, stateful duplicate detector for one pipeline run.

    Call `check` BEFORE accepting a candidate payable; if the verdict is
    NONE or ADVISORY, the caller may still book it — call `register`
    immediately after booking so later documents can be checked against it.
    A document that is itself declined (not booked) must NOT be registered,
    so it can never cause a false "duplicate of a non-payable" verdict.
    """

    def __init__(self) -> None:
        self._by_file_hash: dict[str, _BookedRecord] = {}
        self._by_content_hash: dict[str, _BookedRecord] = {}
        self._by_business_key: dict[str, _BookedRecord] = {}

    def check(self, identifier: str, evidence: DuplicateEvidence) -> DuplicateCheck:
        # File-hash and content-hash are properties of the whole SOURCE
        # FILE, not of an individual logical segment within it. A single
        # PDF that bundles several distinct payables (e.g. a consolidated
        # customs invoice bundling 10+ sub-invoices — a real corpus pattern,
        # see STEP1_STEP2_ANALYSIS.md) will trivially be "byte-identical to
        # itself" across its own segments; that must never count as evidence
        # of duplication. Only a match against a DIFFERENT identifier
        # (a different source file) is genuine file/content-hash evidence.
        if evidence.file_hash and evidence.file_hash in self._by_file_hash:
            prior = self._by_file_hash[evidence.file_hash]
            if prior.identifier != identifier:
                return DuplicateCheck(
                    verdict=DuplicateVerdict.DUPLICATE_OF_BOOKED_PAYABLE,
                    method="file_hash",
                    matched_against=prior.identifier,
                    reason=f"Byte-identical to already-booked file {prior.identifier!r}.",
                )

        if evidence.content_hash and evidence.content_hash in self._by_content_hash:
            prior = self._by_content_hash[evidence.content_hash]
            if prior.identifier != identifier:
                return DuplicateCheck(
                    verdict=DuplicateVerdict.DUPLICATE_OF_BOOKED_PAYABLE,
                    method="content_hash",
                    matched_against=prior.identifier,
                    reason=f"Content-identical (normalized text) to already-booked document {prior.identifier!r}.",
                )

        if evidence.business_key and evidence.business_key in self._by_business_key:
            prior = self._by_business_key[evidence.business_key]
            return DuplicateCheck(
                verdict=DuplicateVerdict.DUPLICATE_OF_BOOKED_PAYABLE,
                method="business_key",
                matched_against=prior.identifier,
                reason=f"Same supplier+invoice_number+invoice_date+currency+gross_total as "
                f"already-booked document {prior.identifier!r}.",
            )

        # Near-duplicate: advisory only by default (locked policy) — EXCEPT
        # the high-confidence promotion below, which requires independent
        # corroboration from a second signal family (financial fields), not
        # just a higher similarity number. Same same-file exclusion as
        # above: segments from one bundled PDF naturally share boilerplate
        # text and must not be compared against each other here.
        if evidence.normalized_text:
            best_advisory: DuplicateCheck | None = None
            for prior in self._by_content_hash.values():
                if prior.identifier == identifier:
                    continue
                if not prior.evidence.normalized_text:
                    continue
                score = text_similarity(evidence.normalized_text, prior.evidence.normalized_text)
                if score < NEAR_DUPLICATE_SIMILARITY_THRESHOLD:
                    continue

                if (
                    score >= HIGH_CONFIDENCE_NEAR_DUPLICATE_SIMILARITY_THRESHOLD
                    and _exact_nonempty_match(evidence.currency, prior.evidence.currency)
                    and _exact_nonempty_match(evidence.gross_total, prior.evidence.gross_total)
                ):
                    return DuplicateCheck(
                        verdict=DuplicateVerdict.DUPLICATE_OF_BOOKED_PAYABLE,
                        method="high_confidence_near_duplicate",
                        matched_against=prior.identifier,
                        reason=(
                            f"High-confidence duplicate: near-total text similarity "
                            f"(similarity={score:.3f}) AND exact matching currency "
                            f"({evidence.currency}) AND exact matching gross_total "
                            f"({evidence.gross_total}) against already-booked "
                            f"{prior.identifier!r} — independent identity fields "
                            f"(invoice number/date/supplier) were unavailable to build a "
                            f"business-key match, but textual and financial corroboration "
                            f"together are strong enough to auto-decline."
                        ),
                    )

                if best_advisory is None:
                    reason = f"Near-duplicate text (similarity={score:.3f}) of {prior.identifier!r} — advisory only."
                    if evidence.has_copy_indicator:
                        reason += " Also carries a 'copy'-style indicator, but that alone is not sufficient evidence."
                    best_advisory = DuplicateCheck(
                        verdict=DuplicateVerdict.ADVISORY, method="near_duplicate",
                        matched_against=prior.identifier, reason=reason,
                    )
            if best_advisory is not None:
                return best_advisory

        if evidence.has_copy_indicator:
            return DuplicateCheck(
                verdict=DuplicateVerdict.ADVISORY,
                method="copy_indicator",
                reason="Document carries a 'copy'/'duplicate'/'reprint' style label — this alone is "
                "not sufficient evidence to decline (e.g. a legitimate 'Copy Tax Invoice' may still "
                "be a genuine, distinct payable).",
            )

        return DuplicateCheck(verdict=DuplicateVerdict.NONE)

    def register(self, identifier: str, evidence: DuplicateEvidence) -> None:
        """Record a document as booked so later documents are checked
        against it. Only call this for a payable that was ACTUALLY booked
        (passed ERP reconciliation) — never for a declined document."""
        record = _BookedRecord(identifier=identifier, evidence=evidence)
        if evidence.file_hash:
            self._by_file_hash.setdefault(evidence.file_hash, record)
        if evidence.content_hash:
            self._by_content_hash.setdefault(evidence.content_hash, record)
        if evidence.business_key:
            self._by_business_key.setdefault(evidence.business_key, record)
