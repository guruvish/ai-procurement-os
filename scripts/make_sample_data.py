"""Creates realistic synthetic RFQ + supplier quotation files for trying the app by hand.
Run:  python scripts/make_sample_data.py   -> files appear in sample_data/RFQ-2026-001/"""
from io import BytesIO
from pathlib import Path

import pandas as pd
import pymupdf as fitz

OUT = Path(__file__).resolve().parent.parent / "sample_data" / "RFQ-2026-001"
RFQ_NO = "RFQ-2026-001"

DOCS = {
    "RFQ-2026-001.pdf": f"""REQUEST FOR QUOTATION
RFQ No: {RFQ_NO}        Date: 05/11/2026
Buyer: Sunrise Pharma Pvt Ltd, Purchase Department
Item: Paracetamol API (IP/BP grade)      Quantity: 10,000 kg
Technical requirements:
- Assay (purity): minimum 99.5%
- Loss on drying: not more than 0.5%
- Particle size D90: preferably below 150 micron (desirable)
Documents required: Certificate of Analysis (CoA) with every batch; valid GMP certificate.
Delivery: within 30 days of purchase order.   Payment terms: 30 days after delivery.
Prices to be quoted in INR per kg, exclusive of GST.""",
    "Acme_Quotation.pdf": f"""QUOTATION - Acme Chem Industries, Hyderabad
Quotation No: QUO-ACM-118      Date: 10/11/2026      Ref: {RFQ_NO}
Product: Paracetamol IP     Quantity: 10,000 kg
Rate: Rs. 185 per kg (GST 18% extra). Freight: included.
Assay: 99.8%    LOD: 0.3%
Delivery: 3 weeks from PO.  Payment: 30 days from delivery.
CoA provided with each batch. GMP certificate attached.
Validity: 30 days from quotation date.""",
    "Beta_Quotation.pdf": f"""QUOTATION - Beta Pharma Chem, Ahmedabad
Ref: {RFQ_NO}   Quote No: BPC/2026/771   Date: 12/11/2026   Valid till: 15/12/2026
Paracetamol API, 10000 kg @ INR 172/kg + GST 18%
Specification: Assay 99.2%, Loss on drying 0.4%
Delivery 25 days. Payment 30 days after delivery. CoA with each batch; GMP certificate available.""",
    "Gamma_Quotation.pdf": f"""QUOTATION - Gamma Organics Ltd, Vapi
Our ref: GO-5512   Date: 01/10/2026   Your ref: {RFQ_NO}
Paracetamol IP grade - 10,000 kg
Price: to be confirmed after sample approval.
Assay NLT 99.6%, LOD 0.2%. Delivery: 4 weeks.
Payment: 50% advance, balance within 15 days.
CoA available on request. Offer valid for 30 days.""",
}


def pdf(text: str) -> bytes:
    doc = fitz.open()
    doc.new_page().insert_textbox(fitz.Rect(50, 50, 550, 800), text, fontsize=10)
    return doc.tobytes()


def delta_xlsx() -> bytes:
    rows = [["Supplier", "Delta Life Sciences, Pune"], ["Quotation No", "DLS-Q-0098"], ["Date", "2026-11-14"],
            ["Valid until", "2026-12-31"], ["RFQ ref", RFQ_NO], ["Product", "Paracetamol API"],
            ["Quantity", "10,000 kg"], ["Price per gram (INR, incl. GST 18%)", 0.2124],
            ["Purity (assay) %", 99.7], ["Moisture (LOD) %", 0.25], ["Delivery", "20 days"],
            ["Payment", "45 days after delivery"], ["Documents", "CoA per batch, WHO-GMP certificate"]]
    buf = BytesIO()
    pd.DataFrame(rows, columns=["Field", "Value"]).to_excel(buf, index=False)
    return buf.getvalue()


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in DOCS.items():
        (OUT / name).write_bytes(pdf(text))
    (OUT / "Delta_Quotation.xlsx").write_bytes(delta_xlsx())
    (OUT / "Epsilon_Quotation_CORRUPTED.pdf").write_bytes(b"%PDF-1.4 this file got corrupted in email")
    print(f"Sample files written to {OUT}:")
    for f in sorted(OUT.iterdir()):
        print("  ", f.name)
