# Zycus "The Bookable Payable" — Assignment Analysis

Prepared as a pre-coding deep-dive of the candidate kit. No solution code was written or modified; all files in this kit are read-only source material. This document and its companion `ZYCUS_ASSIGNMENT_QUICK_SUMMARY.md` are the only two files added.

---

## 1. Executive Summary

This is **not** a document-extraction/OCR exercise, despite appearances. The brief (`README.md`) states this explicitly and repeatedly. The actual task is a **judgment and modeling problem**: given a scanned supplier document (PDF, mostly image-only), decide (a) whether it represents money owed at all, (b) how many distinct payables it contains, and (c) how to decompose its structure — lines, taxes, discounts, charges — into raw components such that an external, fixed recompute engine (`erp.py`) arrives at the exact gross the document states, **while also preserving the document's own structural placement of each tax and charge** (line-level vs. header-level). Matching the total is necessary but explicitly declared **not sufficient**; the grader also inspects structural fidelity and the legitimacy of every emitted master-data code.

The dataset is deliberately messy and adversarial in a specific way: documents include invoices, credit memos (negative-total documents that must be resubmitted as positive `CREDIT_MEMO` records), a delivery note with no monetary content, a compliance/sponsorship approval form with no invoice content at all, customs/consolidated-shipment documents, and heavily degraded/overlapping scans. **Every PDF is unlabeled** — the `DU-`/`HLD-`/`INV-` filename prefixes carry no guaranteed semantic meaning and must not be relied upon for classification logic (confirmed both by the brief's explicit statement and by direct inspection: an `HLD-` file and a `DU-` file were both found to be ordinary tax invoices, while another `DU-` file is a delivery note and another is an internal donations-approval form with zero financial data).

Grading has two tiers: an **open set** (visible, self-checkable via `erp.py`) and a **held-back set** (unseen, decisive for final score), and the reported meta-metric is the **gap between open-set and held-back performance** — a large gap signals overfitting/special-casing rather than genuine generalization. The brief explicitly warns against building a "growing list of special cases."

Deliverables are a runnable system (one command, stdlib-agnostic stack choice) that writes `output/<file>.json` per input PDF, the actual `output/*.json` results for the open documents, and a `DESIGN.md` (≤3 pages) answering three specific reflective questions — including identifying at least one document that cannot honestly be solved and explaining why.

---

## 2. Complete File/Folder Inventory

| Path | Type | Size | Purpose | Mandatory/Optional/Reference |
|---|---|---|---|---|
| `README.md` | Markdown | ~6.9 KB | The assignment brief: mandate, materials, grading, constraints | Mandatory — read first |
| `AUTODRAFT_SCHEMA.md` | Markdown | ~4.6 KB | Exact JSON schema for a payable + per-file output wrapper | Mandatory — defines output contract |
| `erp.py` | Python 3.10+, stdlib only | ~4.3 KB | The fixed "oracle" recompute engine (`erp_book`) that turns raw components into the gross the ERP will book | Mandatory — sealed, must be imported/called, never edited |
| `example_check.py` | Python | ~0.8 KB | Minimal usage example calling `erp_book` on a payable JSON | Reference — shows the one call needed, not a grading script itself |
| `sample_autodraft.json` | JSON | ~1.4 KB | One fully worked example payable (a 2-line German services invoice under reverse-charge VAT) | Reference — shape example only, not a template to copy blindly |
| `documents/` | Folder of 35 PDFs | 11 KB – 2.9 MB each | The actual input corpus — real supplier documents, mostly scanned page images | Mandatory input |
| `documents/DU-*.pdf` | 9 files (DU-02,03,05,05s,06,08,09,10,11) | 87 KB – 2.9 MB | Mixed: at least one delivery note (no financial content), at least one credit memo, at least one ordinary invoice, a customs consolidated invoice, and an internal donations/sponsorship approval form (not a payable at all) | Input — heterogeneous, do not assume prefix meaning |
| `documents/HLD-*.pdf` | 5 files (HLD-01,03,05,08,10) | 105 KB – 227 KB | Mixed: ordinary tax invoices observed (Thai invoice with management fee/VAT/withholding; South African tax invoice) — no evidence of a distinct "held" semantic | Input — heterogeneous |
| `documents/INV-*.pdf` | 21 files | 11 KB – 1.24 MB | Mixed: several are real embedded-text PDFs (not scans) — US utility/vendor invoices (PECO, AmeriHealth Caritas, Oracle America), an Australian serviced-office invoice, a Thai staffing invoice, and more | Input — the only files with a native text layer in the corpus |
| `master_data/README.md` | Markdown | ~1.1 KB | Explains the 5 master files, resolution semantics, and the explicit **scale warning** (samples here are a handful of rows; production masters run to hundreds of thousands/millions) | Mandatory — governs matching-design requirements |
| `master_data/suppliers.json` | JSON | ~2.1 KB | 14 sample supplier records: `supplier_id`, `name`, `vat_id`, `country`, `email`, `address`, `bank_iban` | Reference data to match against |
| `master_data/chart_of_books.json` | JSON | ~1.6 KB | Buyer/tenant org structure: one company (`BOLTGROUP`) → 6 business units (Estonia×2, Ghana, Malaysia, South Africa, UK) → one location each | Reference data to match against |
| `master_data/tax_master.json` | JSON | ~4.6 KB | 32 sample tax codes across ~16 countries/regimes (VAT, IVA, SST, GST, MOMS, HST, NHIL, GETFL, COVID levy, CST, WHT, USE, NP) | Reference data to match against |
| `master_data/payment_terms.json` | JSON | ~1.5 KB | 10 payment-term codes with `days` and free-text `text_aliases` for matching | Reference data to match against |
| `master_data/po_master.json` | JSON | ~0.9 KB | 2 sample purchase orders with lines, tied to specific supplier_ids and currencies | Reference data to match against |
| `.pytest_cache/` | Build artifact | — | Empty pytest cache shell (no actual test files found) | Ignore |
| `.DS_Store` | macOS artifact | — | Finder metadata | Ignore |
| (outer) `__MACOSX/` | Zip artifact | — | macOS zip resource-fork junk | Ignore — explicitly excluded by the task instructions |

**Document count verified:** 35 PDFs total — 9 `DU-`, 5 `HLD-`, 21 `INV-`. No PDF filename encodes a document type; several PDFs' visible content contradicts what a naive read of the prefix would suggest.

**Text-layer finding (important, not stated anywhere in the docs — established here by direct inspection):** Of the 35 PDFs, 29 have **zero extractable text** (page-image scans at ~1240×1754 px, i.e., ~150 DPI A4 JPEGs embedded as a single full-page image per page) and **require OCR or a vision-capable model** to read. Six PDFs (`INV-31, INV-32, INV-34, INV-35, INV-36, INV-37`) carry a native PDF text layer and can be parsed directly (though `INV-35` yields only 20 characters — effectively still image-based with a token artifact). This is the concrete evidence behind the brief's "mostly page images... OCR/vision/LLM is up to you" statement, and it means the pipeline must support **both** a text-extraction path and an OCR/vision path, or normalize everything through vision.

---

## 3. Assignment Problem Statement (from README.md, quoted/paraphrased precisely)

> "Given a supplier document as a PDF, produce structured **autodrafts** — the records a downstream accounting system (the *ERP*) uses to book what is owed."

> "For each PDF, your system must decide **what the document is** and **what, if anything, is owed**, and emit one record per bookable payable. A single PDF may contain **no** payable, **one**, or **several** — and may include pages that are not payables at all."

> "Where a value has a master-data entry — supplier, tax, buyer org, payment term, PO — resolve it against `master_data/` and set the corresponding code in the autodraft; leave that code blank only when there is genuinely no match."

> On correctness: "A payable is correct when the ERP's own recomputation — **from the parts you supplied** — arrives at what the document genuinely says is owed, to the cent... Note too: the ERP can reach the right gross by the wrong path. Two different structures can foot to the same number, and only one of them is the payable that should be booked."

> On structural fidelity: "**Your autodraft must mirror the document's structure, not just its total.**" — placement of taxes (line vs. header) is graded independently of the arithmetic outcome.

> The closing warning (read literally as instructed): "The obvious approach — read the fields, fill the record — will book perhaps a third of these, and then stall... There is no list of special cases to implement... Past that stall there is a shift in how you picture *what one of these documents actually is*... We are not going to tell you what that shift is. Arriving at it, unaided, is the exam."

This last paragraph is the single most important sentence in the whole kit for planning purposes: it tells the candidate directly that a document-by-document, rule-by-rule strategy is a known failure mode the exercise is designed to induce, and that whatever generalizes must come from a single unifying model of "what a payable is," not from enumerating cases.

---

## 4. Exact Functional Requirements (individually numbered)

1. Ingest every PDF in `documents/` (one input folder, run over all files with a single command).
2. For each PDF, determine whether it is or contains any "bookable payable" at all.
3. For each PDF that contains one or more payables, extract/derive **0..N** payable records (a document may yield zero, one, or multiple payable records).
4. For content within a PDF judged **not** a payable, emit a `declined` entry with `doc_type` and `reason`, rather than omitting it or forcing it into `payables`.
5. For each payable, populate the full `AUTODRAFT_SCHEMA.md` record: header identity fields (`invoice_number`, `invoice_date`, `due_date`, `invoice_type`, `currency`), `supplier{}`, `buyer{}`, `payment_term_id`, `po_number`/`po_id`, top-level totals as printed (`gross_total`, `subtotal`, `total_tax_amount`), header-level charges/discount fields, header `taxes[]`, and `line_items[]` with per-line raw components and optional per-line `taxes[]`.
6. Submit **raw components only** (quantities, unit prices, discounts, per-line/header tax rates or amounts, charges) — never pre-compute or submit ERP-derived totals (net-of-tax lines, computed subtotal, computed gross) as if they were inputs; `erp.py` derives those from the raw parts.
7. Place each tax exactly where the document places it: a tax charged per-line goes in that line's `taxes[]` (or `tax_rate`/`tax_amount`); a tax stated once at the header goes in the header `taxes[]`. Do not migrate or collapse across levels even if arithmetically equivalent.
8. Represent each tax with correct `tax_name`, `tax_rate`, and `tax_amount` as printed; do not blend multiple line-level rates into one header rate, and do not split a single header rate into fabricated per-line entries.
9. Keep components decomposed: quantities, unit prices, discounts (`discount` amount vs. `discount_percentage`), charges (freight/insurance/extra/excise), and levies must go in their own dedicated fields, not pre-summed or folded together.
10. For every field with a master-data counterpart (`supplier.supplier_id`, `buyer.company_code`/`business_unit_code`/`location_code`, `taxes[].tax_type_code`, `payment_term_id`, `po_id`), attempt resolution against the corresponding `master_data/*.json` file and set the matched code; leave the field `""` (empty string) when there is no genuine match — never fabricate/guess a code.
11. Keep the raw, as-printed value in its own field regardless of match outcome (e.g., `supplier.name`, `po_number`, `taxes[].tax_name`/`tax_rate` always carry what the document says; the `_id`/`_code` fields carry only the matched key or blank).
12. Represent a credit memo using the **same schema/keys** as an invoice, with `invoice_type: "CREDIT_MEMO"`, and with all monetary figures expressed as **positive magnitudes** even though the source document may show negative figures (confirmed present in the corpus — see §9).
13. Every numeric value emitted must literally appear on the source document — no value may be invented merely to make a total balance ("every value you emit must appear on the document").
14. Every master-data code emitted must be a genuine match; "no match" (empty string) is an explicitly sanctioned, correct answer — a fabricated code is explicitly called out as a scoring failure mode.
15. Any "correction" the system applies to a document's apparent values must be justified by an independent, verifiable fact — not applied speculatively or defensively, because a wrongly-applied "fix" is penalized more heavily than making no fix at all (documents are stated to exist that are "built to look like they need a fix they do not").
16. Produce output as one JSON file per input PDF at `output/<same-basename>.json`, using the exact per-file wrapper shape (`file`, `payables[]`, `declined[]`).
17. Create the `output/` directory if it does not already exist.
18. Ship the system as one command (script or Dockerfile) that runs over an arbitrary folder of PDFs and produces this output — the brief states graders "will re-run it," implying it must be reproducible in a clean environment without candidate-specific setup steps beyond what's documented.
19. Provide a `README` (candidate's own, distinct from the kit's `README.md`) documenting that single command.
20. Submit the working system, the generated `output/*.json` for the open documents, and `DESIGN.md`.
21. `DESIGN.md` must be ≤3 pages and must explicitly answer: (a) what was understood about the documents by the end that wasn't understood on day one; (b) what the system does, concretely, when it meets a document unlike any it has seen, and why that behavior generalizes rather than guesses; (c) identify at least one document in the set that could **not** be solved the way the others were, name which one, and explain how that was determined.
22. Do not modify `erp.py`'s core computation — it may be imported, wrapped, or reimplemented for speed, but its recompute logic must remain behaviorally identical, because grading uses the original, unmodified `erp.py`.

---

## 5. Technical Requirements

**Mandatory (explicit in the brief):**
- Any tech stack ("any stack") for the candidate's own system.
- `erp.py` itself must run standalone on Python 3.10+, stdlib only — but this constraint is about the *provided* oracle, not necessarily the candidate's whole pipeline (candidate code may use any language/libraries as long as it can still `import`/call or faithfully reimplement `erp_book`'s logic if not using Python).
- One documented command runs the whole pipeline over a folder of PDFs → `output/*.json`.
- Output JSON must conform exactly to `AUTODRAFT_SCHEMA.md`'s field names, nesting, and string-typed dot-decimal numeric convention (e.g., `"438.00"`, not `438.00` as a JSON number — the sample and schema consistently quote all monetary/rate/quantity values as strings).
- Master-data matching must be designed to scale to hundreds of thousands/millions of rows (explicit non-functional requirement) — i.e., not "load all rows and Python-loop `==` compare with fuzzy string distance over the whole set" as the assumed final design, though it's fine for a 14-row demo.

**Recommended (strongly implied, not phrased as a hard requirement):**
- A document classification/triage step that runs before or alongside extraction, given documents may be non-payables, multi-payable, or credit memos.
- Use of OCR or a vision-capable LLM for the 29/35 image-only PDFs; a text-extraction fallback for the 6 PDFs with a native text layer.
- A "confidence gate" architecture so uncertain matches/corrections default to leaving fields blank rather than guessing (this follows directly from Rule 2 and Rule 3 in the README).
- Self-checking each produced payable against `erp.py`'s `will_book_gross` compared to the document's stated gross before finalizing output, since the oracle is provided specifically to let candidates iterate.

**Optional / candidate's choice:**
- Docker packaging vs. a plain script.
- Any OCR/vision provider or local model.
- Any matching algorithm for master-data resolution (blocking/indexing strategy, fuzzy matching thresholds, embeddings, etc.) — "how strictly, and on which fields, is your call."
- Any internal intermediate representation between OCR output and the final schema.

**My inference (labeled):**
- **LIKELY EXPECTATION / INFERENCE:** Given the "scale to millions of masters" requirement paired with only 14/6/32/10/2 sample rows respectively, graders likely check the *design* of the matching approach (e.g., indexed lookup by normalized VAT ID/name/country rather than full fuzzy scan) via `DESIGN.md` and/or code review, not via an actual million-row runtime test — since no such larger dataset ships in the kit.
- **LIKELY EXPECTATION / INFERENCE:** Given `erp.py` is explicitly "the same recompute we grade with," a large part of automated grading is almost certainly: parse candidate's `output/*.json`, run each payable through the shipped `erp_book`, and diff `will_book_gross`/`currency` against a ground-truth "what the document says is owed" value the graders hold internally — combined with a structural/placement check and a master-data-code legitimacy check that a black-box gross comparison cannot see (this is stated outright: "a check of what the oracle cannot see — that your codes are real and every value is grounded in the document").

---

## 6. Input Requirements

**From `erp.py`:**
- Exposes `erp_book(payable: dict) -> {"will_book_gross": float, "currency": str}` plus helper functions `num()` (locale-tolerant numeric parsing, strips currency symbols/`%`, returns `0.0` on failure) and `round2()` (Decimal-based half-up rounding to 2dp).
- Computation order, read directly from source:
  1. For each line item: `_line_base()` = `quantity × unit_price`, reduced by `discount_percentage` (if present, takes precedence) or by an absolute `discount` (spread per-unit: `unit_price − discount/|quantity|`, then re-multiplied by quantity) — rounded to 2dp.
  2. `_line_taxes()`: sums each line's `taxes[]` (or synthesizes a single one from `tax_rate`/`tax_amount` if `taxes[]` is empty but either field is populated); each tax is either an explicit `tax_amount` or, if zero, derived as `base × rate/100` (rounded); amounts may be negative (withholding).
  3. Sum all line bases → `item_discounted_total`; sum all line taxes → `line_tax_total`.
  4. `header_discount` = `abs(discount_amount)`; `net_base` = `item_discounted_total − header_discount`.
  5. `_header_taxes()`: same logic as line taxes but applied against `net_base`.
  6. `other_charges` = sum of `freight_charges + insurance_charges + extra_charges + excise_duties` (each independently parsed via `num()`, no sign-stripping — so a negative charge value passed in would subtract).
  7. Final gross = `item_discounted_total − header_discount + line_tax_total + header_tax + other_charges`, rounded to 2dp.
  8. Returns that gross plus whatever `currency` string was in the payable (empty string if absent).
- CLI usage: `python erp.py payable.json` prints the JSON result.

**From `example_check.py`:** Nothing beyond a usage demo — confirms the one call needed (`erp_book`) and that `sample_autodraft.json` is the default input if none given. It performs no assertions, no pass/fail logic, and no comparison against a ground truth — it is explicitly "a usage example, nothing more."

**From `documents/`:** 35 real-world-sourced supplier PDFs (see §2, §9) spanning multiple countries (Germany, Estonia, UK, Ghana, Malaysia, South Africa, Kenya, Portugal, Thailand, Turkey, Singapore, Indonesia, Australia, the US), multiple currencies, multiple languages (German, Estonian, Thai, Portuguese, English), 1–35 line items per the brief, and non-payable content mixed in.

**From `master_data/`:** Five lookup tables (see §8) the candidate resolves document values against — deliberately small ("sample rows") but structurally representative of a production-scale master.

---

## 7. Output Requirements (exact schema)

**Per-file wrapper** (`output/<file-basename>.json`):
```jsonc
{
  "file": "X.pdf",
  "payables": [ /* 0..N payable objects, each per the schema below */ ],
  "declined": [ { "doc_type": "...", "reason": "..." } /* 0..N, may be empty */ ]
}
```

**Payable object** (verbatim field list from `AUTODRAFT_SCHEMA.md` / `sample_autodraft.json`):

| Field | Type/format | Notes |
|---|---|---|
| `invoice_number` | string | as printed |
| `invoice_date` | string, ISO `YYYY-MM-DD` | |
| `due_date` | string, ISO `YYYY-MM-DD` | |
| `invoice_type` | `"INVOICE"` \| `"CREDIT_MEMO"` | |
| `currency` | string (ISO code) | |
| `supplier.name` | string | raw printed name |
| `supplier.supplier_id` | string | matched code from `suppliers.json`, or `""` |
| `supplier.address` | string | |
| `supplier.vat_id` | string | |
| `buyer.company_code` | string | matched from `chart_of_books.json` |
| `buyer.business_unit_code` | string | matched from `chart_of_books.json` |
| `buyer.location_code` | string | matched from `chart_of_books.json` |
| `payment_term_id` | string | matched from `payment_terms.json`, or `""` |
| `po_number` | string | raw printed PO reference, or `""` |
| `po_id` | string | matched from `po_master.json`, or `""` |
| `gross_total` | string, dot-decimal | as printed on the document |
| `subtotal` | string, dot-decimal | optional |
| `total_tax_amount` | string, dot-decimal | declared total tax as printed |
| `discount_amount` | string, dot-decimal | header-level, magnitude |
| `freight_charges` | string, dot-decimal | |
| `insurance_charges` | string, dot-decimal | |
| `extra_charges` | string, dot-decimal | |
| `excise_duties` | string, dot-decimal | |
| `taxes[]` | array of tax objects | header-level taxes |
| `taxes[].tax_type` | string | e.g. `"VAT"` |
| `taxes[].tax_name` | string | as printed |
| `taxes[].tax_rate` | string, percent, no `%` sign | |
| `taxes[].tax_amount` | string, dot-decimal, may be `""` or negative | empty ⇒ ERP derives from rate; negative ⇒ withholding |
| `taxes[].tax_type_code` | string | matched from `tax_master.json`, or `""` |
| `line_items[]` | array | raw line components |
| `line_items[].description` | string | |
| `line_items[].item_type` | `GOODS` \| `SERVICE` \| `FREIGHT` \| `TAX` | |
| `line_items[].uom` | string | |
| `line_items[].quantity` | string, numeric | |
| `line_items[].unit_price` | string, numeric, **NET (tax-exclusive)** | |
| `line_items[].total` | string, numeric | line extension "as printed" |
| `line_items[].discount` | string, numeric magnitude | amount discount |
| `line_items[].discount_percentage` | string, numeric | percentage discount |
| `line_items[].tax_rate` | string, numeric, optional | per-line shorthand rate |
| `line_items[].tax_amount` | string, numeric, optional | per-line shorthand amount |
| `line_items[].taxes[]` | array, same shape as header `taxes[]` | explicit per-line taxes, alternative to `tax_rate`/`tax_amount` shorthand |

**Numeric convention:** all numbers are dot-decimal strings (e.g., `"1234.56"`), never locale-formatted (`"1.234,56"` is explicitly called out as wrong) and never bare JSON numbers in the sample.

**Cross-check against `sample_autodraft.json`:** The sample is internally consistent with the schema — a 2-line German services invoice, reverse-charge VAT at 0%, no PO, matched supplier/buyer/payment-term codes, no discounts/charges. It demonstrates: (a) `taxes[]` can hold a single header-level 0% tax while both lines carry empty `tax_rate`/`taxes: []` — i.e., the tax sits at the header, not per-line, in this example; (b) `po_number`/`po_id` both legitimately empty together; (c) all monetary fields as strings. No discrepancy found between the sample and the schema doc.

---

## 8. Dataset/Master Data Analysis

### `suppliers.json`
- 14 records. Fields: `supplier_id`, `name`, `vat_id`, `country`, `email`, `address`, `bank_iban`.
- Countries represented: DE(1), EE(3), MY(2), GH(3), ZA(2), KE(1), PT(2).
- Data quality: `vat_id` and `bank_iban` are frequently empty strings (5/14 missing `bank_iban` entirely is actually 9/14 missing `bank_iban`; 1/14 missing `vat_id`) — i.e., the master itself is incomplete, meaning strict "must match on VAT ID" logic would silently under-match; name/country/address are the more reliably populated match keys.
- Relationship: `suppliers.supplier_id` is referenced by `po_master.supplier_id` (both PO rows point to a valid supplier: `2807582` and `2731927`).
- The `_comment` field explicitly says not every document's supplier is present — an unmatched supplier is a legitimate outcome, not a bug to fix.

### `chart_of_books.json`
- One company: `BOLTGROUP` ("Bolt Group"). 6 business units, each with exactly one location:
  - `EE001` (Bolt Technology OU) → `LOC_EE_001` (Tallinn HQ)
  - `EE004` (Bolt Holdings OU) → `LOC_EE_001` (same location code as EE001 — **note: two different business units share the identical location_code**, a real data-quality wrinkle for matching logic)
  - `GH001` (Bolt Ghana Ltd) → `LOC_GH_001` (Accra)
  - `MY001` (Bolt Malaysia Sdn Bhd) → `LOC_MY_001` (Kuala Lumpur)
  - `ZA001` (Bolt South Africa) → `LOC_ZA_001` (Johannesburg)
  - `GB001` (Bolt Operations UK Ltd) → `LOC_GB_001` (London)
- Critical structural fact, established by direct document inspection (§9): **none of the sampled PDFs are addressed to any entity literally named "Bolt Group" or a visible "Bolt ..." business unit** except a partially-legible fragment in one badly-scanned document (`HLD-03`, where "Bolt [...] Alc[...]" appears truncated/overlapping in the "Destinatário" block — plausibly a Bolt-related buyer name obscured by scan artifacts). Real buyer names actually observed in the corpus include AmeriHealth Caritas, Oracle America, PECO, Zycus Infotech Private Limited, Northwind Operations OÜ / Northwind SUPPORT SERVICES, Kingsley Services Inc, 215 B.E.A.R.S., Meridian Technologies. **This is the single largest structural ambiguity in the kit — see §12.**

### `tax_master.json`
- 32 tax codes covering 16 country/regime combinations: DE (19%, 7%, 0% reverse-charge), EE (24%, 22%, 0%), GB (20%, 0%), PT (23%, 13%, 6%), ZA (15%), KE (16%), MY (SST 8%, 0%), GH (VAT 15%, NHIL 2.5%, GETFund 2.5%, COVID levy 1%, Communication Service Tax 5% — Ghana alone has 5 distinct stackable levies, implying multi-tax-per-line/header scenarios are expected for Ghanaian documents), CH (8.1%), CA (HST 13%), DK (25%), PL (23%, "not-subject-to-VAT" 0%), TH (VAT 7%, Withholding 3% — an explicit withholding tax code confirming negative `tax_amount` scenarios are intended, not hypothetical), SG (GST 9%, 0%), SE (moms 25%), RO (19%), VN (8%, 10%), US (Use Tax 0%, self-assessed).
- Matching key ambiguity: rows carry `country` + `rate` + `tax_type` + `name`, but no VAT-ID-prefix or explicit locale/language alias list (unlike `payment_terms.json`, which does provide `text_aliases`) — so matching a printed tax label like "IVA 23%" or "MwSt 0%" to `tax_type_code` requires the candidate to build their own normalization (language → tax_type, rate as a numeric key, country inferred from supplier/buyer).

### `payment_terms.json`
- 10 terms, each with `days` and a `text_aliases[]` list for fuzzy/keyword matching (e.g. `Net_30` aliases `"net 30"`, `"30 days"`, `"one month"`). This is the only master file that ships its own matching hints — an explicit design signal that payment-term resolution is meant to be done via text/alias matching (and/or by computing `due_date − invoice_date` in days and matching against `days`), not via an ID printed on the document (documents rarely print an internal code like `"Net_10"` verbatim).

### `po_master.json`
- 2 PO records only (`PO-EE-2026-0044`, `PO-GH-2026-0177`), each tied to one supplier, one currency, and a single PO line with quantity/uom/unit_price. The `_comment` explicitly states a PO printed on a document but absent from this master is a "non-ERP reference" — i.e., `po_number` (raw) should still be captured, but `po_id` must stay blank. With only 2 sample POs against 35 documents, the overwhelming majority of PO references (if any appear at all) are expected to resolve to `po_id: ""`.

**Cross-cutting data-quality issues to design around:**
- Sparse/optional fields across every master (`vat_id`, `bank_iban` frequently blank) mean single-field exact-match strategies will under-match; multi-field fallback (name+country, VAT+country, etc.) is implied.
- Two business units sharing one `location_code` (`EE001`/`EE004` → `LOC_EE_001`) means "match by location" alone is ambiguous without also resolving `business_unit_code`.
- All five masters are explicitly called out as **non-representative in scale** (a few rows now, hundreds of thousands/millions in production) — this is a stated non-functional constraint on matching design, not just a data note.

---

## 9. Sample/Reference Analysis (what `sample_autodraft.json` and `example_check.py` reveal about grading)

- `sample_autodraft.json` is a single, fully "nice" case: no discounts, no charges, no PO, a single header-level 0% reverse-charge tax, two clean service lines. It functions purely as a **shape reference**, not as a difficulty calibration — it is almost certainly *easier* than the median document in `documents/`, since it has none of the multi-tax, multi-currency, or non-payable complications observed directly in the corpus (see below). Candidates should not anchor their mental model of "typical difficulty" on this file.
- `example_check.py` proves the **only sanctioned self-check mechanism** provided is: build a payable dict → call `erp_book` → compare the returned gross/currency to what the document states. It performs no schema validation, no master-data-code validation, and no structural (line vs. header placement) validation — confirming those checks are **held privately by the grader** and are exactly the parts "the oracle cannot see" that the brief warns about. A candidate who only iterates against `erp.py` until the gross matches is optimizing a proxy metric, not the actual grading criteria.
- Direct inspection of the document corpus (extracting the embedded page images/text of `DU-02, DU-05s, DU-06, DU-09, DU-10, DU-11, HLD-01, HLD-03, HLD-08, INV-01, INV-31, INV-32, INV-34, INV-35, INV-36, INV-37`) surfaced concrete evidence for several of the brief's abstract warnings:
  - **A genuine credit memo exists** (`DU-11`, an Estonian "Kreeditarve nr 6265-K"): stated total is **-400.00 EUR** on the document itself, confirming the schema's instruction that `CREDIT_MEMO` values must be resubmitted as **positive** magnitudes is not a hypothetical edge case but something the pipeline must actively detect and sign-flip.
  - **A non-payable document exists** (`DU-10`): an internal donations/sponsorship compliance approval form (a $1,995 sponsorship request with approval checkboxes) — no supplier invoice, no gross owed to an external party in the payable sense, no line items in the schema's sense. This is a strong `declined[]` candidate and plausibly one of the "not every PDF is a payable" cases the brief warns about.
  - **A pure delivery note exists** (`DU-05s`): a "Delivery note" with quantities/weights but **no prices, no currency, no monetary total anywhere on the page** — clearly not bookable, another `declined[]` candidate, and a clean illustration that "looks financial" ≠ "is a payable."
  - **A customs/consolidated shipment invoice exists** (`DU-02`, "Customs Consolidated Invoice," 2 pages, 14 HTS-coded line items with per-line "Extended Total" but comma-decimal European formatting and no visible tax/currency/grand-total on page 1) — ambiguous whether this is a bookable payable or a customs-compliance document; a judgment call, not an extraction problem.
  - **Multi-rate, per-line tax structures exist** (`DU-06`, a Europastry/Blackpine Supply invoice): 5 line items carrying **two different IVA rates within the same document** (23% on one line, 6% on four others) plus a summary breakdown by rate at the bottom — directly the scenario the brief calls out ("a document with three rates across its lines yields three line-level taxes, not one blended rate").
  - **Compounded/derived tax-on-tax and fee-on-fee structures exist** (`HLD-01`, a Thai staffing invoice): Subtotal → +9% "Management Fee" (a charge, not a tax) → +7% VAT (applied to the fee-inclusive amount) → -3% Withholding Tax (a negative tax reducing the payable) → final "Total Payment." This is a 4-step derived total that will not trivially decompose into the schema's flat `taxes[]`/`charges` fields without deliberate modeling of order-of-operations and of the management fee as an `extra_charges` (or similar) rather than a tax.
  - **The 6 "text-layer" PDFs (`INV-31/32/34/35/36/37`) are thematically and geographically disjoint from the master data** — they reference AmeriHealth Caritas (US healthcare payer), PECO (US utility), Oracle America, Zycus Infotech itself (Melbourne serviced office invoice — an in-joke: the assignment issuer appears as a "customer" on a sample document), and a Thai staffing company — none of which correspond to any Bolt Group entity, and most of which are US-domestic invoices with no cross-border VAT/GST mechanics at all. This reinforces that the corpus was assembled from heterogeneous, likely-public/real-world invoice samples rather than being purpose-built around the `chart_of_books.json` buyer scenario, and strengthens the ambiguity flagged in §8/§12 about how `buyer.*` codes are meant to be resolved when the visible "Bill To" name never says "Bolt."
- Filename-prefix hypothesis explicitly disproven: `HLD-01`, `HLD-08`, `DU-06`, `DU-09` are all ordinary-looking tax invoices with no evident "hold/exception" semantics distinguishing them from `INV-` files; `DU-10` and `DU-05s` are not invoices at all despite the `DU-` prefix. **Treat every filename prefix as meaningless for classification logic** — this matches the brief's explicit "nothing is labelled or categorised."

---

## 10. Explicit Constraints

1. `erp.py`'s core computation must not be altered; grading always runs the shipped, unmodified version. Wrapping/reimplementing for speed is permitted, but behavior must match exactly.
2. Output numbers must be dot-decimal strings; no locale-formatted numbers.
3. `unit_price` must be NET (tax-exclusive); the ERP adds tax on top.
4. Master-data codes may only be set when a genuine match exists; empty string is the required value otherwise — fabrication is explicitly and repeatedly forbidden (README Rule 2, schema field notes, master_data README).
5. Every emitted value must be traceable to something printed on the document — no value may exist purely to balance the arithmetic (README Rule 1).
6. Corrections/"fixes" to a document's apparent data must be grounded in an independent fact, not applied speculatively (README Rule 3) — over-correction is explicitly penalized more than under-correction.
7. Credit memos use the identical schema/keys as invoices, with `invoice_type: "CREDIT_MEMO"` and positive-magnitude values — no separate shape.
8. One command must run the entire pipeline over an arbitrary documents folder and produce `output/<file>.json` for each PDF; the folder is created if missing.
9. `DESIGN.md` is capped at 3 pages and must answer three specific questions (see §4.21) — it is graded content, not a formality.
10. Matching design must not assume the sample masters are the full production data; it must be architected for scale (hundreds of thousands to millions of rows).

---

## 11. Hidden/Likely Expectations

- **LIKELY EXPECTATION / INFERENCE:** The "shift in how you picture what one of these documents actually is," which the brief deliberately withholds, is plausibly the recognition that a document is not "a total plus some line items to reverse-engineer" but rather **a derivation chain of the issuer's own accounting logic** (fees compounding into tax bases, discounts applied before or after tax, withholding applied last, multi-rate splits) — and that the candidate's job is to reconstruct *that specific chain* per document (grounded in what's printed) rather than to find *any* combination of raw components that happens to foot to the stated total. This reading is consistent with: the explicit warning that two structures can foot to the same number with only one being correct; the requirement that placement (line vs. header) is graded; and the observed `HLD-01` compounding example in §9.
- **LIKELY EXPECTATION / INFERENCE:** Given the corpus mixes clean invoices, a credit memo, a delivery note, a customs invoice, and an internal compliance form, at least part of the grading rubric on the *open* set is almost certainly a straightforward "did you correctly triage payable vs. non-payable, and INVOICE vs. CREDIT_MEMO" check, separate from and prior to the arithmetic/placement checks.
- **LIKELY EXPECTATION / INFERENCE:** The held-back set "contains situations the open set does not — including at least one you will not have seen before at all," which strongly suggests the held-back set includes a category of document not represented in the open 35 (e.g., a multi-payable single PDF, a document in a currency/tax regime absent from `tax_master.json`, or a genuinely unsolvable case analogous to the one `DESIGN.md` Q3 asks about). A system whose non-payable/blank-code/no-guess behavior is a genuine fallback (rather than hardcoded per file) should handle this without modification — that is very likely the point of the open/held-back gap metric.
- **LIKELY EXPECTATION / INFERENCE:** `DESIGN.md` question 3 ("was there a document you concluded could not be solved the way the others were") most plausibly points at one of: (a) `HLD-03`, whose scan is badly overlapping/garbled to the point that the buyer name and several fields are genuinely illegible even to a human without extra context; (b) `DU-02`, the customs consolidated invoice, where it may be genuinely undecidable from the page alone whether it represents a bookable payable versus a customs/compliance artifact; or (c) `DU-10`, the donations-approval form, where the honest answer is "this was never a payable, and no amount of extraction makes it one." Any of these is a defensible answer; the point the brief is testing is the candidate's willingness to say "not solvable as a payable" rather than force an answer.

---

## 12. Ambiguities and Open Questions

1. **How is `buyer.*` (Bolt Group / chart_of_books) meant to be resolved when no inspected document's visible "Bill To" name matches any Bolt entity?**
   Why it matters: `buyer` is a required object in every payable, and its three codes are explicitly master-data-backed fields subject to the "no guessing" rule. If no textual signal maps a document to `BOLTGROUP`/a business unit/a location, the honest answer under the stated rules would be to leave all three blank on every document — but the sample payable populates all three confidently (`BOLTGROUP` / `EE004` / `LOC_EE_001`), implying the intended workflow does successfully resolve a buyer per document. Possible interpretations: (a) the "tenant" is meant to be supplied out-of-band per batch/run rather than read from the page (the `chart_of_books.json` `_comment` literally says "The tenant is provided with each document"), which would make buyer resolution a fixed/contextual assignment rather than something OCR'd from page content; (b) buyer resolution is meant to be inferred indirectly (ship-to/service country, currency, or an account/customer number that a real deployment would map via a separate customer-account table not included in this kit); (c) the open documents intentionally do not carry a resolvable buyer and blank buyer codes are simply the expected, correct answer for most/all of them. **Safest interpretation:** treat buyer-code resolution the same as every other master-data field — attempt matching using whatever signal is genuinely present (ship-to address/country, any explicit customer/account reference, currency), and leave it blank when nothing genuinely supports a match, rather than defaulting every payable to `BOLTGROUP` by assumption. Document this reasoning explicitly in `DESIGN.md` since it's a live ambiguity the graders may specifically be probing.
2. **What exactly counts as "a payable" for a customs/consolidated-shipment document like `DU-02`?**
   Why it matters: it has line-level extended totals but no visible page-1 currency/tax/grand-total, and represents inventory movement/customs declaration rather than a request for payment in the ordinary sense. Possible interpretations: it's a payable from the shipper's freight-forwarding invoice, or it's a customs-compliance artifact that should be declined. **Safest interpretation:** if no explicit "amount owed to a party, to be booked" framing is present on the page, decline it with a clear `reason`, since Rule 1/Rule 3 both favor abstaining over guessing.
3. **How strictly should `po_number` (raw, printed) vs. blank be handled when a document doesn't mention a PO at all?**
   The schema always includes the two PO fields; it's unclear whether an absent PO reference should be `""` for both or omitted. **Safest interpretation:** always include both keys per the schema (never omit keys), set both to `""` when no PO is printed.
4. **Should `subtotal` and `total_tax_amount` be included even though the schema marks `subtotal` "optional"?** Given `erp.py` never reads `subtotal`/`total_tax_amount` (it derives everything from lines/taxes), these two fields appear to be purely informational cross-checks against the document, used by the grader's structural/placement review rather than by the arithmetic oracle. **Safest interpretation:** populate them whenever printed (they cost nothing and support the "as printed" fidelity Rule 1 implies), leave blank only if genuinely absent from the page.
5. **Does "several payables in one PDF" ever actually occur in the open 35, or is it purely a held-back-set concern?** Not established by inspection of the sampled subset; worth a full pass over all 35 documents (multi-page ones especially) before finalizing pipeline assumptions.
6. **How should the 6 text-layer PDFs be handled relative to the 29 scan-only PDFs — same pipeline path, or a distinct one?** Nothing in the brief forbids branching logic by input type (text-layer vs. image-only) since that's a property of the file, not of "special-casing the document's content" — the warned-against special-casing is about document-specific business rules, not about legitimate format-detection. **Safest interpretation:** branch on presence/absence of an extractable text layer as an engineering optimization (skip OCR when a good text layer exists), but feed both paths into the same downstream classification/decomposition logic so no document-specific business rule differs by prefix or filename.

---

## 13. Required Deliverables Checklist

**Explicit / mandatory:**
- [ ] Working system, any stack, single documented command, running over `documents/` → `output/`.
- [ ] Generated `output/*.json` for all open documents (one file per input PDF, correct wrapper shape).
- [ ] `DESIGN.md`, ≤3 pages, answering all three specified questions honestly (including naming a document judged unsolvable).
- [ ] A candidate-authored `README` documenting the one run command (script or Dockerfile).

**Recommended (not stated as a separate deliverable, but functionally necessary to satisfy the above):**
- [ ] Internal self-check step that calls `erp.py`/`erp_book` on generated payables before finalizing, to catch arithmetic mismatches pre-submission.
- [ ] Some internal logging/trace of *why* a document was declined or a code left blank, to support writing an honest `DESIGN.md`.

**Optional:**
- [ ] Dockerfile (vs. plain script) — either satisfies "one documented command."
- [ ] Automated tests beyond the provided `example_check.py`.

---

## 14. Requirements Matrix

| ID | Requirement | Source/File | Mandatory? | Implementation implication |
|---|---|---|---|---|
| R1 | Emit `output/<file>.json` per PDF, exact wrapper shape | README §Output contract | Yes | Batch driver iterating `documents/`, deterministic filenames |
| R2 | `payables[]` 0..N per file | README, SCHEMA | Yes | Classification/segmentation step before extraction |
| R3 | `declined[]` with `doc_type`+`reason` for non-payables | README, SCHEMA | Yes | Explicit triage decision, not an omission |
| R4 | Submit raw components, not ERP-derived totals | SCHEMA intro | Yes | Never write computed net/gross into `unit_price`/line `total` fields as if raw |
| R5 | Tax placement (line vs. header) must match document | README, SCHEMA field notes | Yes | Extraction must track *where* each tax appears, not just its value |
| R6 | Each tax's name/rate/amount as printed, not blended | README | Yes | No auto-aggregation of multiple line rates into one header rate |
| R7 | Components (qty, price, discount, charges) stay decomposed | README | Yes | Schema-shaped extraction target, not a single "total" field |
| R8 | Master-data code resolution, honest blank on no-match | SCHEMA, master_data README | Yes | Matching layer with an explicit no-match path returning `""` |
| R9 | Raw printed value always retained alongside matched code | SCHEMA | Yes | Two parallel fields per resolvable value (raw + code) |
| R10 | `CREDIT_MEMO` same schema, positive magnitudes | README, SCHEMA | Yes | Sign-detection + sign-flip step for credit documents |
| R11 | No invented values to balance totals | README Rule 1 | Yes | Validation pass rejecting synthesized-but-unprinted numbers |
| R12 | No fabricated master-data codes | README Rule 2 | Yes | Matching confidence threshold with abstain option |
| R13 | Corrections must be independently justified | README Rule 3 | Yes | Any "fix" logic must cite a verifiable source fact, logged for DESIGN.md |
| R14 | Dot-decimal numeric strings only | SCHEMA field notes | Yes | Output serialization layer enforces format |
| R15 | `unit_price` NET/tax-exclusive | SCHEMA field notes | Yes | Must distinguish gross vs. net unit prices during extraction |
| R16 | `erp.py` computation must not change | README | Yes (hard constraint) | Treat as a black-box dependency, never fork its logic differently |
| R17 | One command reproducible run | README §What you submit | Yes | Document exact invocation; avoid hidden manual steps |
| R18 | `DESIGN.md` ≤3 pages, 3 specific questions | README §What you submit | Yes | Must be written reflectively, post-implementation |
| R19 | Matching must scale to large masters | master_data README | Yes (design-level) | Indexed/blocked lookup design, not naive full-scan fuzzy match |
| R20 | Every PDF is unlabeled; no prefix-based logic | README, confirmed by inspection | Yes (implicit) | Classification must be content-driven, never filename-driven |
| R21 | Avoid growing per-document special-case branches | README closing section | Yes (implicit, meta) | Architecture should generalize a single "what is a payable" model |
| R22 | Open vs. held-back gap is itself scored | README §How you are judged | Yes (meta) | Prioritize generalizable heuristics over document-specific tuning |

---

## 15. Acceptance Checklist

- [ ] Running the documented single command from a clean checkout produces an `output/` folder with exactly one JSON file per PDF in `documents/`.
- [ ] Every output JSON parses as valid JSON and matches the wrapper shape (`file`, `payables`, `declined`).
- [ ] Every payable object contains all schema keys (even if empty-string/empty-array), matching `AUTODRAFT_SCHEMA.md` field-for-field.
- [ ] All numeric fields are dot-decimal strings.
- [ ] For every payable, `erp_book(payable)["will_book_gross"]` (using the unmodified `erp.py`) equals the document's stated gross to the cent.
- [ ] For every payable, header vs. line tax placement matches what is visibly printed on the source document.
- [ ] No numeric value appears in any payable that cannot be pointed to on the source document.
- [ ] No master-data `_id`/`_code` field is populated without a genuine, defensible match against the corresponding `master_data/*.json` file.
- [ ] Every `CREDIT_MEMO` payable carries positive-magnitude values even where the source document prints negative figures.
- [ ] Every non-payable page/document is represented in `declined[]` with a specific, truthful `reason`, not silently dropped.
- [ ] `DESIGN.md` exists, is ≤3 pages, and directly answers all three required questions with specific document references.
- [ ] The candidate's own `README` gives one exact command that a grader can run without additional undocumented setup.
- [ ] `erp.py`'s source is untouched from the shipped version (diff-clean).

---

## 16. Potential Evaluation Criteria

Inferred from the brief's explicit statements in "How you are judged," cross-referenced with what `erp.py`/`example_check.py` can and cannot verify:
1. **Booking accuracy** — fraction of payables whose ERP-recomputed gross matches the document's true owed amount, on both open and held-back sets.
2. **Triage correctness** — correct identification of payable vs. non-payable, and correct payable count per document (0/1/N).
3. **Structural fidelity** — tax/charge placement (header vs. line) and decomposition (no blending/pre-summing), independently of whether the gross happens to match.
4. **Master-data integrity** — no fabricated codes; codes present wherever a genuine match exists (both over- and under-resolution likely penalized).
5. **Groundedness** — every emitted value traceable to the source document; no invented balancing figures.
6. **Generalization gap** — the explicit open-vs-held-back distance metric, rewarding approaches that are not overfit/hand-tuned to the visible 35 documents.
7. **`DESIGN.md` quality** — evidence of genuine reflection and an honest "unsolvable document" identification, not a feature list.
8. **Reproducibility** — whether the one-command run actually works when re-executed by someone else.

---

## 17. Potential Quality Improvements (beyond minimum)

- Confidence scores or an internal audit trail per field (why a value/code was chosen or left blank) — supports both debugging and an honest `DESIGN.md`.
- Automatic pre-submission validation that runs every payable through `erp_book` and flags/logs any mismatch before writing final output, rather than discovering mismatches after submission.
- A structured intermediate representation (e.g., a normalized "parsed document" object with page-anchored provenance for every value) so structural-placement correctness can be checked programmatically, not just eyeballed.
- Currency/locale-aware number normalization (comma-decimal European formats, thousands separators) applied consistently before schema serialization.
- Idempotent, resumable processing (skip already-processed files) for practical iteration speed against 35+ documents during development.

---

## 18. Potential Differentiators

- A genuinely unified "payable reconstruction" model (e.g., explicitly modeling the issuer's own derivation order — discount → tax base → tax → charges → withholding — per document) rather than a flat field-extraction template, directly addressing the brief's central hint.
- Deliberate, demonstrated restraint: a visibly non-trivial rate of `""` codes and non-empty `declined[]` entries, rather than a suspiciously "complete" output — this is explicitly what the brief says it wants ("no match" as a legitimate, valued answer).
- A `DESIGN.md` that names a specific document and gives a concrete, falsifiable reason it cannot be solved (e.g., citing exactly what information is missing/illegible), rather than a generic disclaimer.
- Handling the buyer/chart_of_books ambiguity (§12.1) transparently and consistently rather than silently defaulting every document to `BOLTGROUP`.
- Robustness demonstrably validated on at least one deliberately-degraded document (e.g., `HLD-03`'s garbled scan) with a documented, honest failure/partial-fill behavior rather than a fabricated full record.

---

## 19. Risks and Failure Modes

1. **Overfitting to the 35 open documents** via per-document heuristics — directly penalized by the open/held-back gap metric; the single largest named risk in the brief itself.
2. **Treating filename prefixes as signal** — disproven by direct inspection (§9); any logic keyed on `DU-`/`HLD-`/`INV-` will misclassify on the held-back set, which likely uses different naming or none at all.
3. **Guessing master-data codes to "complete" a record** — explicitly and repeatedly penalized (Rule 2); a natural temptation once a candidate has built a matcher and wants every field populated.
4. **Inventing values to force `erp.py`'s output to match a target gross** — explicitly and repeatedly penalized (Rule 1); tempting once a candidate is iterating against the oracle.
5. **Over-aggressive "correction" logic** — explicitly penalized more harshly than doing nothing (Rule 3); e.g., auto-normalizing a tax rate that looks "wrong" but is deliberately unusual on the source document.
6. **Collapsing multi-rate line taxes into one header rate for convenience** — explicitly called out as wrong even when it foots to the same total (observed as a real risk given `DU-06`'s genuine 2-rate structure).
7. **Missing the credit-memo sign convention** — booking `DU-11`'s -400.00 EUR document as a positive INVOICE, or as a negative CREDIT_MEMO (violates the "positive magnitudes" rule), both plausible mistakes.
8. **Misjudging non-payable documents as payables** (e.g., extracting a fabricated "payable" from `DU-10`'s donations form or `DU-05s`'s delivery note) — inflates `payables[]` incorrectly and likely scores worse than a correct `declined[]` entry.
9. **Assuming buyer codes are always resolvable and defaulting to `BOLTGROUP`** when no genuine textual match exists — risks systematic fabrication across most/all of the corpus (§12.1).
10. **Underestimating the OCR/vision workload** — 29 of 35 documents have zero text layer; treating this as a "quick regex over `pdftotext` output" project will fail immediately on the majority of the corpus.
11. **Matching design that doesn't scale** — a brute-force full-table fuzzy scan per document, while functionally correct on 14 sample suppliers, is an explicitly flagged design smell for a "millions of rows" production master.
12. **Underweighting `DESIGN.md`** — treating it as boilerplate rather than graded content risks losing credit disproportionate to its 3-page size, given how specifically the brief describes what it must contain.

---

## 20. Important Things Not To Miss

- Read the **entire** brief, including the final section, before writing any code — the brief itself insists on this, and the final section contains the single most load-bearing statement about failure mode and strategy.
- The oracle (`erp.py`) tells you *a* number, never *the* correctness verdict — don't mistake "gross matches" for "payable is correct."
- `subtotal`/`total_tax_amount`/`gross_total` are **as-printed record fields for fidelity**, not inputs the ERP consumes to compute anything — don't confuse them with the raw components that actually drive `erp_book`.
- The schema's `_id`/`_code` fields and their raw counterparts are **both required to be populated correctly and independently** — a resolved code does not replace the raw text field, and vice versa.
- At least one document is stated to be intentionally unsolvable in the way others are — actively look for it rather than assuming full coverage is expected or achievable.
- The masters are intentionally tiny; do not read "14 suppliers" as "there are only 14 suppliers to worry about" — the real design target is scale-appropriate matching, not memorizing the sample rows.
- Filenames and folder-prefix conventions carry no guaranteed semantic information; verified false by direct inspection.
- Ghana-related documents may require summing multiple stackable levies (VAT + NHIL + GETFund + COVID levy + CST) — a candidate optimizing only for VAT-style single-tax documents will underperform there.

---

## 21. Questions We May Need to Ask Zycus

(For a real hiring process, not to be resolved by guessing in the submission — but worth having in one's back pocket if a clarification channel exists.)
1. Is the `buyer.*` tenant meant to be inferred purely from document content, or is a tenant context supplied out-of-band per batch/run (as `chart_of_books.json`'s comment "the tenant is provided with each document" seems to imply)?
2. Are `DU-`/`HLD-`/`INV-` filename prefixes meaningful in the held-back set, or purely an artifact of how this open sample was assembled?
3. Is there a canonical list of acceptable `doc_type` strings for `declined[]` entries, or is free text acceptable?
4. Should `line_items[].item_type: "TAX"` ever be used for a line that is purely a tax/levy line item on the document (as opposed to representing that tax within `taxes[]`), or is `"TAX"` reserved for a different scenario?
5. For documents in a currency/country entirely absent from the provided masters (e.g., none of PECO/Oracle America/AmeriHealth's US-domestic invoices correspond to any country in `tax_master.json`/`chart_of_books.json`), is the expected behavior simply "every master-backed field stays blank," or are such documents themselves expected to be declined as out-of-scope?

---

## 22. Recommended Next Step

Before writing any extraction or matching code:
1. Do a **full manual pass over all 35 documents** (not just the sampled subset used for this analysis) — render every page to an image and read it, cataloguing: document type (invoice/credit memo/delivery note/other), page count, currency, country, tax structure (single/multi-rate, header/line-level), presence of PO reference, presence of discounts/charges, and a first-pass judgment on payable vs. non-payable. This turns the open set into a ground-truth reference the candidate controls, against which `erp.py` outputs can be sanity-checked before any code is trusted.
2. From that pass, explicitly enumerate the **distinct structural patterns** observed (e.g., "flat single-VAT invoice," "multi-rate per-line VAT," "fee-then-tax-then-withholding chain," "non-payable form," "credit memo") — this is the concrete, evidence-based version of "the shift in how you picture what one of these documents actually is" that the brief withholds; the goal is to derive it inductively from the real 35 documents rather than from an a priori theory.
3. Only then design the extraction (OCR/vision) → normalization → tax/charge decomposition → master-matching → schema-serialization pipeline, explicitly built around the general derivation-chain model from step 2 rather than around any individual document.
4. Build the `erp.py` self-check loop early and use it continuously during development — but always alongside the manual ground truth from step 1, never as the sole correctness signal.
