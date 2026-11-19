from datetime import date

import pytest

from app.schemas import (CheckStatus, OfferedSpec, RFQRequirements, SupplierQuotation,
                         TechRequirement)
from app.services.evaluation_engine import evaluate_all, recommend
from app.services.normalization import convert

TODAY = date(2026, 11, 19)
S = CheckStatus


def rfq():
    return RFQRequirements(
        rfq_id="RFQ-T", product_name="Paracetamol API", required_quantity=10000, unit="kg", currency="INR",
        technical_requirements=[
            TechRequirement(name="purity", operator=">=", value=99.5, unit="%"),
            TechRequirement(name="moisture", operator="<=", value=0.5, unit="%"),
            TechRequirement(name="particle_size_d90", operator="<", value=150, unit="micron", mandatory=False),
        ],
        required_certificates=["Certificate of Analysis"], max_delivery_days=30,
        payment_terms="30 days after delivery")


def quote(**kw):
    base = dict(supplier_name="Good Co", unit_price=185, price_per="kg", currency="INR",
                tax_status="exclusive", delivery_days=21, valid_until=date(2026, 12, 10),
                payment_terms="30 days from delivery", quantity=10000, unit="kg", certificates=["CoA"],
                specifications=[OfferedSpec(name="purity", value=99.8, unit="%"),
                                OfferedSpec(name="moisture", value=0.3, unit="%")])
    base.update(kw)
    return SupplierQuotation(**base)


def one(q):
    return evaluate_all(rfq(), [q], today=TODAY)[0]


def status(ev, name):
    return next(c.status for c in ev.checks if c.requirement.startswith(name))


def test_tc01_complete_quote_is_compliant():
    ev = one(quote())
    assert ev.overall_status == "COMPLIANT"
    assert ev.total_cost == 1_850_000
    assert status(ev, "particle_size_d90") == S.UNKNOWN   # optional + unstated: never PASS, but not blocking


def test_tc02_missing_price_is_unknown_not_zero():
    ev = one(quote(unit_price=None))
    assert status(ev, "price") == S.UNKNOWN
    assert ev.total_cost is None
    assert ev.overall_status == "NEEDS_CLARIFICATION"


def test_tc03_price_per_gram_normalised_to_kg():
    ev = one(quote(unit_price=0.19, price_per="g"))
    assert ev.normalized_unit_price == pytest.approx(190)


def test_tc05_conflicting_purity_needs_review():
    ev = one(quote(conflicts=["purity: 99.8% (page 1) vs 99.2% (page 2)"]))
    assert status(ev, "purity") == S.REVIEW_REQUIRED
    assert any(f.category == "conflict" for f in ev.findings)


def test_tc06_missing_coa_marks_documentation_incomplete():
    ev = one(quote(certificates=[]))
    assert status(ev, "certificate") == S.UNKNOWN
    assert ev.overall_status == "NEEDS_CLARIFICATION"


def test_tc07_late_delivery_fails():
    ev = one(quote(delivery_days=45))
    assert status(ev, "delivery_days") == S.FAIL
    assert ev.overall_status == "NOT_COMPLIANT"


def test_tc08_expired_quote_flagged():
    ev = one(quote(valid_until=date(2026, 11, 1)))
    assert status(ev, "quotation_validity") == S.REVIEW_REQUIRED
    assert any(f.severity == "HIGH" and f.category == "validity" for f in ev.findings)


def test_tc09_tax_inclusive_normalised_and_unknown_tax_incomparable():
    ev = one(quote(unit_price=218.3, tax_status="inclusive", tax_rate_percent=18))
    assert ev.normalized_unit_price == pytest.approx(185, abs=0.01)
    ev2 = one(quote(tax_status="unknown"))
    assert ev2.commercially_comparable is False


def test_purity_below_spec_fails():
    ev = one(quote(specifications=[OfferedSpec(name="purity", value=99.2, unit="%"),
                                   OfferedSpec(name="moisture", value=0.3, unit="%")]))
    assert status(ev, "purity") == S.FAIL


def test_low_price_cannot_hide_mandatory_failure():
    cheap = quote(supplier_name="Cheap Co", unit_price=150,
                  specifications=[OfferedSpec(name="purity", value=99.0, unit="%"),
                                  OfferedSpec(name="moisture", value=0.3, unit="%")])
    evals = evaluate_all(rfq(), [cheap, quote()], today=TODAY)
    assert recommend(evals)["recommended_supplier"] == "Good Co"
    assert evals[-1].supplier_name == "Cheap Co"


def test_foreign_currency_without_rate_is_not_converted():
    ev = one(quote(currency="USD", unit_price=2.2))
    assert ev.normalized_unit_price is None and ev.commercially_comparable is False


def test_unit_conversion_helper():
    assert convert(1000, "g", "kg") == 1
    assert convert(1, "kg", "litre") is None
