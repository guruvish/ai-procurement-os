"""Full v0 run with REAL Gemini calls:
create request -> upload RFQ + 4 quotations (PDF + Excel) + 1 corrupted file -> LangGraph workflow
-> deterministic evaluation -> human correction -> re-evaluation -> human approval.
"""
import hashlib
from datetime import datetime
from io import BytesIO

import pandas as pd
import pymupdf as fitz

from app import db
from app.agents import workflow

RFQ = """REQUEST FOR QUOTATION
RFQ No: {rfq}        Date: 05/11/2026
Buyer: Sunrise Pharma Pvt Ltd, Purchase Department
Item: Paracetamol API (IP/BP grade)      Quantity: 10,000 kg
Technical requirements:
- Assay (purity): minimum 99.5%
- Loss on drying: not more than 0.5%
- Particle size D90: preferably below 150 micron (desirable)
Documents required: Certificate of Analysis (CoA) with every batch; valid GMP certificate.
Delivery: within 30 days of purchase order.   Payment terms: 30 days after delivery.
Prices to be quoted in INR per kg, exclusive of GST."""

ACME = """QUOTATION - Acme Chem Industries, Hyderabad
Quotation No: QUO-ACM-118      Date: 10/11/2026      Ref: {rfq}
Product: Paracetamol IP     Quantity: 10,000 kg
Rate: Rs. 185 per kg (GST 18% extra). Freight: included.
Assay: 99.8%    LOD: 0.3%
Delivery: 3 weeks from PO.  Payment: 30 days from delivery.
CoA provided with each batch. GMP certificate attached.
Validity: 30 days from quotation date."""

BETA = """QUOTATION - Beta Pharma Chem, Ahmedabad
Ref: {rfq}   Quote No: BPC/2026/771   Date: 12/11/2026   Valid till: 15/12/2026
Paracetamol API, 10000 kg @ INR 172/kg + GST 18%
Specification: Assay 99.2%, Loss on drying 0.4%
Delivery 25 days. Payment 30 days after delivery. CoA with each batch; GMP certificate available."""

GAMMA = """QUOTATION - Gamma Organics Ltd, Vapi
Our ref: GO-5512   Date: 01/10/2026   Your ref: {rfq}
Paracetamol IP grade - 10,000 kg
Price: to be confirmed after sample approval.
Assay NLT 99.6%, LOD 0.2%. Delivery: 4 weeks.
Payment: 50% advance, balance within 15 days.
CoA available on request. Offer valid for 30 days."""


def pdf(text: str) -> bytes:
    doc = fitz.open()
    doc.new_page().insert_textbox(fitz.Rect(50, 50, 550, 800), text, fontsize=10)
    return doc.tobytes()


def delta_xlsx(rfq: str) -> bytes:
    rows = [["Supplier", "Delta Life Sciences, Pune"], ["Quotation No", "DLS-Q-0098"], ["Date", "2026-11-14"],
            ["Valid until", "2026-12-31"], ["RFQ ref", rfq], ["Product", "Paracetamol API"],
            ["Quantity", "10,000 kg"], ["Price per gram (INR, incl. GST 18%)", 0.2124],
            ["Purity (assay) %", 99.7], ["Moisture (LOD) %", 0.25], ["Delivery", "20 days"],
            ["Payment", "45 days after delivery"], ["Documents", "CoA per batch, WHO-GMP certificate"]]
    buf = BytesIO()
    pd.DataFrame(rows, columns=["Field", "Value"]).to_excel(buf, index=False)
    return buf.getvalue()


def upload(rid, name, data, role):
    db.save_document(rid, name, data, hashlib.sha256(data).hexdigest(), name.rsplit(".", 1)[1], role)


db.init_db()
rfq_no = f"RFQ-DEMO-{datetime.now():%H%M%S}"
rid = db.create_request(rfq_no, title="Paracetamol API Q4", department="Purchase", buyer="Sunrise Pharma")
upload(rid, f"{rfq_no}.pdf", pdf(RFQ.format(rfq=rfq_no)), "RFQ")
upload(rid, "Acme_Quotation.pdf", pdf(ACME.format(rfq=rfq_no)), "QUOTATION")
upload(rid, "Beta_Quotation.pdf", pdf(BETA.format(rfq=rfq_no)), "QUOTATION")
upload(rid, "Gamma_Quotation.pdf", pdf(GAMMA.format(rfq=rfq_no)), "QUOTATION")
upload(rid, "Delta_Quotation.xlsx", delta_xlsx(rfq_no), "QUOTATION")
upload(rid, "Epsilon_Quotation.pdf", b"%PDF-1.4 this file got corrupted in email", "QUOTATION")

print(f"\n>>> Processing {rfq_no} (5 AI calls, ~1 minute)...\n")
result = workflow.run_processing(rid)


def show():
    print(f"\nSTATUS: {db.get_status(rid).value}")
    print(f"{'Supplier':<28}{'Verdict':<22}{'Risk':<8}{'INR/kg':>10}{'Total':>16}")
    for e in db.get_evaluations(rid):
        price = f"{e.normalized_unit_price:,.2f}" if e.normalized_unit_price is not None else "-"
        total = f"{e.total_cost:,.0f}" if e.total_cost is not None else "-"
        print(f"{e.supplier_name[:27]:<28}{e.overall_status:<22}{e.risk_level:<8}{price:>10}{total:>16}")
        for f in e.findings:
            if f.severity != "LOW":
                print(f"      [{f.severity}] {f.message}")
    print("\nRECOMMENDATION:", db.get_recommendation(rid)["explanation"])


show()
print("\nDocument errors:", *[f"\n  - {e['filename']}: {e['error']}" for e in result["doc_errors"]] or [" none"])
print("Review reasons:", *[f"\n  - {r}" for r in result["review_reasons"]] or [" none"])
print("Metrics:", result["metrics"])

print("\n>>> HUMAN REVIEW: buyer calls Gamma, gets a revalidated price of INR 178/kg (excl. GST)")
gamma = next((x for x in db.list_quotations(rid) if x["quotation"].supplier_name.startswith("Gamma")), None)
if gamma is None:
    print("   Gamma was not extracted (see document errors above) - skipping the correction step.")
else:
    db.human_edit_quotation(rid, gamma["document_id"],
                            {"unit_price": 178.0, "price_per": "kg", "currency": "INR",
                             "tax_status": "exclusive", "valid_until": "2026-12-20"}, actor="demo-buyer")
    workflow.reevaluate(rid, actor="demo-buyer")
    show()

print("\n>>> HUMAN DECISION")
rec = db.get_recommendation(rid)["recommended_supplier"]
db.record_decision(rid, "APPROVED", reviewer="demo-manager", comments="Approved per evaluation",
                   selected_supplier=rec)
print(f"STATUS: {db.get_status(rid).value} | selected: {rec}")
print("\nAUDIT TRAIL:")
for a in db.list_audit(rid):
    print(f"  {a['created_at']}  {a['actor']:<13} {a['event_type']:<20} {a['description'][:90]}")
