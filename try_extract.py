"""v0 end-to-end check: synthetic RFQ + quotation -> Gemini extraction -> deterministic evaluation."""
from datetime import date

import pymupdf as fitz

from app.agents.extractors import extract_quotation, extract_rfq
from app.services.document_parser import parse_document
from app.services.evaluation_engine import evaluate_all, recommend

RFQ_TEXT = """REQUEST FOR QUOTATION
RFQ No: RFQ-2026-001        Date: 05/11/2026
Buyer: Sunrise Pharma Pvt Ltd, Purchase Department

Item: Paracetamol API (IP/BP grade)
Quantity: 10,000 kg

Technical requirements:
- Assay (purity): minimum 99.5%
- Loss on drying: not more than 0.5%
- Particle size D90: preferably below 150 micron (desirable)

Documents required: Certificate of Analysis (CoA) with every batch; valid GMP certificate.
Delivery: within 30 days of purchase order.
Payment terms: 30 days after delivery.
Prices to be quoted in INR per kg, exclusive of GST."""

QUOTE_TEXT = """QUOTATION
Acme Chem Industries, Hyderabad
Quotation No: QUO-ACM-118      Date: 10/11/2026
To: Sunrise Pharma Pvt Ltd     Ref: RFQ-2026-001

Product: Paracetamol IP
Quantity: 10,000 kg
Rate: Rs. 185 per kg (GST 18% extra)
Freight: included
Assay: 99.8%
LOD: 0.3%
Delivery: 3 weeks from PO
Payment: 30 days from delivery
CoA provided with each batch. GMP certificate attached.
Validity: 30 days from quotation date."""


def make_pdf(text: str) -> bytes:
    doc = fitz.open()
    doc.new_page().insert_textbox(fitz.Rect(50, 50, 550, 800), text, fontsize=10)
    return doc.tobytes()


rfq_doc = parse_document("RFQ-2026-001.pdf", make_pdf(RFQ_TEXT))
quote_doc = parse_document("Acme_Quotation.pdf", make_pdf(QUOTE_TEXT))

rfq, m1 = extract_rfq(rfq_doc, rfq_id="RFQ-2026-001")
quote, m2 = extract_quotation(quote_doc, rfq)
print(f"\nExtraction: RFQ {m1.latency_s}s ({m1.attempts} attempt) | Quote {m2.latency_s}s ({m2.attempts} attempt)")

evals = evaluate_all(rfq, [quote], today=date.today())
for ev in evals:
    print(f"\n===== {ev.supplier_name}: {ev.overall_status} (risk {ev.risk_level}) =====")
    for c in ev.checks:
        flag = "*" if c.mandatory else " "
        print(f" {flag} {c.status.value:<16} {c.requirement:<36} req {c.required:<22} got {c.offered:<14} | {c.reason}")
    print(f"   Normalized price: {ev.normalized_unit_price} per {rfq.unit} | Total: {ev.total_cost}")
    for f in ev.findings:
        print(f"   [{f.severity}] {f.message}")

print("\nRECOMMENDATION:", recommend(evals)["explanation"])
print("(* = mandatory requirement)")
