# Quick Summary — "The Bookable Payable" (Zycus take-home)

## What Zycus wants
Not an OCR project. You're given scanned supplier documents (invoices, credit memos, delivery notes, and some things that aren't payables at all) and must decide, per document: is this a payable, how many payables does it contain, and what exactly does it say is owed. You then emit a structured JSON record ("autodraft") per payable that a fixed external calculator (`erp.py`) can recompute to the exact cent the document states — **and** that record must mirror the document's own structure (which taxes sit at the header vs. on individual lines), not just arithmetically add up to the right number. Matching the total with the wrong structure is explicitly a wrong answer.

## What to build
One command that reads every PDF in `documents/` and writes `output/<name>.json` for each, containing `payables[]` (0..N schema-conformant records) and `declined[]` (anything judged not a payable, with a reason). Plus a `DESIGN.md` (≤3 pages) reflecting honestly on what you learned, how your system handles novel documents, and which document you concluded could not be solved.

## Inputs you're given
- `documents/`: 35 PDFs. **29 of 35 have no text layer at all** — pure scanned images requiring OCR or a vision model. Only 6 (`INV-31,32,34,35,36,37`) have embedded text. Filenames (`DU-`, `HLD-`, `INV-`) carry **no reliable meaning** — confirmed by inspection: some `HLD-`/`DU-` files are ordinary invoices, one `DU-` file is a delivery note with no prices at all, one is an internal donations-approval form (not a payable), and one is a genuine credit memo (Estonian, printed as -400.00 EUR).
- `erp.py`: the fixed, sealed oracle. Feed it raw components (quantities, prices, discounts, tax rates/amounts, charges); it returns the gross it would book. It never tells you if that's *correct* — only what it computes. Must never be modified.
- `master_data/`: 5 small lookup tables (suppliers, buyer org structure "Bolt Group", tax codes, payment terms, POs) to resolve document values into codes. Explicitly sample-sized — real masters run to millions of rows, so matching must be designed to scale, not brute-forced.
- `AUTODRAFT_SCHEMA.md` + `sample_autodraft.json`: the exact output shape and one worked (easy) example.

## Output required
Per PDF, one JSON file with the exact schema fields (raw quantities/prices/discounts/taxes/charges as strings, dot-decimal, tax-exclusive unit prices, header vs. line tax placement preserved). Master-data `_id`/`_code` fields set only on a genuine match — empty string is a correct, valued answer; a guessed code is explicitly penalized. Credit memos use the same schema with `invoice_type: "CREDIT_MEMO"` and positive-magnitude values even though the source document shows negatives.

## Mandatory vs. recommended
**Mandatory:** one documented run command; correct output schema/shape; don't touch `erp.py`'s calculation; every emitted number must appear on the document (no invented balancing figures); every code must be a real match or blank; corrections must be independently justified, never speculative; `DESIGN.md` answering its three specific questions.
**Recommended, not stated as hard rules:** an OCR/vision extraction layer for the 29 image-only PDFs plus a text-parsing path for the 6 that have text; a pre-submission self-check against `erp.py`; a scalable (indexed, not brute-force) matching design for master data.

## Key constraints
- `erp.py` is sealed — you may wrap/reimport/reimplement it, but its computation logic must not change; grading uses the original.
- Numbers are dot-decimal strings; `unit_price` is always net of tax.
- Grading uses **both** an open set (self-checkable) and a **held-back set** with novel situations; your score also reports the **gap** between the two — a big gap signals overfitting/special-casing, which the brief explicitly warns against ("no list of special cases").

## Biggest risks
1. Treating this as an OCR/field-extraction task and stopping there — the brief says this approach "books perhaps a third" of documents and then stalls.
2. Relying on filename prefixes for classification — directly disproven by inspection.
3. Fabricating master-data codes or invented numbers to make totals balance — both explicitly and heavily penalized.
4. Over-correcting documents that don't actually need a fix — penalized more than doing nothing.
5. Missing that at least one document (credit memo, delivery note, or non-payable form) needs different handling than a standard invoice — several such cases are confirmed present in just the sampled subset.
6. Building per-document special-case logic that doesn't survive the held-back set.

## Biggest opportunities
- A genuinely unified model of "what a payable's derivation chain looks like" (discount → tax base → tax(es) → charges → withholding, in the order the document actually shows) will generalize far better than a flat extract-and-fill template — this is very likely the "shift" the brief deliberately withholds.
- Visible, deliberate restraint (non-empty `declined[]`, a non-trivial rate of blank codes) signals understanding of the grading rules rather than a "complete-looking but fabricated" output.
- A specific, well-reasoned `DESIGN.md` answer to "which document can't be solved" is explicitly called out as worth more than code that fakes an answer.

## Recommended direction (no code)
1. Manually review all 35 documents first (render every page, read it) and catalogue document type, currency, tax structure (single vs. multi-rate, header vs. line), and payable vs. non-payable — build your own ground truth before writing extraction code.
2. From that review, identify the recurring *structural patterns* (fee-then-tax-then-withholding chains, multi-rate per-line VAT, pure non-payables, credit memos) — design the pipeline around modeling those patterns generally, not around individual documents.
3. Build extraction (vision/OCR + a text-layer fast path) → normalization → tax/charge decomposition → master-data matching (scale-aware) → schema serialization, with an `erp.py` self-check loop used continuously but never as your only correctness signal, since it can't see structural placement or master-data legitimacy.
4. Write `DESIGN.md` last, from real notes kept during steps 1–3, so the three required answers are concrete and specific rather than generic.

See `ZYCUS_ASSIGNMENT_ANALYSIS.md` in this same folder for the full 22-section deep-dive (file inventory, full requirements list, schema cross-reference, master-data analysis, ambiguities, risks, and an acceptance checklist).
