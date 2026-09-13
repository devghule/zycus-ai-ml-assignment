# ARCHITECTURE.md — The Bookable Payable: Full Architecture Reference

> **Note on this file**: this is the full, detailed architecture design
> produced during Step 3 (pre-implementation planning), kept as a
> comprehensive engineering reference. The assignment's `DESIGN.md`
> (≤3 pages, answering three specific reflective questions) is a separate,
> short document at the repository root — see that file for the actual
> required submission deliverable. This document is supplementary context,
> not a replacement for it, and some of its forward-looking design
> proposals were adjusted during implementation (see `IMPLEMENTATION_PROGRESS.md`
> and `CORPUS_EVALUATION.md` for what was actually built and observed).

---

# The Bookable Payable: Solution Architecture (Full Reference)

*Step 3: architecture and design only. No implementation code. `erp.py` and all other kit files
are read-only inputs to this design and are not modified. Grounded in `STEP1_STEP2_ANALYSIS.md`
(the completed forensic read of all 42 documents and the technical contract); facts established
there are cited by document ID rather than re-derived.*

---

## 0. Framing: what this system actually is

The brief and the analysis converge on one point: this is not an extraction pipeline with a
classification step bolted on. It is an **adjudication system**. For every document it must
answer, with evidence it can point to, three questions — *is anything genuinely owed here*,
*what exactly does the document say is owed and by what structure*, and *which master-data codes
are provably this document's, versus honestly unknown*. Every stage below exists to serve one of
those three questions, and every stage is justified against a concrete failure mode the 42-document
corpus is already known to contain (HLD-01's tax-base trap, HLD-03's illegibility, HLD-08's
entity conflation, INV-23's two totals, INV-04/07's duplication, DU-05s/DU-09/DU-02's non-payable
bundling). Nothing below is designed to make these specific 42 PDFs pass; each stage is described
in terms of the general document property it detects, so it also fires correctly on a held-back
document that shares the property but not the filename.

---

## 1. End-to-end pipeline

```
Input discovery → Page rendering/OCR → Document segmentation (bundling detection)
→ Classification (payable / credit / non-payable / ambiguous)
→ Extraction (deterministic parse + LLM-assisted field capture)
→ Locale normalization → Canonical financial modeling
→ Master-data matching → Duplicate detection
→ ERP validation (erp.py) → Business-rule / groundedness validation
→ Output assembly (payables[] / declined[])
```

Stage-by-stage justification:

1. **Input discovery.** Dynamically lists `documents/*.pdf` at runtime. The kit's own 35-vs-42
   discrepancy is direct proof a hardcoded count/manifest is wrong; the held-back set will differ
   again. No stage anywhere may assume a document count or a fixed filename set.

2. **Page rendering/OCR.** Documents are scanned images with layout structure (tables, multi-column
   headers, stamps, embedded charts). A vision-capable extraction step is required, not
   text-layer PDF parsing alone — several PDFs (HLD-01, HLD-03, HLD-08) have corrupted or
   overlapping text layers where the *rendered* image is more trustworthy than the embedded text.

3. **Document segmentation / bundling detection — genuinely warranted, not generic boilerplate.**
   DU-02 (customs consolidated + 10 sub-invoices), DU-03 (tax invoice + cartage advice + customs
   forms + 5 waybills), DU-05s (11 delivery notes + waybills + a shipment receipt), and INV-09/
   DU-02/DU-03's page-2 customs declarations are all one PDF file containing multiple *logically
   independent* documents, only some of which are payables. Without an explicit segmentation
   stage, a per-file classifier is forced into an artificial single verdict for a file that
   actually contains zero, one, or several distinct documents — which is exactly the "0..N
   payables per file" shape the schema anticipates. Segmentation output is a list of
   `(page_range, doc_role_hint)` tuples; classification and extraction then run **per segment**,
   not per file. This is the one stage a naive design skips and then cannot correctly handle
   DU-02/DU-03/DU-05s at all.

4. **Classification** gates everything downstream — see §2.

5. **Extraction** happens only for segments classified as payable-shaped (invoice or credit
   memo) with sufficient confidence — see §3.

6. **Locale normalization** is a separate, narrow, purely-deterministic stage (not folded into
   extraction) because it is a mechanical transform (parse "1.234,56" → `1234.56`) that must be
   perfectly reproducible and independently testable — see §7.

7. **Canonical financial modeling** builds the internal representation that decides tax-base
   placement (line vs. header, taxed-together vs. post-tax) *before* touching `erp.py` — see §4.
   This is a separate stage from extraction because it requires cross-field reasoning (does this
   header charge's percentage tax match the document's own arithmetic if computed on goods-only,
   or on goods+charge?) that a field-by-field extractor should not be doing inline.

8. **Master-data matching** — see §5. Runs after the canonical model exists, because VAT-ID and
   country signals used for matching are stabilized by then.

9. **Duplicate detection** — see §6. Runs after extraction (needs invoice number/supplier/amount/
   date) but before final output, so a detected duplicate can still be recorded/flagged rather
   than silently dropped.

10. **ERP validation** calls the sealed `erp_book()` oracle to confirm the candidate payable's
    parts foot to the document's own stated gross, to the cent — see §9.

11. **Business-rule / groundedness validation** — the checks `erp.py` explicitly does not perform
    (real master code? real document value? sane cross-field relationships?) — see §9.

12. **Output assembly** writes `output/X.json` per input file, partitioning segments into
    `payables[]` and `declined[]`, guaranteeing a segment never appears in both.

Stages *not* included, with reasons: no separate "OCR correction" stage (folded into extraction,
since OCR errors are best resolved with document-image context, not as blind post-hoc string
repair); no generic "confidence aggregation" microservice (confidence is carried as a field on
each candidate object through the pipeline, not computed by a dedicated stage).

---

## 2. Document classification design

**Classes:** `PAYABLE_INVOICE`, `PAYABLE_CREDIT_MEMO`, `NON_PAYABLE` (with a decline taxonomy),
`AMBIGUOUS_UNSOLVABLE` (declined with an explicit "insufficient evidence" reason, distinct from
ordinary non-payable reasons).

**Signals used (deliberately generalizable, not per-document):**
- *Structural signals*: presence of a stated invoice number + a running-total footer arithmetic
  that closes (subtotal → tax → total chain foots); presence of a "Due Date"/payment-terms
  block; presence of both a supplier tax ID and a buyer address (bill-to).
- *Negative/decline signals*: explicit document-type words in the document's own language
  ("Mahnung"/dunning, "ESTIMATE"/quote, "Delivery Note"/"Waybill"/"Packing List", "Approval
  Form", "Customs Declaration", "Cartage Advice") — matched via semantic classification of the
  document's own heading text, not a fixed keyword list in one language, since the corpus already
  spans German, Estonian, Portuguese, Thai, Ghanaian English, etc. A held-back document in a new
  language must still be classifiable from its structural shape (no commercial bill-to, no
  discrete priced line items owed by the recipient) even if its heading word is unrecognized.
  This is why the classifier is signal-based, never a keyword dictionary alone.
- *Sign/reference signals* for credit memos: negative amounts on the page, or explicit
  "Credit Note"/"Kreeditarve"/"Gutschrift"-class headings, or an explicit reference to an
  original invoice being reversed.
- *Ambiguity signals*: two independent totals for the same apparent transaction that do not
  reconcile (INV-23); identity fields that are illegible due to overlapping/garbled rendering,
  detected as low OCR/vision-model confidence *combined with* internal inconsistency (garbled
  street names, mixed scripts) rather than merely "OCR was noisy" (HLD-03).

**Rules vs. LLM reasoning:** Rule-based checks handle unambiguous mechanical evidence (does the
arithmetic close; is there a bill-to and a due date; is the total negative). An LLM (vision +
text) handles semantic judgment: "given this document's stated purpose in its own words and its
relationship to the receiving entity, is this an amount currently owed by the buyer to the
supplier, or is it evidentiary/logistics/internal paperwork?" The LLM is prompted to output a
structured verdict plus a natural-language justification citing specific document text, which is
retained for audit and validation but never trusted blind (see §8, §9 groundedness checks).

**Confidence handling:** every classification carries a confidence score. High confidence →
proceed. Low confidence but leaning payable → proceed to extraction but mark the resulting
payable "low-confidence" so validation later applies a stricter agreement threshold. Low
confidence and no reconcilable path → `AMBIGUOUS_UNSOLVABLE`, decline with reason
`"insufficient_evidence"` rather than forcing a class. This directly implements README rule 1/2's
spirit at the classification layer: guessing a class is the same category of error as guessing a
number.

**Decline taxonomy (fixed, closed enum, used for `declined[].doc_type`):**
`DELIVERY_NOTE`, `WAYBILL_OR_SHIPPING_DOCUMENT`, `CUSTOMS_OR_LOGISTICS_PAPERWORK`,
`DUNNING_OR_REMINDER`, `INTERNAL_APPROVAL_OR_COMPLIANCE_FORM`, `QUOTATION_OR_ESTIMATE`,
`DUPLICATE_OF_BOOKED_PAYABLE`, `AMBIGUOUS_INSUFFICIENT_EVIDENCE`, `OTHER_NON_PAYABLE`. A closed
taxonomy (vs. free text per document) keeps `declined[].reason` auditable and testable; `reason`
remains free text giving the specific justification, `doc_type` is the closed category.

**Avoiding false-booking of the known trap shapes, stated generally:** a delivery note is
recognized by *absence* of a monetary obligation structure (quantities/dates but no priced
total owed), not by the words "delivery note"; a dunning letter is recognized by referencing a
prior invoice's balance rather than presenting new goods/services; a customs form is recognized
by being addressed to/from a customs authority rather than between commercial trading parties;
an internal approval form is recognized by lacking a supplier-to-buyer commercial relationship
(it's an internal sign-off artifact); an estimate/quote is recognized by explicit conditional
language ("pending deposit", "quotation valid until") even when it contains a fully-populated,
invoice-shaped totals table (INV-23) — this is precisely why "has a total" cannot be the payability
signal.

---

## 3. Extraction architecture

**What's deterministic vs. LLM-driven, stated up front:** anything that is a *lookup or format
transform* (locale-number parsing, date parsing, currency-symbol mapping) is deterministic
Python. Anything that requires *reading and interpreting a rendered page* (which text block is
the supplier vs. buyer, which column is really a per-unit price vs. a line extension, whether a
percentage is applied to goods alone or goods+fee) is LLM-driven, because these require visual/
semantic judgment no regex can generalize across the corpus's layout diversity. All arithmetic
happens later in `erp.py` and the canonical model, never inside extraction.

**Per-field extraction approach:**
- **Header identity fields** (supplier name/address/VAT ID, buyer name/address, invoice number,
  dates, currency, PO number): extracted via a structured-output LLM call against the rendered
  page image(s), with the VAT ID and invoice number cross-checked by a regex/format validator
  (VAT IDs have per-country checksum-shaped patterns; invoice numbers are checked for internal
  consistency across pages of the same document) before being accepted.
- **Line items**: extracted as a table (description, qty, unit price, line total, discount,
  per-line tax rate/amount) directly from the visual table structure. A **sanity check runs
  immediately**: does `qty × unit_price ≈ total` (within rounding)? If not — as with HLD-08's
  "Nett Price" column, which is actually the line extension, not a restated unit price — the
  extractor is instructed to re-derive `unit_price = total / qty` rather than trust the column
  label, and to flag which happened. This generalizes the HLD-08 lesson into a rule ("verify the
  qty×price identity; trust arithmetic over labels") rather than special-casing that document.
- **Header charges/discounts/taxes**: captured with their *placement as printed* (this line vs.
  header-once), and this placement is explicitly preserved into the schema's `taxes[]` vs.
  `line_items[].taxes[]` distinction — never collapsed for convenience (this is separately
  re-verified in §4 and §9, since it is independently graded per the brief).
- **Multi-page documents**: pages belonging to one logical document are extracted jointly (one
  extraction call sees all pages of that segment), so a total shown only on a later page (or,
  conversely, a document like HLD-05 where no single page shows a grand total) can still be
  reasoned over jointly; if no page-spanning total can be found or derived from the document's own
  sub-totals, the system does not invent one — it flags the document for the ambiguous-handling
  path (§10) rather than silently summing assumptions.
- **OCR errors / overlapping text / illegible fields**: extraction is instructed to report a
  field as *unknown* rather than guess when the model's own visual reading is inconsistent
  (mixed scripts in one address block, a street name incompatible with the stated country — the
  HLD-03 signature) — this is a generalizable check ("does this reading make internal sense"),
  not a lookup table of known-bad documents.
- **Varied layouts/countries/languages**: extraction is language-agnostic by design — the LLM
  reads in the document's own language and returns structured fields in the schema's fixed
  English keys; no per-country template library is built, since a held-back document may be
  in a language not seen in the open set.
- **Decimal/thousands separator variance**: extraction returns numbers *as printed*, including
  their original separators (e.g. "1.234,56"); normalization to dot-decimal happens in the
  dedicated locale stage (§7), not inside the extraction prompt, so the two concerns stay testable
  independently.

**Structured output contract:** extraction returns a strict JSON object mirroring
`AUTODRAFT_SCHEMA.md`'s payable shape plus a `confidence` and `evidence` (text/bbox pointers)
sidecar per field group, validated against a JSON Schema before proceeding; a response that fails
schema validation triggers one bounded retry with the validation error fed back into the prompt,
then a decline-as-ambiguous fallback rather than an unbounded retry loop.

---

## 4. Financial calculation model (canonical representation)

**Ground truth is `erp_book()`'s actual formula** (verified in the analysis, §7 of that report):

```
gross = Σ line_base(i) − |discount_amount|
        + Σ line_tax(i)
        + header_tax( Σ line_base(i) − |discount_amount| )
        + freight_charges + insurance_charges + extra_charges + excise_duties
```

with `line_base` applying a percentage or per-unit-spread absolute discount, and `freight/
insurance/extra_charges/excise_duties` **excluded** from the header tax base entirely.

**The canonical internal model**, built *before* any master-data matching or ERP call, represents
each monetary component with an explicit tag:

- `TAXED_LINE_ITEM` — a good/service/fee whose amount is meant to sit inside whatever base header
  or line taxes are computed on. Maps to `line_items[]`.
- `HEADER_DISCOUNT` — reduces the tax base. Maps to `discount_amount`.
- `POST_TAX_ADDITION` — a charge that the document adds *after* tax computation, outside the
  taxable base (freight/insurance/misc/excise as erp.py implements them). Maps to
  `freight_charges`/`insurance_charges`/`extra_charges`/`excise_duties`.
- `TAX` (header or line-scoped) — with explicit `rate` when the document states a percentage,
  or explicit `amount` when the document states a derived/compound figure directly (INV-09's
  import duties/customs VAT, stated as amounts with a nominal 0% rate — must NOT be back-solved
  into a fake rate).

**The decision rule that resolves the "taxed-together vs. post-tax" ambiguity** (the single most
important modeling decision in the whole design, per the analysis's INF-3): for every charge that
is not an obvious line good/service, the pipeline checks whether the document's own printed tax
amount is consistent with a base that *includes* that charge, or a base that *excludes* it, by
literally trying both and comparing to the document's own stated tax figure (a deterministic
arithmetic check, not an LLM guess). Whichever base reproduces the document's own printed numbers
is the base actually used, which mechanically forces the charge into `TAXED_LINE_ITEM` (schema:
a `line_items[]` entry) rather than `POST_TAX_ADDITION` (schema: `extra_charges` etc.) whenever
the taxed-together reading matches. This generalizes past HLD-01 to any document with a
percentage-based surcharge whose tax treatment is ambiguous by column label alone (INV-11's BAF
fuel surcharge, INV-16/HLD-10's fuel surcharges are the same shape).

**Walkthrough: HLD-01's management fee, reproduced exactly.**
Document: base 7,200.00 THB → +9% management fee (648.00) → VAT 7% on 7,848.00 (549.36) →
withholding 3% on 7,848.00 (−235.44) → net payable 8,161.92.

The canonical model represents this as:
- `line_items`: `[{description: "Staff 2 Units X 6 Days", qty: 12, unit_price: 600.00, total:
  7200.00}, {description: "Management Fee 9%", item_type: SERVICE, qty: 1, unit_price: 648.00,
  total: 648.00}]` — the fee is a genuine second line, **not** `extra_charges`, because the
  taxed-base check above shows 7,848 × 0.07 = 549.36 matches the printed VAT only when the fee is
  included in the base.
- `taxes` (header): `[{tax_name: "VAT", tax_rate: "7", tax_amount: "", tax_type_code:
  "TH_070_VAT"}, {tax_name: "Withholding Tax", tax_rate: "3", tax_amount: "-235.44",
  tax_type_code: "TH_WHT_003"}]` — VAT's amount is left blank so `erp.py` derives 549.36 from
  `net_base` (= 7,200 + 648 = 7,848, since no header discount exists); withholding is given as an
  **explicit negative amount** because the schema's rate field cannot itself encode sign, and
  `erp.py`'s `_header_taxes` sums given amounts directly — a derived-from-rate withholding would
  come out positive and wrongly increase the gross.
- ERP recompute: `item_discounted_total` = 7,200 + 648 = 7,848.00; `header_tax` = 549.36 +
  (−235.44) = 313.92; `other_charges` = 0 (nothing routed there). `gross = 7,848.00 − 0 + 0 +
  313.92 + 0 = 8,161.92`. Matches the document exactly, and the structure (fee as a real line,
  VAT/WHT at header, both keyed to the correct rates) mirrors what the document itself shows —
  satisfying both the numeric and the structural grading criteria.

**Credit memos**: sign convention is normalized at the canonical-model boundary — the model
always stores positive magnitudes internally with `invoice_type: CREDIT_MEMO` set once, regardless
of whether the source document printed negative numbers (DU-10, DU-11) or a "Credit Note" label
with positive numbers; this conversion happens exactly once, in one place, so it cannot be
applied inconsistently document-to-document.

**Multiple rates / compound taxes**: represented as multiple discrete `taxes[]` entries (never
blended into one weighted rate), each with its own `tax_rate`/`tax_amount`/`tax_type_code`,
matching the "components stay decomposed" requirement verbatim.

---

## 5. Master-data matching (scalable design)

**Explicit non-goal:** no stage ever performs an all-pairs comparison against a master table.
Every match is index/candidate-generation based, so the design is correct at the provided
handful-of-rows scale and unchanged in shape at a hundred-thousand-to-million-row scale.

**Per-master strategy:**

- **Suppliers** (`suppliers.json`): primary key is a normalized-VAT-ID exact-match index
  (VAT IDs are unique, transliteration-proof, and O(1) to look up via a hash index — the single
  most reliable field per the analysis). If no VAT-ID hit, fall back to a *blocked* fuzzy-name
  search: block candidates by country + normalized first n-gram/phonetic key (so the fuzzy
  comparison only ever runs against a small candidate set sharing country + a name prefix
  signature, never the full table), then score candidates on normalized-name edit distance
  *and* address overlap. A name-only match below a defensible similarity floor (chosen
  conservatively, e.g. requiring near-exact normalized-name equality, not merely shared common
  words like "Print"/"Distribution"/"Trading" that recur across unrelated entities in this
  corpus) is rejected rather than accepted as a low-confidence hit — blank beats guess.
- **Buyer / chart of books** (`chart_of_books.json`): keyed by buyer country (parsed from the
  buyer's address) → business unit/location. This is an inferential match (the document rarely
  says "BOLTGROUP" outright), so it is only accepted when the buyer's parsed country has **exactly
  one** BU in the master; if the buyer's country has zero BUs in the master (Portugal, Thailand,
  Denmark, Switzerland, Singapore all currently have none), the match is correctly left blank —
  this is not treated as an extraction failure, and the design explicitly forbids substituting
  the "closest" country's BU.
- **Tax codes** (`tax_master.json`): composite index on `(country, tax_type, rate)`, with rate
  compared at normalized fixed precision (e.g. "8.10%" and "8.1" treated as equal) to avoid
  string-format false negatives. Country is joined first because rate alone collides across
  countries (23% appears for both Poland and Portugal in the sample). No match at this composite
  key → blank `tax_type_code`, even though `tax_rate`/`tax_name` are still recorded from the
  document.
- **Payment terms** (`payment_terms.json`): keyword/alias substring match against the document's
  own payment-terms text (multilingual: "net 30", "Netto", "päeva", "dias") first; if no terms
  text is printed, fall back to day-count derived from `due_date − invoice_date`, but only when
  that derived day-count uniquely identifies one term code (the sample data's `Immediate`/
  `Monthly_in_advance` both being `days: 0` shows day-count alone can be ambiguous) — otherwise
  blank.
- **PO matching** (`po_master.json`): exact string match only, on the raw `po_number` as printed —
  PO numbers are identifiers, not names, so fuzzy matching is inappropriate here. Once matched,
  the PO's own `supplier_id`/`currency` are cross-checked against the document's independently
  matched supplier/currency as an integrity signal (agreement raises confidence; disagreement is
  logged, not auto-corrected — see rule 3 on over-correction). The overwhelming majority of
  printed PO numbers across the corpus are legitimately not in the master and are explicitly
  called out by the kit's own README as non-ERP references — this is expected, not a bug.

**Why "prefer blank over invented ID" is the stated policy, not just a fallback:** `erp.py` never
validates whether a master code is real (§7 of the analysis) — a fabricated code and a genuine one
are numerically indistinguishable to the oracle, so nothing downstream will ever catch a
fabrication automatically. The brief's rule 2 and the grading description ("a check of what the
oracle cannot see — that your codes are real") make this the one place a system can silently
cheat itself into a better-looking pass rate on the open set while catastrophically failing the
held-back set (which will contain entities not in this master by construction, exactly the
INV-31..37 pattern already observed). A blank code costs partial credit on one field; a fabricated
code that happens to be wrong is a Rule-2 violation and, unlike a blank, actively corrupts a
downstream real ERP's data if this were production. The asymmetry of consequences is why blank
strictly dominates a low-confidence guess.

---

## 6. Duplicate detection

**Detection layers, cheapest/most certain first:**
1. **File hash** (exact byte-identical PDFs) — catches INV-04/INV-07.
2. **Document hash after segmentation** (normalized rendered content hash) — catches a
   duplicate embedded as one of several segments in a larger bundle, or a re-scanned copy with
   different embedded metadata but identical content.
3. **Business-key match**: normalized `(supplier_id_or_name, invoice_number, invoice_date,
   gross_total, currency)` — catches INV-25's "Original"/"Duplicado" pair even though they are
   different pages within one PDF, and would catch a duplicate arriving as a *separate* file in
   a later batch run (important for idempotent re-runs, not just within-batch dedup).
4. **Near-duplicate text similarity** (normalized line-item text + amounts) as a lower-confidence
   signal for cases where the invoice number itself differs slightly (OCR noise) but everything
   else matches — used only to *flag*, never to auto-merge.
5. **Explicit "Copy" framing** (HLD-08's "Copy Tax Invoice" label) is captured as a document
   attribute even when no actual duplicate exists elsewhere in the batch, because it is evidence
   about *risk*, independent of whether a matching original was actually found this run.

**Auto-decline vs. flag — explicit decision:** layers 1–2 (byte-identical or content-identical)
**auto-decline** the second occurrence into `declined[]` with `doc_type:
DUPLICATE_OF_BOOKED_PAYABLE`, because there is no legitimate reading under which the same exact
document should be booked twice — the risk of a false decline is effectively zero. Layer 3
(business-key match on different-but-similar documents) **flags rather than auto-declines**: the
corpus explicitly contains a document (INV-04) whose "Amount Due" nets a prior credit, and the
system must not let a fuzzy business-key rule steamroll the *legitimately distinct* INV-14/INV-15
pair (identical totals, genuinely different invoices) into a wrongful auto-decline — a false
decline of a real payable is treated as a worse outcome here than surfacing a probable duplicate
for confirmation, consistent with §15's false-positive/false-negative asymmetry. Layer 4 is
always advisory only, never a decision on its own.

---

## 7. Locale normalization

A single, narrow, purely-deterministic module, run after extraction and before the canonical
model, responsible only for:
- **Numeric parsing**: disambiguating `1.234,56` (EU) vs `1,234.56` (US) vs `1234,56` (no
  thousands separator) using positional heuristics (a `,`/`.` followed by exactly two trailing
  digits and nothing after is the decimal separator; the other symbol, if present, is the
  thousands separator) plus a language/country signal from the document (a Portuguese or German
  document defaults EU-style on genuine ties). Every parsed number's *original string* is
  retained alongside the parsed value for audit.
- **Currency symbols**: symbol → ISO code mapping (€→ context-dependent EUR, R→ZAR, ฿ or Thai
  script cues →THB, etc.), cross-checked against any explicit currency code/IBAN country printed.
- **Negative/parenthetical numbers**: `(123.45)` and `-123.45` and a document-native minus sign
  are all normalized to a signed float before the credit-memo sign-flip logic in §4 runs.
- **Percentages**: strip `%`, keep as a bare number string per schema convention.
- **Dates**: parses `DD.MM.YYYY`, `DD/MM/YYYY`, `YYYY-MM-DD`, and explicitly non-Gregorian
  calendars observed in the corpus (Thai Buddhist Era: subtract 543 from the printed year) —
  implemented as a small table of calendar offsets keyed by detected script/locale, not a
  single hardcoded rule, so an unseen calendar system in the held-back set fails safely
  (field left blank + flagged) rather than silently mis-converting.

This stage never guesses when parsing is genuinely ambiguous (e.g., "10,000" with no other
context could be ten or ten-thousand) — it uses corroborating signals (does the resulting number
reconcile with qty×price or with a nearby stated total) before committing, and flags for review
otherwise.

---

## 8. LLM usage design

**Where the LLM adds value (semantic/visual judgment, no reliable deterministic substitute):**
- Document classification (payable/credit/non-payable/ambiguous) — §2.
- Semantic field extraction from a rendered page (who is supplier vs. buyer when labels are
  absent or contradictory, which column is truly the unit price) — §3.
- Ambiguous entity resolution (HLD-08's three-name conflation) — reasoned about explicitly with
  the *layout convention* it relies on (VAT number position implies issuer identity) stated in the
  output, so the reasoning is auditable and disputable, not a black-box guess.
- Tax interpretation in translation (mapping "IVA"/"KM"/"Moms"/"NHIL" to the schema's `tax_type`)
  and initial hypothesis for whether a charge sits inside or outside a tax base (though the final
  decision is deterministically verified per §4, not LLM-asserted).
- Payability reasoning in the document's own language and cultural/format context.
- Structured JSON generation of the final extraction shape.

**Where deterministic Python is mandatory, never delegated:**
- All arithmetic: line bases, discounts, tax amounts, gross totals — computed only by `erp.py`
  (for the ERP-facing gross) and by the canonical model's own reconciliation checks (for the
  taxed-base decision in §4). The LLM never states a number and has that number trusted as the
  system's answer without a numeric consistency check.
- Locale parsing (§7), duplicate hashing (§6 layers 1–2), and master-data index lookups (§5) —
  all pure functions with no ambiguity worth spending model judgment on.

**Prompt design principles:** every extraction/classification prompt (a) shows the rendered
page image(s), never OCR text alone, since layout carries meaning (column position implies
semantics, as HLD-08 shows); (b) requires a strict JSON Schema-conformant response with a
`confidence` and short `evidence` justification per field group, so hallucination is at least
visible and auditable; (c) explicitly instructs the model that leaving a field blank/null is
correct and preferred over guessing, mirroring the brief's own rules, since models otherwise
default to "helpfully" filling every field; (d) never asks the model to compute a final gross,
tax amount from a rate, or master code match — those are always deterministic follow-up steps.

**Post-hoc validation / hallucination prevention:** every LLM-extracted numeric or identity value
is checked against the source: numbers via the qty×price/subtotal-foots consistency checks (§3),
identity strings via presence-in-document string matching (a name the model "extracted" that does
not actually appear, verbatim or near-verbatim, anywhere in the OCR'd/rendered text is rejected
and the field is blanked) — this is the concrete mechanism behind the "groundedness" validation
layer in §9.

**Retry/fallback:** schema-invalid responses get one retry with the validation error appended to
the prompt; a second failure or a low-aggregate-confidence result routes the segment to
`AMBIGUOUS_UNSOLVABLE` rather than looping indefinitely or accepting a poor-quality guess.

**Confidence handling:** confidence is per-field, propagated through extraction → matching →
validation, and the final payable carries an aggregate confidence used only for
logging/prioritizing human review — it never itself changes what gets booked; booking is decided
by the deterministic validation gates in §9, not by a confidence threshold alone, so confidence
never becomes a backdoor for "close enough" fabrication.

---

## 9. Validation layers

| Layer | Checks | Failure mode |
|---|---|---|
| **Schema validation** | Payable JSON conforms exactly to `AUTODRAFT_SCHEMA.md` (required keys present, types correct, enums valid) | **Hard failure** — payable is not emitted; segment routed to ambiguous/decline with a schema-error reason |
| **Financial (ERP) validation** | `erp_book(payable)["will_book_gross"]` equals the document's own stated `gross_total` to the cent | **Hard failure** — if it does not match after the taxed-base reconciliation in §4, the payable is not emitted as-is; either the modeling is retried with the alternate base hypothesis, or (if neither reproduces the total) the document is routed to the unsolvable path (§10) |
| **Groundedness validation** | Every emitted value (numbers and identity strings) is traceable to specific document text/region, per §8's post-hoc check | **Hard failure** for fabricated numeric values (Rule 1 is non-negotiable); ungrounded identity strings are blanked rather than failing the whole payable |
| **Master-data validation** | Every non-blank `_id`/`_code` field is a real key present in the corresponding master file (a final defensive check, in addition to only ever writing values sourced from an actual match) | **Hard failure** — any code not traceable to an actual master lookup is stripped to blank before output, never allowed through even if it "looks right" |
| **Business-rule validation** | Currency present and consistent across lines; `invoice_date` ≤ `due_date` when both present; credit memos carry positive magnitudes with `invoice_type: CREDIT_MEMO`; a matched PO's currency/supplier agrees with the document's own (§5); tax placement (header vs. line) matches what was detected in the document (§4); duplicate-risk flags attached (§6) | **Warnings**, logged and attached as metadata — except the credit-memo sign convention and tax-placement-mirrors-document rules, which are hard failures since they are explicitly, separately graded per the brief |

Validation order matters: schema → groundedness/master-data → financial → business-rule, so a
structurally invalid or fabricated payable never even reaches the (expensive, and per-payable)
ERP call.

---

## 10. Unsolvable-document handling

**Concrete example: INV-23.** The document is a Ghanaian customs "ESTIMATE" (cover total
13,724.19 GHS) with an attached ICUMS duty-calculator printout stating a different total
(13,289.19 GHS) for what appears to be the same shipment. Neither page is itself a payable
(an estimate is explicitly conditional/pending; a duty-calculator printout is a computation tool's
output, not a supplier's invoice) — so the classification stage would decline both on payability
grounds regardless. But even setting classification aside, the deeper point (and the reason this
is the report's leading nominee for "a document that asks something the page does not contain the
answer to") is that **the page itself contains two different numbers for the same event with no
stated reconciling relationship between them** — there is no textual or arithmetic path from one
figure to the other visible on the document. A system that picked either number to "complete" a
payable would be manufacturing a fact the page does not support, which is a more precise version
of the same violation as inventing a number from nothing: *choosing between two printed-but-
irreconcilable numbers is still a guess, dressed up as a citation.*

**What the system does instead:** decline the document (or, if classification alone did not
already decline it, still refuse to emit a payable at the reconciliation step) with
`doc_type: AMBIGUOUS_INSUFFICIENT_EVIDENCE` (or the more specific non-payable type, since both
apply here) and a `reason` that names the conflict explicitly ("cover total and attached duty
calculator disagree; no reconciling figure present on the document"). This is preferred over
guessing because: (a) the brief's own rules and grading description treat a confident wrong
answer as worse than an honest decline; (b) `erp.py` will happily compute *a* gross from either
number — passing that check numerically proves nothing about correctness, since the whole failure
mode here is that "arithmetically consistent" and "actually true" have come apart; (c) a system
that resolves this kind of conflict by picking a number will, on the held-back set, resolve some
future analogous conflict silently and wrongly, which is exactly the generalization failure the
open/held-back gap is designed to expose.

**Secondary example: HLD-03.** The supplier/buyer identity block is genuinely illegible due to
overlapping text layers baked into the source rendering (confirmed by an internal inconsistency
check: an Estonian street name appearing inside what should be a Lisbon address, proving the
overlap is a rendering artifact, not just noisy OCR). Here the *document as a commercial event* is
still solvable (the totals arithmetic foots cleanly to 67.25 EUR) — only the identity fields are
unsolvable. The system's response is narrower than INV-23's: still emit the payable (financial
data is genuinely there and grounded), but leave `supplier.supplier_id`, buyer codes, and even
`supplier.name`/`address` blank or best-effort-flagged rather than asserting a confident reading
of text that cannot actually be read. This distinguishes "the whole document is unsolvable"
(INV-23) from "specific fields within an otherwise solvable document are unsolvable" (HLD-03) —
both are legitimate outcomes, and the design treats them as different granularities of the same
underlying discipline rather than collapsing every hard case into one blunt "decline everything"
reflex.

---

## 11. Project structure

Given a 4-day take-home, the structure below optimizes for reviewer clarity and testability over
framework completeness — no web server, no database, no queue system, since the brief asks for
"one command over a folder."

```
solution/
  README.md                     # the one documented run command
  pyproject.toml / requirements.txt
  run.py                        # entry point: discovers documents/, writes output/
  config.py                     # thresholds, model name/version, confidence floors
  pipeline/
    discovery.py                # input discovery (dynamic)
    ocr_render.py                # page rendering + OCR/vision call wrapper
    segmentation.py               # bundling detection
    classification.py             # §2
    extraction.py                  # §3 (LLM calls + schema validation of raw extraction)
    locale_normalize.py            # §7 (pure functions, heavily unit-testable)
    financial_model.py             # §4 canonical model + taxed-base reconciliation
    matching/
      suppliers.py                # §5 per-master matcher
      chart_of_books.py
      tax_master.py
      payment_terms.py
      po_master.py
      index.py                    # shared indexing/candidate-generation primitives
    duplicates.py                  # §6
    erp_validate.py                 # wraps erp.py's erp_book(), never modifies it
    business_rules.py               # §9 non-ERP validations
    assemble_output.py              # payables[]/declined[] partition + schema-final-check
  tests/
    unit/                          # locale parsing, tax calc reconciliation, matcher scoring, dedup keys
    integration/                   # per-stage pipeline wiring on synthetic fixtures
    corpus/                        # the 42 known docs as named regression cases (§14)
  master_data/  (kit-provided, read-only)
  documents/    (kit-provided, read-only)
  output/       (generated)
```

**Against the example structure implied by the kit** (a flat `erp.py`/`example_check.py`
pair with no package structure): that shape is appropriate for a single-file oracle a candidate
calls into, not for the actual deliverable, which has ~10 independently testable concerns.
Splitting `matching/` per master file (rather than one monolithic matcher) is deliberately chosen
because each master has a genuinely different matching strategy (§5) and independent unit tests
per master read far more clearly than one large conditional matcher. `financial_model.py` is kept
separate from `extraction.py` because the taxed-base reconciliation in §4 is a distinct
deterministic-reasoning concern from LLM-driven field capture, and needs its own focused unit
tests (feed it known-good and known-ambiguous charge placements) independent of any LLM call.
No `models/`, `services/`, `repositories/` layering — that ceremony buys nothing at this scale
and would cost meaningful implementation time better spent on the matching/reconciliation logic
that actually determines the score.

---

## 12. Major interfaces / classes / functions

Only abstractions earning their existence are kept; each entry states why.

- **`discover_documents(dir) -> list[Path]`** — dynamic glob, no manifest. Trivial but load-bearing
  (kills the 35-vs-42 hardcoding trap at the source).
- **`DocumentSegmenter.segment(pdf) -> list[Segment]`** — Input: rendered pages. Output: page
  ranges + a coarse role hint (`likely_payable`/`likely_supporting`). Dependency: vision LLM call.
  Failure behavior: if segmentation confidence is low, falls back to treating the whole file as one
  segment (never silently drops pages) — a conservative default, not a crash. *Justified*: without
  it, DU-02/DU-03/DU-05s cannot be correctly handled at all (§1).
- **`DocumentClassifier.classify(segment) -> Classification{label, confidence, evidence}`** —
  Input: one segment. Output: one of the four classes (§2) + evidence. Dependency: LLM + rule
  checks. Failure behavior: below-floor confidence → `AMBIGUOUS_UNSOLVABLE`, never a forced guess.
  *Justified*: this is the pipeline's single most consequential decision point.
- **`DocumentExtractor.extract(segment) -> RawExtraction`** — Input: one payable-classified
  segment. Output: schema-shaped raw values (pre-locale-normalization) + per-field confidence/
  evidence. Dependency: vision LLM, JSON-schema validator. Failure behavior: schema-invalid after
  retry → decline as ambiguous. *Justified*: isolates the one LLM call whose output shape must be
  strictly validated.
- **`normalize_locale(raw: RawExtraction) -> NormalizedExtraction`** — pure function, no LLM,
  fully unit-testable (§7). *Justified* as its own function specifically so it can be unit-tested
  against dozens of format-variance cases independent of any model call.
- **`FinancialModelBuilder.build(NormalizedExtraction) -> CanonicalPayable`** — Input: normalized
  fields. Output: schema-shaped payable with charges correctly tagged per §4's reconciliation
  (including the try-both-bases check). Dependency: none but arithmetic + `erp_book()` for the
  trial recomputes. Failure behavior: if no tagging reproduces the document's stated total, returns
  an "irreconcilable" marker consumed by §10's unsolvable-handling path rather than picking either
  guess. *Justified*: this is the component that actually encodes the HLD-01 lesson generically.
- **`MasterDataMatcher` (one per master, sharing an `Index` interface: `candidates(query) ->
  list[Candidate]`, `score(query, candidate) -> float`)** — Input: a canonical payable's relevant
  fields. Output: `(code, confidence)` or `(None, reason)`. Dependency: pre-built indexes over the
  master file (§5). Failure behavior: below-floor score → `None`, never the best-available
  candidate. *Justified*: kept as five small, independently testable matchers rather than one
  generic "master matcher," because the matching *strategy* genuinely differs per master (VAT-ID
  vs. country-inference vs. composite-key vs. exact-only) — collapsing them would hide that
  the strategies are not interchangeable.
- **`DuplicateDetector.check(payable, batch_index) -> DuplicateVerdict{is_duplicate, layer,
  confidence}`** — Input: one candidate payable + an in-memory/on-disk index of already-processed
  payables in this run (and, ideally, prior runs, for cross-run idempotency). Output: verdict +
  which layer fired (§6). Failure behavior: ambiguous near-duplicate signals never auto-decline,
  only flag. *Justified*: a distinct concern from matching (compares payables to each other, not
  to master data).
- **`ERPValidator.validate(payable) -> {matches: bool, will_book_gross, stated_gross}`** — thin
  wrapper around the *imported, unmodified* `erp_book()`. *Justified* as a thin wrapper (not
  reimplementing erp.py) specifically to satisfy the "import/wrap only" constraint while giving
  the rest of the pipeline a stable call signature and a place to log mismatches.
- **`BusinessRuleValidator.validate(payable) -> list[Finding{rule, severity, message}]`** —
  Implements §9's non-ERP checks; `severity` distinguishes hard failure from warning.
- **`OutputWriter.write(file, payables, declined)`** — final schema-conformant serialization,
  guarantees no segment appears in both lists (pipeline invariant checked here as a last gate).

**Abstractions explicitly rejected as unnecessary ceremony for a 4-day project:** a generic
plugin/strategy registry for classifiers (five master matchers are enough variety to justify
per-master classes; a full plugin architecture is not); a message-queue-based orchestrator (a
plain in-process loop with per-document isolation, §13, is sufficient at this scale); a separate
"Normalizer" class distinct from `normalize_locale` (a module of pure functions is simpler and
just as testable as a class with no state).

---

## 13. Orchestration strategy

- **Input discovery** is dynamic (§1/§12) — never a fixed count or manifest.
- **Per-document processing** runs each PDF's pipeline independently; **error isolation** wraps
  each document's full pipeline in a try/except at the top level of `run.py` — an exception
  anywhere in one document's stages is caught, logged with the file name and stage, and results in
  that file's `output/X.json` containing an empty `payables[]` plus a `declined[]` entry with
  `doc_type: OTHER_NON_PAYABLE` (or a dedicated `PROCESSING_ERROR` reason) rather than crashing
  the batch or omitting the output file entirely — every input file gets a corresponding output
  file, always.
- **Logging**: structured per-document, per-stage logs (classification verdict + confidence,
  extraction confidence, financial reconciliation outcome, matching results, ERP validation
  pass/fail) written alongside `output/`, so a reviewer or the candidate can audit *why* any given
  document landed where it did without re-running the LLM calls.
- **Retries**: bounded, stage-local (one retry on schema-invalid LLM output per §8); no
  batch-level retry loop.
- **Output naming**: `output/<source_stem>.json`, deterministic given the input filename, matching
  the brief's contract exactly.
- **Determinism**: the deterministic stages (locale normalization, financial modeling arithmetic,
  matching, dedup, ERP validation) are fully deterministic given the same extraction output; the
  LLM-driven stages are pinned to a fixed model version/temperature=0 (or lowest available) to
  minimize run-to-run variance, and raw extraction output is cached per document hash so a re-run
  over the same file does not re-call the model unnecessarily.
- **Parallelization feasibility**: documents are independent units of work (no cross-document
  state except the duplicate-detection index, which is append-only and can be built incrementally),
  so per-document processing parallelizes trivially (a process/thread pool sized to the LLM
  provider's rate limits); the only serialization point is writing to the shared duplicate index,
  which needs a lock or a single-writer queue.

---

## 14. Testing strategy

**Unit tests** (deterministic, no LLM calls, fast):
- Locale/number parsing: `1.234,56`→`1234.56`, `1,234.56`→`1234.56`, negative/parenthetical
  forms, percentage stripping, Thai BE date conversion, and other calendar/format edge cases.
- Tax calculation reconciliation: given known line/header structures, confirm `erp_book()`
  produces the expected gross (property-based tests against the documented formula).
- Discount calculation: percentage vs. absolute-per-unit-spread discount behavior (the
  `_line_base` subtlety in erp.py) verified with hand-computed expected values.
- Master-data matching: per-matcher unit tests with synthetic near-miss and true-miss cases
  (e.g., a supplier name sharing "Print"/"Trading" with a master entry but different country/VAT
  → expect no match), confirming the conservative floor actually rejects plausible-looking
  false positives.
- Duplicate detection: byte-identical, business-key match, and legitimately-distinct-but-
  same-amount cases (mirroring INV-14/INV-15) produce different verdicts.
- Classification rules: synthetic documents exercising each decline category and each
  ambiguous-signal type.

**Integration tests**: full PDF → extraction → normalization → validation → ERP-validation
pipeline run on a handful of representative synthetic or redacted fixtures, checking the
pipeline's stage-to-stage data contracts (schema conformance at each boundary) independent of the
corpus's specific documents.

**Corpus tests** (named regression cases over the 42 provided documents, used as a *regression
safety net*, not as the design's target — the design must not be tuned to make these pass by
special-casing):
- `HLD-01` — asserts the management fee lands as a `line_items[]` entry (not `extra_charges`) and
  the recomputed gross equals 8,161.92 THB with VAT=549.36, WHT=−235.44.
- `HLD-03` — asserts the payable is still emitted (67.25 EUR) with `supplier.supplier_id` and
  buyer codes blank, and that no fabricated name is asserted despite the illegibility.
- `HLD-05` — asserts multiple IVA rate buckets are preserved as distinct `taxes[]`/line-tax entries,
  not blended.
- `HLD-08` — asserts `unit_price` is correctly derived as 276.74 (not 129,514.32), and that the
  entity-conflation is either resolved with an explicit caveat or fields are conservatively left
  blank rather than confidently wrong.
- `INV-23` — asserts the document is declined (not booked) with a reason citing the two
  irreconcilable totals.
- Credit memos (`DU-10`, `DU-11`) — assert positive-magnitude output with `invoice_type:
  CREDIT_MEMO` despite differing native sign conventions (UK vs. Estonian formats).
- Multi-rate-tax docs (`DU-06`, `INV-13`) — assert each rate bucket survives as a separate tax
  entry and the gross reconciles.
- The `INV-04`/`INV-07` duplicate pair — assert the second is declined as
  `DUPLICATE_OF_BOOKED_PAYABLE` and the first books the invoice's own gross (19,730.55), not the
  netted "amount due" (6,620.55).
- The off-universe cluster (`INV-31`..`INV-37`) — assert supplier/buyer/tax/PO codes are all blank
  across the entire cluster (a "master-data honesty" regression test, checked in aggregate).
- Docs with no master-data match generally (the majority of the 42) — assert the *modal* expected
  output profile is mostly-blank codes, and add an aggregate test that fails if the match rate
  across the whole corpus is implausibly high (a canary against an overly permissive fuzzy
  matcher creeping back in during future changes).

**Explicit test-design discipline**: corpus tests assert *properties* (blank codes, correct
structural placement, correct decline reasons) rather than hardcoding exact LLM output text,
so the tests remain meaningful if the extraction model's phrasing changes, and so passing them
is evidence of correct general behavior, not memorization of these 42 answers.

---

## 15. Evaluation metrics

- **Payability-classification accuracy** (precision/recall per class, not just overall accuracy —
  README's "how you are judged" section directly ties this to score).
- **Field-extraction accuracy** (per-field exact/normalized match rate against ground truth where
  available).
- **Supplier/buyer/tax/PO matching accuracy**, reported separately as **match precision** (of
  codes emitted, how many are correct) and **match recall** (of documents with a genuine master
  hit, how many were found) — precision matters far more here per Rule 2.
- **Tax accuracy**: correct rate, correct amount, correct placement (header vs. line) as three
  separate sub-metrics, since the brief grades placement independently of amount.
- **Gross-total reconciliation rate**: fraction of emitted payables whose `erp_book()` result
  matches the document's stated gross to the cent.
- **Schema validity rate**: fraction of outputs that are structurally valid per
  `AUTODRAFT_SCHEMA.md`.
- **False-booking rate**: non-payables incorrectly emitted into `payables[]` — the analysis (§15
  below) and the brief both treat this as the worst failure category.
- **False-decline rate**: genuine payables incorrectly routed to `declined[]`.
- **Duplicate-detection rate**: true duplicates caught vs. missed, and false-duplicate flags on
  genuinely distinct documents (the INV-14/INV-15 trap).
- **Coverage**: fraction of the corpus (open and, by extension, expected on held-back) that
  produces *any* determination (payable or declined) rather than an unhandled processing error.

**Explicit priority statement**: false-booking (wrongly booking a non-payable, or booking with a
fabricated master code) is weighted worse than false-decline (conservatively declining a
genuinely ambiguous document), matching the brief's own framing that a confident wrong answer
costs more than an honest "I don't know." Any metric dashboard for this system should surface the
false-booking rate first, not overall pass rate, since overall pass rate alone rewards exactly the
over-eager behavior the brief warns against.

---

## 16. Implementation priority for a 4-day take-home

**Must-have** (drives the majority of the score; without these the system cannot pass the
brief's own stated grading criteria):
- Dynamic input discovery + one-command batch runner with per-document error isolation (§1, §13).
- Classification stage with a real decline taxonomy (§2) — the single highest-leverage piece,
  since booking a non-payable is the worst failure mode.
- Deterministic locale normalization (§7) and the canonical financial model with the taxed-base
  reconciliation (§4) — this is what actually makes HLD-01-shaped documents (and the generalized
  class they represent) book correctly, not just the sample-simple ones.
- `erp_book()` integration as the financial validation gate (§9).
- Conservative master-data matching for at least suppliers (VAT-ID + blocked fuzzy name) and
  chart-of-books (country-keyed), with "blank is correct" enforced as a hard rule (§5).
- Basic duplicate detection (file hash + business-key) (§6).
- Schema-conformant output assembly (§1, §12).

**Should-have** (meaningfully improves score, not load-bearing for basic correctness):
- Payment-term and PO matching (§5) — smaller share of fields, but still explicitly graded.
- Groundedness post-hoc validation of LLM-extracted values (§8/§9) — protects against
  hallucination the schema/ERP checks alone would not catch.
- Multi-page/multi-segment document handling for bundled PDFs (§1 segmentation) — needed
  specifically for DU-02/DU-03/DU-05s-shaped documents, a meaningful but bounded slice of the
  corpus.
- Near-duplicate flagging beyond exact hash/business-key (§6 layer 4).
- Structured per-stage logging for auditability (§13).

**Nice-to-have** (polish, given remaining time):
- Confidence-score surfacing in output metadata for human review prioritization.
- Parallelized batch execution (§13) — valuable mainly at larger corpus sizes than 42.
- A richer calendar-normalization table beyond Thai BE (other non-Gregorian calendars not yet
  observed in the open set).
- An evidence/audit-trail export per field (bounding boxes or text spans) beyond the minimum
  needed for groundedness validation.

Priority ordering is driven by the metrics in §15: classification and the financial model
directly gate the false-booking rate and gross-reconciliation rate, which the brief weights most
heavily; matching precision and duplicate detection are meaningfully scored but narrower in
blast radius; logging/parallelism/audit polish do not move the pass rate at all and are
correctly last.

---

## 17. Risks and traps

- **erp.py's tax-base exclusion of freight/insurance/extra/excise charges** — the single highest-
  risk misunderstanding; any charge genuinely taxed alongside goods must never be routed to these
  fields no matter how much its label resembles them (§4).
- **Line-vs-header tax placement** — graded independently of the numeric gross; a system that only
  optimizes for `will_book_gross` matching can still fail outright on structure.
- **Explicit vs. derived tax amounts** — a document that states an amount directly at a nominal 0%
  rate (INV-09) must not be back-solved into an invented percentage.
- **Credit-memo sign conventions** — differ by jurisdiction on the page but must always normalize
  to one internal convention.
- **Net-unit-price requirements** — a line-extension column mislabeled as "unit price" (HLD-08)
  will silently corrupt every downstream tax calculation if trusted at face value; the qty×price
  identity check is the generalizable defense.
- **Master-data hallucination risk** — the highest-consequence risk category, since `erp.py`
  cannot catch it and the brief explicitly grades for it; the design's layered defense is
  index-based matching with a conservative floor plus a final master-data validation gate (§9).
- **Locale-parsing risk** — ambiguous separator conventions without corroborating context; the
  mitigation is cross-checking parsed numbers against nearby arithmetic (qty×price, stated
  subtotals) rather than parsing in isolation.
- **Duplicate invoices** — both the "same document twice" (INV-04/07, INV-25) and the inverse trap
  of "different documents, same amount" (INV-14/INV-15) must be distinguished, not conflated.
- **Non-payable invoice-like documents** — the dominant volume risk in this corpus; a
  classification stage that is too permissive drives the false-booking rate up directly.
- **Missing BU/master records for entire countries** — Portugal/Thailand/Denmark/Switzerland/
  Singapore have no buyer BU at all in the sample master; a system must not "round" a document's
  country to the nearest available BU.
- **Off-universe document clusters** (INV-31–37 pattern) — a real risk the held-back set will
  very likely repeat in a different guise; the general defense is match-floor discipline, not
  a blocklist of specific off-universe entity names.
- **HLD-03-style illegibility** — the risk is not the illegibility itself but a system's temptation
  to produce a plausible-sounding reading anyway; internal-consistency checks (script/geography
  mismatches) are the generalizable detector.
- **HLD-08-style entity ambiguity with no From/To labels** — layout-convention reasoning (VAT
  number position implies issuer) is a judgment call that must be flagged as such, not asserted
  with false confidence.
- **INV-23-style conflicting totals** — the risk is treating "the arithmetic closes" as proof of
  truth when two closed-but-different arithmetics both exist on the same page.
- **Additional risk — over-correction (Rule 3):** any auto-fix logic (e.g., "correcting" a
  seemingly swapped supplier/buyer, or normalizing an odd-looking total) must be independently
  justified per instance and must be demonstrably safe against documents that only *look* like
  they need the fix; without disciplined scoping, a fix layer built to rescue one hard document
  will corrupt several already-correct ones elsewhere in the corpus (and, more dangerously, in
  the held-back set, where the specific triggering shape cannot be anticipated).
- **Additional risk — LLM run-to-run variance**: without pinned model settings and cached raw
  extraction, re-running the "one command" could non-deterministically change which documents
  pass, undermining both grading reproducibility and the open/held-back consistency the brief
  measures.
- **Additional risk — silent stage failures masking as "no match":** a bug in an indexer or a
  malformed master-data load could make every lookup fail closed, which looks identical to
  "correctly mostly-blank" output; the design mitigates this with the canary aggregate test in
  §14 (flagging an implausibly *low* match rate, not just an implausibly high one) and stage-level
  logging (§13) so a systemic failure is distinguishable from correct conservatism.

---

## 18. Final Design Decision

### Recommended Architecture

The recommended system is a segmentation-first, classification-gated pipeline that treats every
document as a claim to adjudicate rather than a form to transcribe. Documents are dynamically
discovered and, where a single PDF bundles multiple logical documents, split into segments before
any payability judgment is made. Each segment is classified into payable/credit/non-payable/
ambiguous using a mix of deterministic structural checks and LLM-driven semantic reasoning over
the rendered page, with a hard bias toward declining rather than guessing when evidence is thin.
Payable-classified segments are extracted (vision-LLM, strictly schema-validated, with immediate
arithmetic sanity checks against qty×price identities), then passed through a purely-deterministic
locale-normalization stage, then into a canonical financial model that explicitly resolves the
recurring "is this charge taxed together with the goods, or added after tax" ambiguity by trial
recomputation against `erp.py` rather than by LLM guess or column-label trust. Master-data matching
is index-based per master (VAT-ID/exact keys first, blocked fuzzy search only as a bounded
fallback, always defaulting to blank over a low-confidence guess), duplicate detection runs in
layered tiers from certain (byte/content-identical) to advisory (near-duplicate text similarity),
and every candidate payable must clear schema, groundedness, master-data-reality, ERP-gross, and
business-rule validation gates before being emitted — with false-booking treated throughout as a
strictly worse outcome than a conservative decline. The project structure favors a small number
of independently testable modules over generic frameworks, appropriate to a 4-day build, and
testing is organized around properties (correct placement, correct decline reasons, honest blanks)
rather than memorized answers to the 42 known documents, since the system's real target is the
generalization gap the brief measures on the held-back set.

```
Processing flow:
  discover_documents(documents/)
    -> for each pdf (parallel, isolated):
         render_pages(pdf)
         segments = segment_bundling(pdf)          # 0..N logical sub-documents
         for each segment:
             classification = classify(segment)     # payable | credit | non-payable | ambiguous
             if classification in {non-payable, ambiguous}:
                 declined.append({doc_type, reason})
                 continue
             raw = extract(segment)                  # schema-shaped, LLM + arithmetic sanity checks
             normalized = normalize_locale(raw)
             canonical = build_financial_model(normalized)   # taxed-base reconciliation via erp.py trials
             if canonical is irreconcilable:
                 declined.append({doc_type: AMBIGUOUS_INSUFFICIENT_EVIDENCE, reason})
                 continue
             canonical = match_master_data(canonical)         # per-master indexed lookups, blank-by-default
             dup_verdict = check_duplicates(canonical, batch_index)
             if dup_verdict.auto_decline:
                 declined.append({doc_type: DUPLICATE_OF_BOOKED_PAYABLE, reason})
                 continue
             findings = validate(canonical)                    # schema, groundedness, master, ERP, business rules
             if findings.hard_failure:
                 declined.append({doc_type: ..., reason: findings.summary})
                 continue
             payables.append(canonical)
         write output/<pdf_stem>.json {file, payables, declined}
```

```
Core components:
  DocumentSegmenter      -> Segment[]
  DocumentClassifier      -> Classification{label, confidence, evidence}
  DocumentExtractor        -> RawExtraction{fields, confidence, evidence}
  locale_normalize()        -> NormalizedExtraction        (pure function)
  FinancialModelBuilder      -> CanonicalPayable | Irreconcilable
  MasterDataMatcher (x5)      -> (code, confidence) | (None, reason)
  DuplicateDetector             -> DuplicateVerdict
  ERPValidator (wraps erp.py)    -> {matches, will_book_gross, stated_gross}
  BusinessRuleValidator            -> Finding[]
  OutputWriter                      -> output/<file>.json
```

```
Data flow:
  PDF bytes
    -> rendered page images
    -> Segment[] (page ranges + role hint)
    -> RawExtraction (schema-shaped, locale-raw values + confidence/evidence)
    -> NormalizedExtraction (dot-decimal numbers, ISO dates, ISO currency)
    -> CanonicalPayable (charges tagged TAXED_LINE_ITEM / HEADER_DISCOUNT / POST_TAX_ADDITION / TAX,
                          credit-memo sign normalized)
    -> CanonicalPayable + master codes (blank where no genuine match)
    -> CanonicalPayable + duplicate verdict
    -> validated Payable (AUTODRAFT_SCHEMA.md-conformant) | declined entry
    -> output/<file>.json {file, payables[], declined[]}
```

```
Validation flow:
  schema_validate(payable)          -- hard fail -> declined
    -> groundedness_check(payable)   -- hard fail (fabricated number) -> declined
                                       -- (ungrounded identity string -> blank field, continue)
    -> master_data_reality_check(payable)  -- hard fail (non-real code) -> code stripped to blank
    -> erp_validate(payable)          -- hard fail (gross mismatch after reconciliation attempts) -> declined
    -> business_rules(payable)         -- hard fail: sign convention / tax placement -> declined
                                         -- warning: PO/supplier/currency cross-check disagreement -> logged, kept
    -> emit to payables[]
```

```
Implementation order:
  Phase 1 (Day 1):   Input discovery, batch runner + error isolation, erp.py wrapper,
                      AUTODRAFT_SCHEMA.md-conformant output assembly on a stub payable,
                      end-to-end plumbing proven on 2-3 simplest documents (INV-01, INV-20, INV-33).
  Phase 2 (Day 1-2): Classification stage + decline taxonomy; extraction stage with schema
                      validation and qty*price sanity checks; locale normalization module
                      with its unit tests.
  Phase 3 (Day 2-3): Canonical financial model + taxed-base reconciliation (HLD-01-class fix);
                      credit-memo sign normalization; header vs. line tax placement fidelity.
  Phase 4 (Day 3):   Master-data matching per master (VAT-ID/exact-key first, bounded fuzzy
                      fallback, blank-by-default enforced); PO cross-check.
  Phase 5 (Day 3-4): Duplicate detection layers; groundedness post-hoc validation; segmentation
                      for bundled PDFs (DU-02/DU-03/DU-05s-shaped documents).
  Phase 6 (Day 4):   Full corpus regression pass with named test cases (§14); ambiguous-document
                      policy finalized and applied consistently (INV-23/HLD-03/HLD-08); logging
                      and README finalize; final review against the brief's three rules.
```
