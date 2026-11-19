"""The 10 evaluation cases from the project blueprint, with hand-written ground truth.

Each case = one RFQ + supplier documents (in several formats) + what a careful buyer would extract and
decide. Dates are relative to the day the evaluation runs, so "expired" stays expired and "valid" stays
valid whenever you run it. Ground truth was written by hand from the document text below - review it
before trusting the numbers (docs/evaluation_report.md explains how).
"""
from datetime import date, timedelta

from app.schemas import OfferedSpec, RFQRequirements, SupplierQuotation, TechRequirement

TODAY = date.today()
QDATE = TODAY - timedelta(days=5)          # quotation date for normal quotes
VALID = TODAY + timedelta(days=25)         # validity for normal quotes
OLD_QDATE = TODAY - timedelta(days=60)     # TC-08 expired quote
OLD_VALID = TODAY - timedelta(days=30)


def d(x: date) -> str:
    return x.strftime("%d/%m/%Y")


# ---------------------------------------------------------------- RFQs
def rfq_text(rfq_no: str) -> str:
    return f"""REQUEST FOR QUOTATION
RFQ No: {rfq_no}        Date: {d(TODAY - timedelta(days=10))}
Buyer: Sunrise Pharma Pvt Ltd, Purchase Department

Item: Paracetamol API (IP/BP grade)
Quantity: 10,000 kg

Technical requirements:
- Assay (purity): minimum 99.5%
- Loss on drying: not more than 0.5%

Documents required: Certificate of Analysis (CoA) with every batch; valid GMP certificate.
Delivery: within 30 days of purchase order.
Payment terms: 30 days after delivery.
Prices to be quoted in INR per kg, exclusive of GST."""


def rfq_truth(rfq_no: str) -> RFQRequirements:
    return RFQRequirements(
        rfq_id=rfq_no, product_name="Paracetamol API", required_quantity=10000, unit="kg", currency="INR",
        technical_requirements=[TechRequirement(name="purity", operator=">=", value=99.5, unit="%"),
                                TechRequirement(name="moisture", operator="<=", value=0.5, unit="%")],
        required_certificates=["Certificate of Analysis", "GMP certificate"], max_delivery_days=30,
        payment_terms="30 days after delivery")


MCC_RFQ = """REQUEST FOR QUOTATION
RFQ No: {rfq_no}        Date: {date}
Buyer: Sunrise Pharma Pvt Ltd, Purchase Department

Item: Microcrystalline Cellulose PH-102 (excipient)
Quantity: 5 MT (metric tonnes)

Technical requirements:
- Loss on drying: not more than 5.0%

Documents required: Certificate of Analysis.
Delivery: within 21 days of purchase order.
Payment terms: 45 days after delivery.
Prices in INR per kg, exclusive of GST."""


def mcc_truth(rfq_no: str) -> RFQRequirements:
    return RFQRequirements(
        rfq_id=rfq_no, product_name="Microcrystalline Cellulose", required_quantity=5, unit="MT", currency="INR",
        technical_requirements=[TechRequirement(name="moisture", operator="<=", value=5.0, unit="%")],
        required_certificates=["Certificate of Analysis"], max_delivery_days=21, payment_terms="45 days after delivery")


# ---------------------------------------------------------------- supplier quote builder
def quote(name, city, qno, rfq_no, price_line, specs_line, delivery_line, payment_line, docs_line,
          validity_line=None, qdate=QDATE, qty_line="Quantity: 10,000 kg", extra=""):
    validity_line = validity_line or f"Valid until: {d(VALID)}"
    return f"""QUOTATION
{name}, {city}
Quotation No: {qno}      Date: {d(qdate)}
To: Sunrise Pharma Pvt Ltd     Ref: {rfq_no}

Product: Paracetamol IP
{qty_line}
{price_line}
{specs_line}
{delivery_line}
{payment_line}
{docs_line}
{validity_line}
{extra}""".strip()


def truth(name, price, delivery, purity, moisture, certs, *, price_per="kg", tax="exclusive", rate=18.0,
          valid=VALID, qdate=QDATE, pay="30 days after delivery", qty=10000, unit="kg", conflicts=False,
          currency="INR"):
    specs = []
    if purity is not None:
        specs.append(OfferedSpec(name="purity", value=purity, unit="%"))
    if moisture is not None:
        specs.append(OfferedSpec(name="moisture", value=moisture, unit="%"))
    q = SupplierQuotation(supplier_name=name, unit_price=price, price_per=price_per if price is not None else None,
                          currency=currency if price is not None else None, tax_status=tax,
                          tax_rate_percent=rate, delivery_days=delivery, valid_until=valid, quotation_date=qdate,
                          payment_terms=pay, certificates=certs, specifications=specs, quantity=qty, unit=unit)
    q.conflicts = ["purity: conflicting values"] if conflicts else []
    return q


FULL_DOCS = "Certificate of Analysis provided with each batch. GMP certificate attached."
CERTS = ["Certificate of Analysis", "GMP certificate"]


def _std(rfq_no, name, city, qno, price, purity=99.8, moisture=0.3, delivery=21, fmt="pdf", **kw):
    """A normal, complete quotation in the requested format."""
    text = quote(name, city, qno, rfq_no, f"Rate: INR {price} per kg (GST 18% extra)",
                 f"Assay: {purity}%    Loss on drying: {moisture}%", f"Delivery: {delivery} days from PO",
                 "Payment: 30 days after delivery", FULL_DOCS)
    return {"file": f"{name.split()[0]}_{qno}.{ 'xlsx' if fmt == 'xlsx' else 'docx' if fmt == 'docx' else 'pdf'}",
            "format": fmt, "text": text, "truth": truth(name, price, delivery, purity, moisture, CERTS, **kw)}


# ---------------------------------------------------------------- the 10 cases
def build_cases() -> list:
    cases = []

    r = "EV-TC01"
    cases.append({"id": "TC-01", "title": "Normal RFQ - three complete quotations (PDF, Excel, Word)",
                  "rfq": rfq_text(r), "rfq_truth": rfq_truth(r),
                  "quotes": [dict(_std(r, "Acme Chem Industries", "Hyderabad", "A-101", 185), verdict="COMPLIANT"),
                             dict(_std(r, "Delta Life Sciences", "Pune", "D-202", 180, fmt="xlsx"), verdict="COMPLIANT"),
                             dict(_std(r, "Orion Pharma", "Mumbai", "O-303", 190, fmt="docx"), verdict="COMPLIANT")],
                  "expect_recommended": "Delta Life Sciences"})

    r = "EV-TC02"
    nop = quote("Gamma Organics Ltd", "Vapi", "G-11", r, "Price: to be confirmed after sample approval.",
                "Assay: 99.7%    Loss on drying: 0.2%", "Delivery: 20 days from PO", "Payment: 30 days after delivery",
                FULL_DOCS)
    cases.append({"id": "TC-02", "title": "Supplier quotation missing price",
                  "rfq": rfq_text(r), "rfq_truth": rfq_truth(r),
                  "quotes": [dict(_std(r, "Acme Chem Industries", "Hyderabad", "A-102", 185), verdict="COMPLIANT"),
                             {"file": "Gamma_G-11.pdf", "format": "pdf", "text": nop, "verdict": "NEEDS_CLARIFICATION",
                              "truth": truth("Gamma Organics Ltd", None, 20, 99.7, 0.2, CERTS, tax="unknown", rate=None)}],
                  "expect_recommended": "Acme Chem Industries"})

    r = "EV-TC03"
    mt = quote("Cellutech Industries", "Ahmedabad", "C-31", r, "Rate: INR 1,95,000 per MT (GST 12% extra)",
               "Loss on drying: 4.2%", "Delivery: 2 weeks from PO", "Payment: 45 days after delivery",
               "Certificate of Analysis provided.", qty_line="Quantity: 5 MT").replace("Paracetamol IP", "MCC PH-102")
    gr = quote("FibreChem Pvt Ltd", "Surat", "F-32", r, "Price: INR 0.21 per gram, GST 12% extra",
               "LOD: 3.8%", "Delivery: 18 days", "Payment: 45 days after delivery", "CoA with each lot.",
               qty_line="Quantity: 5,000 kg").replace("Paracetamol IP", "Microcrystalline Cellulose PH102")
    cases.append({"id": "TC-03", "title": "Different measurement units (price per MT vs per gram)",
                  "rfq": MCC_RFQ.format(rfq_no=r, date=d(TODAY - timedelta(days=10))), "rfq_truth": mcc_truth(r),
                  "quotes": [{"file": "Cellutech_C-31.pdf", "format": "pdf", "text": mt, "verdict": "COMPLIANT",
                              "truth": truth("Cellutech Industries", 195000, 14, None, 4.2, ["Certificate of Analysis"],
                                             price_per="MT", rate=12.0, pay="45 days after delivery", qty=5, unit="MT")},
                             {"file": "FibreChem_F-32.pdf", "format": "pdf", "text": gr, "verdict": "COMPLIANT",
                              "truth": truth("FibreChem Pvt Ltd", 0.21, 18, None, 3.8, ["Certificate of Analysis"],
                                             price_per="g", rate=12.0, pay="45 days after delivery", qty=5000)}],
                  # 195,000 per MT vs 0.21 per g (= 210,000 per MT): both compliant, Cellutech is cheaper
                  "expect_recommended": "Cellutech Industries"})

    r = "EV-TC04"
    cases.append({"id": "TC-04", "title": "Scanned quotation PDF (image only, no text layer)",
                  "rfq": rfq_text(r), "rfq_truth": rfq_truth(r),
                  "quotes": [dict(_std(r, "Acme Chem Industries", "Hyderabad", "A-104", 185), verdict="COMPLIANT"),
                             dict(_std(r, "Kappa Fine Chemicals", "Chennai", "K-404", 182, delivery=25, fmt="scanned"),
                                  verdict="COMPLIANT")],
                  "expect_recommended": "Kappa Fine Chemicals"})
    cases[-1]["quotes"][1]["file"] = "Kappa_K-404_scanned.pdf"

    r = "EV-TC05"
    conf = quote("Sigma Actives", "Hyderabad", "S-55", r, "Rate: INR 178 per kg (GST 18% extra)",
                 "Assay: 99.8%    Loss on drying: 0.3%", "Delivery: 21 days from PO", "Payment: 30 days after delivery",
                 FULL_DOCS, extra="\n\nATTACHED CERTIFICATE OF ANALYSIS (batch SA-2291)\nAssay: 99.2%\nLoss on drying: 0.3%")
    cases.append({"id": "TC-05", "title": "Conflicting purity values in one quotation",
                  "rfq": rfq_text(r), "rfq_truth": rfq_truth(r),
                  "quotes": [dict(_std(r, "Acme Chem Industries", "Hyderabad", "A-105", 185), verdict="COMPLIANT"),
                             {"file": "Sigma_S-55.pdf", "format": "pdf", "text": conf, "verdict": "NEEDS_CLARIFICATION",
                              "truth": truth("Sigma Actives", 178, 21, 99.8, 0.3, CERTS, conflicts=True)}],
                  "expect_recommended": "Acme Chem Industries"})

    r = "EV-TC06"
    nocoa = quote("Beta Pharma Chem", "Ahmedabad", "B-66", r, "Rate: INR 176 per kg (GST 18% extra)",
                  "Assay: 99.7%    Loss on drying: 0.4%", "Delivery: 25 days from PO", "Payment: 30 days after delivery",
                  "GMP certificate available.")
    cases.append({"id": "TC-06", "title": "Missing Certificate of Analysis",
                  "rfq": rfq_text(r), "rfq_truth": rfq_truth(r),
                  "quotes": [dict(_std(r, "Acme Chem Industries", "Hyderabad", "A-106", 185), verdict="COMPLIANT"),
                             {"file": "Beta_B-66.pdf", "format": "pdf", "text": nocoa, "verdict": "NEEDS_CLARIFICATION",
                              "truth": truth("Beta Pharma Chem", 176, 25, 99.7, 0.4, ["GMP certificate"])}],
                  "expect_recommended": "Acme Chem Industries"})

    r = "EV-TC07"
    late = quote("Zeta Labs", "Bengaluru", "Z-77", r, "Rate: INR 170 per kg (GST 18% extra)",
                 "Assay: 99.9%    Loss on drying: 0.2%", "Delivery: 6 weeks from PO", "Payment: 30 days after delivery",
                 FULL_DOCS)
    cases.append({"id": "TC-07", "title": "Supplier delivery exceeds the limit",
                  "rfq": rfq_text(r), "rfq_truth": rfq_truth(r),
                  "quotes": [dict(_std(r, "Acme Chem Industries", "Hyderabad", "A-107", 185), verdict="COMPLIANT"),
                             {"file": "Zeta_Z-77.pdf", "format": "pdf", "text": late, "verdict": "NOT_COMPLIANT",
                              "truth": truth("Zeta Labs", 170, 42, 99.9, 0.2, CERTS)}],
                  "expect_recommended": "Acme Chem Industries"})

    r = "EV-TC08"
    exp = quote("Omega Drugs", "Indore", "OM-88", r, "Rate: INR 174 per kg (GST 18% extra)",
                "Assay: 99.6%    Loss on drying: 0.3%", "Delivery: 21 days from PO", "Payment: 30 days after delivery",
                FULL_DOCS, validity_line=f"Valid until: {d(OLD_VALID)}", qdate=OLD_QDATE)
    cases.append({"id": "TC-08", "title": "Quotation has expired",
                  "rfq": rfq_text(r), "rfq_truth": rfq_truth(r),
                  "quotes": [dict(_std(r, "Acme Chem Industries", "Hyderabad", "A-108", 185), verdict="COMPLIANT"),
                             {"file": "Omega_OM-88.pdf", "format": "pdf", "text": exp, "verdict": "NEEDS_CLARIFICATION",
                              "truth": truth("Omega Drugs", 174, 21, 99.6, 0.3, CERTS, valid=OLD_VALID, qdate=OLD_QDATE)}],
                  "expect_recommended": "Acme Chem Industries"})

    r = "EV-TC09"
    incl = quote("Theta Healthcare", "Vadodara", "T-91", r, "Rate: INR 212.40 per kg inclusive of GST @18%",
                 "Assay: 99.7%    Loss on drying: 0.3%", "Delivery: 20 days from PO", "Payment: 30 days after delivery",
                 FULL_DOCS)
    unk = quote("Lambda Chem", "Nashik", "L-92", r, "Rate: INR 175 per kg",
                "Assay: 99.7%    Loss on drying: 0.3%", "Delivery: 20 days from PO", "Payment: 30 days after delivery",
                FULL_DOCS)
    cases.append({"id": "TC-09", "title": "GST treatment differs (inclusive / exclusive / unclear)",
                  "rfq": rfq_text(r), "rfq_truth": rfq_truth(r),
                  "quotes": [dict(_std(r, "Acme Chem Industries", "Hyderabad", "A-109", 185), verdict="COMPLIANT"),
                             {"file": "Theta_T-91.pdf", "format": "pdf", "text": incl, "verdict": "COMPLIANT",
                              "truth": truth("Theta Healthcare", 212.40, 20, 99.7, 0.3, CERTS, tax="inclusive")},
                             {"file": "Lambda_L-92.pdf", "format": "pdf", "text": unk, "verdict": "NEEDS_CLARIFICATION",
                              "truth": truth("Lambda Chem", 175, 20, 99.7, 0.3, CERTS, tax="unknown", rate=None)}],
                  # Theta: 212.40 / 1.18 = 180.00 per kg excl. tax -> cheaper than Acme (185)
                  "expect_recommended": "Theta Healthcare"})

    r = "EV-TC10"
    cases.append({"id": "TC-10", "title": "Corrupted / wrong documents among valid ones",
                  "rfq": rfq_text(r), "rfq_truth": rfq_truth(r),
                  "quotes": [dict(_std(r, "Acme Chem Industries", "Hyderabad", "A-110", 185), verdict="COMPLIANT"),
                             {"file": "Epsilon_quote.pdf", "format": "corrupt_pdf", "expect_rejected": True},
                             {"file": "Notes_quote.xlsx", "format": "fake_xlsx", "expect_rejected": True}],
                  "expect_recommended": "Acme Chem Industries"})
    return cases
