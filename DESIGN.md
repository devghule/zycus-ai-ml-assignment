# DESIGN.md

*A full architecture reference (pipeline stages, interfaces, testing strategy,
etc.) is kept in `ARCHITECTURE.md` for anyone who wants the detail. This
document answers the three questions the brief actually asks for.*

## 1. What did I understand about these documents by the end that I didn't on day one?

At the start, this looked like an extraction problem: read a PDF, find the
fields, fill in the record. That view survives contact with maybe a third of
the corpus and then stalls, because the documents that defeat it don't fail
in a way that looks like a parsing bug — they fail because **a faithful
transcription of the page is not the same thing as the record that should be
booked.**

The shift was realizing that most of the difficulty lives in structure, not
values. A management fee that's clearly printed and clearly totalled can
still produce the wrong ERP gross if it's placed in `extra_charges` when the
document actually taxes it as part of the base (or vice versa) — the number
you copied was real, and the total still comes out wrong, because the
*shape* you put it in doesn't match the *shape* the document describes.
Once I saw this as the actual failure mode, the system stopped being "an
extractor with some tax logic bolted on" and became something closer to a
small adjudicator: for every candidate structure, ask the real `erp.py`
whether it reproduces the stated total, and never accept a record just
because its parts were individually true.

The second thing I understood late: entity and number consistency across a
document is itself evidence. Several documents in this corpus reuse the same
handful of shell-company-style names in shifting roles (a name that's a
supplier on one document and a bank on another), and a naive name-match
would confidently produce a wrong master-data ID. The correct response
wasn't a smarter name matcher — it was accepting that "no reliable match"
is frequently the true answer, and that a blank field is not a failure of
the system, it's the system working.

## 2. When the system meets a document unlike anything it has seen, what does it actually do — and why does that generalize instead of guessing?

Nothing in the pipeline branches on a document's identity, filename, or any
value observed only in the visible corpus. Every decision point is a
general rule over document *properties*:

- **Classification** scores structural/textual signals (invoice-identity
  patterns, priced-line-item patterns, non-payable vocabulary, credit-memo
  vocabulary) across several languages. A document with too little signal,
  or with conflicting signal, is declined as ambiguous — it is never forced
  into a class because *some* document has to end up somewhere.
- **The financial model** resolves an ambiguous charge (does it sit inside
  or outside the taxable base?) by constructing both candidate structures
  and asking the real, unmodified `erp.py` which one reproduces the
  document's stated gross. This is a mechanism, not a lookup table — it
  applies identically to a charge on a document I've never seen, because it
  never depends on having seen it before.
- **Master-data matching** requires strong evidence (an exact VAT ID, an
  exact name, or a clearly-separated fuzzy match) before emitting an ID, and
  requires a buyer-country signal to map to *exactly one* business unit
  before inferring it. When evidence is absent or contradictory, the answer
  is blank, by construction, not by exception-handling.
- **Validation** is a final, general gate: is the value actually present in
  the source text, is it schema-valid, does it reconcile exactly against
  `erp.py`? None of these questions can be answered "yes" by memorizing this
  corpus — they can only be answered by re-deriving the answer from the
  document in front of the system.

This is why the design generalizes rather than accumulates special cases: a
system built by adding a branch every time a document defeats it would grow
a list that stops working the moment a *new* document defeats it in a
slightly different way. This system instead asks the same small set of
general questions of every document, and the honest answer to those
questions — including "I don't know" — is what gets emitted.

## 3. Which document could not be solved the way the others were, and how did I know?

**INV-23.** It is a Ghanaian customs "estimate" bundled with an attached
duty-calculator printout, and the two pages state two different totals for
what is presented as the same shipment (13,724.19 vs. 13,289.19 GHS) — with
no arithmetic or textual path from one figure to the other anywhere on the
page. This is different from every other hard case in the corpus. A
document with illegible identity fields (e.g. `HLD-03`) is still, in
principle, a solvable *financial* event — the totals foot cleanly, only the
identity is unreadable; in the final run it happened to be declined for a
separate, more mundane reason (its OCR text didn't clear the classifier's
evidence threshold), which is an honest extraction-quality limitation, not a
structural impossibility. INV-23 is a different kind of failure: **the page
itself contains no single true number to recover.** Picking either printed
total, or some blend of the two documents' components, to force a payable
would not be extracting a fact from the document — it would be manufacturing
a resolution the document does not supply. `erp.py` would happily compute a
gross from whichever number I chose; that a number passes the ERP check
proves nothing here, because the actual failure is that "arithmetically
consistent" and "true" have come apart on this specific page.

I knew this was categorically different, not just difficult, because every
other hard document reduces to a *missing-evidence* problem (illegible text,
absent totals, weak classification signal), where the honest answer is "not
enough information." INV-23 is a *contradictory-evidence* problem: there is
too much information, and it disagrees with itself. The system's actual
behavior reflects that distinction — it declines the document rather than
resolving the contradiction, and the decline reason names the conflict
explicitly rather than reporting a generic "insufficient evidence," so a
human reviewer sees *why* it stopped rather than being told nothing was
found.

---

*Actual final-run results, corpus statistics, decline breakdown, and the
list of real bugs found and fixed during development are in
`CORPUS_EVALUATION.md` and `IMPLEMENTATION_PROGRESS.md`. This document
answers only the three required questions above; it does not restate the
architecture (see `ARCHITECTURE.md`) or the results.*
