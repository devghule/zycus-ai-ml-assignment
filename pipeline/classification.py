"""Stage: document classification (Phase 4).

Decides, per segment: PAYABLE_INVOICE / PAYABLE_CREDIT_MEMO / NON_PAYABLE /
AMBIGUOUS_UNSOLVABLE.

Two classification paths are implemented:

1. Deterministic rule-based signal scoring over the segment's page text
   (multi-language regex patterns for invoice identity, priced line items,
   totals/tax, credit-memo vocabulary, and non-payable vocabulary). This is
   the ONLY path exercised against the real corpus in this environment,
   because no LLM SDK/API key is available here.

2. An LLM-based semantic classification interface
   (`classify_via_llm_response`) matching DESIGN.md's LLM-usage design:
   strict structured JSON in, schema-validated, with bounded retries and a
   safe fallback to AMBIGUOUS_UNSOLVABLE on validation failure or exhausted
   retries. This path is NOT live-tested (no API key in this environment) —
   it is only exercised in unit tests via mocked LLM responses.

`classify_segment` is the production entry point run.py uses; it always
takes the deterministic path unless an LLM client is explicitly configured
(none is, in this environment), which is documented rather than silently
assumed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from pipeline.ocr_render import RenderedDocument
from pipeline.segmentation import Segment


class DocumentClass(str, Enum):
    PAYABLE_INVOICE = "PAYABLE_INVOICE"
    PAYABLE_CREDIT_MEMO = "PAYABLE_CREDIT_MEMO"
    NON_PAYABLE = "NON_PAYABLE"
    AMBIGUOUS_UNSOLVABLE = "AMBIGUOUS_UNSOLVABLE"


@dataclass
class Classification:
    doc_class: DocumentClass
    doc_type: str = "unknown"  # human-readable type, e.g. "delivery_note"
    reason: str = ""
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)  # internal audit only, not schema output


# --- Multi-language signal patterns -----------------------------------------
# Positive (payable) signals -------------------------------------------------
_INVOICE_IDENTITY_RE = re.compile(
    r"\b(invoice\s*(no\.?|nr\.?|number|#)|rechnung(s)?\s*nr\.?|arve\s*nr\.?|"
    r"fatura\s*(no\.?|n[uú]mero)?|factura\s*n[uú]mero)\b",
    re.IGNORECASE,
)
_SUPPLIER_BUYER_RE = re.compile(
    r"\b(bill\s*to|sold\s*to|supplier|vendor|remit\s*to|lieferant|rechnungsempf[äa]nger|"
    r"m[uü][uü]ja|ostja|fornecedor)\b",
    re.IGNORECASE,
)
_TOTAL_RE = re.compile(
    r"\b(sub\s*total|subtotal|total\s*due|amount\s*due|grand\s*total|gesamt(betrag)?|"
    r"summa|kokku|total\s*a\s*pagar|valor\s*total)\b",
    re.IGNORECASE,
)
_TAX_RE = re.compile(r"\b(vat|tax|k[äa]ibemaks|mwst|iva|steuer)\b", re.IGNORECASE)
_CURRENCY_AMOUNT_RE = re.compile(
    r"(?:[$€£]|\bEUR\b|\bUSD\b|\bGBP\b)\s*\d[\d.,]*\d|\d[\d.,]*\d\s*(?:[$€£]|\bEUR\b|\bUSD\b|\bGBP\b)"
)
_PAYMENT_TERMS_RE = re.compile(
    r"\b(due\s*date|payment\s*terms?|net\s*\d{1,3}|f[äa]lligkeitsdatum|maksetingimused)\b",
    re.IGNORECASE,
)
_LINE_ITEM_TABLE_RE = re.compile(
    r"\b(qty|quantity|unit\s*price|description|kogus|hind|menge|einzelpreis)\b", re.IGNORECASE
)

# Credit-memo specific signals ------------------------------------------------
# Trailing boundary is a negative lowercase-lookahead rather than a plain
# \b: OCR commonly glues a title-case label directly against the next
# title-case word/number with no space (confirmed — DU-10's own text reads
# "CreditNoteNo.:5900366703"), and a plain \b fails there since both "e"
# and "N" are word characters with no transition between them. Only a
# following LOWERCASE letter is rejected (e.g. a hypothetical unrelated
# "creditnotebook"), matching the same fix already applied to PO/VAT label
# glue elsewhere in this corpus.
_CREDIT_MEMO_RE = re.compile(
    # (?-i:...) locally disables the module-level IGNORECASE flag just for
    # this lookahead: without it, [a-z] under re.IGNORECASE also matches
    # uppercase letters, defeating the whole point (it would then reject
    # "CreditNoteNo." too, since "N" is a letter).
    r"\b(credit\s*note|credit\s*memo|gutschrift|kreeditarve|nota\s*de\s*cr[ée]dito|"
    r"nota\s*credito)(?-i:(?![a-z]))",
    re.IGNORECASE,
)
_REVERSAL_RE = re.compile(
    r"\b(reverses?|cancels?|correction\s*to|referring\s*to\s*invoice|"
    r"in\s*reference\s*to\s*invoice)\b",
    re.IGNORECASE,
)
_NEGATIVE_AMOUNT_RE = re.compile(r"-\s*(?:[$€£]|\bEUR\b|\bUSD\b)?\s*\d[\d.,]*\d|\(\s*\d[\d.,]*\d\s*\)")

# Negative (non-payable) signals ---------------------------------------------
_DELIVERY_WAYBILL_RE = re.compile(
    r"\b(delivery\s*note|packing\s*list|waybill|bill\s*of\s*lading|cmr|lieferschein|"
    r"frachtbrief|saateleht|guia\s*de\s*remessa)\b",
    re.IGNORECASE,
)
_CUSTOMS_RE = re.compile(
    # "customs...invoice" (e.g. "Customs Consolidated Invoice") added
    # alongside "customs declaration" (corpus audit — Combined Improvement
    # Pass: DU-02 is titled exactly this, a customs/logistics bundle, not a
    # genuine supplier AP invoice, but previously carried no non-payable
    # signal at all). Deliberately requires "customs" directly followed by
    # "invoice" (with only "consolidated"/"detailed" allowed between) so it
    # does not fire on an ordinary invoice that merely mentions customs
    # duties/VAT as a line item (e.g. INV-09's "Customs VAT" line, which
    # has no adjacent "invoice" word).
    r"\b(customs\s*declaration|export\s*declaration|zolldeklaration|toll(deklarat)?|"
    r"declara[cç][aã]o\s*de\s*exporta[cç][aã]o|"
    r"customs\s*(?:consolidated|detailed)?\s*invoice)\b",
    re.IGNORECASE,
)
_DUNNING_RE = re.compile(
    r"\b(reminder|dunning|overdue\s*notice|mahnung|zahlungserinnerung|meeldetuletus)\b",
    re.IGNORECASE,
)
_INTERNAL_APPROVAL_RE = re.compile(
    r"\b(purchase\s*requisition|approval\s*request|internal\s*memo|quotation|estimate|"
    r"angebot|kostenvoranschlag|pakkumus)\b",
    re.IGNORECASE,
)
# Internal governance/compliance workflow forms (e.g. a donation/sponsorship
# approval form) are a distinct non-payable class from the above: they can
# still contain a currency amount and even the word "total", so they need
# their own, deliberately NARROW multi-signal detector rather than relying
# on the general invoice-vocabulary conflict check alone. Each individual
# phrase here is specific enough that an ordinary invoice mentioning one of
# them in passing (e.g. "approved by") would not match on its own — the
# override only fires when MULTIPLE distinct phrases co-occur (see
# _governance_workflow_score below), which is what actually distinguishes a
# governance form from an invoice.
_GOVERNANCE_WORKFLOW_RE = re.compile(
    r"\b(donations?\s*and\s*sponsorship|sponsorship\s*(?:and|&)\s*donations?|"
    r"charitable\s*contributions?|compliance\s*risk|requestor|"
    r"group\s*cfo|group\s*ceo|group\s*compliance\s*officer|"
    r"approve\W{0,3}reject|reject\W{0,3}approve)\b",
    re.IGNORECASE,
)
# Minimum number of DISTINCT governance-workflow phrases required before
# this overrides ordinary invoice-like evidence — one phrase alone is not
# enough (keeps this narrow; a real invoice with a single incidental match
# must not be rejected).
_GOVERNANCE_WORKFLOW_MIN_DISTINCT_HITS = 2

# Minimum amount of extracted text (across the segment) needed before we're
# willing to make any positive-or-negative call at all.
_MIN_EVIDENCE_CHARS = 20


def _segment_text(rendered: RenderedDocument, segment: Segment) -> str:
    by_number = {p.page_number: p for p in rendered.pages}
    parts = []
    for n in segment.page_numbers:
        page = by_number.get(n)
        if page is not None and page.text:
            parts.append(page.text)
    return "\n".join(parts)


def _count_hits(pattern: re.Pattern, text: str) -> int:
    return len(pattern.findall(text))


def classify_segment_from_text(text: str, evidence_hint: str = "") -> Classification:
    """Deterministic rule-based classification over raw segment text.

    Kept separate from `classify_segment` so unit tests can feed synthetic
    page-text fixtures directly without constructing full RenderedDocument
    objects.
    """
    stripped = text.strip()
    evidence: list[str] = []

    if len(stripped) < _MIN_EVIDENCE_CHARS:
        return Classification(
            doc_class=DocumentClass.AMBIGUOUS_UNSOLVABLE,
            doc_type="unknown",
            reason="Insufficient extracted text to classify (render failed, empty scan, or no interpretable content).",
            confidence=0.0,
            evidence=["text length below minimum evidence threshold"],
        )

    positive_score = 0
    if _INVOICE_IDENTITY_RE.search(stripped):
        positive_score += 2
        evidence.append("invoice identity pattern")
    if _SUPPLIER_BUYER_RE.search(stripped):
        positive_score += 1
        evidence.append("supplier/buyer block")
    if _TOTAL_RE.search(stripped):
        positive_score += 1
        evidence.append("total/subtotal pattern")
    if _TAX_RE.search(stripped):
        positive_score += 1
        evidence.append("tax/VAT pattern")
    if _CURRENCY_AMOUNT_RE.search(stripped):
        positive_score += 1
        evidence.append("currency amount pattern")
    if _PAYMENT_TERMS_RE.search(stripped):
        positive_score += 1
        evidence.append("payment terms/due date pattern")
    if _LINE_ITEM_TABLE_RE.search(stripped):
        positive_score += 1
        evidence.append("priced line-item table pattern")

    credit_signal = bool(_CREDIT_MEMO_RE.search(stripped))
    if credit_signal:
        evidence.append("credit note/memo vocabulary")
    reversal_signal = bool(_REVERSAL_RE.search(stripped))
    if reversal_signal:
        evidence.append("reversal/correction reference")
    negative_amount_signal = bool(_NEGATIVE_AMOUNT_RE.search(stripped))
    if negative_amount_signal:
        evidence.append("negative-looking amount")

    negative_score = 0
    if _DELIVERY_WAYBILL_RE.search(stripped):
        negative_score += 2
        evidence.append("delivery/waybill vocabulary")
    if _CUSTOMS_RE.search(stripped):
        negative_score += 2
        evidence.append("customs vocabulary")
    if _DUNNING_RE.search(stripped):
        negative_score += 2
        evidence.append("dunning/reminder vocabulary")
    if _INTERNAL_APPROVAL_RE.search(stripped):
        negative_score += 2
        evidence.append("internal approval/quotation vocabulary")

    governance_hits = {m.group(0).lower() for m in _GOVERNANCE_WORKFLOW_RE.finditer(stripped)}
    if len(governance_hits) >= _GOVERNANCE_WORKFLOW_MIN_DISTINCT_HITS:
        evidence.append(f"internal governance/compliance workflow vocabulary ({len(governance_hits)} distinct phrases)")
        # A strong, MULTI-signal governance-workflow match overrides even
        # substantial positive/monetary evidence: this is a fundamentally
        # different document class from an invoice (a currency amount and a
        # "total" label are the exception, not evidence of a commercial
        # transaction, on this class of internal form). Checked before the
        # ordinary positive/negative-score comparisons below so it cannot be
        # outvoted by a bare monetary total.
        return Classification(
            doc_class=DocumentClass.NON_PAYABLE,
            doc_type="internal_approval_form",
            reason="Internal governance/compliance workflow vocabulary (multiple distinct signals) "
            "dominates — this is an internal approval form, not a supplier invoice, regardless of "
            "any currency amount present.",
            confidence=0.85,
            evidence=evidence,
        )

    # Credit memo takes priority when its vocabulary is present alongside
    # payable-ish structure (it IS a payable-adjacent document, just the
    # opposite sign) and there's no stronger non-payable signal drowning it.
    if credit_signal and negative_score == 0 and (positive_score >= 1 or reversal_signal):
        return Classification(
            doc_class=DocumentClass.PAYABLE_CREDIT_MEMO,
            doc_type="credit_memo",
            reason="Credit note/memo vocabulary with supporting structural signals.",
            confidence=0.8,
            evidence=evidence,
        )

    # Conflict: meaningful signals on both sides -> ambiguous rather than a
    # forced guess.
    if positive_score >= 2 and negative_score >= 2:
        return Classification(
            doc_class=DocumentClass.AMBIGUOUS_UNSOLVABLE,
            doc_type="unknown",
            reason="Conflicting payable and non-payable signals; declining to guess.",
            confidence=0.3,
            evidence=evidence,
        )

    if negative_score >= 2 and positive_score < 2:
        return Classification(
            doc_class=DocumentClass.NON_PAYABLE,
            doc_type="non_payable_document",
            reason="Non-payable vocabulary (delivery/customs/dunning/internal) dominates with no strong invoice structure.",
            confidence=0.75,
            evidence=evidence,
        )

    if positive_score >= 3:
        return Classification(
            doc_class=DocumentClass.PAYABLE_INVOICE,
            doc_type="invoice",
            reason="Invoice identity plus supporting structural signals (totals/tax/line items/terms).",
            confidence=min(0.5 + 0.1 * positive_score, 0.95),
            evidence=evidence,
        )

    return Classification(
        doc_class=DocumentClass.AMBIGUOUS_UNSOLVABLE,
        doc_type="unknown",
        reason="Insufficient or too-weak signal to confidently classify.",
        confidence=0.2,
        evidence=evidence,
    )


def classify_segment(rendered: RenderedDocument, segment: Segment) -> Classification:
    """Production entry point: deterministic rule-based classification of a
    segment's pages, drawn from the rendered document's per-page text.

    No LLM client is configured in this environment, so this always takes
    the deterministic path. If an LLM client were wired in, this function
    would be the natural place to gate on its presence (see
    `classify_via_llm_response` below for the validated-response contract
    such a call would need to satisfy).
    """
    text = _segment_text(rendered, segment)
    return classify_segment_from_text(text)


# --- LLM-based classification interface (unverified, no live API key) ------

_VALID_LABELS = {c.value for c in DocumentClass}


class LLMResponseError(Exception):
    """Raised when an LLM response fails schema validation."""


def _validate_llm_response(payload: Any) -> Classification:
    """Validate a raw (already-JSON-decoded) LLM response against the
    strict contract: {"label": ..., "confidence": ..., "evidence": [...]}.
    Raises LLMResponseError on any violation."""
    if not isinstance(payload, dict):
        raise LLMResponseError("response is not a JSON object")

    label = payload.get("label")
    if label not in _VALID_LABELS:
        raise LLMResponseError(f"invalid or missing label: {label!r}")

    confidence = payload.get("confidence")
    if not isinstance(confidence, (int, float)) or not (0.0 <= float(confidence) <= 1.0):
        raise LLMResponseError(f"invalid or missing confidence: {confidence!r}")

    evidence = payload.get("evidence")
    if not isinstance(evidence, list) or not all(isinstance(e, str) for e in evidence):
        raise LLMResponseError(f"invalid or missing evidence list: {evidence!r}")

    return Classification(
        doc_class=DocumentClass(label),
        doc_type=payload.get("doc_type", "unknown"),
        reason=payload.get("reason", "LLM semantic classification"),
        confidence=float(confidence),
        evidence=list(evidence),
    )


def classify_via_llm_response(
    call_llm: Callable[[], Any],
    max_retries: int = 2,
) -> Classification:
    """Bounded-retry wrapper around an LLM call that must return a
    JSON-decodable structured response matching the strict contract.

    `call_llm` is injected so tests can supply a fake/mocked response
    (well-formed or malformed) without any real network/API access. On
    validation failure, retries up to `max_retries` times, then falls back
    to AMBIGUOUS_UNSOLVABLE rather than propagating the error or guessing.

    NOT exercised against a real LLM in this environment: no API key/SDK is
    available here. Only unit-tested via mocked `call_llm` callables.
    """
    last_error: str = "no attempts made"
    for attempt in range(max_retries + 1):
        try:
            raw = call_llm()
            return _validate_llm_response(raw)
        except LLMResponseError as exc:
            last_error = str(exc)
        except Exception as exc:  # noqa: BLE001 - any unexpected failure is also a safe-fallback case
            last_error = f"unexpected error calling LLM: {exc}"

    return Classification(
        doc_class=DocumentClass.AMBIGUOUS_UNSOLVABLE,
        doc_type="unknown",
        reason=f"LLM classification failed validation after {max_retries + 1} attempt(s): {last_error}",
        confidence=0.0,
        evidence=[],
    )
