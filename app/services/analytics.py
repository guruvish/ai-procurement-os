"""Decision & BI analytics. Pure, deterministic calculations on evaluation data - no AI, no hidden weights.
Every figure is derived from values shown elsewhere in the app, so a reviewer can verify it."""
import json
import re
from datetime import datetime
from statistics import mean
from typing import Optional

from app.schemas import CheckStatus, RFQRequirements, SupplierEvaluation

S = CheckStatus
NON_TECH = ("price", "delivery_days", "quotation_validity")


def _pct(part: float, whole: float) -> Optional[float]:
    return round(100 * part / whole, 1) if whole else None


def payment_days(text: Optional[str]) -> Optional[int]:
    """'30 days after delivery' -> 30; '50% advance, balance within 15 days' -> 0 (advance = pay before delivery)."""
    if not text:
        return None
    t = text.lower()
    if "advance" in t:
        return 0
    m = re.search(r"(\d+)\s*days?", t)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- one evaluation
def decision_analysis(evals: list, rec: dict) -> dict:
    """Savings, gap to runner-up, compliance premium and how robust the recommendation is."""
    comparable = [e for e in evals if e.total_cost is not None]
    compliant = sorted([e for e in comparable if e.overall_status == "COMPLIANT"], key=lambda e: e.total_cost)
    best = compliant[0] if compliant else None
    out = {"n_suppliers": len(evals), "n_compliant": sum(e.overall_status == "COMPLIANT" for e in evals),
           "n_clarification": sum(e.overall_status == "NEEDS_CLARIFICATION" for e in evals),
           "n_not_compliant": sum(e.overall_status == "NOT_COMPLIANT" for e in evals),
           "recommended": best.supplier_name if best else None, "recommended_total": best.total_cost if best else None,
           "runner_up": None, "gap_to_runner_up": None, "gap_to_runner_up_pct": None,
           "savings_vs_highest": None, "savings_vs_highest_pct": None, "savings_vs_average": None,
           "cheapest_overall": None, "compliance_premium": None, "compliance_premium_pct": None,
           "robustness": "No compliant supplier with a comparable price yet - no recommendation to analyse."}
    if not best:
        return out
    highest = compliant[-1]
    out["savings_vs_highest"] = round(highest.total_cost - best.total_cost, 2)
    out["savings_vs_highest_pct"] = _pct(out["savings_vs_highest"], highest.total_cost)
    out["savings_vs_average"] = round(mean(e.total_cost for e in compliant) - best.total_cost, 2)
    if len(compliant) > 1:
        ru = compliant[1]
        out.update(runner_up=ru.supplier_name, gap_to_runner_up=round(ru.total_cost - best.total_cost, 2),
                   gap_to_runner_up_pct=_pct(ru.total_cost - best.total_cost, best.total_cost))
        unit_gap = (ru.normalized_unit_price or 0) - (best.normalized_unit_price or 0)
        out["robustness"] = (
            f"{best.supplier_name} is {out['gap_to_runner_up_pct']}% cheaper than the next compliant supplier "
            f"({ru.supplier_name}). The recommendation would change only if {ru.supplier_name} lowered its price by more "
            f"than {unit_gap:,.2f} per unit (to below {best.normalized_unit_price:,.2f}), or if {best.supplier_name} "
            "fails a requirement after clarification.")
        if out["gap_to_runner_up_pct"] is not None and out["gap_to_runner_up_pct"] < 2:
            out["robustness"] += " The margin is small (<2%) - consider asking both suppliers for a best and final offer."
    else:
        out["robustness"] = (f"{best.supplier_name} is the only compliant supplier with a comparable price, so there is "
                             "no competitive alternative. Resolving the clarifications of other suppliers would "
                             "strengthen the decision.")
    cheapest = min(comparable, key=lambda e: e.total_cost)
    out["cheapest_overall"] = cheapest.supplier_name
    if cheapest.supplier_name != best.supplier_name:
        out["compliance_premium"] = round(best.total_cost - cheapest.total_cost, 2)
        out["compliance_premium_pct"] = _pct(out["compliance_premium"], cheapest.total_cost)
    return out


def scorecard(rfq: Optional[RFQRequirements], evals: list, quotes: dict) -> list:
    """One row per supplier with real, verifiable metrics (no invented scores or weights)."""
    rows = []
    for e in evals:
        tech = [c for c in e.checks if c.requirement not in NON_TECH and not c.requirement.startswith("certificate")]
        docs = [c for c in e.checks if c.requirement.startswith("certificate")]
        q = quotes.get(e.supplier_name)
        delivery = q.delivery_days if q else None
        rows.append({
            "Supplier": e.supplier_name, "Verdict": e.overall_status,
            "Price / unit": e.normalized_unit_price, "Total cost": e.total_cost,
            "Technical pass %": _pct(sum(c.status == S.PASS for c in tech), len(tech)),
            "Documents %": _pct(sum(c.status == S.PASS for c in docs), len(docs)),
            "Delivery days": delivery,
            "Delivery headroom": (rfq.max_delivery_days - delivery) if (rfq and rfq.max_delivery_days is not None
                                                                         and delivery is not None) else None,
            "Payment days": payment_days(q.payment_terms if q else None),
            "Open items": e.unknowns, "Mandatory failures": e.mandatory_failures,
            "High risks": sum(f.severity == "HIGH" for f in e.findings),
            "Risk": e.risk_level})
    return rows


def check_mix(evals: list) -> list:
    """Long format for a stacked chart: supplier x result -> count."""
    out = []
    for e in evals:
        for status in (S.PASS, S.FAIL, S.UNKNOWN, S.REVIEW_REQUIRED):
            n = sum(c.status == status for c in e.checks)
            if n:
                out.append({"Supplier": e.supplier_name, "Result": status.value, "Checks": n})
    return out


def risk_mix(evals: list) -> list:
    out = []
    for e in evals:
        for sev in ("HIGH", "MEDIUM", "LOW"):
            n = sum(f.severity == sev for f in e.findings)
            if n:
                out.append({"Supplier": e.supplier_name, "Severity": sev, "Findings": n})
    return out


# ---------------------------------------------------------------- all evaluations (portfolio)
def _hours(a: str, b: str) -> Optional[float]:
    try:
        return round((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 3600, 1)
    except (TypeError, ValueError):
        return None


def portfolio(db) -> dict:
    reqs = db.list_requests()
    rows, suppliers, categories = [], {}, {}
    for r in reqs:
        rid = r["id"]
        evals = db.get_evaluations(rid)
        rec = json.loads(r["recommendation_json"]) if r["recommendation_json"] else {}
        approvals = db.list_approvals(rid)
        final = next((a for a in reversed(approvals) if a["decision"] == "APPROVED"), None)
        audit = db.list_audit(rid)
        da = decision_analysis(evals, rec) if evals else {}
        rows.append({
            "RFQ": r["rfq_number"], "Title": r["title"], "Status": r["status"], "Suppliers": len(evals),
            "Compliant": da.get("n_compliant", 0), "Recommended": rec.get("recommended_supplier"),
            "Selected": final["selected_supplier"] if final else None,
            "Followed recommendation": (final["selected_supplier"] == rec.get("recommended_supplier")) if final else None,
            "Savings vs highest compliant": da.get("savings_vs_highest"),
            "Compliance premium": da.get("compliance_premium"),
            "Cycle time (h)": _hours(r["created_at"], final["reviewed_at"]) if final else None,
            "Human corrections": sum(a["event_type"] == "HUMAN_CORRECTION" for a in audit)})
        for e in evals:
            s = suppliers.setdefault(e.supplier_name, {"Supplier": e.supplier_name, "Quotes": 0, "Compliant": 0,
                                                       "Recommended": 0, "Selected": 0, "High risks": 0})
            s["Quotes"] += 1
            s["Compliant"] += e.overall_status == "COMPLIANT"
            s["Recommended"] += e.supplier_name == rec.get("recommended_supplier")
            s["Selected"] += bool(final and final["selected_supplier"] == e.supplier_name)
            s["High risks"] += sum(f.severity == "HIGH" for f in e.findings)
            for f in e.findings:
                if f.severity != "LOW":
                    categories[f.category] = categories.get(f.category, 0) + 1
    decided = [x for x in rows if x["Selected"]]
    runs = [json.loads(r["metrics_json"]) for r in db.list_runs() if r["metrics_json"]]
    runs = [m for m in runs if "ai_calls" in m]
    for s in suppliers.values():
        s["Compliance rate %"] = _pct(s["Compliant"], s["Quotes"])
    return {
        "rows": rows,
        "kpis": {"evaluations": len(rows), "decided": len(decided),
                 "acceptance_pct": _pct(sum(bool(x["Followed recommendation"]) for x in decided), len(decided)),
                 "savings_total": round(sum(x["Savings vs highest compliant"] or 0 for x in decided), 2),
                 "avg_cycle_h": round(mean(x["Cycle time (h)"] for x in decided if x["Cycle time (h)"] is not None), 1)
                 if any(x["Cycle time (h)"] is not None for x in decided) else None,
                 "avg_suppliers": round(mean(x["Suppliers"] for x in rows), 1) if rows else None,
                 "corrections": sum(x["Human corrections"] for x in rows),
                 "avg_processing_s": round(mean(m["total_seconds"] for m in runs), 1) if runs else None,
                 "ai_calls": sum(m["ai_calls"] for m in runs)},
        "suppliers": sorted(suppliers.values(), key=lambda s: (-s["Selected"], -s["Compliant"], s["Supplier"])),
        "issue_categories": [{"Category": k, "Findings": v} for k, v in sorted(categories.items(), key=lambda x: -x[1])],
    }
