import pytest
from pydantic import ValidationError

from app.schemas import RFQRequirements, SupplierQuotation, TechRequirement


def test_string_numbers_and_indian_dates_are_parsed():
    q = SupplierQuotation(supplier_name="A", unit_price="185", quotation_date="10/11/2026",
                          currency=" inr ")
    assert q.unit_price == 185.0
    assert q.quotation_date.month == 11
    assert q.currency == "INR"


def test_missing_price_stays_none_not_zero():
    q = SupplierQuotation(supplier_name="B")
    assert q.unit_price is None


def test_invalid_tax_status_rejected():
    with pytest.raises(ValidationError):
        SupplierQuotation(supplier_name="C", tax_status="maybe")


def test_requirement_names_normalised():
    r = TechRequirement(name="Moisture Content", operator="<=", value=0.5, unit="%")
    assert r.name == "moisture_content"


def test_rfq_reports_missing_core_fields():
    assert RFQRequirements(product_name="X").missing_core_fields() == ["required_quantity", "unit"]
