"""RFQ Analyst + Supplier Analyst: Gemini reads documents, Pydantic enforces the contract."""
from app.agents.llm import call_json
from app.schemas import RFQRequirements, SupplierQuotation
from app.services.document_parser import ParsedDocument
from app.services.verification import verify_quotation

MAX_PROMPT_CHARS = 60_000

RFQ_PROMPT = """You are an RFQ Analyst in a procurement team.
Extract the BUYER REQUIREMENTS from the RFQ document below.

RULES
1. Never invent values. If something is not stated, use null (or [] for lists).
2. Copy numbers as written; do NOT convert units or currencies.
3. technical_requirements: one entry per measurable spec. name = short snake_case
   (e.g. purity, moisture, particle_size, heavy_metals). Treat "assay" as purity and "loss on drying/LOD" as moisture.
   operator is one of >=, <=, >, <, ==, present. "min"/"not less than" -> ">=", "max"/"not more than" -> "<=".
4. mandatory = false ONLY if the text says preferred / desirable / optional; otherwise true.
5. required_certificates: short names, e.g. "Certificate of Analysis", "GMP Certificate".
6. max_delivery_days: integer days (weeks x 7). null if not stated.
7. evidence: for product_name, required_quantity, max_delivery_days, payment_terms, currency add
   {"page": <n from === PAGE n ===>, "quote": "<exact short text>", "confidence": 0-1}.
   Each technical requirement gets its own evidence object.
   ONLY include evidence for fields that have a value. Omit the key entirely for null fields - never write null.

Return ONLY JSON with this shape:
{"rfq_id": "...", "product_name": "...", "required_quantity": 10000, "unit": "kg",
 "technical_requirements": [{"name": "purity", "operator": ">=", "value": 99.5, "unit": "%", "mandatory": true,
     "evidence": {"page": 1, "quote": "Purity: min 99.5%", "confidence": 0.95}}],
 "required_certificates": ["Certificate of Analysis"], "max_delivery_days": 30,
 "payment_terms": "...", "currency": "INR", "tax_basis": "...",
 "evidence": {"product_name": {"page": 1, "quote": "...", "confidence": 0.9}}}

DOCUMENT: <<FILENAME>>
<<TEXT>>
"""

SUPPLIER_PROMPT = """You are a Supplier Analyst in a procurement team.
Extract what the SUPPLIER OFFERS from the quotation below. The buyer's RFQ asks for product
"<<PRODUCT>>" in unit "<<UNIT>>".

RULES
1. Never invent values. Not stated -> null (or []). A missing price must stay null, never 0.
   "Price on request", "to be confirmed", "TBC" mean the price is NOT stated -> null.
2. specifications: when the quotation states a matching property, use EXACTLY these names: <<REQ_NAMES>>.
   ("assay" = purity, "LOD/loss on drying" = moisture). Other specs: short snake_case names.
   value = number only when numeric (99.8 not "99.8%"), unit separately.
3. unit_price: the number EXACTLY as written. price_per: the unit the price refers to (kg, g, MT, litre...).
   NEVER convert units or currencies - conversion is done later by the system.
   Example: "INR 0.21 per gram" -> unit_price 0.21, price_per "g"  (NOT 210 per kg).
   If only a lump-sum total is given, unit_price = null and add "Only total price given: <amount>" to exclusions.
4. currency: ISO code (Rs / Rs. / INR / rupees -> "INR").
5. tax_status: "inclusive", "exclusive" or "unknown". tax_rate_percent if stated (e.g. GST 18% -> 18).
6. freight_cost: number if a separate freight charge is stated, else null.
7. delivery_days: integer days (weeks x 7).
8. Dates as YYYY-MM-DD. If validity is "N days from quotation date", compute valid_until.
9. certificates: only certificates the supplier states it provides.
10. exclusions: short list of conditions / exclusions / deviations stated by the supplier.
11. conflicts: if the document states the SAME property with DIFFERENT values, add
    "<name>: <value A> (page x) vs <value B> (page y)". Still fill the field from the main offer.
12. supplier_name: company issuing the quotation (if unknown, use "<<FILENAME>>").
13. evidence for supplier_name, unit_price, currency, delivery_days, valid_until, payment_terms, tax_status:
    {"page": n, "quote": "<exact short text>", "confidence": 0-1}. Each specification gets its own evidence.
    ONLY include evidence for fields that have a value. Omit the key entirely for null fields - never write null.

Return ONLY JSON with this shape:
{"supplier_name": "...", "quotation_number": "...", "quotation_date": "2026-11-10", "valid_until": "2026-12-10",
 "product_name": "...", "quantity": 10000, "unit": "kg", "unit_price": 185, "price_per": "kg", "currency": "INR",
 "tax_status": "exclusive", "tax_rate_percent": 18, "freight_cost": null, "delivery_days": 25,
 "payment_terms": "...", "specifications": [{"name": "purity", "value": 99.8, "unit": "%",
     "evidence": {"page": 1, "quote": "Assay 99.8%", "confidence": 0.95}}],
 "certificates": ["Certificate of Analysis"], "exclusions": [], "conflicts": [],
 "evidence": {"unit_price": {"page": 1, "quote": "Rs. 185/kg", "confidence": 0.95}}}

DOCUMENT: <<FILENAME>>
<<TEXT>>
"""


def _payload(doc: ParsedDocument):
    if doc.needs_vision:
        return "(Scanned document attached as PDF - read it directly. Page = PDF page order.)", doc.raw_bytes
    return doc.as_prompt_text()[:MAX_PROMPT_CHARS], None


def _stamp(evidences, filename: str):
    for ev in evidences:
        if ev is not None:
            ev.source_document = filename


def extract_rfq(doc: ParsedDocument, rfq_id: str = ""):
    text, pdf = _payload(doc)
    prompt = RFQ_PROMPT.replace("<<FILENAME>>", doc.filename).replace("<<TEXT>>", text)
    rfq, meta = call_json("rfq_analyst", prompt, RFQRequirements, pdf_bytes=pdf)
    if rfq_id:
        rfq.rfq_id = rfq_id
    _stamp(list(rfq.evidence.values()) + [r.evidence for r in rfq.technical_requirements], doc.filename)
    return rfq, meta


def extract_quotation(doc: ParsedDocument, rfq: RFQRequirements):
    text, pdf = _payload(doc)
    names = ", ".join(r.name for r in rfq.technical_requirements) or "(none)"
    prompt = (SUPPLIER_PROMPT.replace("<<PRODUCT>>", rfq.product_name or "?")
              .replace("<<UNIT>>", rfq.unit or "?").replace("<<REQ_NAMES>>", names)
              .replace("<<FILENAME>>", doc.filename).replace("<<TEXT>>", text))
    q, meta = call_json("supplier_analyst", prompt, SupplierQuotation, pdf_bytes=pdf)
    q.source_document = doc.filename
    _stamp(list(q.evidence.values()) + [s.evidence for s in q.specifications], doc.filename)
    q.verification_warnings = verify_quotation(q)
    q.extraction_status = ("review_required" if (doc.needs_vision or q.conflicts or q.verification_warnings)
                           else "extracted")
    return q, meta
