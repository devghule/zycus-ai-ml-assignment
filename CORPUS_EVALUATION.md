# Corpus Evaluation Report

Internal engineering/evaluation artifact — does not replace the required
`output/*.json` files, which remain the actual deliverable.

## Methodology

Every number in this report comes from running the actual system
(`.venv/Scripts/python.exe run.py`) over the real, complete `documents/`
corpus (42 PDFs, discovered dynamically — never assumed or hardcoded) and
inspecting its own `output/*.json` files afterward. No ground-truth labels
were supplied with this assignment, and none are invented here: every
"correct"/"grounded"/"reconciled" claim below is verified programmatically
against `erp.py`, `master_data/`, `AUTODRAFT_SCHEMA.md`, or the source
document text itself — never against an assumed right answer. Two
independent, clean, back-to-back runs (`output_determinism_1/` and
`output_determinism_2/`) were diffed and are **byte-for-byte identical**
(`diff -rq` reports no differences) — the results below reflect a fully
deterministic system, not one run's luck.

`erp.py` checksum, verified unchanged across this and every prior phase:
`dd86616512f2fd0dd55ef47c3c10bac8`.

This report distinguishes three kinds of statement throughout:
- **Observed** — a fact directly measured from a real run.
- **Engineering limitation** — a boundary of the current implementation,
  traced to a specific cause (see each section's "Interpretation").
- **Future improvement** — a change that would plausibly help but has not
  been built (see Section "Future Improvements" in `SOLUTION_README.md`).

## Headline numbers

| Metric | Value |
|---|---|
| Documents discovered | 42 (dynamic, never hardcoded) |
| Payables booked | 8 |
| — of which credit memos | 1 (`DU-11.pdf`) |
| Declined | 39 |
| Duplicate declines | 0 |
| Master-data matches (of 8 payables) | supplier 0, BU 0, tax 0, payment-term 0, PO 0 |
| Full-suite tests | 239 unit + 13 integration/corpus = 252 (all passing at time of writing) |
| Two-run determinism | **Identical** (diff -rq: no differences) |

## Per-document disposition (Part E)

Every one of the 42 source PDFs produced exactly one or more logical-document
dispositions (segmentation may split a PDF into multiple logical documents —
none observed a genuine split on this corpus's mostly-scanned pages, since
segmentation's structural signals need embedded/OCR text that most pages
lack; DU-02's 10+ bundled sub-invoices are a documented exception discussed
under Duplicate Detection below and in `IMPLEMENTATION_PROGRESS.md`).

### Bookable payables (8)

| Source PDF | Invoice type | Gross | Currency | Invoice # (as extracted) | ERP reconciliation |
|---|---|---|---|---|---|
| DU-03.pdf | INVOICE | 1040.06 | USD | *(blank)* | exact match |
| DU-09.pdf | INVOICE | 1995.00 | USD | *(blank)* | exact match |
| DU-11.pdf | CREDIT_MEMO | 400.00 | EUR | *(blank)* | exact match |
| INV-09.pdf | INVOICE | 37767.32 | EUR | "Invoice" *(noisy — see Known Limitations)* | exact match |
| INV-11.pdf | INVOICE | 83.21 | EUR | "Invoice" *(noisy)* | exact match |
| INV-14.pdf | INVOICE | 29253.72 | GBP | "Parnumnt117" *(noisy — an address fragment, not a real invoice number)* | exact match |
| INV-15.pdf | INVOICE | 29253.72 | GBP | "Parnumnt117" *(noisy, same cause as INV-14)* | exact match |
| INV-27.pdf | INVOICE | 70654.30 | KES | *(blank)* | exact match |

All 8 passed every Phase 10 gate: schema-valid, grounded (gross total
verified present in the source OCR/embedded text under some plausible
printed form), classification-consistent, financially consistent, and
exactly `erp.py`-reconciled (Decimal-exact, no tolerance). Master-data
fields are honestly blank on all 8 — no supplier/VAT/buyer-country/PO
evidence was extractable from these documents' OCR text with sufficient
confidence to attempt a match (see Master-Data Audit below).

### Declined (39) — see Decline Analysis (Part F) below for the full breakdown.

## Decline analysis (Part F)

| Category | Count | % of declines | Primary cause |
|---|---|---|---|
| Insufficient/too-weak classification signal | 14 | 35.9% | Scanned page with zero or near-zero embedded/OCR text — no OCR engine limitation beyond what RapidOCR could recognize on that specific scan quality |
| INSUFFICIENT_EVIDENCE (Phase 10 gate) | 13 | 33.3% | Overwhelmingly a missing `currency` field — text was classified as payable and a gross total was found, but no ISO currency code or unambiguous symbol (€/£) was recognizable in the extracted text |
| Unbuildable financial facts | 7 | 17.9% | Classified as payable, but no normalizable stated-gross-total pattern found (e.g. no clearly labeled/inferable total in the available text) |
| Conflicting classification signals | 4 | 10.3% | Both payable-like and non-payable-like vocabulary detected on the same page (e.g. a bundled customs+invoice page) — correctly declined as ambiguous rather than guessed |
| Non-payable document | 1 | 2.6% | Delivery/customs/dunning/internal-approval vocabulary dominated with no strong invoice structure |
| Duplicate of booked payable | 0 | 0% | The DU-02 false-positive bug (Phase 9) is fixed and re-verified with a clean run — zero duplicate declines on the real corpus |
| ERP mismatch / irreconcilable | 0 (visible in this run) | — | No candidate reached the ERP gate and failed it in this run; irreconcilable candidates are declined upstream in Phase 7's `build_canonical_payable` before ever reaching a document-level decline, and are exercised directly in `tests/unit/test_financial_model.py`'s irreconcilable-case tests |
| Unsupported/ambiguous format | 0 (visible in this run) | — | No document in this run hit a locale/calendar Phase 6 couldn't parse; the fail-safe path is unit-tested (`test_locale_normalize.py`) |

**Interpretation, not invented ground truth**: the two largest categories
(insufficient classification signal, insufficient corroborating evidence)
both trace to the same root cause — **OCR text quality/coverage on this
specific scanned corpus**, not a defect in classification or validation
logic. `STEP1_STEP2_ANALYSIS.md` independently confirms ~88% of the corpus
is pure scans; RapidOCR (this environment's only available OCR engine)
recognizes text on some of those pages well enough to extract a total, but
not always well enough to also surface a currency code, invoice number, or
supplier identity on the same page.

## Payable quality audit (Part G)

| # | Check | Result across all 8 payables |
|---|---|---|
| 1 | Invoice/credit-memo identity | All 8 have an explicit `invoice_type` (7 INVOICE, 1 CREDIT_MEMO), set from classification evidence, never guessed |
| 2 | Supplier evidence | 0/8 have a resolved `supplier_id` (see Master-Data Audit) — `supplier.name`/`vat_id` are blank on all 8 except INV-11, which has a noisy partial capture flagged below |
| 3 | Buyer evidence | 0/8 have `business_unit_code` — no buyer-country evidence was ever extracted from this corpus's text |
| 4 | Document date | Present-but-frequently-blank; not required by the Phase 10 gate (optional field) |
| 5 | Currency | 8/8 present (EUR/USD/GBP/KES) — a hard gate, verified |
| 6 | Financial total | 8/8 grounded — verified present in raw text under a plausible printed form |
| 7 | Financial model construction | 8/8 built via `pipeline.financial_model.build_canonical_payable` |
| 8 | Exact ERP reconciliation | 8/8 exact (Decimal-equal, no tolerance) — verified via `pipeline.erp_validate.reconciles_exactly` against the unmodified `erp.py` |
| 9 | Master-data validity | 8/8 pass trivially (every ID is blank, and blank always passes — no invalid ID was ever emitted) |
| 10 | Duplicate status | 8/8 NONE (no duplicate evidence) |
| 11 | Schema validity | 8/8 pass `pipeline.validation.check_schema` |
| 12 | Groundedness | 8/8 pass `pipeline.validation.check_groundedness` |

**Flagged for manual review, not silently accepted as clean**: INV-09,
INV-11, INV-14, INV-15's `invoice_number` field contains OCR-layout noise
("Invoice", "Parnumnt117") rather than a genuine invoice number — this is
grounded (groundedness only checks the field's value actually appears in
the source text, which it does, since it WAS extracted from that text) but
not a MEANINGFUL invoice number. This is a real, honestly-reported
extraction-quality limitation, not a validation-logic gap — see Part J
below and "Known Limitations."

## ERP reconciliation audit (Part H)

Every payable's document-stated gross was checked for **exact** equality
(`Decimal(erp_computed) == Decimal(document_stated)`), never
`abs(a - b) < tolerance`. All 8 payables reconcile exactly. A deliberate
one-cent-mismatch fixture is unit-tested
(`tests/unit/test_validation.py::test_one_cent_mismatch_declines` and
`tests/unit/test_financial_model.py::test_irreconcilable_case_returns_no_payload`)
and confirmed declined, not passed with rounding.

## Master-data audit (Part I)

Traced the evidence chain for a representative case (INV-27.pdf, a Kenyan
logistics invoice that DOES book — gross 70654.30 KES):

```
PDF page (scanned, no embedded text)
  -> RapidOCR recognized text (contains "Total Due: KES 70654.30" and other
     lines, but the supplier/buyer identity blocks did not OCR cleanly
     enough to match the extractor's label patterns — verified by
     inspecting the raw OCR text directly)
  -> extraction.py's _SUPPLIER_LABEL_RE / _VAT_ID_RE found no match
  -> supplier_name = "", supplier_vat_id = "" (honest, not a bug)
  -> MasterDataMatcher.match_supplier(name="", vat_id="") -> UNMATCHED
     (correctly: no evidence was ever offered to match against)
  -> supplier.supplier_id stays "" in the final payload
```

**Conclusion**: the 0% real-corpus master-data match rate traces to
**extraction quality on this scanned corpus's OCR output**, category (2) of
the five possible causes in the Phase 11 brief — NOT genuinely-absent
master-data records (the 14 sample suppliers, 34 tax codes, etc. are real
and matchable, as proven by 37 dedicated unit tests using realistic
evidence), NOT a normalization defect (Phase 6 is separately, thoroughly
tested), and NOT Phase 8 matching logic being too strict (it correctly
matches when given real evidence). Phase 8's matching was deliberately
**not loosened** to inflate this percentage, per the explicit instruction.

## Extraction quality audit & improvements made this phase (Part J)

- **Currency**: extended the ISO-code allowlist (added AUD, CAD, SEK, NOK,
  RON, VND, INR, JPY) and added an unambiguous-symbol fallback (€→EUR,
  £→GBP only — deliberately excluding "$" since it's shared by
  USD/SGD/AUD/CAD/... and guessing would violate the "never guess an
  ambiguous symbol" rule). Currency is still never inferred from supplier
  country. 4 new regression tests.
- **Invoice number false positives — a real bug found and fixed**: the
  extraction regex's field-label suffix (No./Nr./Number/#) was optional,
  so a bare "INVOICE" title immediately followed by an unrelated field
  (e.g. "Date:") would wrongly capture that field's value as the invoice
  number — confirmed on real corpus output ("Date", "INVOICE", Estonian
  "kokku"/"Kuupäev" were all being captured). Fixed by making the
  label-indicator suffix required. 4 regression tests added. A residual,
  smaller-scale version of this noise remains on 4 payables (see Known
  Limitations) — traced to OCR line-layout artifacts specific to those
  pages' scan quality, not the same structural regex flaw, and not chased
  further to avoid speculative, unverifiable regex tuning against noise
  patterns with no other example to generalize from.
- **Supplier/buyer, totals, PO, payment terms**: inspected but no
  additional SAFE, GENERIC improvement was obvious this phase beyond what
  Phase 5's upgrade already added — the remaining gap is OCR text quality
  itself (garbled/incomplete recognition of identity blocks), not a
  pattern-matching gap. Per the brief, full SKU/line-item table extraction
  was explicitly out of scope for this phase.

## Repository cleanliness (Part O)

- No secrets, API keys, or `.env` files found (checked explicitly).
- `.venv/` (341MB) and `.cache/` (40MB, regenerable rendered-page images)
  now excluded via a new `.gitignore` — never committed.
- `output_determinism_1/` and `output_determinism_2/` (this phase's
  determinism-check snapshots) are development scratch artifacts, also
  gitignored — not deliverables. `output/` itself is intentionally NOT
  ignored (`output/*.json` is a required submission per the brief).
- No machine-specific absolute paths are hardcoded in source (all paths
  resolve via `pathlib`/`config.py` relative to the project root).

## Representative difficult cases

`STEP1_STEP2_ANALYSIS.md` (an earlier forensic pass over this corpus)
identified several documents as structurally hard. Their actual disposition
in the final run, with no document-specific handling anywhere in the
pipeline:

| Document | Why it's hard (per prior analysis) | Actual disposition this run |
|---|---|---|
| HLD-01.pdf | Thai management-fee/tax-base/withholding chain | Declined: insufficient/too-weak classification signal (OCR text on this scan didn't clear the classifier's evidence threshold) |
| HLD-03.pdf | Genuinely illegible supplier/buyer identity | Declined: insufficient/too-weak classification signal |
| HLD-05.pdf | Multiple tax rates on one document | Declined: insufficient/too-weak classification signal |
| HLD-08.pdf | Three-way entity-name conflation | Declined: classified as payable, but no normalizable stated gross total was found |
| INV-23.pdf | Two conflicting totals (estimate vs. duty calculator) | Declined: conflicting payable/non-payable signals — correctly refused to guess |

None of these were forced into a payable, and none required document-specific
logic to handle correctly — each was declined by the same general
classification/extraction/financial-model machinery every other document
goes through. This is the intended behavior: a document the system cannot
safely interpret should be declined, not guessed.

## Interpretation of results

**Observed**: the pipeline is deterministic, every payable it produces
reconciles exactly against `erp.py`, no duplicate false positives occur, no
invalid master-data ID is ever emitted, and every documented hard case is
declined rather than forced.

**Engineering limitations** (traced, not assumed): payable yield and
master-data match coverage are both bounded by RapidOCR's recognition
quality on this specific scanned corpus — confirmed by tracing a
representative document's evidence chain (Master-Data Audit, above) rather
than inferred. Per-SKU line-item extraction is architecturally out of scope
for the current text-pattern extractor.

**Future improvements** (not implemented, listed for completeness): a
vision-capable extractor would very likely raise both payable yield and
master-data match coverage simultaneously, since both are downstream of the
same OCR/extraction evidence bottleneck — see `SOLUTION_README.md`'s Future
Improvements section.
