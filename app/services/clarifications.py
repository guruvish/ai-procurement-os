"""Turns open evaluation items into a ready-to-send clarification email for a supplier.
Deterministic templates (no AI): every question maps to a specific failed/unknown check,
so the buyer never sends a question the system cannot justify."""
from datetime import date, timedelta
from typing import Optional

from app.schemas import CheckStatus, RFQRequirements, SupplierEvaluation, SupplierQuotation

S = CheckStatus


def _question(c, rfq: RFQRequirements, q: SupplierQuotation) -> Optional[str]:
    name = c.requirement
    if name == "price":
        if c.status == S.UNKNOWN:
            qty = f"{rfq.required_quantity:g} {rfq.unit}" if rfq.required_quantity else "the required quantity"
            return (f"Please confirm your unit price for {qty} of {rfq.product_name or 'the product'} "
                    f"in {rfq.currency or 'our currency'} per {rfq.unit or 'unit'}, and whether it is "
                    "inclusive or exclusive of GST (with the applicable rate).")
        if c.status == S.REVIEW_REQUIRED:
            return f"Please clarify your pricing basis: {c.reason}."
    if name == "quotation_validity":
        if c.status == S.REVIEW_REQUIRED:
            ref = f" {q.quotation_number}" if q.quotation_number else ""
            return (f"Your quotation{ref} expired on {q.valid_until}. Please send a revalidated quotation "
                    "with a new validity date.")
        if c.status == S.UNKNOWN:
            return "Please confirm the validity period of your quotation."
    if name == "delivery_days":
        if c.status == S.UNKNOWN:
            return "Please confirm the delivery lead time (in days) from receipt of our purchase order."
        if c.status == S.FAIL:
            return (f"Our requirement is delivery {c.required}; your offer is {c.offered}. "
                    "Please let us know if you can meet our timeline.")
    if name.startswith("certificate: "):
        if c.status != S.PASS:
            return f"Please confirm that you will provide the {name.split(': ', 1)[1]} with the supply."
        return None
    # technical specifications
    label = name.replace("_", " ")
    if c.status == S.UNKNOWN:
        return f"Please confirm the {label} of the offered material (our requirement: {c.required})."
    if c.status == S.REVIEW_REQUIRED:
        return (f"Your documents state different values for {label}. Please confirm the guaranteed value "
                f"(our requirement: {c.required}).")
    if c.status == S.FAIL:
        return (f"The offered {label} ({c.offered}) does not meet our requirement ({c.required}). "
                "Please let us know if you can offer material that meets this specification.")
    return None


def draft_clarification(rfq: RFQRequirements, q: SupplierQuotation, ev: SupplierEvaluation,
                        buyer: str = "", today: Optional[date] = None) -> Optional[str]:
    """Returns an email draft, or None when nothing needs clarifying."""
    questions = [x for x in (_question(c, rfq, q) for c in ev.checks
                             if c.status in (S.UNKNOWN, S.REVIEW_REQUIRED, S.FAIL)) if x]
    if q.payment_terms and any("Payment terms less favourable" in f.message for f in ev.findings):
        questions.append(f"Our standard payment terms are '{rfq.payment_terms}'. "
                         "Please confirm whether you can accept them.")
    if not q.payment_terms:
        questions.append("Please confirm your payment terms.")
    if not questions:
        return None
    reply_by = (today or date.today()) + timedelta(days=3)
    ref = f" (your ref. {q.quotation_number})" if q.quotation_number else ""
    lines = [f"Subject: Clarification required - {rfq.rfq_id} - {rfq.product_name or ''}".rstrip(" -"),
             "",
             f"Dear {q.supplier_name} team,",
             "",
             f"Thank you for your quotation{ref} against our {rfq.rfq_id}. "
             "Before we can complete our evaluation, please clarify the following:",
             ""]
    lines += [f"{i}. {text}" for i, text in enumerate(questions, 1)]
    lines += ["", f"We would appreciate your reply by {reply_by:%d %b %Y}.", "", "Regards,",
              buyer or "Purchase Department"]
    return "\n".join(lines)
