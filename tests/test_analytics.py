"""Decision analytics: every figure is checked by hand against the evaluation data."""
from datetime import date

import pytest

from app.schemas import OfferedSpec, RFQRequirements, SupplierQuotation, TechRequirement
from app.services import analytics as A
from app.services.evaluation_engine import evaluate_all, recommend

TODAY = date(2026, 11, 19)
RFQ = RFQRequirements(rfq_id="R", product_name="P", required_quantity=10000, unit="kg", currency="INR",
                      technical_requirements=[TechRequirement(name="purity", operator=">=", value=99.5, unit="%")],
                      required_certificates=["CoA"], max_delivery_days=30, payment_terms="30 days after delivery")


def q(name, price, purity=99.8, delivery=20, pay="30 days after delivery"):
    return SupplierQuotation(supplier_name=name, unit_price=price, price_per="kg", currency="INR", tax_status="exclusive",
                             delivery_days=delivery, valid_until=date(2026, 12, 31), payment_terms=pay,
                             certificates=["CoA"], specifications=[OfferedSpec(name="purity", value=purity, unit="%")])


def analysed(*quotes):
    evals = evaluate_all(RFQ, list(quotes), today=TODAY)
    return evals, A.decision_analysis(evals, recommend(evals))


def test_savings_gap_and_compliance_premium_match_hand_calculation():
    evals, da = analysed(q("Delta", 180), q("Acme", 185), q("Zeta", 200), q("Beta", 172, purity=99.2))
    assert da["recommended"] == "Delta" and da["runner_up"] == "Acme"
    assert da["savings_vs_highest"] == 200_000                  # (200 - 180) * 10,000
    assert da["savings_vs_highest_pct"] == 10.0
    assert da["gap_to_runner_up"] == 50_000 and da["gap_to_runner_up_pct"] == 2.8
    assert da["cheapest_overall"] == "Beta" and da["compliance_premium"] == 80_000   # (180 - 172) * 10,000
    assert "below 180.00" in da["robustness"]


def test_small_margin_triggers_best_and_final_offer_hint():
    _, da = analysed(q("A", 180), q("B", 181))
    assert da["gap_to_runner_up_pct"] < 2 and "best and final offer" in da["robustness"]


def test_no_compliant_supplier_means_no_savings_claimed():
    _, da = analysed(q("Bad", 150, purity=98.0))
    assert da["recommended"] is None and da["savings_vs_highest"] is None


def test_scorecard_uses_real_values():
    evals, _ = analysed(q("Delta", 180, delivery=20, pay="45 days after delivery"), q("Gamma", None, pay="50% advance"))
    rows = {r["Supplier"]: r for r in A.scorecard(RFQ, evals, {"Delta": q("Delta", 180, delivery=20,
                                                                           pay="45 days after delivery"),
                                                               "Gamma": q("Gamma", None, pay="50% advance")})}
    assert rows["Delta"]["Technical pass %"] == 100.0 and rows["Delta"]["Delivery headroom"] == 10
    assert rows["Delta"]["Payment days"] == 45 and rows["Gamma"]["Payment days"] == 0
    assert rows["Gamma"]["Price / unit"] is None


@pytest.mark.parametrize("text,days", [("30 days after delivery", 30), ("Net 45 days", 45),
                                       ("50% advance, balance within 15 days", 0), (None, None), ("on delivery", None)])
def test_payment_days_parsing(text, days):
    assert A.payment_days(text) == days
