"""Deterministic supplier evaluation. No AI: same inputs -> same verdicts, each with a reason."""
import re
from datetime import date
from typing import Optional

from app.schemas import (CheckStatus, Finding, RequirementCheck, RFQRequirements,
                         SupplierEvaluation, SupplierQuotation, TechRequirement)
from app.services.normalization import NormalizedPrice, convert, normalize_price, same_unit

S = CheckStatus
OPS = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b,
       "<": lambda a, b: a < b, "==": lambda a, b: abs(a - b) < 1e-9}
STATUS_ORDER = {"COMPLIANT": 0, "NEEDS_CLARIFICATION": 1, "NOT_COMPLIANT": 2}


def _fmt(v, unit=None) -> str:
    if v is None:
        return "not stated"
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if not unit:
        return str(v)
    return f"{v}{unit}" if unit == "%" else f"{v} {unit}"


def _rc(req, required, offered, status, mandatory, reason) -> RequirementCheck:
    return RequirementCheck(requirement=req, required=required, offered=offered,
                            status=status, mandatory=mandatory, reason=reason)


def _related(a: str, b: str) -> bool:
    return a == b or a.startswith(b) or b.startswith(a)


def _find_spec(q: SupplierQuotation, name: str):
    exact = [s for s in q.specifications if s.name == name]
    if exact:
        return exact[0]
    loose = [s for s in q.specifications if _related(s.name, name)]
    return loose[0] if loose else None


def _has_conflict(q: SupplierQuotation, name: str) -> bool:
    for c in q.conflicts:
        key = c.split(":")[0].strip().lower().replace(" ", "_")
        if key and _related(key, name):
            return True
    return False


# ---------- individual checks ----------
def check_spec(req: TechRequirement, q: SupplierQuotation) -> RequirementCheck:
    required = f"{req.operator} {_fmt(req.value, req.unit)}"
    spec = _find_spec(q, req.name)
    offered = _fmt(spec.value, spec.unit) if spec else "not stated"
    if _has_conflict(q, req.name):
        return _rc(req.name, required, offered, S.REVIEW_REQUIRED, req.mandatory,
                   "Quotation states conflicting values - confirm with supplier")
    if spec is None or spec.value is None:
        return _rc(req.name, required, "not stated", S.UNKNOWN, req.mandatory,
                   "Not stated in quotation - cannot be treated as a pass")
    if req.operator == "present":
        ok = str(spec.value).strip().lower() not in ("", "no", "false", "none", "0")
        return _rc(req.name, required, offered, S.PASS if ok else S.FAIL, req.mandatory,
                   "Provided" if ok else "Not provided")
    try:
        value, target = float(spec.value), float(req.value)
    except (TypeError, ValueError):
        return _rc(req.name, required, offered, S.REVIEW_REQUIRED, req.mandatory,
                   "Non-numeric value - needs human check")
    note = ""
    if req.unit and spec.unit and not same_unit(req.unit, spec.unit):
        converted = convert(value, spec.unit, req.unit)
        if converted is None:
            return _rc(req.name, required, offered, S.REVIEW_REQUIRED, req.mandatory,
                       f"Unit '{spec.unit}' cannot be compared with '{req.unit}'")
        note = f" (converted from {_fmt(value, spec.unit)})"
        value = converted
    elif req.unit and not spec.unit:
        note = " (supplier gave no unit; assumed same unit)"
    ok = OPS[req.operator](value, target)
    return _rc(req.name, required, offered, S.PASS if ok else S.FAIL, req.mandatory,
               ("Meets requirement" if ok else "Does not meet requirement") + note)


def _cert_key(s: str) -> str:
    s = s.lower()
    if "analysis" in s or re.search(r"\bcoa\b", s):
        return "coa"
    if "gmp" in s:
        return "gmp"
    m = re.search(r"iso\s*\d+", s)
    if m:
        return m.group(0).replace(" ", "")
    return re.sub(r"[^a-z0-9]", "", s.replace("certificate", ""))


def check_certificates(rfq: RFQRequirements, q: SupplierQuotation) -> list:
    offered = {_cert_key(c) for c in q.certificates}
    out = []
    for cert in rfq.required_certificates:
        ok = _cert_key(cert) in offered
        out.append(_rc(f"certificate: {cert}", "Provided", "Offered" if ok else "not offered",
                       S.PASS if ok else S.UNKNOWN, True,
                       "Supplier states it will provide this" if ok
                       else "Not offered in quotation - documentation incomplete"))
    return out


def check_delivery(rfq: RFQRequirements, q: SupplierQuotation):
    if rfq.max_delivery_days is None:
        return None
    required = f"<= {rfq.max_delivery_days} days"
    if q.delivery_days is None:
        return _rc("delivery_days", required, "not stated", S.UNKNOWN, True, "Delivery time not stated")
    ok = q.delivery_days <= rfq.max_delivery_days
    reason = ("Within delivery limit" if ok else
              f"Exceeds delivery limit by {q.delivery_days - rfq.max_delivery_days} days")
    return _rc("delivery_days", required, f"{q.delivery_days} days", S.PASS if ok else S.FAIL, True, reason)


def check_validity(q: SupplierQuotation, today: date) -> RequirementCheck:
    if q.valid_until is None:
        return _rc("quotation_validity", "Valid today", "not stated", S.UNKNOWN, False,
                   "Validity date not stated - confirm with supplier")
    if q.valid_until < today:
        return _rc("quotation_validity", "Valid today", str(q.valid_until), S.REVIEW_REQUIRED, True,
                   f"Quotation expired on {q.valid_until} - request a revalidated quote")
    days = (q.valid_until - today).days
    reason = f"Valid for {days} more days" + (" - expires soon" if days <= 7 else "")
    return _rc("quotation_validity", "Valid today", str(q.valid_until), S.PASS, True, reason)


def check_price(np_: NormalizedPrice, q: SupplierQuotation, rfq: RFQRequirements) -> RequirementCheck:
    required = f"Stated and comparable ({rfq.currency or '?'} per {rfq.unit or '?'}, excl. tax)"
    if q.unit_price is None:
        return _rc("price", required, "not stated", S.UNKNOWN, True, "Unit price not stated")
    offered = f"{q.currency or '?'} {q.unit_price:g} per {q.price_per or q.unit or '?'} ({q.tax_status} of tax)"
    if any(w.startswith("unit_price") for w in q.verification_warnings):
        return _rc("price", required, offered, S.REVIEW_REQUIRED, True,
                   "Extracted price does not match the source text - a human must verify it")
    if np_.comparable:
        return _rc("price", required, offered, S.PASS, True,
                   "Comparable: " + ("; ".join(np_.notes) if np_.notes else "as quoted"))
    return _rc("price", required, offered, S.REVIEW_REQUIRED, True, "; ".join(np_.issues))


# ---------- findings ----------
def _category(name: str) -> str:
    if name == "price":
        return "commercial"
    if name == "delivery_days":
        return "delivery"
    if name == "quotation_validity":
        return "validity"
    if name.startswith("certificate"):
        return "documentation"
    return "technical"


def _findings_from_checks(supplier: str, checks: list) -> list:
    out = []
    for c in checks:
        if c.status in (S.PASS, S.NOT_APPLICABLE):
            continue
        if c.mandatory and c.status in (S.FAIL, S.REVIEW_REQUIRED):
            sev = "HIGH"
        elif c.mandatory:
            sev = "MEDIUM"
        else:
            sev = "LOW"
        out.append(Finding(supplier_name=supplier, severity=sev, category=_category(c.requirement),
                           message=f"{c.requirement}: {c.reason}"))
    return out


def _extra_findings(rfq: RFQRequirements, q: SupplierQuotation) -> list:
    out, s = [], q.supplier_name
    for c in q.conflicts:
        out.append(Finding(supplier_name=s, severity="HIGH", category="conflict",
                           message=f"Conflicting values: {c}"))
    for w in q.verification_warnings:
        out.append(Finding(supplier_name=s, severity="HIGH", category="verification",
                           message=f"AI value not found in source text - {w}"))
    if q.extraction_status == "review_required":
        out.append(Finding(supplier_name=s, severity="MEDIUM", category="extraction",
                           message="Values extracted from a scanned or conflicting document - verify against source"))
    if not q.payment_terms:
        out.append(Finding(supplier_name=s, severity="MEDIUM", category="commercial",
                           message="Payment terms not stated"))
    elif rfq.payment_terms:
        want = re.search(r"(\d+)\s*days", rfq.payment_terms.lower())
        got = re.search(r"(\d+)\s*days", q.payment_terms.lower())
        if want and got and int(got.group(1)) < int(want.group(1)):
            out.append(Finding(supplier_name=s, severity="MEDIUM", category="commercial",
                               message=f"Payment terms less favourable: '{q.payment_terms}' "
                                       f"vs RFQ '{rfq.payment_terms}'"))
    if q.quantity is not None and rfq.required_quantity:
        qty = convert(q.quantity, q.unit, rfq.unit) if (q.unit and rfq.unit) else q.quantity
        if qty is not None and qty < rfq.required_quantity:
            out.append(Finding(supplier_name=s, severity="MEDIUM", category="commercial",
                               message=f"Offers only {_fmt(q.quantity, q.unit)} of "
                                       f"{_fmt(rfq.required_quantity, rfq.unit)} required"))
    for e in q.exclusions:
        out.append(Finding(supplier_name=s, severity="LOW", category="condition",
                           message=f"Supplier condition: {e}"))
    return out


# ---------- public API ----------
def evaluate_supplier(rfq: RFQRequirements, q: SupplierQuotation, today: date,
                      exchange_rates: Optional[dict] = None) -> SupplierEvaluation:
    np_ = normalize_price(q, rfq, exchange_rates)
    checks = [check_spec(r, q) for r in rfq.technical_requirements]
    checks += check_certificates(rfq, q)
    delivery = check_delivery(rfq, q)
    if delivery:
        checks.append(delivery)
    checks.append(check_validity(q, today))
    checks.append(check_price(np_, q, rfq))
    return SupplierEvaluation(
        supplier_name=q.supplier_name, checks=checks,
        normalized_unit_price=np_.unit_price, total_cost=np_.total_cost,
        commercially_comparable=np_.comparable, price_notes=np_.notes + np_.issues,
        findings=_findings_from_checks(q.supplier_name, checks) + _extra_findings(rfq, q),
    )


def evaluate_all(rfq: RFQRequirements, quotes: list, today: Optional[date] = None,
                 exchange_rates: Optional[dict] = None) -> list:
    today = today or date.today()
    evals = [evaluate_supplier(rfq, q, today, exchange_rates) for q in quotes]
    return sorted(evals, key=lambda e: (STATUS_ORDER[e.overall_status],
                                        e.total_cost if e.total_cost is not None else float("inf")))


def recommend(evals: list) -> dict:
    compliant = [e for e in evals if e.overall_status == "COMPLIANT" and e.total_cost is not None]
    n_nc = sum(e.overall_status == "NOT_COMPLIANT" for e in evals)
    n_cl = sum(e.overall_status == "NEEDS_CLARIFICATION" for e in evals)
    if not compliant:
        return {"recommended_supplier": None,
                "explanation": "No supplier meets every mandatory requirement with a comparable price. "
                               f"{n_nc} not compliant, {n_cl} need clarification. Resolve the listed "
                               "clarifications before deciding."}
    best = min(compliant, key=lambda e: e.total_cost)
    return {"recommended_supplier": best.supplier_name,
            "explanation": f"{best.supplier_name} is the lowest-cost supplier that meets all mandatory "
                           f"requirements (comparable total {best.total_cost:,.2f}). {n_nc} supplier(s) not "
                           f"compliant, {n_cl} need clarification. This is a recommendation for human "
                           "review - not an approved purchasing decision."}
