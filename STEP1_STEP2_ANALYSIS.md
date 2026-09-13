# Zycus "Bookable Payable" Take-Home — STEP 1 + STEP 2 Analysis

*Pure analysis document. No implementation, no solution code, no modification of `erp.py` or any other original assignment file.*

---

## 1. Executive Summary

The `documents/` folder actually contains **42 PDF files** (not 35 — see the discrepancy note under §14 "Open Questions"). All 42 were opened and read at high resolution. Three (`HLD-01`, `HLD-03`, `HLD-08`) had only medium-confidence, incomplete prior analysis and were freshly re-read end-to-end for this report; the remaining 39 were re-verified at normal effort against the source PDFs directly (not from a prior batch transcript, since no verbatim batch text was actually available to this pass — every fact below was pulled straight from the PDFs).

The assignment is not a document-extraction exercise. It is a **judgment exercise**: for every PDF you must decide (a) whether it represents a bookable payable at all, (b) exactly what the ERP (`erp.py`) needs to reproduce the document's own stated total from raw, ungrounded components, and (c) which master-data codes are legitimately resolvable versus honestly blank. The corpus is deliberately built around one recurring trap: **many documents look like simple invoices but are not payables at all** (delivery notes, dunning/reminder letters, donation-approval forms, customs/logistics paperwork, quotations/estimates, credit notes, a "copy" invoice, utility bills addressed to an unrelated third party). A second, equally important pattern is that a large cluster of documents (INV‑31 through INV‑37) belongs to a **completely different corporate universe** (AmeriHealth Caritas / Zycus Melbourne office / Oracle / PECO / Ciox Health) that shares no entities with the "Bolt Group / Northwind / Cloverdale / Meridian / Silverbrook" universe the master data is built from — meaning every one of those documents is, by construction, a supplier/buyer master-data non-match, and is probably present specifically to test whether a candidate's system fabricates master codes under pressure rather than leaving them blank.

Key technical finding for STEP 2: `erp.py` computes header taxes and header discount against `net_base = item_discounted_total − header_discount` but **excludes `freight_charges`, `insurance_charges`, `extra_charges`, and `excise_duties` from that base**. Several documents (most importantly the freshly re-read **HLD-01**) apply their percentage taxes over a base that *includes* a charge/fee — meaning that charge must be modeled as its own **line item**, not as a header `extra_charges` figure, or the ERP recompute will diverge from the document's true math. This is the single most important "same total, wrong structure" trap uncovered in this pass.

---

## 2. Complete Document Table (all 42 PDFs found in `documents/`)

Legend: **Payable?** = Y (produces ≥1 `payables[]` entry) / N (→ `declined[]`) / Y+ (multiple payables in one file) / ? (genuinely ambiguous).

| # | File | Doc type | Payable? | Supplier (as printed) | Buyer/Customer (as printed) | Currency | Total / key figure | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | DU-02.pdf | Customs Consolidated + 10× Customs Detailed Invoices (Novatek U.S. LLC → Turkish importer, multi-page) | N | Novatek U.S. LLC / Redwater Mobility BV | Sağlık ve Çevre Bilim. LTDŞTİ (Turkey) | EUR / TRY (mixed) | 37,534.94 EUR (consolidated) + several TRY sub-invoices | Customs/logistics paperwork, not a supplier AP invoice to a Bolt entity; no buyer in chart_of_books; decline as customs documentation |
| 2 | DU-03.pdf | Freight/logistics bundle (Blueharbor Tax invoice, MAERSK cartage advice, customs cargo permit pages, House Air Waybills ×5, Polvex order confirmation) | ? | Blueharbor Logistics & Services Singapore Pte Ltd | Cadence PTE. LTD. | USD/SGD | 1,040.06 USD (=1,350.55 SGD) | The Blueharbor "TAX" invoice (p.1–2) is the only page with a payable structure; rest are waybills/permits (not payables). Neither party is Bolt Group |
| 3 | DU-05.pdf | Tax Invoice (Vantek Asia Pte Ltd → Cadence Pte Ltd / ship-to Fairmont Technologies) | Y | Vantek Asia Pte Ltd | Cadence Pte. Ltd | SGD | 771.66 | 90 days net; no VAT line shown (0/blank); no PO/master match found |
| 4 | DU-05s.pdf | Bundle of 11 Delivery Notes + DHL waybills + shipment receipt (Vantek → many different recipient names, same address) | N | Vantek | Kingsley/Cloverdale/Meridian/Redwater/Northwind/Brightside/Silverbrook (11 different customer names, same Laguna Technopark address) | — | — | Pure delivery notes — no prices except one shipment receipt (declared value 52,542.97 SGD, not an invoice figure); classic "many entity names sharing one address" conflation pattern; decline all |
| 5 | DU-06.pdf | Europastry invoice + delivery note (2pp) | Y | Blackpine Supply S.A (t/a Europastry) | Northwind SUPPORT SERVICES PT / Cloverdale Distribution LDA | EUR | 153.58 | Mixed VAT rates (23%, 6%) per line; delivery note confirms qty match |
| 6 | DU-08.pdf | German dunning letter ("Mahnung") | N | Silverbrook Media GmbH & Co.KG | Kingsley Trading GmbH & Co. KG / Northwind Services DE GmbH | EUR | Restbetrag 4.10 (after a prior invoice 48.94 and an offsetting storno of −44.84) | A payment reminder referencing an already-issued invoice, not itself a new invoice; decline (dunning letter, not an original payable) |
| 7 | DU-09.pdf | Internal donation/sponsorship approval form + forwarded email | N | — (Ashford Systems, USA, recipient of sponsorship) | Cadence/Northwind (requestor) | USD | $1,995.00 | Internal compliance approval form for a sponsorship, not a supplier invoice; decline |
| 8 | DU-10.pdf | UK Credit Note | Y (CREDIT_MEMO) | Blackpine Consulting Limited | Northwind Services UK Limited | GBP | 5,076.17 (credit) | "failed delivery" reason stated; VAT 20% on 4,230.14 net; positive magnitudes per schema convention |
| 9 | DU-11.pdf | Estonian "Kreeditarve" (credit invoice) | Y (CREDIT_MEMO) | Tavolo OÜ | Northwind Operations OÜ | EUR | 400.00 (credit) | Printed as negative (-400,00 / -327,87 / -72,13); must be submitted as positive magnitudes with `invoice_type: CREDIT_MEMO` |
| 10 | HLD-01.pdf | Thai staffing invoice ("ใบวางบิล / INVOICE") | Y | บริษัท ซิงค์ ครีเอชั่น จำกัด (Sync Creation Co., Ltd.) | Northwind Support Services (Thailand)…Limited | THB | 8,161.92 (net payable, after WHT) | **Freshly re-read — see §3 for full detail.** Management fee (9%) taxed together with the base; VAT 7%; withholding 3%; amount-in-words confirms 8,161.92 |
| 11 | HLD-03.pdf | Portuguese beverage "Fatura" (heavily overlapping/garbled template) | Y (with caveats) | Illegible with certainty — "Vinora" appears at footer with NIPC PT241239094; header shows overlapping "Larkspur Print"/"Northwind…"/other text | "Bolt…Alc…Rua…1350-0[1]9 Lisboa" (partially obscured) | EUR | 67.25 | **Freshly re-read — see §3.** Several fields are genuinely illegible due to overlapping text layers; do not guess |
| 12 | HLD-05.pdf | Portuguese beverage distributor invoice (2pp, multi-line, IEC excise) | Y | Northwind Support Services PT Unipessoal, Lda (printed as both "Sede Social" and recipient — likely a template/self-billing artifact) | Northwind Parkside, Lisboa | EUR | Sub-total 835.27 (page 2) + separate page-1 computation; header IVA 13%/23% split | Complex multi-rate IVA + IEC excise structure across many SKUs; two pages, no explicit page total shown—needs careful per-line VAT-rate bucketing |
| 13 | HLD-08.pdf | South African "Copy Tax Invoice" | Y (with caveat) | Cloverdale Partners CC (VAT No. 2731114415) — OR "Meridian Technologies / A Division of Meridian Print Ltd" — entity identity is conflated (3 names appear); footer: "Silverbrook Distribution Ltd" | Deliver-to: Johannesburg, GP | ZAR | 148,941.47 | **Freshly re-read — see §3.** "Copy" invoice = reprint/duplicate risk flag; 15% VAT matches ZAF_150_VAT |
| 14 | HLD-10.pdf | Speedwell Estonia courier consolidated invoice (2pp, "Arve") | Y | Speedwell Estonia AS | Northwind Operations OÜ | EUR | 254.52 | Multiple shipment lines, KM codes A (24%) / B (0%); needs per-shipment line + 2 tax buckets |
| 15 | INV-01.pdf | German "Rechnung" (project management re-invoice) | Y | Northwind Operations OÜ (issuer confusingly also matches buyer name pattern — see §4) | Herrn Alex Kask / Northwind Operations OÜ | EUR | 438.00 | 0% MwSt / reverse charge; this is the `sample_autodraft.json` source document |
| 16 | INV-02.pdf | Estonian equipment-rental "Arve" | Y | Northwind Technology OÜ | Meridian Logistics OÜ | EUR | 608.23 | Header discount 15% then 24% VAT; many €0.00 sub-lines (cables) |
| 17 | INV-03.pdf | South African Tax Invoice (office cleaning) | Y | Cloverdale Print Ltd (t/a "We Clean It All") | Northwind Services ZA (Pty) Ltd | ZAR | 8,550.00 | 15% VAT; single service line |
| 18 | INV-04.pdf | South African Tax Invoice (criminal verification, background checks) | Y | Larkspur Distribution / Meridian Print Ltd (conflated letterhead) | Northwind Services ZA (Pty) Ltd | ZAR | Amount Due 6,620.55 (after "Less Amount Credited" 13,110.00 against 19,730.55 gross) | The document nets a prior credit into the amount due — the *payable* the ERP should book is the invoice's own gross (19,730.55) as printed, not the post-credit "amount due"; the credit is a separate, already-settled transaction |
| 19 | INV-06.pdf | South African online-grocery Tax Invoice (personal shopper) | Y | Meridian Mobility Ltd (t/a "Oakhaven Trading") | Northwind Services ZA (Pty) Ltd | ZAR | 1,683.98 | Consumer-style grocery receipt; delivery cost 50.00; many individual food SKUs; likely genuinely below Zycus's line-item-worthy threshold — good candidate for aggressive line bundling test |
| 20 | INV-07.pdf | Duplicate of INV-04 (identical content) | Y | (same as INV-04) | (same as INV-04) | ZAR | 6,620.55 | Byte-for-byte the same invoice as INV-04 — a genuine **duplicate-document test**: must not double-book |
| 21 | INV-09.pdf | Estonian freight "ARVE" (import duties/customs VAT) + attached customs declaration | Y | Cloverdale Trading | Northwind Operations | EUR | 37,767.32 | Two lines: "Import duties" 31,889.09 + "Customs VAT" 5,878.23, both at "KM VAT % = 0" (i.e. the VAT amount is stated directly, not derived from a rate) — must be modeled as explicit `tax_amount`, not `tax_rate` |
| 22 | INV-10.pdf | Estonian "Arve" (catering, "Toitlustus") | Y | Larkspur Print OÜ | Northwind Operations OÜ | EUR | 594.30 | Includes a −0.01 rounding line; 24% VAT |
| 23 | INV-11.pdf | Estonian/Portuguese freight "ARVE INVOICE" | Y | Northwind Operations OÜ (S.o João da Talha) | Northwind Operations OÜ (Dos Hermanas) — intercompany | EUR | 83.21 | 4 freight-fee lines incl. a BAF fuel surcharge percentage line "6.93%"; all at 24% KM |
| 24 | INV-13.pdf | Estonian parking-services consolidated "Arve" | Y | Cloverdale Supply OÜ | Northwind Services EE OÜ | EUR | 152,587.46 | ~24 lines mixing 24%-VAT and 0%-VAT parking fee types, several negative "discount" and "success fee" lines; a genuinely complex multi-rate, multi-sign line set |
| 25 | INV-14.pdf | UK Tax Invoice (office management fee, June 2026) | Y | Northwind Services UK Ltd | Silverbrook Media Limited | GBP | 29,253.72 | Mixed VAT (20% and "No VAT" lines in the same invoice) |
| 26 | INV-15.pdf | UK Tax Invoice (office management fee, May 2026) | Y | Northwind Services UK Ltd | Silverbrook Media Limited | GBP | 29,253.72 | **Identical amounts to INV-14** but different invoice number/period — a "same numbers, different month" trap: these are two distinct payables, not duplicates, despite identical totals |
| 27 | INV-16.pdf | Estonian DHL-style courier "Arve" (2pp) | Y | Speedwell Express Estonia AS | Northwind Operations OÜ | EUR | 26.47 | Fuel surcharge sub-line; 22% VAT |
| 28 | INV-19.pdf | Ghanaian catering invoice (multi-levy) | Y | Redwater Technologies | Northwind HOLDINGS OÜ | GHS | 8,045.40 | Full NHIL/GETFund/COVID levy chain + VAT 15% on tax-exclusive value — textbook Ghana 4-tax chain matching tax_master.json entries TAX024/028/029/030 |
| 29 | INV-20.pdf | Swiss shipping/warranty invoice | Y | (Northwind CH sarl is the buyer; supplier name is at top, largely blank/illegible — appears to be an auto-parts distributor) | Northwind CH sarl | CHF | 12.10 | 8.10% VAT matches CH_081_VAT exactly; tiny single-line invoice with an embedded QR-bill payment slip |
| 30 | INV-21.pdf | Portuguese "FATURA" (beverage/coffee supplier) | Y | Oakhaven Partners LDA | Northwind SUPPORT SERVICES PT, UNIPESSOAL LDA | EUR | 535.79 | Line discount 51% on one SKU; IVA 23% only on the discounted incidência base |
| 31 | INV-23.pdf | Ghanaian customs "ESTIMATE" + ICUMS Duty Calculator printout (4pp) | N | Kingsley Supply LIMITED | Northwind HOLDINGS (Ghana) | GHS | Est. total 13,724.19 / ICUMS total 13,289.19 | An "ESTIMATE," not an invoice — explicitly a quote pending a required deposit; the attached ICUMS calculator print is a duty-computation tool output, not a payable document either; decline both |
| 32 | INV-25.pdf | Portuguese "Fatura" (printing services, original + duplicate copy of the same invoice) | Y | Fairmont Services LDA | Support Services PT Unipessoal, Lda | EUR | 176.00 | Two identical pages (Original + Duplicado) — same duplicate-detection trap as INV-04/07 |
| 33 | INV-26.pdf | Malaysian "SALES" invoice (grocery/consumer goods, 2pp) | Y | Meridian Print Sdn Bhd | Northwind MY SDN BHD | MYR | 873.53 | SST 0.00% throughout (all zero-rated); "Amount in Words" cross-check field present |
| 34 | INV-27.pdf | Kenyan warehousing/logistics invoice (2pp) | Y | Oakhaven Supply Ltd | Northwind Support Kenya Ltd | KES | 70,654.30 | Several usage-based (CBM×days) storage-fee lines; VAT 16% matches KEN_160_VAT |
| 35 | INV-28.pdf | Danish waste-management "AFREGNINGSBILAG" (3pp, settlement invoice) | Y | Silverbrook Print (issuer letterhead) — actual biller appears to be a waste-disposal contractor | Northwind Services Dk Aps | DKK | 4,478.20 | ~18 small fee/rental lines, uniform 25% moms; page 3 is a supporting "Specifikation" (date-level detail, not a second payable) |
| 36 | INV-31.pdf | US commercial real-estate + PECO electric utility bill (3pp) | Y | 100 Airport KPG III, LLC / PECO (An Exelon Company) | AmeriHealth Caritas | USD | 17,657.53 | **Outside the Bolt Group universe entirely** — no master-data match possible for supplier, buyer, tax, or PO on principle; complex utility tariff (distribution + supply + taxes) bundled into one "Electric" line |
| 37 | INV-32.pdf | US ground-transportation invoice | Y | 215 B.E.A.R.S. | AmeriHealth Caritas Transportation | USD | 750.00 | 0% tax explicitly marked "non-taxable item"; PO# and Req# both printed but neither is a Bolt Group PO |
| 38 | INV-33.pdf | Singapore signage/fabrication invoice | Y | AD Notions Int'l Pte Ltd | Changi Airport Group (S) Pte Ltd | SGD | 250.00 | No VAT/GST shown ("Without GST" column header); COD terms; heavily annotated with handwritten approval stamps |
| 39 | INV-34.pdf | Australian serviced-office "tax invoice" (3pp) | Y | Asian Pacific Serviced Offices Pty Ltd | Zycus Infotech Private Limited (Melbourne) | AUD | 572.00 | GST 10% on 520.00; BPAY payment slip; **this is a real Zycus corporate invoice** — notable that "Zycus" itself appears as a bill-to party in its own take-home kit |
| 40 | INV-35.pdf | US medical-records copy invoice | Y | Ciox Health | AmeriHealth Caritas LA (Quality Management Dept) | USD | 30.25 | Sales tax 2.75 on subtotal 27.50; Zycus PO# printed in a banner above the letterhead (likely an OCR/layout artifact, not part of the invoice itself) |
| 41 | INV-36.pdf | US cloud-services invoice | Y | Oracle America, Inc. | AmeriHealth Caritas Services | USD | 91,580.50 | Single large service line marked tax "N" (not taxed); PO number printed |
| 42 | INV-37.pdf | US commercial building utilities-reimbursement invoice (2pp, spreadsheet-style) | Y | 1120 Vermont Avenue Associates, LLP | AmeriHealth ("2nd Floor") | USD | 2,487.73 | Extremely granular derived-formula layout (meter reads × multiplier × rate); several sub-totals (electric, generator fuel, condenser water, building service fees) that must be summed into one net reimbursement figure; also contains a stray unrelated bar chart image |

**Discrepancy note:** the brief/README says "documents/... 1–35 lines each," and the assignment prompt for this task also refers to "35 PDFs" and asks the count to "confirm... should be 35." The actual `documents/` directory, read via `ls`, contains **42 files**. All 42 are included above and none were dropped to force the count down to 35; see §14 for how this is being flagged rather than silently resolved.

---

## 3. Individual Document Analysis — Freshly Re-Read: HLD-01, HLD-03, HLD-08

### HLD-01.pdf — Thai staffing invoice (full forensic re-read)

**Document type:** Thai-language commercial invoice, header reads "ใบวางบิล (INVOICE)" ("billing note / invoice"). Single page.

**Supplier (as printed):** บริษัท ซิงค์ ครีเอชั่น จำกัด (Sync Creation Co., Ltd.), "สำนักงานใหญ่" (head office), address เลขที่ 799/124 หมู่ 3 ตำบลแพรกษา, จังหวัดสมุทรปราการ 10280. Tax ID (เลขประจำตัวผู้เสียภาษี): 0 1055 56100 87 9. Not present in `suppliers.json` → `supplier_id` must be left blank.

**Buyer (as printed):** The customer field is corrupted by an overlapping/double-printed text layer: legible fragments read "Northwind SUPPORT SERVICES (THAILAND)..." overlapping with what appears to be a second company name and address block bleeding through from behind (garbled characters interspersed, e.g. "เลขที่ 8 อาคารทีวัน ชั้น 16 ห้องเลขที่ 16-103 16-104 16-105... ซอยสุขุมวิท 40 ถนนสุขุมวิท แขวงพระโขนง เขตคลองเตย กรุงเทพมหานคร"). Best-effort reading: **"Northwind Support Services (Thailand) ... Limited"**, Bangkok. This entity does **not** appear in `chart_of_books.json` (which has only EE, GH, MY, ZA, GB business units for Bolt Group) — so even a perfectly legible buyer name would still be a non-match for `company_code`/`business_unit_code`/`location_code`. This is treated as a genuine no-match, not a transcription failure.

**Invoice number:** SI6675/02/467. **Date:** 05.05.2569 (Thai Buddhist Era) = **2026-05-05** (BE year − 543 = CE year). **No separate due date is printed** — leave `due_date` blank rather than inferring one.

**Project reference:** "Staff Impact (May 2026)."

**Line items:**
| Description | Qty | Unit price | Amount |
|---|---|---|---|
| Staff 2 Units X 6 Days | 12 | 600.00 | 7,200.00 |

**Header charges/taxes (as printed, in order):**
- Total: 7,200.00
- Management Fee 9%: 648.00 → subtotal "Total (including agency fee)": 7,848.00
- Vat 7%: 549.36 → "Grand Total (including VAT)": 8,397.36
- ภาษีหัก ณ ที่จ่าย 3% (Withholding Tax): 235.44 → "จำนวนเงินที่ต้องชำระ (Total Payment)": **8,161.92**
- Amount in words: "แปดพันหนึ่งร้อยหกสิบเอ็ดบาทเก้าสิบสองสตางค์" = eight thousand one hundred sixty-one baht ninety-two satang = confirms **8,161.92 THB**.

**Verification of the arithmetic:** 7,200 × 1.09 = 7,848.00 (management fee applied to the base); 7,848 × 0.07 = 549.36 (VAT applied to base **plus** management fee); 7,848 × 0.03 = 235.44 (withholding, also computed on the pre-VAT 7,848 base, not on the VAT-inclusive grand total); 8,397.36 − 235.44 = 8,161.92. All figures foot exactly.

**Currency:** THB (บาท), confirmed by the amount-in-words baht/satang phrasing.

**Difficult-case flag (the reason this document was singled out as medium-confidence originally):** the layout has genuinely overlapping/garbled text in the customer block, and the tax structure is a compounding, non-trivial chain. **erp.py implication:** `_header_taxes` computes both VAT and withholding against a single `net_base = item_discounted_total − header_discount`, which does **not** include `extra_charges`. If the 9% management fee is placed in `extra_charges` (648.00), the ERP would compute VAT/WHT only on the 7,200 line total, giving VAT = 504.00 and WHT = −216.00 — **not** matching the document's 549.36 / 235.44. The management fee must instead be submitted as its own `line_items[]` entry (e.g. description "Management Fee 9%", `item_type: SERVICE`, `total: 648.00`) so that it becomes part of `item_discounted_total` (7,848.00) before header taxes are applied. Header `taxes[]` then carries VAT (`tax_rate: 7`, amount left blank to derive 549.36) and Withholding (`tax_amount: -235.44` given explicitly, since the schema's rate field would otherwise force it positive). This reproduces the ERP gross exactly: 7,848.00 + 549.36 − 235.44 = 8,161.92.

**Master-data relevance:** supplier — no match (not in `suppliers.json`). Buyer — no match (Thailand not present in `chart_of_books.json`). Tax — no direct Thailand VAT/WHT entries exist in `tax_master.json` either (it has Thai entries `TH_070_VAT` 7% and `TH_WHT_003` 3%, which **do** match this document's stated 7% and 3% rates) — so `tax_type_code` should resolve to `TH_070_VAT` and `TH_WHT_003` respectively even though supplier/buyer do not resolve. Payment term — none stated on the document; leave blank. PO — none printed.

**Payable determination:** Yes — this is a genuine invoice for services rendered (staffing), addressed to a (probably) real but unmapped Bolt Group Thailand entity.

---

### HLD-03.pdf — Portuguese beverage "Fatura" (full forensic re-read, with explicit illegibility disclosure)

**Document type:** Portuguese commercial invoice ("Fatura"), stamped "Original," classification code "ZF1" in top-right corner. Single page.

**Legibility caveat (stated explicitly, not guessed around):** This PDF has two or more text layers rendered on top of one another across the header/supplier/buyer region. The words "Larkspur Print ou," a Decreto-Lei legal boilerplate paragraph, "Destinatário:" and a "Bolt … Alc … Rua … 1350-0[1]9 Lisboa" address are all superimposed and partially overlapping, as are the right-hand blocks reading "Northw[ind]… Servic[es]… Blackpine … Unipessoal Lda … Kadaka tee 224 … 1250-148 Lisboa" (note: "Kadaka tee" is an Estonian street name, which should not literally appear in a Lisbon address — this confirms the overlap is a genuine rendering/template artifact mixing two different address blocks, not a real bilingual address). **The true supplier name, the true buyer name, and the exact recipient address cannot be read with confidence from this file.** The most reliable identifying data point is the footer block: "Vinora," a telephone number, "C.R.C. DE V.N. DE GAIA," and **NIPC (tax ID) PT241239094** — this does not match any entry in `suppliers.json` (which has PT501234567 "Zoomcopia Impressao Lda" and PT502345678 "Distribeer Bebidas Lda," neither matching this NIPC). Given the illegibility, **supplier_id and buyer codes should both be left blank** rather than guessed from the fragmentary overlapping text.

**What is clearly legible:**
- Invoice date: 02.12.2025. Due date ("Data de Vencimento"): 01.01.2026.
- Nº Cliente: 3845708.
- IBAN: 0033 0000 05, SWIFT: CTQEB9FM.
- Single line item: "1 CX TRINCA ALE T22 6X1500 CXE NTT" (a case of canned beer, 6×1500ml), EAN 5601012004984. %ALC (alcohol content) 13.5. Preço Unitário (unit price) 123,36. Ilíquido (gross) 123,36. Descontos Promocionais 51,76% = 63,85. IEC column shows 13,00 / 59,51 (see ambiguity note below). %IVA 13,00, Incidência (taxable base) 59,51, IVA (tax amount) 7,74.
- Totals: Total ilíquido 123,36; Descontos Promocionais −63,85; IVA 7,74; IVA Adiantamento (blank); **Total da factura: 67,25.**

**Arithmetic check:** 123.36 − 63.85 = 59.51 (matches both the "Incidência" and the value shown in the "IEC" column, i.e. these two columns appear to reference the same net-of-discount base rather than representing two independent charges). 59.51 × 0.13 = 7.7363 → rounds to 7.74. 59.51 + 7.74 = 67.25. All printed totals foot correctly using only the discounted net base and the 13% IVA — **there is no separate/additional excise duty being added on top**; the "IEC" figure is best read as a duplicate display of the incidência column, not a second charge. This is flagged as an interpretive judgment call, not a certainty, because Portuguese alcohol invoices commonly do carry a genuine separate IEC (Imposto sobre Consumo) excise line, and the arithmetic here is also consistent with IEC being folded into the unit price rather than shown separately.

**Currency:** EUR (values use comma-decimal Portuguese formatting; must be normalized to dot-decimal, e.g. "67,25" → "67.25").

**Master-data relevance:** Supplier — no match (illegible / NIPC not in master). Buyer — the recipient's country is Portugal, but `chart_of_books.json` has no Portugal business unit for Bolt Group at all (only EE, GH, MY, ZA, GB) — so even a fully legible buyer name would still fail to resolve a `company_code`. Tax — 13% matches `PT_130_IVA` in `tax_master.json` exactly. Payment term — none stated (only a due date). PO — none printed.

**Payable determination:** Likely yes (67.25 EUR appears to be a genuine, arithmetically self-consistent commercial invoice for a delivered case of beer), but with an explicit caveat that the supplier and buyer identity fields are not reliably extractable from this particular scan and must be submitted blank rather than fabricated.

---

### HLD-08.pdf — South African "Copy Tax Invoice" (full forensic re-read)

**Document type:** "Copy Tax Invoice" — explicitly labeled as a **copy/reprint** of an original tax invoice, not a first issuance. Single page, South African format.

**Entity-name conflation (three names on one document):**
1. Top-left contact block: "Cloverdale Partners CC, PO Box 2505, Market Road 73, Rua do Ouro 138, 4300," with **VAT No: 2731114415**.
2. Mid-left block: "Meridian Technologies, A Division of Meridian Print LTD, Meridian Print Ltd, P.O.Box 13385, Jacobs 4026, **Vendor Number 432145**."
3. Footer: "Silverbrook Distribution Ltd."

Given standard South African tax-invoice layout (issuer's own VAT number appears near the top, together with contact numbers; the "Vendor Number" field is a *customer's own internal code for this supplier*), the most defensible reading is: **Cloverdale Partners CC is the issuing supplier** (it carries the VAT registration number that must belong to the invoice issuer), and **Meridian Technologies is the customer/bill-to party** (the "Vendor Number 432145" is Meridian's internal AP code identifying Cloverdale as their vendor). "Silverbrook Distribution Ltd," appearing only in the footer, is most likely a shared holding/distribution-network name printed on the template and not one of the two transacting parties. **This reading is a judgment call, not a certainty — flagged explicitly as such**, since the layout does not use standard "From/To" labels.

**Deliver-to (clearly labeled):** "High Street 1, EXT 1, Johannesburg, GP 1401" — a third, distinct address from either of the two named entities above, consistent with a normal ship-to.

**Header fields:** Date 19/05/2026. Document No 162547. Account TGB001. Your Reference 9267418170. Tax Exempt: N. Tax Reference 7414745407. Sales Code AP001. Terms "Exclusive" (i.e., prices exclusive of tax).

**Line item:**
| Code | Description | Qty | Unit | Unit Price | Tax | Nett Price |
|---|---|---|---|---|---|---|
| TGB001/531 | Hall's Smooth Fruit Punch 1lt M 337521 | 468.00 | 1000 | 276.74 | 15.00% | R129,514.32 |

Note the "Unit Price" column here (276.74) multiplied by "Quantity" (468) gives 468 × 276.74 = 129,514.32, which **matches the "Nett Price" column exactly** — meaning "Nett Price" in this template is the **line extension**, not the unit price restated. This must not be confused with `unit_price` in the autodraft schema; the schema's `unit_price` should be 276.74 (the genuinely per-unit net figure) and `total` should be 129,514.32.

**Totals:** Sub Total R129,514.32; Discount @ 0.00% R0.00; Amount Excl Tax R129,514.32; Tax R19,427.15; **Total R148,941.47.**

**Arithmetic check:** 129,514.32 × 0.15 = 19,427.148 → rounds to 19,427.15. 129,514.32 + 19,427.15 = 148,941.47. All figures foot exactly at a flat 15% VAT.

**Currency:** ZAR (R symbol).

**Difficult-case / trap flag:** This document being explicitly labeled a **"Copy"** (i.e., a reprinted duplicate of an already-issued original) is itself the primary difficulty — it is a strong signal for a duplicate-payment risk check (the same real-world control problem as INV-04/INV-07 and the two identical pages inside INV-25), even though, taken alone with no other document in the corpus sharing this exact Document No. 162547, there is no internal duplicate to detect here. It should still be treated as payable (the underlying commercial obligation is real), but the "copy" status is worth carrying as contextual information for a human reviewer / anti-duplicate control, since a system that books blindly every time it sees a valid-looking tax invoice — original or copy — is exactly the failure mode Rule 3 in the brief warns about.

**Master-data relevance:** Supplier — neither "Cloverdale Partners CC" nor "Meridian Technologies"/"Meridian Print Ltd" nor "Silverbrook Distribution Ltd" appears in `suppliers.json` → no match, leave blank. Buyer — South Africa does map to Bolt Group's `ZA001`/`LOC_ZA_001` (Johannesburg) in `chart_of_books.json`, and the Deliver-to address ("Johannesburg, GP") is consistent with that location — this is the one field on this document that plausibly *does* resolve, though the invoice never actually names "Bolt" or "Northwind" as the buyer, so this match is inferential (via geography) rather than an exact name match, and should be treated cautiously. Tax — 15% matches `ZAF_150_VAT` in `tax_master.json` exactly. PO — none printed (the "Your Reference" 9267418170 is not present in `po_master.json`).

**Payable determination:** Yes, with the entity-identity caveats above carried through as low-confidence fields rather than fabricated.

---

## 4. Document Pattern Analysis (across all 42)

1. **Non-payable clusters recur in predictable shapes:** delivery notes (DU-05s, one page of DU-06), dunning/reminder letters (DU-08), internal approval forms (DU-09), pure customs/logistics paperwork with no commercial charge to the receiving Bolt entity (DU-02, DU-03's waybill pages, INV-23's ICUMS printout), and quotations/estimates (INV-23's "ESTIMATE" itself). A system that treats "looks like a table of numbers with a total" as sufficient evidence of payability will over-book all of these.
2. **Credit memos use two different native formats but must map to one schema:** UK-style "Credit Note" (DU-10) and Estonian "Kreeditarve" (DU-11) both print their figures as **negative numbers on the page**; the autodraft schema requires them submitted as **positive magnitudes** with `invoice_type: CREDIT_MEMO`. A naive "copy the sign you see" extractor fails both.
3. **Tax-chain shapes vary by jurisdiction in a small number of recognizable families:** (a) single flat VAT/IVA/GST rate (most PT/ZA/CH/SG documents), (b) multi-rate line-level VAT within one invoice (DU-06, INV-13, HLD-05), (c) compounding percentage chains — fee-then-tax-then-withholding (HLD-01), (d) explicit multi-levy government chains (Ghana NHIL+GETFund+COVID+VAT in INV-19/INV-23), (e) taxes given as a stated **amount** with a 0% nominal rate rather than a derivable percentage (INV-09's "Import duties"/"Customs VAT" lines) — these must be modeled with `tax_amount` set and `tax_rate` left at "0"/blank, never invented as a percentage.
4. **Entity-name conflation is the dominant "difficulty" signature across the whole corpus, not just the three re-read documents.** Nearly every DU/HLD/INV document drawn from the Bolt-Group-style universe shows two or more company names sharing one street address (e.g. DU-05s's eleven different "customer" names all at "Gartenweg 24, Laguna Technopark"; HLD-08's Cloverdale/Meridian/Silverbrook trio; DU-06 and HLD-05's Northwind/Cloverdale overlap). This looks like deliberately generated synthetic noise designed to punish "confident string-match the first plausible name" logic and reward genuinely conservative master-data matching.
5. **Real-world "off-universe" documents (INV-31 through INV-37) form their own coherent sub-cluster:** all seven concern AmeriHealth Caritas / a Philadelphia commercial building / Oracle / Zycus's own Melbourne office, and none of their supplier or buyer names exist anywhere in the provided master data. This sub-cluster is structurally simple (mostly flat-rate or zero tax, single or few lines) but is a **pure master-data-honesty test**: nothing should resolve, and a system that pattern-matches "AmeriHealth" to "Northwind" or invents a plausible-looking company_code fails Rule 2 outright.
6. **Duplicate-detection traps appear at least three times:** INV-04/INV-07 (byte-identical), the two pages inside INV-25 ("Original"/"Duplicado"), and the "Copy Tax Invoice" framing of HLD-08. INV-14/INV-15 is the inverse trap — identical *amounts* but genuinely different invoices (different month, different invoice number) that must **both** be booked.
7. **"Net-of-credit" totals appear as a decoy (INV-04/INV-07):** the printed "Amount Due" nets an already-settled credit against the current invoice's own gross. The payable to submit is the invoice's own gross_total (19,730.55), not the post-netting "amount due" (6,620.55), because the credit is a separate transaction with its own history, not a discount on this invoice.
8. **Charges that sit "inside" the tax base versus "beside" it are a recurring structural hazard**, most sharply illustrated by HLD-01's management fee (must be a line item, not `extra_charges`, to land inside `net_base` for VAT/WHT purposes) — this generalizes to any document where a fee/surcharge is shown as taxed alongside the goods/services (e.g. INV-11's BAF fuel surcharge, INV-16/HLD-10's fuel surcharge lines, which are similarly percentage-based add-ons subject to the same header-tax-base question).

---

## 5. Technical Contract Explanation (engineering terms)

**What the system must do, end to end, per input PDF `X.pdf`:**
1. **Classify** the document: is it a payable-bearing commercial document at all (invoice, credit memo, self-billing invoice), or non-payable paperwork (delivery note, waybill, customs form, dunning letter, internal approval, quotation/estimate)? A single PDF may contain 0, 1, or several distinct payables (e.g., a consolidated customs invoice bundling many sub-invoices), and may also contain pages that are not payables at all.
2. **Extract** raw, document-stated values only: invoice number, dates, currency, supplier/buyer identity and address, line items (description, quantity, unit price, discount, per-line tax), header-level discount/freight/insurance/extra charges/excise, and header-level taxes (name, rate, amount) **exactly as placed in the document** (line vs. header).
3. **Derive** nothing that isn't asked for — the schema explicitly says the ERP derives per-line nets, tax amounts (when a rate but no amount is given), subtotals, and the gross. The system must **not** pre-compute any of erp.py's own outputs and must not fill in `tax_amount` unless the document itself states an amount that isn't simply rate × base (e.g., a compound levy).
4. **Match** every master-data-backed field (`supplier.supplier_id`, `buyer.company_code`/`business_unit_code`/`location_code`, `taxes[].tax_type_code`, `payment_term_id`, `po_id`) against the corresponding master file, at whatever confidence threshold the system designer chooses, and leave the field **blank** on anything short of a genuine match — "no match" is a first-class, correct answer, not a fallback failure.
5. **Never invent** a value (a number not printed anywhere on the document, or a master code not genuinely backed by a match) merely to make the ERP's recomputed gross agree with the document's printed total. If a document's own numbers do not foot, that is information about the document (it may be unsolvable, or may need to be flagged), not license to insert a plug figure.
6. **Emit** one JSON object per document at `output/X.json` with `payables[]` (0..N, schema-conformant) and `declined[]` (doc_type + reason) — never the same document logically counted in both.
7. **Verify** each candidate payable against `erp.py`'s `erp_book()` — the returned `will_book_gross` must equal the document's own stated gross to the cent, **and** the structural placement of every tax (header vs. line) must mirror the document, since the grader inspects shape, not just the number.

**Extracted vs. derived vs. matched vs. never-invented, summarized:**
- **Extracted (verbatim from the page):** invoice/ref numbers, dates, currency, supplier/buyer name & address & VAT ID as printed, `po_number` as printed, quantities, unit prices, discounts, line/header charge amounts, tax names/rates/amounts as printed, `gross_total`/`subtotal`/`total_tax_amount` as printed.
- **Derived (by `erp.py`, never precomputed by the candidate system):** per-line net base after discount, a tax's amount when only its rate is given, the item-discounted total, the final gross.
- **Matched (against `master_data/`):** `supplier_id`, `company_code`/`business_unit_code`/`location_code`, `tax_type_code`, `payment_term_id`, `po_id`.
- **Never invented:** any of the above when there is no genuine textual/numeric support on the document or no genuine master-data hit.

---

## 6. Complete Schema Analysis — Field-by-Field Table (`AUTODRAFT_SCHEMA.md`)

| Field | Required? | Type | Meaning | From document? | Derived? | Master-data match? | Important rules |
|---|---|---|---|---|---|---|---|
| `file` (wrapper) | Yes | string | Source PDF filename | N/A (system-assigned) | — | — | Matches input filename exactly |
| `payables[]` (wrapper) | Yes (may be empty) | array | 0..N bookable payables | — | — | — | One entry per distinct payable within the file |
| `declined[]` (wrapper) | Yes (may be empty) | array of `{doc_type, reason}` | Non-payable determinations | Yes (`doc_type` inferred from doc) | — | — | Never overlaps with `payables[]` |
| `invoice_number` | Effectively required | string | Document's own invoice/ref number | Yes | No | No | Raw as printed |
| `invoice_date` | Effectively required | string (ISO `YYYY-MM-DD`) | Issue date | Yes | Format-normalized only | No | Must reparse non-ISO/locale dates (DD.MM.YYYY, Thai BE year, etc.) |
| `due_date` | Optional | string (ISO) | Payment due date | Yes, if printed | May be derivable from `payment_term_id` + `invoice_date` if not printed, but do so cautiously | No | Leave blank if genuinely absent rather than guessing |
| `invoice_type` | Required | enum `INVOICE`\|`CREDIT_MEMO` | Determines sign convention | Inferred from doc type | — | — | Credit documents use this + positive magnitudes, not a separate shape |
| `currency` | Required | string (ISO code) | Document currency | Yes | — | — | erp.py just echoes it back; get it right from context (symbol, IBAN country, "Currency" field) |
| `supplier.name` | Required | string | Supplier legal name as printed | Yes | — | — | Keep exactly as printed even if it doesn't match master |
| `supplier.supplier_id` | Required field, may be `""` | string | Master supplier code | No | No | **Yes** — `suppliers.json` | Blank is a legitimate, honest answer |
| `supplier.address` | Optional | string | Supplier address as printed | Yes | — | No (informational only) | — |
| `supplier.vat_id` | Optional | string | Supplier VAT/tax ID as printed | Yes | — | Can cross-check against `suppliers.json.vat_id` for higher-confidence matching | Strong matching signal — often more reliable than name matching |
| `buyer.company_code` | Required field, may be `""` | string | Tenant company code | No (inferred from context/tenant) | No | **Yes** — `chart_of_books.json` | Bolt Group is always `BOLTGROUP` in this corpus, but leave blank if the buyer clearly isn't a Bolt Group entity |
| `buyer.business_unit_code` | Required field, may be `""` | string | Tenant BU code | No | No | **Yes** — `chart_of_books.json` | One per country/BU in this master; matched by buyer address/country |
| `buyer.location_code` | Required field, may be `""` | string | Tenant location code | No | No | **Yes** — `chart_of_books.json` | — |
| `payment_term_id` | Required field, may be `""` | string | Master payment-term code | No | Derived by matching document text/day-count to `payment_terms.json` aliases | **Yes** — `payment_terms.json` | Match on explicit day-count phrases ("30 days," "Net 10," "60 Days Net") |
| `po_number` | Optional | string | PO number exactly as printed | Yes | — | No (this is the raw field) | Distinct from `po_id` — always keep the raw text even if unmatched |
| `po_id` | Optional, may be `""` | string | Matched PO master code | No | No | **Yes** — `po_master.json` | A PO printed on the document but absent from `po_master.json` is explicitly called out in the brief as "a non-ERP reference" — leave blank |
| `gross_total` | Required | string (dot-decimal) | Document's own stated total owed | Yes | — | — | This is the number `erp_book()` must reproduce |
| `subtotal` | Optional | string | Document's own stated subtotal | Yes, if printed | — | — | For cross-checking only; erp.py does not consume it |
| `total_tax_amount` | Optional | string | Document's own stated total tax | Yes, if printed | — | — | Cross-check field; not consumed directly by erp.py's gross formula (it re-derives tax itself from `taxes[]`) |
| `discount_amount` | Optional | string (magnitude) | Header-level discount | Yes, if printed | — | — | Subtracted from `item_discounted_total` before header tax base |
| `freight_charges` | Optional | string | Header freight | Yes, if printed | — | — | Added post-tax-base, i.e. **not** taxed by header taxes in erp.py's model |
| `insurance_charges` | Optional | string | Header insurance | Yes, if printed | — | — | Same caveat as freight |
| `extra_charges` | Optional | string | Header misc. charge | Yes, if printed | — | — | **Trap:** if the document actually taxes this charge together with the goods/services (as in HLD-01's management fee), it must be a line item instead, not this field, or the ERP recompute under-taxes it |
| `excise_duties` | Optional | string | Header excise | Yes, if printed | — | — | Same base-exclusion caveat as freight/insurance/extra_charges |
| `taxes[]` (header) | Optional (0..N) | array of tax objects | Header-level tax lines | Yes, when the document states a tax once at the header | — | `tax_type_code` matched against `tax_master.json` | Only for taxes the *document* places at the header — never migrate a line-level tax up here |
| `taxes[].tax_type` | Optional | string | Broad category (VAT/GST/WHT/…) | Yes/inferred | — | — | — |
| `taxes[].tax_name` | Optional | string | Tax's own name as printed | Yes | — | — | Keep the document's own phrasing (e.g. "VAT Reverse Charge") |
| `taxes[].tax_rate` | Optional | string (percent, no `%`) | Rate as printed | Yes | — | — | Leave blank only if the document gives an amount with no derivable rate |
| `taxes[].tax_amount` | Optional | string, may be negative | Amount as printed, or blank to let erp.py derive it | Yes, when stated; otherwise blank | erp.py derives it from rate × base if left blank | — | Negative encodes withholding; must be set explicitly negative since erp.py doesn't infer sign from `tax_type` |
| `taxes[].tax_type_code` | Optional, may be `""` | string | Master tax code | No | No | **Yes** — `tax_master.json` | Match on country + rate + type; blank when no genuine hit |
| `line_items[]` | Required (0..N, but almost always ≥1 for a payable) | array | Raw line components | Yes | — | — | — |
| `line_items[].description` | Required | string | Line text as printed | Yes | — | — | — |
| `line_items[].item_type` | Optional | enum `GOODS`\|`SERVICE`\|`FREIGHT`\|`TAX` | Classification | Inferred | — | — | — |
| `line_items[].uom` | Optional | string | Unit of measure | Yes, if printed | — | — | — |
| `line_items[].quantity` | Required for erp.py math | string (number) | Qty | Yes | — | — | — |
| `line_items[].unit_price` | Required for erp.py math | string (number, NET) | Tax-exclusive unit price | Yes | — | — | **Must be the true per-unit figure**, not a line-extension mislabeled as "unit price" (see HLD-08 trap) |
| `line_items[].total` | Optional (informational) | string | Line extension as printed | Yes | — | — | erp.py recomputes its own base from qty×price; this field is for cross-checking |
| `line_items[].discount` | Optional | string (magnitude) | Amount discount | Yes, if printed | — | — | Mutually exercised vs. `discount_percentage` in erp.py (percentage takes precedence if both present) |
| `line_items[].discount_percentage` | Optional | string (percent) | Percentage discount | Yes, if printed | — | — | — |
| `line_items[].tax_rate` | Optional | string | Per-line rate (shorthand form) | Yes, if printed at line level | — | — | Used only when no explicit `taxes[]` array is given for the line |
| `line_items[].tax_amount` | Optional | string | Per-line amount (shorthand form) | Yes, if printed | — | — | Same as above |
| `line_items[].taxes[]` | Optional | array, same shape as header taxes | Explicit per-line multi-tax | Yes, when a line carries more than one tax or needs full tax-object detail | — | `tax_type_code` matched | Preferred over the shorthand `tax_rate`/`tax_amount` pair when a line has more than one tax or needs a named tax |

---

## 7. `erp.py` Analysis (line-by-line explanation; the file itself was **not modified**)

**`num(v)`** — tolerant numeric parser: strips a leading currency symbol/whitespace and `%`, returns `0.0` for `None`/empty/unparseable input. Implication: a value the extractor leaves as an empty string is silently treated as zero everywhere — there is no error surfaced for a missing number, so validation of "is this field actually populated" is entirely the candidate system's own responsibility.

**`round2(x)`** — banker-safe money rounding to 2dp, half-up, via `Decimal`. All intermediate and final money figures in the recompute go through this, so cent-level rounding differences between a candidate's arithmetic and the document's own rounding are the most common source of "close but not exact" failures.

**`_line_base(li)`** — the line's net base = `quantity × unit_price`, then:
- if `discount_percentage` > 0: `base − base × pct/100`, rounded;
- else if `discount` (an absolute amount) > 0 and `quantity != 0`: treats the discount as **spread per unit** (`item_price = price − disc_amt/|qty|`) then multiplies by qty again — i.e., an absolute line discount is NOT simply subtracted from the extension; it is first converted to a per-unit reduction. This is a subtle, easy-to-miss detail: a candidate who submits `discount: 50` expecting a flat €50 off the line extension will get a different number than intended unless quantity is 1.
- else: plain `qty × price`, rounded.

**`_line_taxes(li, base)`** — sums a line's taxes. If no `taxes[]` array is given but `tax_rate`/`tax_amount` shorthand fields are non-empty, it synthesizes a single-tax list from them. For each tax: if `tax_amount` is 0 and `rate` > 0, derive `amount = round2(base × rate/100)`; otherwise use the given `tax_amount` (which may be negative, e.g. a per-line withholding). If both rate and amount are empty/zero **and** the rate string was truly empty, the tax contributes nothing (skipped) rather than erroring.

**`_header_taxes(taxes, net_base)`** — same derive-or-use-given-amount logic as line taxes, but keyed on `net_base = item_discounted_total − header_discount` (see below) rather than any individual line's base. Amounts may be negative (withholding).

**`erp_book(payable)`** — the full recompute, in order:
1. For each `line_items[]` entry: compute `base` via `_line_base`, accumulate into `item_discounted_total`; compute that line's taxes via `_line_taxes(li, base)`, accumulate into `line_tax_total`.
2. `header_discount = abs(num(discount_amount))`.
3. `net_base = item_discounted_total − header_discount`.
4. `header_tax = _header_taxes(taxes, net_base)`.
5. `other_charges = freight_charges + insurance_charges + extra_charges + excise_duties` (all via tolerant `num()`, summed with no discounting or taxing).
6. `gross = round2(item_discounted_total − header_discount + line_tax_total + header_tax + other_charges)`.
7. Returns `{"will_book_gross": gross, "currency": payable.get("currency","") or ""}`.

**Expressed as one formula:**

```
gross = Σᵢ line_base(i) − |discount_amount|
        + Σᵢ line_tax(i)
        + header_tax( Σᵢ line_base(i) − |discount_amount| )
        + freight_charges + insurance_charges + extra_charges + excise_duties
```

where `line_base(i) = round2( qty·price · (1 − disc_pct/100) )` if a percentage discount is given, else `round2( (price − disc_amt/|qty|) · qty )` if an absolute discount is given, else `round2(qty · price)`.

**What `erp.py` does NOT validate (structural, not computational):**
- Whether a `tax_amount`/`tax_rate`/any numeric value genuinely appears anywhere on the source document (it will happily compute a "correct-looking" gross from entirely fabricated inputs).
- Whether a master-data code (`supplier_id`, `company_code`, `tax_type_code`, `payment_term_id`, `po_id`) is a real, legitimate match, or even present in any master file at all — it doesn't look at these fields.
- Whether a tax the candidate placed at the header actually belongs at the header on the source document (or vice-versa) — it will compute *a* gross either way; only the grader's separate structural inspection catches misplacement.
- Whether the document is actually payable at all (it has no concept of "declined").
- Whether a discount was genuinely a percentage vs. an absolute figure — it trusts whichever field is populated.
- Whether two payables are duplicates of one another (it evaluates one payable in isolation).
- Currency correctness — it simply echoes back whatever string is in `currency`, doing no FX conversion or validation.
- Date logic, VAT-ID checksum validity, or any cross-field consistency (e.g., `subtotal` disagreeing with the sum of line totals).

---

## 8. Master-Data Analysis

**`suppliers.json`** — Contents: 14 sample suppliers spanning DE/EE/MY/GH/ZA/KE/PT, each with `supplier_id`, `name`, `vat_id`, `country`, `email`, `address`, `bank_iban` (often empty). Matchable fields: `name` (fuzzy/normalized string match — accents, legal-entity suffixes like GmbH/OÜ/Ltd/Lda vary), `vat_id` (exact, high-confidence match when present on both sides — the single most reliable field, since VAT IDs are unique and don't suffer transliteration noise), `country` (weak disambiguator only). Frequently missing: `bank_iban` (absent for most non-DE/PT suppliers) — cannot be used as a matching key in general. Ambiguity: several document suppliers share partial name overlap with master entries only by coincidence of common words ("Print," "Distribution," "Services," "Trading," "Supply," "Consulting" recur across many entities) — name-only fuzzy matching without a VAT-ID or address cross-check will produce false positives. No-match behavior: the vast majority of the 42 documents' suppliers are **not** in this 14-row sample — correctly leaving `supplier_id` blank is the modal correct answer, not the exception. At scale (hundreds of thousands to millions of rows), a real system needs indexed lookup by normalized VAT ID first (exact match, O(1) via a hash/index), then a blocked/candidate-generation fuzzy-name search (e.g. by country + first N characters or a phonetic/n-gram index) rather than any full-table scan per document.

**`chart_of_books.json`** — Contents: one company (`BOLTGROUP`) with 6 business units (EE001, EE004, GH001, MY001, ZA001, GB001), each with exactly one location. Matchable fields: country/region implied by the buyer's printed address, and (weakly) the business-unit *name* if printed on the document. Likely-useful field: `invoice_to_address` — can be used to disambiguate which BU/location a document is actually addressed to when the buyer name alone is ambiguous. Frequently missing: the document rarely names "Bolt Group" or "BOLTGROUP" explicitly — the actual buyer entity printed is almost always one of the "Northwind"/"Cloverdale"/etc. proxy names, meaning this match is **inferential** (via country/address) far more often than literal. Ambiguity: **Portugal, Thailand, Singapore, Denmark, Switzerland, and several other countries appearing across the corpus have no business unit in this master at all** — a large fraction of documents (including both HLD-01 and HLD-03 above) can only ever produce a blank buyer match through no fault of the extraction logic. At scale, this table would carry many more BU/location combinations; a real system needs a country → BU/location lookup that degrades gracefully to "no match" rather than picking the "closest" wrong country.

**`tax_master.json`** — Contents: ~32 tax codes across ~15 countries, each with `code`, `country`, `tax_type`, `rate` (numeric percent), `name`. Matchable fields: `country` + `rate` is the strongest combined key (rate collisions across countries are common — e.g. 23% appears for both `PL_230_VAT` and `PT_230_IVA` — so country must be joined first). Likely useful: `tax_type` string (VAT/GST/IVA/MOMS/SST/HST/NHIL/etc.) helps disambiguate same-rate/same-country entries when a jurisdiction has multiple tax types at similar rates (e.g. Ghana's five distinct levies). Frequently missing: many documents' exact tax rate/jurisdiction combination is simply absent from this 32-row sample (e.g. Thailand's compounding management-fee scenario in HLD-01 does have direct rate matches for VAT 7% and WHT 3%, but many other rate/country pairs seen across the 42 docs will not). No-match behavior: leave `tax_type_code` blank; never round a document's rate to the "nearest" master entry. At scale, lookup should be a composite index on (country, tax_type, rate) with rate compared at fixed precision (rounding/formatting differences, e.g. "8.10%" vs. "8.1", must be normalized before comparison).

**`payment_terms.json`** — Contents: 10 term codes with `days` and `text_aliases` (multilingual-ish free text hints like "net 30," "60 days," "monthly in advance"). Matchable fields: alias substring/keyword match against the document's payment-terms text, or day-count parsed from an explicit "Due Date − Invoice Date" delta when no explicit terms text is printed. Likely useful: the numeric `days` field, which lets a system derive/cross-check a term even from a document that states only a due date and an invoice date but no explicit "Net N" phrase (e.g. HLD-01's grand total is stated with no explicit terms at all — no code should be forced). Frequently missing: several documents in this corpus print no payment-terms text at all (leave blank). Ambiguity: "Immediate" and "Monthly_in_advance" both have `days: 0` — day-count alone cannot disambiguate them; alias text is required. At scale this stays a small, essentially static lookup table — the main design challenge is normalizing free-text phrasing across languages (German "netto," Estonian "päeva," Portuguese "dias") into a consistent day-count/keyword match.

**`po_master.json`** — Contents: only 2 sample POs, each tied to a specific `supplier_id` and `currency`, with `po_lines`. Matchable field: exact `po_number` string match (POs are unique identifiers by nature; fuzzy matching a PO number is inappropriate). Likely useful: cross-checking the matched PO's `supplier_id`/`currency`/`po_lines` against the document's own supplier/currency/line data as an integrity check once a `po_number` match is found. Frequently missing: the overwhelming majority of PO numbers seen printed across the 42 documents (e.g. INV-31's "PO#16299," INV-32's "PO#: 30193," INV-36's "1000021496") are **not** present in this 2-row sample — this is explicitly called out in the brief/master README as intentional: "a PO not listed here is a non-ERP reference." No-match behavior: keep the raw `po_number` as printed, leave `po_id` blank. At scale, this remains a simple exact-key lookup (POs don't need fuzzy matching), but the volume of legitimately-unmatched POs (because they're the *customer's* PO system, not the ERP's) will be very high and must not be treated as an extraction failure.

**Relationships between tables:** `po_master.json.supplier_id` links to `suppliers.json.supplier_id` (enabling a supplier-identity cross-check once a PO is matched); `chart_of_books.json` has no direct foreign key to any other master (it is purely a country/BU/location tree for the buyer side); `tax_master.json.country` implicitly aligns with both `suppliers.json.country` (supplier's home tax jurisdiction) and the buyer's `chart_of_books` country (destination-country tax rules), meaning a robust tax match should consider both country signals, not just one.

---

## 9. Requirements Matrix

### HARD REQUIREMENTS (explicit, load-bearing, from README.md / AUTODRAFT_SCHEMA.md / erp.py)

| ID | Requirement | Source | Importance | Implementation Impact |
|---|---|---|---|---|
| HR-1 | System runs with one command over `documents/`, writes `output/X.json` per input PDF | README "Output contract" | Critical | Must build a batch driver, not a one-off script |
| HR-2 | Output has exactly `file`, `payables[]`, `declined[]` at the top level | README | Critical | Fixed wrapper shape |
| HR-3 | Every value emitted must appear on the document (no fabricated numbers) | README "Three rules," rule 1 | Critical | Drives all extraction-vs-invention logic |
| HR-4 | Every master code emitted must be a real match; blank is legitimate | README "Three rules," rule 2; AUTODRAFT_SCHEMA field notes | Critical | No fuzzy-match-and-hope; conservative thresholds required |
| HR-5 | Corrections must not fire on documents that were already correct (no over-eager "fixes") | README "Three rules," rule 3 | Critical | Any auto-correction logic needs independent justification, logged |
| HR-6 | `gross_total` etc. are dot-decimal numbers, not locale-formatted | AUTODRAFT_SCHEMA "Field notes" | Critical | Must normalize comma-decimal (DE/EE/PT) inputs |
| HR-7 | `unit_price` is NET (tax-exclusive) | AUTODRAFT_SCHEMA | Critical | Must not submit VAT-inclusive unit prices |
| HR-8 | Tax placement (header vs. line) must mirror the document; this is graded independently of the gross | README "What 'correct' means" | Critical | Structural correctness, not just numeric correctness |
| HR-9 | A credit is `invoice_type: CREDIT_MEMO`, same schema, positive magnitudes | AUTODRAFT_SCHEMA | Critical | Must flip sign convention on ingestion from documents that print negatives |
| HR-10 | `erp.py`'s core calculation must not be modified (may be imported/wrapped only) | README | Critical (compliance, not scoring) | N/A for this analysis-only task, but binding on the eventual implementation |
| HR-11 | Non-payable documents go to `declined[]` with `doc_type` + `reason`, never into `payables[]` | README "Output contract" | Critical | Requires a document-classification step before extraction |

### IMPORTANT EXPECTATIONS (strongly implied by the brief's prose but not machine-checked by erp.py itself)

| ID | Requirement | Source | Importance | Implementation Impact |
|---|---|---|---|---|
| IE-1 | System should generalize to a held-back document unlike any seen — "at least one you will not have seen before at all" | README "How you are judged" | High | Argues against per-document special-casing |
| IE-2 | Distance between open-set and held-back-set pass rate is itself scored — fitting the visible 42 too tightly is penalized | README | High | Avoid hardcoding filenames/entities from this exact corpus |
| IE-3 | DESIGN.md must name at least one document the candidate concludes cannot be solved the way the others were | README "What you submit" | High | This analysis nominates HLD-03 (illegible identity fields) and possibly HLD-01's buyer (no Thailand BU) as candidates — see §11 |
| IE-4 | Matching logic must be designed for master tables that scale to hundreds of thousands/millions of rows, not the tiny provided samples | master_data/README.md | High | No full-table scans; index-first design |
| IE-5 | Duplicate documents/duplicate payables must not double-book | Inferred from INV-04/07, INV-25 pages, HLD-08's "Copy" label | Medium-High | Needs a dedup/idempotency layer keyed on invoice number + supplier + amount |

### OPTIONAL IMPROVEMENTS (reasonable engineering choices, not required by the brief)

| ID | Requirement | Source | Importance | Implementation Impact |
|---|---|---|---|---|
| OI-1 | Confidence scoring surfaced per field (not just a binary matched/blank) | Not stated; good practice | Low-Medium | Would aid human review of low-confidence outputs like HLD-03 |
| OI-2 | A reviewable audit trail per payable showing which document tokens produced which field | Not stated | Low | Supports the "grounding" requirement's auditability |
| OI-3 | Locale-aware date/number parsing library reuse across languages seen (DE, ET, PT, TH, MS, etc.) | Not stated | Medium | Reduces per-language special-casing while still handling the observed variety |

### INFERENCES (this report's own reasoning, not stated by Zycus — kept separate per instructions)

| ID | Inference | Basis | Confidence |
|---|---|---|---|
| INF-1 | The 7-document AmeriHealth/Oracle/PECO/Ciox/215BEARS/Vermont-Ave/Asian-Pacific cluster (INV-31..37) is intentionally "off-universe" to test master-data honesty under documents that look completely normal and payable | No master data or narrative connects them to Bolt Group at all | Medium-High |
| INF-2 | The mismatch between the brief's "35 PDFs" and the actual 42-file folder is either a stale brief, or a signal that file-count itself shouldn't be trusted/hardcoded | Direct observation | Medium |
| INF-3 | HLD-01's management-fee-inside-the-tax-base structure is a deliberately placed "same total, wrong structure" trap, given how explicitly README calls this failure mode out | Textual/structural match to README's warning + exact arithmetic dependency demonstrated in §3 | High |

---

## 10. Assignment Traps

1. **Trusting filename prefixes** (DU-/HLD-/INV-) as a signal of document type or difficulty — they are arbitrary batch labels, not classifications; DU-08 (a dunning letter) and DU-09 (an internal form) are non-payables despite sitting in the same prefix group as several genuine invoices.
2. **Treating everything as an invoice** — delivery notes, waybills, customs declarations, dunning letters, internal approval forms, and quotations/estimates must all be recognized and declined.
3. **OCR-and-stop** — several documents (HLD-01, HLD-03, HLD-08, and arguably DU-03/DU-09) require genuine interpretation of ambiguous layout, overlapping text, or non-Latin scripts/calendars (Thai Buddhist Era dates) beyond raw character recognition.
4. **Inventing numbers to balance totals** — explicitly forbidden (README rule 1); this task's own corpus contains at least one document (HLD-03) where the temptation to guess a supplier name to "complete" the record must be resisted.
5. **Guessing master-data codes** — explicitly forbidden (README rule 2); the sheer number of unmatched suppliers/buyers/taxes/POs across this corpus (a clear majority) means "mostly blank" is the statistically correct output profile, not a sign of a broken matcher.
6. **Collapsing line taxes into a header figure** (or vice-versa) — explicitly called out in README as wrong even when it foots; HLD-05's multi-rate IVA lines and INV-13's mixed 24%/0% parking fees are natural stress tests for this.
7. **Ignoring withholding** — HLD-01's 3% withholding (a negative tax) must reduce the gross; a system that only knows "taxes add" will overstate the payable.
8. **Mishandling credit memos** — sign-flipping (DU-10, DU-11) and recognizing that "no separate shape" means don't build one.
9. **Over-correcting** — README rule 3 explicitly warns that some documents are built to *look* like they need a fix they don't; a system with an aggressive auto-fix layer risks corrupting already-correct records (e.g., "fixing" HLD-08's Meridian/Cloverdale ambiguity by picking one and forcing a master match).
10. **Hard-coding to the visible documents** — since final scoring is dominated by held-back documents "graded the same way," any logic keyed to specific filenames, specific entity name strings, or the exact 42-document set will not generalize.
11. **Treating `sample_autodraft.json` (=INV-01) as "the normal case"** — it is one of the simplest documents in the whole corpus (single 0%-VAT service invoice, no header taxes, no discounts, no master matches shown); building a pipeline whose assumptions are calibrated to that example will immediately break on HLD-01's compounding tax chain or INV-13's 24-line mixed-rate parking bill.
12. **Confusing a line-extension column for a per-unit price column**, as HLD-08's "Nett Price" field demonstrates — labels on real-world templates are not reliable guides to schema semantics; the arithmetic relationship (qty × price = extension) must be checked, not just the column header text.
13. **Netting an already-settled credit into a "amount due" figure and mistaking that net figure for the invoice's own gross_total** (INV-04/INV-07) — the payable owed by the *current* invoice is its own gross, not a running-balance figure that folds in unrelated prior credits.
14. **Assuming every jurisdiction present on a document also exists in the buyer master** — Portugal, Thailand, Denmark, Singapore, Switzerland, and others appear as buyer countries in this corpus with no corresponding Bolt Group business unit at all; forcing a "closest" match here is a fabrication, not a resolution.

---

## 11. Hardest Documents Ranking (all 42, 1 = easiest, 42 = hardest)

*Ranking basis: structural/tax complexity, entity-identity ambiguity, legibility, and number of independent judgment calls required — not merely line count.*

1. INV-01 — single 0%-tax service line, no discounts, no header charges (the `sample_autodraft.json` source)
2. INV-34 — one flat-GST line, standard AU tax-invoice format
3. INV-20 — one flat-VAT line, exact tax_master rate match
4. INV-33 — one line, no tax at all
5. INV-32 — one non-taxable line, explicit "0% tax" label
6. INV-35 — two simple fee lines + flat sales tax
7. INV-36 — single large service line, tax marked "N"
8. DU-05 — single line, no VAT shown, straightforward
9. INV-03 — single-line SA tax invoice, flat 15%
10. INV-16 — two-line courier invoice with one surcharge sub-line
11. INV-02 — multi-line rental invoice, one header discount, one flat VAT rate
12. INV-10 — small catering invoice with rounding line
13. DU-06 — two-rate VAT invoice (23%/6%) but only 5 lines
14. INV-21 — one line discount + flat IVA on discounted base
15. INV-14 / INV-15 — mixed-VAT (20% + "No VAT") in one invoice; identical-amount trap between the two
16. INV-06 — long consumer grocery receipt, many SKUs, but flat/simple tax handling
17. INV-26 — long consumer goods invoice, all zero-rated (simplifies tax, complicates line volume)
18. INV-04 / INV-07 — netted-credit trap + exact duplicate-detection trap
19. INV-25 — Original/Duplicado duplicate-detection trap
20. DU-11 — Estonian credit memo, sign-flip requirement
21. DU-10 — UK credit note, sign-flip + VAT recompute
22. HLD-10 — multi-shipment courier consolidation, two tax buckets (24%/0%)
23. INV-16 (already above) / **INV-27** — multiple usage-based (CBM×days) storage fee lines, flat 16% VAT
24. INV-28 — ~18 small fee lines, uniform 25% moms but high line-count reconciliation
25. DU-08 — dunning letter requiring correct non-payable classification with an embedded prior-invoice/storno history
26. DU-09 — internal approval form, requires recognizing it is not a commercial document at all
27. INV-23 — "ESTIMATE" + ICUMS calculator printout; must correctly decline both despite dense tax-looking tables
28. INV-31 — off-universe US utility bill, layered tariff structure (distribution+supply+taxes) folded into one line
29. INV-37 — off-universe multi-formula spreadsheet-style reimbursement invoice (meter reads × multipliers × rates across 3 sub-systems)
30. INV-11 — multi-line freight invoice with a percentage-based BAF fuel surcharge taxed alongside flat fees
31. INV-19 — Ghana 4-levy chain (NHIL+GETFund+COVID+VAT) computed in sequence
32. INV-13 — ~24 lines, mixed 24%/0% VAT, multiple negative "discount"/"success fee" lines
33. DU-06 (already above) / **HLD-05** — multi-SKU, multi-rate (13%/23%) IVA plus IEC excise across two pages with no single stated grand total
34. DU-03 — a genuine multi-document bundle (tax invoice + cartage advice + customs cargo forms + 5 waybills) requiring correct isolation of the one payable page
35. DU-02 — customs consolidated + 10 detailed sub-invoices across 2 currencies (EUR/TRY), all non-payable to a Bolt entity
36. DU-05s — 11-document delivery-note bundle with 11 different customer names at one address; correctly declining all of it
37. HLD-08 — three-way entity-name conflation + "Copy" duplicate-risk framing + a mislabeled per-unit-vs-extension column
38. **HLD-01** — compounding fee→VAT→withholding chain where the tax base itself depends on a correct structural decision (fee as line item, not header charge), plus overlapping/garbled buyer text and a Buddhist-calendar date
39. **HLD-03** — genuinely overlapping/illegible header and party-identity text; correct answer partly consists of admitting what cannot be read
40. INV-09 — tax amounts given directly (0% nominal rate) rather than as derivable percentages, attached to a dense customs-declaration second page
41. INV-23 (harder facet) — reconciling the "ESTIMATE" cover page against the attached ICUMS duty-calculator's *different* total (13,724.19 vs. 13,289.19) without either being a payable
42. INV-37 (hardest facet) — the single most format-fragile document in the corpus: a spreadsheet-style multi-sub-total reimbursement with an embedded unrelated chart image, requiring careful separation of four independent charge groups into one coherent payable

**Named picks:**
- **Easiest normal invoice:** INV-01 (`sample_autodraft.json`'s own source).
- **Hardest invoice (as opposed to hardest non-invoice paperwork):** HLD-01 (compounding fee/VAT/withholding chain with a genuine structural trap in where the fee must live).
- **Hardest tax structure:** HLD-05 (multi-SKU, dual-rate IVA plus excise across two pages with no single printed grand total) — INV-13 (24-line mixed-rate parking bill with signed adjustment lines) is the runner-up.
- **Hardest OCR/legibility:** HLD-03 (genuinely overlapping/illegible text layers in the party-identity block).
- **Most ambiguous:** HLD-08 (three-way entity-name conflation with no explicit "From/To" labels).
- **Strongest non-payable example:** DU-09 (an internal donation/sponsorship compliance form — nothing about it resembles an invoice once read past the surface tabular layout, yet it is dense with numbers and approval checkboxes that could fool a naive "has a total" heuristic).
- **The credit memo(s):** DU-10 (UK) and DU-11 (Estonia).
- **Document(s) that may be genuinely unsolvable as a normal payable:** HLD-03's supplier/buyer identity (the overlapping text genuinely cannot be resolved to a single confident reading from this scan) and, more fundamentally, INV-23's ESTIMATE + ICUMS pairing, where two different tax authorities' figures for what appears to be the same shipment (13,724.19 vs. 13,289.19) disagree and neither document is itself a payable — there is no way to derive one "correct" gross for this from the page content, because the page content contains two different totals for the same event.

---

## 12. What Zycus Is Really Testing

**INFERENCE — NOT EXPLICITLY STATED BY ZYCUS.**

The basic-candidate behavior this corpus is built to punish is: read every field that looks like an invoice field, fill the schema, submit whatever total is printed, and guess a master code whenever a name looks "close enough." That approach will book perhaps the dozen or so genuinely simple single-line, single-tax-rate documents (INV-01, INV-03, INV-20, INV-33, etc.) and then fail unpredictably on everything else, because the failures (a withholding tax not subtracted, a management fee taxed in the wrong base, a delivery note treated as an invoice, a fabricated supplier code) look like a grab-bag of unrelated bugs rather than one underlying issue.

The strong-candidate behavior this corpus rewards is recognizing that **every one of these documents is answering the same two questions — "is anything genuinely owed here, and can I prove every number and every code I emit against something on the page or in the master data" — and that "I don't know" (decline the document, leave a code blank, refuse to force a fee into the wrong base) is very often the textbook-correct answer**, not a fallback. The conceptual "shift" the brief alludes to (the thing you're supposed to arrive at around "day two") appears, based on this corpus's construction, to be: stop treating each PDF as a data-entry form to fill out faithfully, and start treating it as a claim to be *adjudicated* — a claim that may be false, incomplete, duplicated, out-of-scope, or structured in a way that a faithful transcription would still book wrong. The recurring entity-name-conflation pattern, the duplicate/near-duplicate pairs, the off-universe AmeriHealth cluster, and the deliberately unresolvable HLD-03/INV-23 cases all point toward the same underlying test: **does the system's confidence scale with genuine evidence, or with how invoice-shaped the page looks?**

---

## 13. Explicit Requirements vs. Observations vs. Inferences vs. Open Questions

**EXPLICIT ZYCUS REQUIREMENTS** (see §9 HARD REQUIREMENTS table in full; summarized here):
- One command, `output/X.json` per PDF, `payables[]`/`declined[]` shape.
- Never fabricate a value or a master code.
- Corrections must be justified independently, not just because they "fix" a mismatch.
- Tax placement (header vs. line) and decomposition (no pre-summing) are graded, not just the final gross.
- Credit memos share the invoice schema, positive magnitudes, `invoice_type: CREDIT_MEMO`.
- `erp.py`'s core calculation is immutable; import/wrap only.
- DESIGN.md must answer the three stated questions, including naming an unsolvable document.

**OBSERVATIONS FROM DOCUMENTS** (facts established by directly reading the 42 PDFs and master data in this pass, not inferred):
- The `documents/` folder contains 42 PDF files, not 35.
- `chart_of_books.json` has no business unit for Portugal, Thailand, Denmark, Switzerland, or Singapore, despite documents from all five appearing in the corpus.
- HLD-01's arithmetic requires the 9% management fee to sit inside the tax base (verified exactly: 7,200×1.09=7,848; ×1.07=8,397.36; less 7,848×0.03=235.44 → 8,161.92).
- HLD-03 contains genuinely overlapping/illegible text in its supplier/buyer block.
- HLD-08 prints three different company names with no explicit "From/To" labeling and is itself labeled a "Copy Tax Invoice."
- INV-04 and INV-07 are byte-identical documents; INV-25's two pages are an "Original"/"Duplicado" pair of the same invoice.
- INV-14 and INV-15 are different, genuinely-both-payable invoices that happen to share an identical total (29,253.72 GBP).
- INV-31 through INV-37 concern entities (AmeriHealth Caritas, Oracle, PECO, Ciox Health, 215 B.E.A.R.S., Asian Pacific Serviced Offices, 1120 Vermont Avenue Associates) with zero overlap with any master-data entity.
- INV-23's cover "ESTIMATE" (13,724.19 GHS) and its attached ICUMS duty-calculator printout (13,289.19 GHS payable tax) state two different totals for what appears to be the same shipment.

**INFERENCES** (this report's own reasoning; see §9's INFERENCES sub-table and §12 for full statements; not claimed as Zycus's stated intent):
- The 35-vs-42 mismatch may itself be a deliberate "don't trust the stated count" signal, or simply a stale brief.
- The AmeriHealth/Oracle/PECO cluster is likely intentionally off-universe to test master-data honesty.
- HLD-01's structure is likely a deliberately placed "same total, wrong structure" trap given how precisely it matches the README's own warning language.
- The overall conceptual "shift" the brief gestures at is (in this report's reading) a move from transcription to adjudication.

**OPEN QUESTIONS** (neither answered by the provided materials nor resolvable from this pass alone — see §14 for the full list).

---

## 14. Open Questions

1. **Document count mismatch:** the brief and this task's instructions both reference "35 PDFs," but `documents/` contains 42. Is this a stale README, a held-back-vs-open-set confusion (i.e., some of these 42 might belong to a different, larger sample than the "35" the brief describes), or an intentional distractor? This report has not silently reconciled the two numbers — it lists all 42 file-derived rows and flags the discrepancy rather than guessing which 7 to drop.
2. **HLD-08's supplier/buyer direction** (Cloverdale-as-issuer vs. Meridian-as-customer) is a best-effort reading, not a certainty, given the absence of explicit "From/To" labels on that template — a second opinion or a higher-resolution scan would be needed to fully resolve it.
3. **HLD-03's true supplier/buyer identity** may be permanently unrecoverable from this particular scan (the overlapping text appears to be a rendering artifact baked into the source PDF itself, not a resolution/DPI problem) — would a different source rendering of this same document (if one exists) disambiguate it?
4. **HLD-05's per-page/grand total:** the document spans two pages of line items with a sub-total shown on page 2 but no single explicit page-spanning grand total was located in the OCR-visible text — does a grand total exist off the readable region, or is the correct payable actually the sum of both pages' sub-totals?
5. **INV-23's two conflicting totals** (13,724.19 estimate vs. 13,289.19 ICUMS payable tax) — is this intentionally unsolvable (this report's leading candidate for the brief's "at least one document asks something the page does not contain the answer to"), or is there a reconciling relationship between "Custom Duties" + "Service Charges" (estimate) and "Payable Tax" (ICUMS) that a domain expert in Ghanaian customs would recognize but this analysis did not surface?
6. **Whether the held-back set draws further documents from the same "off-universe" AmeriHealth/Oracle-style cluster**, or introduces an entirely new third universe — the open set alone cannot answer this.

---

## 15. What We Now Know

- The full technical contract: schema shape, field-by-field semantics, and the exact ERP recompute formula (§5–7).
- Every master-data file's contents, matchable fields, and realistic match rates against this corpus (§8) — the overwhelming majority of supplier/buyer/tax/PO fields across the 42 documents are legitimately unmatched, which is the *expected*, correct output profile, not a sign of a broken matcher.
- A verified, cent-exact reconstruction of HLD-01's compounding tax chain and the specific schema-modeling decision (fee-as-line-item, not header extra_charges) required to reproduce it through `erp.py`.
- A verified reconstruction of HLD-08's and HLD-03's printed figures, with explicit, non-fabricated treatment of their respective identity ambiguities.
- A cross-document pattern catalogue (§4) of recurring traps: entity-name conflation, duplicate/near-duplicate documents, netted-credit decoys, off-universe documents, and taxed-charge-vs-header-charge structural hazards.

## 16. What We Still Don't Know

- Whether the document-count and total-mismatch anomalies (§14, items 1 and 5) are intentional test design or artifacts of this particular kit build.
- The true resolved identity of HLD-03's and (with lower confidence) HLD-08's transacting parties.
- Whether any additional "off-universe" document clusters exist in the held-back set beyond the AmeriHealth/Oracle pattern observed here.
- Whether Zycus's grader applies any tolerance band around the "to the cent" gross match, or is strictly exact.

## 17. What Must Be Decided Before Coding

1. **Classification-first architecture:** a document-type/payability classifier must run and gate extraction, rather than treating "table with a total" as sufficient evidence to attempt a payable.
2. **A conservative, explainable master-matching policy** (exact VAT-ID / exact PO-number first, then a bounded fuzzy-name pass with a defensible confidence floor) that defaults to blank, designed against index-based lookups suitable for a million-row master, not the tiny provided samples.
3. **A canonical internal representation that separates "taxed together" from "post-tax" charges**, so that a fee genuinely taxed alongside goods/services (HLD-01) is never silently routed into `freight_charges`/`extra_charges`/etc. purely because it superficially resembles a header charge.
4. **A duplicate/near-duplicate detection layer** (keyed on normalized invoice number + supplier + amount + date) that runs before payables are finalized, given the multiple duplicate-pattern documents observed (§4, §10).
5. **A locale-normalization layer** for numbers (comma vs. dot decimal), dates (including non-Gregorian calendars such as the Thai Buddhist Era seen in HLD-01), and currency symbols, applied uniformly rather than per-language special-cased where avoidable (per IE-4/OI-3).
6. **An explicit "decline with reason" taxonomy** for the non-payable document types actually observed (delivery note, dunning/reminder letter, internal approval/compliance form, customs/logistics paperwork, quotation/estimate, self-billing artifact) so that `declined[].reason` values are consistent and auditable rather than free-text improvised per document.
7. **A policy for genuinely ambiguous documents** (HLD-03, HLD-08, INV-23) — deciding in advance whether the system should emit a low-confidence payable with blank identity fields, or decline with a "cannot be reliably resolved" reason, and applying that policy consistently rather than ad hoc per document.
