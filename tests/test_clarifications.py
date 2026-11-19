from datetime import date

from app.schemas import OfferedSpec, RFQRequirements, SupplierQuotation, TechRequirement
from app.services.clarifications import draft_clarification
from app.services.evaluation_engine import evaluate_all

TODAY = date(2026, 11, 19)
RFQ = RFQRequirements(
    rfq_id="RFQ-2026-001", product_name="Paracetamol API", required_quantity=10000, unit="kg", currency="INR",
    technical_requirements=[TechRequirement(name="purity", operator=">=", value=99.5, unit="%"),
                            TechRequirement(name="moisture", operator="<=", value=0.5, unit="%")],
    required_certificates=["Certificate of Analysis", "GMP certificate"], max_delivery_days=30,
    payment_terms="30 days after delivery")


def test_gamma_style_quote_gets_one_question_per_open_item():
    gamma = SupplierQuotation(
        supplier_name="Gamma Organics Ltd", quotation_number="GO-5512", valid_until=date(2026, 10, 31),
        unit_price=None, delivery_days=28, payment_terms="50% advance, balance within 15 days",
        certificates=["CoA"], specifications=[OfferedSpec(name="purity", value=99.6, unit="%")])
    ev = evaluate_all(RFQ, [gamma], today=TODAY)[0]
    text = draft_clarification(RFQ, gamma, ev, buyer="Sunrise Pharma", today=TODAY)
    assert text.startswith("Subject: Clarification required - RFQ-2026-001")
    assert "unit price for 10000 kg" in text            # missing price
    assert "expired on 2026-10-31" in text              # expired quote
    assert "GMP certificate" in text                    # missing certificate
    assert "moisture" in text                           # spec not stated
    assert "30 days after delivery" in text             # payment terms
    assert "Certificate of Analysis" not in text        # offered -> no question
    assert "22 Nov 2026" in text                        # reply-by date


def test_fully_compliant_quote_needs_no_clarification():
    good = SupplierQuotation(
        supplier_name="Acme", unit_price=185, price_per="kg", currency="INR", tax_status="exclusive",
        delivery_days=21, valid_until=date(2026, 12, 10), payment_terms="30 days after delivery",
        certificates=["CoA", "GMP"], specifications=[OfferedSpec(name="purity", value=99.8, unit="%"),
                                                     OfferedSpec(name="moisture", value=0.3, unit="%")])
    ev = evaluate_all(RFQ, [good], today=TODAY)[0]
    assert draft_clarification(RFQ, good, ev, today=TODAY) is None
