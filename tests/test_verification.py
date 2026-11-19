"""F13: the AI silently converted 'INR 0.21 per gram' into 210 per kg (told not to convert).
The economic value happened to be right, but the next conversion could be wrong and nothing would notice.
Deterministic safety net: a value must appear in its own quoted source text, otherwise a human verifies it."""
from datetime import date

from app.schemas import Evidence, OfferedSpec, RFQRequirements, SupplierQuotation, TechRequirement
from app.services.evaluation_engine import evaluate_all
from app.services.verification import numbers_in, verify_quotation

RFQ = RFQRequirements(rfq_id="R", product_name="MCC", required_quantity=5, unit="MT", currency="INR",
                      technical_requirements=[TechRequirement(name="moisture", operator="<=", value=5.0, unit="%")],
                      required_certificates=["Certificate of Analysis"], max_delivery_days=21,
                      payment_terms="45 days after delivery")


def fibrechem(price, per, quote="Price: INR 0.21 per gram, GST 12% extra"):
    return SupplierQuotation(supplier_name="FibreChem Pvt Ltd", unit_price=price, price_per=per, currency="INR",
                             tax_status="exclusive", tax_rate_percent=12, delivery_days=18,
                             valid_until=date(2030, 1, 1), payment_terms="45 days after delivery",
                             certificates=["CoA"], specifications=[OfferedSpec(name="moisture", value=3.8, unit="%")],
                             evidence={"unit_price": Evidence(page=1, quote=quote, confidence=0.95)})


def test_f13_exact_ai_output_is_flagged():
    q = fibrechem(210.0, "kg")                               # what gemini-3.5-flash-lite returned in TC-03
    w = verify_quotation(q)
    assert len(w) == 1 and "extracted 210 per kg" in w[0] and "0.21 per gram" in w[0]


def test_correct_extraction_is_not_flagged():
    assert verify_quotation(fibrechem(0.21, "g")) == []
    assert verify_quotation(fibrechem(195000, "MT", "Rate: INR 1,95,000 per MT (GST 12% extra)")) == []  # Indian format
    assert numbers_in("INR 1,95,000 @ 18%") == [195000.0, 18.0]


def test_flagged_price_blocks_the_supplier_until_a_human_verifies():
    q = fibrechem(210.0, "kg")
    q.verification_warnings = verify_quotation(q)
    ev = evaluate_all(RFQ, [q], today=date(2026, 11, 19))[0]
    price = next(c for c in ev.checks if c.requirement == "price")
    assert price.status.value == "REVIEW_REQUIRED" and ev.overall_status == "NEEDS_CLARIFICATION"
    assert any(f.category == "verification" and f.severity == "HIGH" for f in ev.findings)


def test_human_confirmation_clears_the_flag_and_is_audited(tmp_path, monkeypatch):
    from app import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "v.db")
    monkeypatch.setattr(db, "UPLOAD_DIR", tmp_path / "u")
    db.init_db()
    rid = db.create_request("RFQ-V")
    did, _ = db.save_document(rid, "f.csv", b"x,y\n", "h" * 64, "csv", "QUOTATION")
    q = fibrechem(210.0, "kg")
    q.verification_warnings = verify_quotation(q)
    db.save_quotation(rid, did, q)
    fixed = db.human_edit_quotation(rid, did, {"unit_price": 0.21, "price_per": "g", "verification_warnings": []}, "priya")
    assert fixed.verification_warnings == [] and fixed.unit_price == 0.21
    assert any(a["event_type"] == "HUMAN_CORRECTION" and "verification_warnings" in a["description"]
               for a in db.list_audit(rid))
